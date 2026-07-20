"""
Selectors de la app notas.

Lecturas/queries: NUNCA modifican datos.
El TenantManager (objects) filtra automáticamente por tenant activo + soft-delete.

Convención: keyword-only args, nombrado acción+entidad.

REGLA: toda lectura de un objeto por id usa note_get; NUNCA Note.objects.get inline en views.
"""

import datetime
import uuid

from django.contrib.auth import get_user_model
from django.db.models import Q, QuerySet

from apps.notas.models import Note, NoteScope
from apps.tenancy.models import Tenant, TenantMembership

User = get_user_model()


def note_get(
    *,
    note_id: uuid.UUID,
    user: User | None = None,  # type: ignore[valid-type]
    sucursal_ids: list[uuid.UUID] | None = None,
) -> Note:
    """Retorna una nota por su UUID (filtrada por tenant activo y no borrada).

    Usa el TenantManager: si el id corresponde a otro tenant devuelve DoesNotExist.
    Las vistas deben capturar DoesNotExist y devolver 404 (nunca 403).

    Multi-sede (cierre de hueco — 2026-07-16): `sucursal_ids` acota qué notas
    son "alcanzables por id" para mutación (PATCH/DELETE/toggle-done). Si se
    provee (actor con alcance PARCIAL — ver
    `apps.clinica.sucursal_scope.sucursal_scope_ids`), la nota solo se
    encuentra si:
        - es una nota PERSONAL del propio `user` (sin noción de sede), o
        - es un aviso (scope role/all) cuya `sucursal` es None ("todas las
          sedes") o está en `sucursal_ids`, Y NO es `is_important` — los
          avisos importantes (solo los crea el owner) quedan
          intencionalmente fuera del alcance de mutación de un no-owner
          aunque SÍ sean visibles en el listado (`note_list_visible`, que
          no aplica este filtro de importancia). Esto hace que "editar/
          borrar un aviso de otra sede o uno importante ajeno" devuelva 404
          en vez de revelar su existencia con un 400 de autorización.
        - `sucursal_ids=None` (actor con alcance TOTAL, p. ej. owner, o
          llamada retro-compatible sin scoping): sin filtro, exactamente el
          comportamiento anterior.

    `user` es requerido cuando se provee `sucursal_ids` (para resolver la
    rama de notas personales propias); se ignora si `sucursal_ids` es None.

    Args:
        note_id:      UUID de la nota a recuperar.
        user:         Usuario para el que se resuelve el alcance de
                      mutación (solo relevante junto con `sucursal_ids`).
        sucursal_ids: Lista de UUIDs de sucursal permitidas para el actor, o
                      None para alcance total (ver `sucursal_scope_ids`).

    Returns:
        Instancia de Note con relaciones precargadas para evitar N+1.

    Raises:
        Note.DoesNotExist: si no existe en el tenant activo, fue borrada
            (soft-delete), o cae fuera del alcance indicado por
            `sucursal_ids`.
    """
    qs = Note.objects.select_related("author", "sucursal")
    if sucursal_ids is not None:
        qs = qs.filter(
            Q(author=user, scope=NoteScope.PERSONAL)
            | Q(
                scope__in=(NoteScope.ROLE, NoteScope.ALL),
                is_important=False,
                sucursal_id__isnull=True,
            )
            | Q(
                scope__in=(NoteScope.ROLE, NoteScope.ALL),
                is_important=False,
                sucursal_id__in=sucursal_ids,
            )
        )
    return qs.get(id=note_id)


def _get_user_role_in_tenant(*, user: User, tenant: Tenant) -> str | None:  # type: ignore[valid-type]
    """Retorna el rol del usuario en el tenant dado, o None si no tiene membresía activa.

    Usa all_objects para ser seguro fuera de contexto HTTP (Celery, management commands).
    Excluye membresías soft-deleted o inactivas.

    Args:
        user:   Usuario cuyo rol se quiere conocer.
        tenant: Tenant en el que se busca la membresía.

    Returns:
        El rol (str) o None.
    """
    try:
        membership = TenantMembership.objects.get(
            user=user,
            tenant=tenant,
            is_active=True,
            deleted_at__isnull=True,
        )
        return str(membership.role)
    except TenantMembership.DoesNotExist:
        return None


def note_list_visible(
    *,
    user: User,  # type: ignore[valid-type]
    tenant: Tenant,
    is_task: bool | None = None,
    done: bool | None = None,
    sucursal_ids: list[uuid.UUID] | None = None,
) -> QuerySet[Note]:
    """Retorna el QuerySet de notas visibles para el usuario dado en el tenant.

    Visibilidad:
        personal: author=user AND scope=personal (solo las propias; sin
                  noción de sede).
        role:     scope=role AND target_role == rol del usuario en el tenant,
                  Y (sucursal es None="todas las sedes" O está en `sucursal_ids`).
        all:      scope=all, Y (sucursal es None O está en `sucursal_ids`).

    El TenantManager ya filtra por tenant activo y excluye soft-deleted.
    Filtros opcionales acumulativos (AND): is_task, done.

    Multi-sede (cierre de hueco — 2026-07-16): `sucursal_ids` es el alcance
    de sedes del VIEWER (`apps.clinica.sucursal_scope.sucursal_scope_ids`,
    resuelto por la vista — este selector es PURO, no toca el Request). Un
    aviso (role/all) es visible si su `sucursal` es None (aviso de "toda la
    clínica") O si está dentro de `sucursal_ids`. `sucursal_ids=None`
    (alcance TOTAL: owner, o llamada retro-compatible) no aplica ningún
    filtro adicional — mismo comportamiento que antes de multi-sede. A
    diferencia de `note_get` (usado para mutación), aquí NO se excluyen los
    avisos `is_important` — son destacados precisamente para que todo el
    mundo en el alcance de sede los vea en el listado.

    Performance: select_related("author", "sucursal") evita N+1 en el serializer.

    Args:
        user:         Usuario para el que se calculan las notas visibles.
        tenant:       Tenant (clínica) del contexto activo.
        is_task:      Si se provee, filtra solo tareas (True) o solo notas (False).
        done:         Si se provee, filtra por estado done/pendiente.
        sucursal_ids: Alcance de sedes del viewer, o None para alcance total.

    Returns:
        QuerySet[Note] ordenado por (-pinned, -created_at) (Meta.ordering).
    """
    user_role: str | None = _get_user_role_in_tenant(user=user, tenant=tenant)

    # Notas personales del autor (sin noción de sede: no se acotan por sucursal_ids).
    personal_condition = Q(author=user, scope=NoteScope.PERSONAL)

    # Notas globales para el rol del usuario (solo si tiene rol en el tenant)
    role_condition = (
        Q(scope=NoteScope.ROLE, target_role=user_role)
        if user_role is not None
        else Q(pk__in=[])  # QuerySet vacío si no hay rol
    )

    # Notas globales para todos
    all_condition = Q(scope=NoteScope.ALL)

    if sucursal_ids is not None:
        # Alcance PARCIAL de sede: un aviso (role/all) solo es visible si es
        # de "todas las sedes" (sucursal NULL) o cae dentro del alcance.
        sucursal_condition = Q(sucursal_id__isnull=True) | Q(sucursal_id__in=sucursal_ids)
        role_condition &= sucursal_condition
        all_condition &= sucursal_condition

    qs: QuerySet[Note] = Note.objects.select_related("author", "sucursal").filter(
        personal_condition | role_condition | all_condition
    )

    if is_task is not None:
        qs = qs.filter(is_task=is_task)

    if done is not None:
        qs = qs.filter(done=done)

    return qs


def note_reminders_for_user(
    *,
    user: User,  # type: ignore[valid-type]
    tenant: Tenant,
    date_from: datetime.datetime,
    date_to: datetime.datetime,
    sucursal_ids: list[uuid.UUID] | None = None,
) -> QuerySet[Note]:
    """Retorna las notas visibles del usuario con remind_at dentro del rango dado.

    Solo notas con remind_at != null y dentro de [date_from, date_to).
    Aplica la misma lógica de visibilidad que note_list_visible, incluido el
    acotamiento por sede (`sucursal_ids` — cierre de hueco 2026-07-16).

    Args:
        user:         Usuario del contexto activo.
        tenant:       Tenant del contexto activo.
        date_from:    Inicio del rango (inclusive) en UTC.
        date_to:      Fin del rango (exclusivo) en UTC.
        sucursal_ids: Alcance de sedes del viewer, o None para alcance total.

    Returns:
        QuerySet[Note] con recordatorios en el rango, ordenado por remind_at ASC.
    """
    qs = note_list_visible(user=user, tenant=tenant, sucursal_ids=sucursal_ids)
    return qs.filter(
        remind_at__isnull=False,
        remind_at__gte=date_from,
        remind_at__lt=date_to,
    ).order_by("remind_at")
