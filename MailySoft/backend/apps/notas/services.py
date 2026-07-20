"""
Services de la app notas.

Toda escritura/modificación de notas pasa por aquí.
Las vistas son delgadas: parsean el request, llaman al service, devuelven respuesta.

Convención: keyword-only args en toda firma, nombrado acción+entidad.

Reglas críticas:
  1. Al menos uno de title/body debe tener contenido.
  2. scope=all (aviso a toda la clínica/sede) lo puede crear el OWNER o un
     ADMIN (el admin queda SIEMPRE forzado a SU propia sede — ver punto 8).
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
  8. Multi-sede (cierre de hueco — 2026-07-16, ver _resolve_broadcast_sucursal):
     un aviso (scope role/all) tiene `sucursal` (null = todas las sedes) e
     `is_important` (aviso destacado). El OWNER elige libremente ambos
     (cualquier sede del tenant, o null = todas; is_important como venga).
     Cualquier OTRO actor (admin incluido) queda SIEMPRE acotado a SU
     PROPIA sede (resuelta con `resolve_write_sucursal`, misma precedencia
     que agenda/personal/finanzas) y `is_important` SIEMPRE False — nunca
     puede elegir "todas las sedes" ni destacar un aviso. Las notas
     PERSONALES (scope=personal) ignoran ambos campos: siempre
     sucursal=None, is_important=False.
"""

import logging
import uuid
from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.clinica.models import Sucursal
from apps.clinica.sucursal_scope import allowed_sucursales, resolve_write_sucursal
from apps.notas.models import Note, NoteScope
from apps.notificaciones.models import NotificationKind, NotificationTarget
from apps.notificaciones.recipients import (
    ROLE_NOTE_SENDERS,
    all_tenant_users,
    filter_recipients_by_sucursal,
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
        # sucursal/is_important solo se fijan en note_create; no son
        # editables vía PATCH genérico (evita que un no-owner reasigne un
        # aviso a otra sede, o que se "cuele" un is_important=True fuera
        # del flujo de creación autorizado por _resolve_broadcast_sucursal).
        "sucursal",
        "sucursal_id",
        "is_important",
    }
)

#: Roles que pueden crear/editar un aviso scope=all (broadcast). El owner
#: siempre puede elegir cualquier sede o "todas"; el admin queda forzado a
#: su propia sede (ver _resolve_broadcast_sucursal).
_SCOPE_ALL_SENDERS: frozenset[str] = frozenset(
    {TenantMembership.Role.OWNER, TenantMembership.Role.ADMIN}
)


# ---------------------------------------------------------------------------
# Helpers privados
# ---------------------------------------------------------------------------


def _get_membership(*, user: Any, tenant: Tenant) -> TenantMembership | None:
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
        raise ValidationError("La nota debe tener al menos un título o un cuerpo con contenido.")


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
    if note.scope in (NoteScope.ROLE, NoteScope.ALL) and _is_owner(user=user, tenant=tenant):
        return True
    return False


def _resolve_broadcast_sucursal(
    *,
    tenant: Tenant,
    user: Any,
    sucursal_id: uuid.UUID | None,
    active_sucursal_id: uuid.UUID | None,
    is_important: bool,
) -> tuple[uuid.UUID | None, bool]:
    """Resuelve (sucursal_id, is_important) finales para un aviso (scope role/all).

    Modelo de negocio (decisión del dueño, 2026-07-16):
      - Actor OWNER: `sucursal_id` tal cual — None significa "todas las
        sedes" (broadcast real a toda la clínica); un UUID debe ser una
        sucursal activa del propio tenant. `is_important` se respeta tal
        cual (el owner es el único que puede destacar un aviso).
      - Cualquier OTRO actor (admin incluido): SIEMPRE queda acotado a SU
        propia sede. Se resuelve con `resolve_write_sucursal` (misma
        precedencia que agenda/personal/finanzas: explícita > sede activa
        del header > predeterminada del tenant) y esa función YA valida el
        resultado contra `allowed_sucursales(user, tenant)` — un admin de
        Centro no puede colarse a Norte ni mandando `sucursal_id` explícito
        de Norte ni omitiendo el header y cayendo en un default ajeno.
        `is_important` se fuerza a False; si vino True, se rechaza
        explícitamente (mensaje claro en vez de "silenciarlo").

    Args:
        tenant:             Clínica del contexto.
        user:                Actor que crea/edita el aviso.
        sucursal_id:         Sede explícita indicada por el cliente (owner) o
                              None. Para un no-owner, típicamente None (la
                              vista no le permite elegir) — ver
                              `resolve_write_sucursal` para la precedencia.
        active_sucursal_id:  Sede activa del request (header X-Sucursal-Id),
                              resuelta por la vista. Solo aplica al camino
                              no-owner.
        is_important:        Valor solicitado para el flag de destacado.

    Returns:
        Tupla (sucursal_id resuelto o None, is_important resuelto).

    Raises:
        ValidationError: sucursal_id inválida o fuera del tenant/alcance del
            actor; is_important=True solicitado por un no-owner.
    """
    if _is_owner(user=user, tenant=tenant):
        if sucursal_id is None:
            return None, is_important
        resolved = allowed_sucursales(user=user, tenant=tenant).filter(id=sucursal_id).first()
        if resolved is None:
            raise ValidationError("Sucursal no encontrada en esta clínica o no está activa.")
        return resolved.id, is_important

    if is_important:
        raise ValidationError("Solo el dueño de la clínica puede marcar un aviso como importante.")

    resolved_sucursal: Sucursal | None = resolve_write_sucursal(
        tenant=tenant,
        user=user,
        sucursal_id=sucursal_id,
        active_sucursal_id=active_sucursal_id,
    )
    return (resolved_sucursal.id if resolved_sucursal is not None else None), False


# El filtro de destinatarios por sede se movió a
# apps.notificaciones.recipients.filter_recipients_by_sucursal (compartido por
# notas/agenda/expediente). Aquí se usa vía ese import.


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
    remind_at: Any | None = None,
    pinned: bool = False,
    sucursal_id: uuid.UUID | None = None,
    active_sucursal_id: uuid.UUID | None = None,
    is_important: bool = False,
) -> Note:
    """Crea una nueva nota o tarea dentro del tenant.

    Valida:
        - title o body deben tener contenido.
        - scope=all solo para owner/admin; scope=role para ROLE_NOTE_SENDERS
          (ValidationError si un rol sin permiso lo intenta).
        - target_role obligatorio y válido cuando scope=role.
        - target_role forzado a "" cuando scope != role.
        - sucursal/is_important (solo aplican a scope role/all — ver
          _resolve_broadcast_sucursal): el owner elige libremente
          (sucursal=None es "todas las sedes"); cualquier otro actor queda
          forzado a SU sede e is_important=False. Las notas personales
          ignoran ambos (siempre sucursal=None, is_important=False).

    Audita:
        - NOTE_CREATE para notas personales.
        - NOTE_GLOBAL_SEND para notas con scope=role o scope=all.

    Args:
        tenant:              Clínica en la que se crea la nota.
        user:                Usuario autor de la nota.
        body:                Cuerpo de la nota (puede estar vacío si title tiene contenido).
        title:               Título breve (puede estar vacío si body tiene contenido).
        scope:               Audiencia: personal | role | all. Default: personal.
        target_role:         Rol destinatario cuando scope=role. Se ignora/vacía en otros scopes.
        is_task:             Si True, es una tarea con checkbox.
        remind_at:           Fecha/hora UTC de recordatorio. None = sin recordatorio.
        pinned:              Si True, aparece al tope del listado.
        sucursal_id:         Sede explícita para el aviso (solo relevante en
                              scope role/all). Para el owner, None = "todas
                              las sedes". Para cualquier otro actor se
                              re-resuelve siempre contra su propia sede
                              (ver _resolve_broadcast_sucursal); la vista lo
                              pasa igualmente por si el owner lo indicó.
        active_sucursal_id:  Sede activa del request (header X-Sucursal-Id),
                              resuelta por la vista. Solo se usa para
                              resolver la sede de un actor NO-owner.
        is_important:        Si True, marca el aviso como destacado. Solo el
                              owner puede dejarlo en True; cualquier otro
                              actor lo fuerza/rechaza (ver
                              _resolve_broadcast_sucursal).

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
        # El aviso a TODA la clínica/sede lo puede enviar el dueño o un
        # administrador (el admin queda forzado a SU sede — punto 8 del
        # docstring del módulo; ya NO es exclusivo del owner).
        if actor_role not in _SCOPE_ALL_SENDERS:
            raise ValidationError(
                "Solo el dueño o un administrador pueden enviar un aviso "
                "a toda la clínica (scope='all')."
            )
    elif scope == NoteScope.ROLE:
        # Dirigir una nota a un rol lo puede hacer el staff clínico (no finance/readonly).
        if actor_role not in ROLE_NOTE_SENDERS:
            raise ValidationError("Tu rol no puede dirigir notas a un rol específico.")

    # 4. Validar target_role
    if scope == NoteScope.ROLE:
        if not target_role:
            raise ValidationError("El campo 'target_role' es obligatorio cuando scope='role'.")
        if target_role not in _VALID_ROLES:
            raise ValidationError(
                f"El rol '{target_role}' no es válido. "
                f"Roles permitidos: {', '.join(sorted(_VALID_ROLES))}."
            )
    else:
        # Forzar target_role vacío para scope != role
        target_role = ""

    # 5. Resolver sucursal/is_important (solo aplica a avisos role/all).
    #    Las notas personales ignoran ambos campos (privadas, sin sede).
    if scope == NoteScope.PERSONAL:
        final_sucursal_id: uuid.UUID | None = None
        final_is_important = False
    else:
        final_sucursal_id, final_is_important = _resolve_broadcast_sucursal(
            tenant=tenant,
            user=user,
            sucursal_id=sucursal_id,
            active_sucursal_id=active_sucursal_id,
            is_important=is_important,
        )

    # 6. Crear la nota
    note = Note.objects.create(
        tenant=tenant,
        author=user,
        created_by=user,
        title=title,
        body=body,
        scope=scope,
        target_role=target_role,
        sucursal_id=final_sucursal_id,
        is_important=final_is_important,
        is_task=is_task,
        done=False,
        remind_at=remind_at,
        pinned=pinned,
    )

    # 7. Auditar
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
            "sucursal_id": str(final_sucursal_id) if final_sucursal_id else None,
            "is_important": final_is_important,
        },
        actor_role=actor_role,
    )

    # 8. Reparto de notificaciones para avisos (campana).
    #    El fanout excluye al propio autor (no auto-notificación).
    #    Cierre de hueco de sedes: si el aviso quedó acotado a una sucursal
    #    (final_sucursal_id != None), la campana SOLO debe llegar a quien
    #    puede ver esa sede (mismo criterio que note_list_visible) — si no,
    #    un no-owner de Norte recibiría una notificación apuntando a un
    #    aviso de Centro que ni siquiera puede abrir en /notas/.
    #    sucursal_id=None ("todas las sedes") no filtra nada.
    if scope == NoteScope.ROLE:
        role_label = TenantMembership.Role(target_role).label
        notification_fanout(
            tenant=tenant,
            recipients=filter_recipients_by_sucursal(
                tenant=tenant,
                recipients=users_with_role(tenant=tenant, role=target_role),
                sucursal_id=final_sucursal_id,
            ),
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
            recipients=filter_recipients_by_sucursal(
                tenant=tenant,
                recipients=all_tenant_users(tenant=tenant),
                sucursal_id=final_sucursal_id,
            ),
            kind=NotificationKind.BROADCAST,
            title=title
            or ("Aviso importante" if final_is_important else "Aviso para toda la clínica"),
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
        - Campos inmutables no incluidos en fields (incluye sucursal/is_important:
          no editables — se fijan solo en note_create).
        - Si se cambia scope a all: owner o admin. Si se cambia a role: ROLE_NOTE_SENDERS.
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
        raise ValidationError("No tienes permiso para editar esta nota.")

    # 2. Rechazar campos inmutables
    bad_fields = set(fields) & _NOTE_IMMUTABLE_FIELDS
    if bad_fields:
        raise ValidationError(
            f"No se pueden modificar los campos: {', '.join(sorted(bad_fields))}."
        )

    # 3. Extraer campos editables conocidos (ignorar desconocidos silenciosamente)
    allowed_fields = {"title", "body", "is_task", "remind_at", "pinned", "target_role", "scope"}
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
    #    scope=all → owner o admin; scope=role → ROLE_NOTE_SENDERS.
    #    Nota: la sucursal/is_important de la nota NO se tocan aquí (no son
    #    campos editables — ver _NOTE_IMMUTABLE_FIELDS); un admin que
    #    convierte su propio aviso a scope=all conserva la sede con la que
    #    fue creado (forzada a la suya en note_create).
    if "scope" in update_data:
        if (
            new_scope == NoteScope.ALL
            and _get_role(user=user, tenant=tenant) not in _SCOPE_ALL_SENDERS
        ):
            raise ValidationError(
                "Solo el dueño o un administrador pueden convertir un aviso "
                "en 'toda la clínica' (scope='all')."
            )
        if (
            new_scope == NoteScope.ROLE
            and _get_role(user=user, tenant=tenant) not in ROLE_NOTE_SENDERS
        ):
            raise ValidationError("Tu rol no puede dirigir notas a un rol específico.")

    # 7. Validar target_role según nuevo scope
    if new_scope == NoteScope.ROLE:
        if not new_target_role:
            raise ValidationError("El campo 'target_role' es obligatorio cuando scope='role'.")
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
        raise ValidationError("Solo el autor puede marcar esta tarea como hecha o pendiente.")

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
        raise ValidationError("No tienes permiso para eliminar esta nota.")

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
