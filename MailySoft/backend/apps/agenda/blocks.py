"""
Eventos de agenda: reuniones y bloqueos (AgendaBlock).

CRUD de eventos sin paciente (junta, bloqueo de horario) con alcance opcional
por médico/consultorio y reparto de avisos para las reuniones. Extraído de
agenda/services.py para mantener el service principal enfocado en las citas.

Convención: keyword-only args, nombrado acción+entidad, auditoría NOM-024.
"""

import datetime
import logging
import uuid
from typing import Optional

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.agenda.models import AgendaBlock
from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.notificaciones.models import NotificationKind, NotificationTarget
from apps.notificaciones.recipients import clinic_staff_users
from apps.notificaciones.services import notification_fanout
from apps.personal.models import Consultorio, Doctor
from apps.personal.selectors import consultorio_get, doctor_get
from apps.tenancy.models import Tenant

logger = logging.getLogger("apps.agenda.blocks")

User = get_user_model()


def agenda_block_create(
    *,
    tenant: Tenant,
    user: "User",  # type: ignore[valid-type]
    kind: str,
    starts_at: datetime.datetime,
    ends_at: datetime.datetime,
    title: str = "",
    doctor_id: Optional[uuid.UUID] = None,
    consultorio_id: Optional[uuid.UUID] = None,
    all_day: bool = False,
    notes: str = "",
) -> AgendaBlock:
    """Crea un evento de agenda (reunión o bloqueo).

    doctor_id/consultorio_id son OPCIONALES; ambos en None = aplica a toda la clínica.
    """
    valid_kinds = [choice[0] for choice in AgendaBlock.Kind.choices]
    if kind not in valid_kinds:
        raise ValidationError(f"Tipo de evento inválido '{kind}'.")
    if ends_at <= starts_at:
        raise ValidationError("La hora de fin debe ser posterior a la hora de inicio.")

    doctor = None
    if doctor_id is not None:
        try:
            doctor = doctor_get(doctor_id=doctor_id)
        except Doctor.DoesNotExist:
            raise ValidationError("Médico no encontrado en esta clínica.")
        if doctor.tenant_id != tenant.id:
            raise ValidationError("El médico no pertenece a esta clínica.")

    consultorio = None
    if consultorio_id is not None:
        try:
            consultorio = consultorio_get(consultorio_id=consultorio_id)
        except Consultorio.DoesNotExist:
            raise ValidationError("Consultorio no encontrado en esta clínica.")
        if consultorio.tenant_id != tenant.id:
            raise ValidationError("El consultorio no pertenece a esta clínica.")

    block = AgendaBlock.objects.create(
        tenant=tenant,
        created_by=user,
        kind=kind,
        title=title,
        doctor=doctor,
        consultorio=consultorio,
        starts_at=starts_at,
        ends_at=ends_at,
        all_day=all_day,
        notes=notes,
    )
    audit_record(
        action=ActionType.AGENDA_EVENT_CREATE,
        resource_type="AgendaBlock",
        actor=user,
        tenant=tenant,
        resource_id=block.id,
        resource_repr=block.title or block.get_kind_display(),
        metadata={"kind": kind},
    )

    # Notificar SOLO las reuniones (no los bloqueos), según su alcance.
    # Best-effort: una falla aquí no debe tumbar la creación del evento.
    if kind == AgendaBlock.Kind.MEETING:
        try:
            if doctor is not None:
                recipients = [doctor.membership.user]
            elif consultorio is not None:
                recipients = [
                    d.membership.user
                    for d in consultorio.doctores.filter(
                        is_active=True, deleted_at__isnull=True
                    ).select_related("membership__user")
                ]
            else:
                recipients = clinic_staff_users(tenant=tenant)
            notification_fanout(
                tenant=tenant,
                recipients=recipients,
                kind=NotificationKind.MEETING,
                title=f"Reunión: {title or 'Junta'}",
                body=notes[:200],
                actor=user,
                target_type=NotificationTarget.AGENDA_BLOCK,
                target_id=block.id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "agenda_block_create: error notificando reunión %s — %s",
                block.id,
                exc,
                exc_info=True,
            )

    return block


def agenda_block_delete(
    *,
    agenda_block: AgendaBlock,
    user: "User",  # type: ignore[valid-type]
) -> AgendaBlock:
    """Elimina (soft) un evento de agenda."""
    agenda_block.deleted_at = timezone.now()
    agenda_block.save(update_fields=["deleted_at", "updated_at"])
    audit_record(
        action=ActionType.AGENDA_EVENT_DELETE,
        resource_type="AgendaBlock",
        actor=user,
        tenant=agenda_block.tenant,
        resource_id=agenda_block.id,
        resource_repr=agenda_block.title or agenda_block.get_kind_display(),
    )
    return agenda_block


_AGENDA_BLOCK_EDITABLE: frozenset[str] = frozenset(
    {"title", "starts_at", "ends_at", "all_day", "notes"}
)


def agenda_block_update(
    *,
    agenda_block: AgendaBlock,
    user: "User",  # type: ignore[valid-type]
    **fields: object,
) -> AgendaBlock:
    """Actualiza un evento de agenda (título, fecha/hora, todo el día, notas).

    El alcance (doctor/consultorio) NO se edita aquí; se define al crear.
    """
    changed = [f for f in fields if f in _AGENDA_BLOCK_EDITABLE]
    for field_name in changed:
        setattr(agenda_block, field_name, fields[field_name])

    if agenda_block.ends_at <= agenda_block.starts_at:
        raise ValidationError("La hora de fin debe ser posterior a la hora de inicio.")

    if changed:
        agenda_block.save(update_fields=[*changed, "updated_at"])
        audit_record(
            action=ActionType.AGENDA_EVENT_UPDATE,
            resource_type="AgendaBlock",
            actor=user,
            tenant=agenda_block.tenant,
            resource_id=agenda_block.id,
            resource_repr=agenda_block.title or agenda_block.get_kind_display(),
            metadata={"changed": sorted(changed)},
        )
    return agenda_block
