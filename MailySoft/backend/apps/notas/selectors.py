"""
Selectors de la app notas.

Lecturas/queries: NUNCA modifican datos.
El TenantManager (objects) filtra automáticamente por tenant activo + soft-delete.

Convención: keyword-only args, nombrado acción+entidad.

REGLA: toda lectura de un objeto por id usa note_get; NUNCA Note.objects.get inline en views.
"""

import datetime
import uuid
from typing import Optional

from django.contrib.auth import get_user_model
from django.db.models import Q, QuerySet

from apps.notas.models import Note, NoteScope
from apps.tenancy.models import Tenant, TenantMembership

User = get_user_model()


def note_get(*, note_id: uuid.UUID) -> Note:
    """Retorna una nota por su UUID (filtrada por tenant activo y no borrada).

    Usa el TenantManager: si el id corresponde a otro tenant devuelve DoesNotExist.
    Las vistas deben capturar DoesNotExist y devolver 404 (nunca 403).

    Args:
        note_id: UUID de la nota a recuperar.

    Returns:
        Instancia de Note con relaciones precargadas para evitar N+1.

    Raises:
        Note.DoesNotExist: si no existe en el tenant activo o fue borrada (soft-delete).
    """
    return Note.objects.select_related("author").get(id=note_id)


def _get_user_role_in_tenant(*, user: User, tenant: Tenant) -> Optional[str]:  # type: ignore[valid-type]
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
    is_task: Optional[bool] = None,
    done: Optional[bool] = None,
) -> QuerySet[Note]:
    """Retorna el QuerySet de notas visibles para el usuario dado en el tenant.

    Visibilidad:
        personal: author=user AND scope=personal (solo las propias).
        role:     scope=role AND target_role == rol del usuario en el tenant.
        all:      scope=all.

    El TenantManager ya filtra por tenant activo y excluye soft-deleted.
    Filtros opcionales acumulativos (AND): is_task, done.

    Performance: select_related("author") evita N+1 en el serializer.

    Args:
        user:    Usuario para el que se calculan las notas visibles.
        tenant:  Tenant (clínica) del contexto activo.
        is_task: Si se provee, filtra solo tareas (True) o solo notas (False).
        done:    Si se provee, filtra por estado done/pendiente.

    Returns:
        QuerySet[Note] ordenado por (-pinned, -created_at) (Meta.ordering).
    """
    user_role: Optional[str] = _get_user_role_in_tenant(user=user, tenant=tenant)

    # Notas personales del autor
    personal_condition = Q(author=user, scope=NoteScope.PERSONAL)

    # Notas globales para el rol del usuario (solo si tiene rol en el tenant)
    role_condition = (
        Q(scope=NoteScope.ROLE, target_role=user_role)
        if user_role is not None
        else Q(pk__in=[])  # QuerySet vacío si no hay rol
    )

    # Notas globales para todos
    all_condition = Q(scope=NoteScope.ALL)

    qs: QuerySet[Note] = (
        Note.objects.select_related("author")
        .filter(personal_condition | role_condition | all_condition)
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
) -> QuerySet[Note]:
    """Retorna las notas visibles del usuario con remind_at dentro del rango dado.

    Solo notas con remind_at != null y dentro de [date_from, date_to).
    Aplica la misma lógica de visibilidad que note_list_visible.

    Args:
        user:      Usuario del contexto activo.
        tenant:    Tenant del contexto activo.
        date_from: Inicio del rango (inclusive) en UTC.
        date_to:   Fin del rango (exclusivo) en UTC.

    Returns:
        QuerySet[Note] con recordatorios en el rango, ordenado por remind_at ASC.
    """
    qs = note_list_visible(user=user, tenant=tenant)
    return qs.filter(
        remind_at__isnull=False,
        remind_at__gte=date_from,
        remind_at__lt=date_to,
    ).order_by("remind_at")
