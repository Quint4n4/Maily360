"""
Services de la app notas.

Toda escritura/modificación de notas pasa por aquí.
Las vistas son delgadas: parsean el request, llaman al service, devuelven respuesta.

Convención: keyword-only args en toda firma, nombrado acción+entidad.

Reglas críticas:
  1. Al menos uno de title/body debe tener contenido.
  2. scope=all (aviso a toda la clínica) SOLO puede crearlo el OWNER.
     scope=role (nota dirigida a un rol) lo puede crear cualquier miembro de
     ROLE_NOTE_SENDERS (owner, admin, doctor, nurse, reception).
     La restricción se aplica aquí (service), no en el permiso HTTP.
     Razón: el service puede llamarse desde Celery/commands sin contexto HTTP.
  3. target_role obligatorio cuando scope=role; forzado a "" en otros scopes.
  4. toggle_done solo aplica cuando is_task=True.
  5. note_update y note_delete verifican que el actor sea el author
     (o el owner para notas globales).
  6. Borrado: soft-delete (deleted_at = now). NUNCA DELETE real.
  7. Los campos inmutables se protegen en _NOTE_IMMUTABLE_FIELDS.
"""

import logging
import uuid
from typing import Any, Optional

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.notas.models import Note, NoteScope
from apps.notificaciones.models import NotificationKind, NotificationTarget
from apps.notificaciones.recipients import (
    ROLE_NOTE_SENDERS,
    all_tenant_users,
    users_with_role,
)
from apps.notificaciones.services import notification_fanout
from apps.tenancy.models import Tenant, TenantMembership

logger = logging.getLogger("apps.notas.services")

User = get_user_model()

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

#: Roles válidos en el tenant (mirrors TenantMembership.Role).
_VALID_ROLES: frozenset[str] = frozenset(
    {
        TenantMembership.Role.OWNER,
        TenantMembership.Role.ADMIN,
        TenantMembership.Role.DOCTOR,
        TenantMembership.Role.NURSE,
        TenantMembership.Role.RECEPTION,
        TenantMembership.Role.FINANCE,
        TenantMembership.Role.READONLY,
    }
)

#: Campos que NUNCA se pueden modificar vía note_update.
_NOTE_IMMUTABLE_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "tenant",
        "tenant_id",
        "created_at",
        "updated_at",
        "deleted_at",
        "author",
        "author_id",
        # done solo cambia via note_toggle_done
        "done",
    }
)


# ---------------------------------------------------------------------------
# Helpers privados
# ---------------------------------------------------------------------------


def _get_membership(*, user: Any, tenant: Tenant) -> Optional[TenantMembership]:
    """Retorna la membresía activa del usuario en el tenant, o None.

    Usa all_objects para funcionar fuera de contexto HTTP (Celery, management commands).
    """
    try:
        return TenantMembership.objects.get(
            user=user,
            tenant=tenant,
            is_active=True,
            deleted_at__isnull=True,
        )
    except TenantMembership.DoesNotExist:
        return None


def _is_owner(*, user: Any, tenant: Tenant) -> bool:
    """Retorna True si el usuario es OWNER del tenant."""
    membership = _get_membership(user=user, tenant=tenant)
    return membership is not None and membership.role == TenantMembership.Role.OWNER


def _get_role(*, user: Any, tenant: Tenant) -> str:
    """Retorna el rol del usuario en el tenant, o '' si no tiene membresía."""
    membership = _get_membership(user=user, tenant=tenant)
    return str(membership.role) if membership is not None else ""


def _validate_content(*, title: str, body: str) -> None:
    """Valida que al menos uno de title/body tenga contenido."""
    if not title.strip() and not body.strip():
        raise ValidationError(
            "La nota debe tener al menos un título o un cuerpo con contenido."
        )


def _can_mutate(*, note: Note, user: Any, tenant: Tenant) -> bool:
    """Retorna True si el user puede editar/borrar la nota.

    Regla:
      - Nota personal (scope=personal): solo el author.
      - Nota global (scope=role|all): el author, o cualquier owner del tenant.
    """
    if note.author_id == user.pk:
        return True
    # Para notas globales, el owner del tenant puede editarlas/borrarlas aunque no
    # las haya creado (supervisión). El autor de una nota scope=role puede ser
    # cualquier miembro de ROLE_NOTE_SENDERS; el de scope=all siempre es el owner.
    if note.scope in (NoteScope.ROLE, NoteScope.ALL) and _is_owner(
        user=user, tenant=tenant
    ):
        return True
    return False


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------


@transaction.atomic
def note_create(
    *,
    tenant: Tenant,
    user: Any,
    body: str = "",
    title: str = "",
    scope: str = NoteScope.PERSONAL,
    target_role: str = "",
    is_task: bool = False,
    remind_at: Optional[Any] = None,
    pinned: bool = False,
) -> Note:
    """Crea una nueva nota o tarea dentro del tenant.

    Valida:
        - title o body deben tener contenido.
        - scope=all solo para el owner; scope=role para ROLE_NOTE_SENDERS
          (ValidationError si un rol sin permiso lo intenta).
        - target_role obligatorio y válido cuando scope=role.
        - target_role forzado a "" cuando scope != role.

    Audita:
        - NOTE_CREATE para notas personales.
        - NOTE_GLOBAL_SEND para notas con scope=role o scope=all.

    Args:
        tenant:      Clínica en la que se crea la nota.
        user:        Usuario autor de la nota.
        body:        Cuerpo de la nota (puede estar vacío si title tiene contenido).
        title:       Título breve (puede estar vacío si body tiene contenido).
        scope:       Audiencia: personal | role | all. Default: personal.
        target_role: Rol destinatario cuando scope=role. Se ignora/vacía en otros scopes.
        is_task:     Si True, es una tarea con checkbox.
        remind_at:   Fecha/hora UTC de recordatorio. None = sin recordatorio.
        pinned:      Si True, aparece al tope del listado.

    Returns:
        Instancia Note recién creada.

    Raises:
        ValidationError: si fallan validaciones de negocio.
    """
    # 1. Normalizar strings
    title = title.strip() if title else ""
    body = body.strip() if body else ""

    # 2. Validar contenido
    _validate_content(title=title, body=body)

    # 3. Validar quién puede usar cada scope.
    actor_role = _get_role(user=user, tenant=tenant)
    if scope == NoteScope.ALL:
        # El aviso a TODA la clínica sigue siendo exclusivo del dueño.
        if not _is_owner(user=user, tenant=tenant):
            raise ValidationError(
                "Solo el dueño de la clínica puede enviar un aviso a toda la clínica (scope='all')."
            )
    elif scope == NoteScope.ROLE:
        # Dirigir una nota a un rol lo puede hacer el staff clínico (no finance/readonly).
        if actor_role not in ROLE_NOTE_SENDERS:
            raise ValidationError(
                "Tu rol no puede dirigir notas a un rol específico."
            )

    # 4. Validar target_role
    if scope == NoteScope.ROLE:
        if not target_role:
            raise ValidationError(
                "El campo 'target_role' es obligatorio cuando scope='role'."
            )
        if target_role not in _VALID_ROLES:
            raise ValidationError(
                f"El rol '{target_role}' no es válido. "
                f"Roles permitidos: {', '.join(sorted(_VALID_ROLES))}."
            )
    else:
        # Forzar target_role vacío para scope != role
        target_role = ""

    # 5. Crear la nota
    note = Note.objects.create(
        tenant=tenant,
        author=user,
        created_by=user,
        title=title,
        body=body,
        scope=scope,
        target_role=target_role,
        is_task=is_task,
        done=False,
        remind_at=remind_at,
        pinned=pinned,
    )

    # 6. Auditar
    action = (
        ActionType.NOTE_GLOBAL_SEND
        if scope in (NoteScope.ROLE, NoteScope.ALL)
        else ActionType.NOTE_CREATE
    )
    audit_record(
        action=action,
        resource_type="Note",
        actor=user,
        tenant=tenant,
        resource_id=note.id,
        resource_repr=str(note),
        description=(
            f"Nota global enviada a scope='{scope}'"
            if scope in (NoteScope.ROLE, NoteScope.ALL)
            else "Nota personal creada"
        ),
        metadata={
            "scope": scope,
            "target_role": target_role,
            "is_task": is_task,
        },
        actor_role=actor_role,
    )

    # 7. Reparto de notificaciones para notas globales (campana).
    #    El fanout excluye al propio autor (no auto-notificación).
    if scope == NoteScope.ROLE:
        role_label = TenantMembership.Role(target_role).label
        notification_fanout(
            tenant=tenant,
            recipients=users_with_role(tenant=tenant, role=target_role),
            kind=NotificationKind.ROLE_NOTE,
            title=title or f"Nueva nota para {role_label}",
            body=body[:200],
            actor=user,
            target_type=NotificationTarget.NOTE,
            target_id=note.id,
        )
    elif scope == NoteScope.ALL:
        notification_fanout(
            tenant=tenant,
            recipients=all_tenant_users(tenant=tenant),
            kind=NotificationKind.BROADCAST,
            title=title or "Aviso para toda la clínica",
            body=body[:200],
            actor=user,
            target_type=NotificationTarget.NOTE,
            target_id=note.id,
        )

    return note


@transaction.atomic
def note_update(
    *,
    note: Note,
    user: Any,
    tenant: Tenant,
    **fields: Any,
) -> Note:
    """Actualiza campos editables de una nota.

    Campos editables: title, body, is_task, remind_at, pinned, target_role, scope.
    Campos inmutables (bloqueados por _NOTE_IMMUTABLE_FIELDS): id, tenant, author,
    timestamps, deleted_at, done (done solo cambia via note_toggle_done).

    Regla de autorización: solo el author puede editar. Para notas globales (scope
    role/all) también el owner del tenant puede editarlas.

    Valida:
        - El usuario tiene permiso de mutación (author o owner para globales).
        - Campos inmutables no incluidos en fields.
        - Si se cambia scope a role/all: solo el owner.
        - Si se cambia scope a role: target_role obligatorio y válido.
        - Si title/body se modifican: al menos uno debe seguir teniendo contenido.

    Args:
        note:   Instancia de Note a actualizar.
        user:   Usuario que realiza la edición.
        tenant: Tenant del contexto (para verificar rol).
        **fields: Campos a actualizar (solo los editables se procesan).

    Returns:
        Instancia Note actualizada.

    Raises:
        ValidationError: si falla alguna validación de negocio.
    """
    # 1. Verificar autorización
    if not _can_mutate(note=note, user=user, tenant=tenant):
        raise ValidationError(
            "No tienes permiso para editar esta nota."
        )

    # 2. Rechazar campos inmutables
    bad_fields = set(fields) & _NOTE_IMMUTABLE_FIELDS
    if bad_fields:
        raise ValidationError(
            f"No se pueden modificar los campos: {', '.join(sorted(bad_fields))}."
        )

    # 3. Extraer campos editables conocidos (ignorar desconocidos silenciosamente)
    allowed_fields = {
        "title", "body", "is_task", "remind_at", "pinned", "target_role", "scope"
    }
    update_data = {k: v for k, v in fields.items() if k in allowed_fields}

    if not update_data:
        return note

    # 4. Calcular valores resultantes para validaciones cruzadas
    new_title = update_data.get("title", note.title)
    new_body = update_data.get("body", note.body)
    new_scope = update_data.get("scope", note.scope)
    new_target_role = update_data.get("target_role", note.target_role)

    # Normalizar strings si vienen
    if "title" in update_data:
        new_title = new_title.strip() if new_title else ""
        update_data["title"] = new_title
    if "body" in update_data:
        new_body = new_body.strip() if new_body else ""
        update_data["body"] = new_body

    # 5. Validar contenido resultante
    _validate_content(title=new_title, body=new_body)

    # 6. Validar cambio de scope (mismas reglas que note_create):
    #    scope=all → solo owner; scope=role → ROLE_NOTE_SENDERS.
    if "scope" in update_data:
        if new_scope == NoteScope.ALL and not _is_owner(user=user, tenant=tenant):
            raise ValidationError(
                "Solo el dueño puede convertir una nota en aviso a toda la clínica."
            )
        if new_scope == NoteScope.ROLE and _get_role(user=user, tenant=tenant) not in ROLE_NOTE_SENDERS:
            raise ValidationError(
                "Tu rol no puede dirigir notas a un rol específico."
            )

    # 7. Validar target_role según nuevo scope
    if new_scope == NoteScope.ROLE:
        if not new_target_role:
            raise ValidationError(
                "El campo 'target_role' es obligatorio cuando scope='role'."
            )
        if new_target_role not in _VALID_ROLES:
            raise ValidationError(
                f"El rol '{new_target_role}' no es válido. "
                f"Roles permitidos: {', '.join(sorted(_VALID_ROLES))}."
            )
    elif new_scope != NoteScope.ROLE:
        # Forzar target_role vacío si scope cambió a algo distinto de role
        update_data["target_role"] = ""

    # 8. Aplicar cambios
    for field, value in update_data.items():
        setattr(note, field, value)
    note.save(update_fields=list(update_data.keys()) + ["updated_at"])

    # 9. Auditar
    actor_role = _get_role(user=user, tenant=tenant)
    audit_record(
        action=ActionType.NOTE_UPDATE,
        resource_type="Note",
        actor=user,
        tenant=tenant,
        resource_id=note.id,
        resource_repr=str(note),
        description="Nota actualizada",
        metadata={"changed_fields": list(update_data.keys())},
        actor_role=actor_role,
    )

    return note


@transaction.atomic
def note_toggle_done(*, note: Note, user: Any, tenant: Tenant) -> Note:
    """Alterna el estado done/pendiente de una tarea.

    Solo el author puede marcar/desmarcar una tarea.
    Solo aplica cuando is_task=True.

    Args:
        note:   Nota/tarea a alternar.
        user:   Usuario que realiza el toggle.
        tenant: Tenant del contexto (para verificar autorización de auditoría).

    Returns:
        Instancia Note con done actualizado.

    Raises:
        ValidationError: si la nota no es una tarea o el usuario no es el author.
    """
    if not note.is_task:
        raise ValidationError(
            "Solo se puede marcar como hecha una nota que sea una tarea (is_task=True)."
        )

    if note.author_id != user.pk:
        raise ValidationError(
            "Solo el autor puede marcar esta tarea como hecha o pendiente."
        )

    note.done = not note.done
    note.save(update_fields=["done", "updated_at"])

    actor_role = _get_role(user=user, tenant=tenant)
    audit_record(
        action=ActionType.NOTE_UPDATE,
        resource_type="Note",
        actor=user,
        tenant=tenant,
        resource_id=note.id,
        resource_repr=str(note),
        description=f"Tarea marcada como {'hecha' if note.done else 'pendiente'}",
        metadata={"done": note.done},
        actor_role=actor_role,
    )

    return note


@transaction.atomic
def note_delete(*, note: Note, user: Any, tenant: Tenant) -> None:
    """Borra una nota con soft-delete (deleted_at = now()).

    Solo el author puede borrar su nota. Para notas globales (scope=role|all),
    también el owner del tenant puede borrarlas.

    Args:
        note:   Nota a borrar.
        user:   Usuario que realiza el borrado.
        tenant: Tenant del contexto.

    Raises:
        ValidationError: si el usuario no tiene permiso para borrar la nota.
    """
    if not _can_mutate(note=note, user=user, tenant=tenant):
        raise ValidationError(
            "No tienes permiso para eliminar esta nota."
        )

    note.deleted_at = timezone.now()
    note.save(update_fields=["deleted_at", "updated_at"])

    actor_role = _get_role(user=user, tenant=tenant)
    audit_record(
        action=ActionType.NOTE_DELETE,
        resource_type="Note",
        actor=user,
        tenant=tenant,
        resource_id=note.id,
        resource_repr=str(note),
        description="Nota eliminada (soft-delete)",
        metadata={"scope": note.scope},
        actor_role=actor_role,
    )
