"""
Notas colaborativas de la agenda (AgendaItemNote).

Hilo de notas de equipo sobre una cita o un evento de agenda, con reparto de
avisos (campana) por fan-out. Extraído de agenda/services.py para mantener el
service principal enfocado en el ciclo de vida de las citas.

Convención: keyword-only args, nombrado acción+entidad, auditoría NOM-024.
"""

import logging
import uuid
from typing import Optional

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.agenda.models import AgendaBlock, AgendaItemNote, Appointment
from apps.agenda.selectors import agenda_block_get, appointment_get
from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.notificaciones.models import NotificationKind, NotificationTarget
from apps.notificaciones.recipients import users_with_role
from apps.notificaciones.services import notification_fanout
from apps.tenancy.models import Tenant, TenantMembership

logger = logging.getLogger("apps.agenda.notes")

User = get_user_model()

#: Roles que pueden borrar cualquier nota (no solo la suya propia).
_NOTE_PRIVILEGED_ROLES: frozenset[str] = frozenset(
    {TenantMembership.Role.OWNER, TenantMembership.Role.ADMIN}
)


def agenda_item_note_create(
    *,
    tenant: Tenant,
    user: "User",  # type: ignore[valid-type]
    body: str,
    appointment_id: Optional[uuid.UUID] = None,
    block_id: Optional[uuid.UUID] = None,
) -> AgendaItemNote:
    """Agrega una nota al hilo colaborativo de una cita o de un evento de agenda.

    Exactamente uno de appointment_id / block_id debe estar presente.
    El objeto destino se valida: debe existir y pertenecer al tenant activo.

    Args:
        tenant:         Clínica activa del request.
        user:           Usuario que agrega la nota (se almacena como author).
        body:           Contenido de la nota. No puede estar vacío.
        appointment_id: UUID de la cita destino (excluyente con block_id).
        block_id:       UUID del evento destino (excluyente con appointment_id).

    Returns:
        Instancia AgendaItemNote recién creada.

    Raises:
        ValidationError: si body está vacío, si no se provee exactamente uno de
                         los ids destino, o si el objeto no pertenece al tenant.
    """
    # -- 1. Validar body no vacío
    if not body.strip():
        raise ValidationError("El contenido de la nota no puede estar vacío.")

    # -- 2. Exactamente uno de los ids destino debe estar presente
    has_appointment = appointment_id is not None
    has_block = block_id is not None
    if has_appointment == has_block:  # ambos True o ambos False
        raise ValidationError(
            "Debe indicarse exactamente uno: appointment_id o block_id."
        )

    # -- 3. Resolver y validar el objeto destino (el TenantManager ya filtra por tenant,
    #       pero validamos tenant_id == tenant.id como defensa en profundidad).
    appointment: Optional[Appointment] = None
    agenda_block: Optional[AgendaBlock] = None

    if has_appointment:
        try:
            appointment = appointment_get(appointment_id=appointment_id)  # type: ignore[arg-type]
        except Appointment.DoesNotExist:
            raise ValidationError("Cita no encontrada en esta clínica.")
        if appointment.tenant_id != tenant.id:
            raise ValidationError("La cita no pertenece a esta clínica.")
    else:
        try:
            agenda_block = agenda_block_get(block_id=block_id)  # type: ignore[arg-type]
        except AgendaBlock.DoesNotExist:
            raise ValidationError("Evento de agenda no encontrado en esta clínica.")
        if agenda_block.tenant_id != tenant.id:
            raise ValidationError("El evento no pertenece a esta clínica.")

    # -- 4. Crear la nota
    note = AgendaItemNote.objects.create(
        tenant=tenant,
        created_by=user,
        author=user,
        appointment=appointment,
        agenda_block=agenda_block,
        body=body,
    )

    audit_record(
        action=ActionType.AGENDA_NOTE_ADD,
        resource_type="AgendaItemNote",
        actor=user,
        tenant=tenant,
        resource_id=note.id,
        resource_repr=str(note),
        metadata={
            "appointment_id": str(appointment_id) if appointment_id else None,
            "block_id": str(block_id) if block_id else None,
        },
    )

    # Reparto de "nota de equipo" (campana). Destinatarios:
    #   - cita:   médico de la cita + recepción + quienes ya comentaron el hilo.
    #   - evento: médico del evento (si lo hay) + quienes ya comentaron el hilo.
    # El fanout excluye al propio autor. Best-effort: no debe tumbar la nota.
    try:
        if appointment is not None:
            recipients = [appointment.doctor.membership.user]
            recipients += users_with_role(
                tenant=tenant, role=TenantMembership.Role.RECEPTION
            )
            recipients += [
                n.author
                for n in AgendaItemNote.objects.filter(appointment=appointment)
                .exclude(author=user)
                .select_related("author")
            ]
            notification_fanout(
                tenant=tenant,
                recipients=recipients,
                kind=NotificationKind.TEAM_NOTE,
                title=f"Nueva nota en la cita de {appointment.patient.full_name}",
                body=body[:200],
                actor=user,
                target_type=NotificationTarget.APPOINTMENT,
                target_id=appointment.id,
            )
        elif agenda_block is not None:
            recipients = []
            if agenda_block.doctor_id is not None:
                recipients.append(agenda_block.doctor.membership.user)
            recipients += [
                n.author
                for n in AgendaItemNote.objects.filter(agenda_block=agenda_block)
                .exclude(author=user)
                .select_related("author")
            ]
            notification_fanout(
                tenant=tenant,
                recipients=recipients,
                kind=NotificationKind.TEAM_NOTE,
                title=f"Nueva nota en {agenda_block.title or 'un evento'}",
                body=body[:200],
                actor=user,
                target_type=NotificationTarget.AGENDA_BLOCK,
                target_id=agenda_block.id,
            )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "agenda_item_note_create: error notificando nota de equipo %s — %s",
            note.id,
            exc,
            exc_info=True,
        )

    return note


def agenda_item_note_delete(
    *,
    note: AgendaItemNote,
    user: "User",  # type: ignore[valid-type]
) -> AgendaItemNote:
    """Elimina (soft-delete) una nota del hilo de agenda.

    Decisión de permiso:
        - El author puede borrar su propia nota.
        - El owner y el admin del tenant pueden borrar cualquier nota.
        - Cualquier otro rol recibe ValidationError (400).
          Se elige 400 (vía ValidationError) en lugar de 403 (PermissionDenied)
          porque la nota ya fue devuelta al cliente (existe y le pertenece al tenant),
          por lo que no se trata de un caso de IDOR. La denegación es una regla de
          negocio ("no tienes ese privilegio"), igual que el resto del módulo.

    Args:
        note: Instancia AgendaItemNote a eliminar (ya recuperada vía selector).
        user: Usuario que solicita el borrado.

    Returns:
        Instancia AgendaItemNote con deleted_at poblado.

    Raises:
        ValidationError: si el usuario no es el autor ni tiene rol privilegiado.
    """
    is_author = note.author_id == user.pk  # type: ignore[union-attr]

    # Resolver el rol del usuario dentro del tenant de la nota
    try:
        membership = TenantMembership.objects.get(
            user=user,
            tenant_id=note.tenant_id,
            is_active=True,
            deleted_at__isnull=True,
        )
        user_role: Optional[str] = membership.role
    except TenantMembership.DoesNotExist:
        user_role = None

    is_privileged = user_role in _NOTE_PRIVILEGED_ROLES

    if not is_author and not is_privileged:
        raise ValidationError("No puedes eliminar esta nota.")

    note.deleted_at = timezone.now()
    note.save(update_fields=["deleted_at", "updated_at"])

    audit_record(
        action=ActionType.AGENDA_NOTE_DELETE,
        resource_type="AgendaItemNote",
        actor=user,
        tenant=note.tenant,
        resource_id=note.id,
        resource_repr=str(note),
        metadata={"deleted_by_role": user_role or "unknown"},
    )
    return note
