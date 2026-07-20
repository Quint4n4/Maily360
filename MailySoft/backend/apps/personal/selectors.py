"""
Selectors de la app personal.

Lecturas/queries: NUNCA modifican datos.
El TenantManager (objects) filtra automáticamente por el tenant activo en el
thread-local cuando context_active=True.

Convención: keyword-only args, nombrado acción+entidad.
"""

import uuid

from django.contrib.auth import get_user_model
from django.db.models import Q, QuerySet

from apps.personal.models import Consultorio, Doctor, DoctorSchedule

_User = get_user_model()


def doctor_get(*, doctor_id: uuid.UUID) -> Doctor:
    """Retorna un Doctor por su UUID.

    Usa el TenantManager (filtra por tenant del contexto activo).
    Lanza Doctor.DoesNotExist si no existe o no pertenece al tenant activo.
    Las vistas deben capturar DoesNotExist y devolver 404.

    Args:
        doctor_id: UUID del Doctor a recuperar.

    Returns:
        Instancia de Doctor con membership__user pre-cargado y consultorios/
        sucursales prefetchados (M2M) para evitar N+1 al serializar.

    Raises:
        Doctor.DoesNotExist: si el doctor no existe en el tenant activo.
    """
    return (
        Doctor.objects.select_related("membership__user")
        .prefetch_related("consultorios", "sucursales")
        .get(id=doctor_id)
    )


def doctor_list(
    *,
    search: str = "",
    only_active: bool = True,
    sucursal_id: uuid.UUID | None = None,
    sucursal_ids: list[uuid.UUID] | None = None,
) -> QuerySet[Doctor]:
    """Retorna el QuerySet de doctores del tenant actual.

    Evita N+1 con select_related("membership__user") para poder acceder
    al full_name sin queries adicionales, y prefetch_related("consultorios")
    para el M2M de consultorios asignados.

    Args:
        search:       Término libre. Filtra por specialty, nombre, apellido o email
                      del usuario asociado (OR icontains). Si es vacío, sin filtro.
        only_active:  Si True (default), retorna solo doctores con is_active=True.
        sucursal_id:  Si se provee (multi-sede — Fase 1), filtra a los doctores
                      asignados a esa sucursal (Doctor.sucursales). None = sin
                      filtro (compatibilidad retro: todas las sedes).
        sucursal_ids: Lista de sucursales permitidas (multi-sede — Fase 3,
                      seguridad; ver `sucursal_scope_ids`). Si se provee,
                      tiene prioridad sobre `sucursal_id`. Usa `.distinct()`
                      porque el M2M puede duplicar filas cuando el doctor
                      está asignado a más de una sede de la lista.

    Returns:
        QuerySet[Doctor] filtrado y ordenado. Sin paginar (paginación en la vista).
    """
    qs: QuerySet[Doctor] = Doctor.objects.select_related("membership__user").prefetch_related(
        "consultorios", "sucursales"
    )

    if only_active:
        qs = qs.filter(is_active=True)

    if sucursal_ids is not None:
        qs = qs.filter(sucursales__id__in=sucursal_ids).distinct()
    elif sucursal_id is not None:
        qs = qs.filter(sucursales__id=sucursal_id)

    if search:
        qs = qs.filter(
            Q(specialty__icontains=search)
            | Q(membership__user__first_name__icontains=search)
            | Q(membership__user__last_name__icontains=search)
            | Q(membership__user__email__icontains=search)
        )

    return qs.order_by("-created_at")


def consultorio_get(
    *,
    consultorio_id: uuid.UUID,
    sucursal_ids: list[uuid.UUID] | None = None,
) -> Consultorio:
    """Retorna un Consultorio por su UUID.

    Usa el TenantManager (filtra por tenant del contexto activo).
    Lanza Consultorio.DoesNotExist si no existe o no pertenece al tenant activo.

    Args:
        consultorio_id: UUID del Consultorio a recuperar.
        sucursal_ids:   Alcance de sucursales del actor (multi-sede — Fase 3,
                        seguridad, A5; ver `sucursal_scope_ids`). Si se
                        provee, el consultorio debe pertenecer a una de esas
                        sedes o `DoesNotExist` (404) — el mismo criterio de
                        `consultorio_list`, para que detalle/PATCH/DELETE
                        acoten EXACTAMENTE igual que el listado. None = sin
                        filtro (compatibilidad retro).

    Returns:
        Instancia de Consultorio.

    Raises:
        Consultorio.DoesNotExist: si el consultorio no existe en el tenant
            activo, o no pertenece a ninguna de las sedes de `sucursal_ids`.
    """
    qs = Consultorio.objects.select_related("sucursal")
    if sucursal_ids is not None:
        qs = qs.filter(sucursal_id__in=sucursal_ids)
    return qs.get(id=consultorio_id)


def consultorio_list(
    *,
    only_active: bool = True,
    sucursal_id: uuid.UUID | None = None,
    sucursal_ids: list[uuid.UUID] | None = None,
) -> QuerySet[Consultorio]:
    """Retorna el QuerySet de consultorios del tenant actual.

    Args:
        only_active:  Si True (default), retorna solo consultorios con is_active=True.
        sucursal_id:  Si se provee (multi-sede — Fase 1), filtra a los consultorios
                      de esa sucursal (Consultorio.sucursal_id). None = sin filtro
                      (compatibilidad retro: todas las sedes).
        sucursal_ids: Lista de sucursales permitidas (multi-sede — Fase 3,
                      seguridad; ver `sucursal_scope_ids`). Si se provee,
                      tiene prioridad sobre `sucursal_id`.

    Returns:
        QuerySet[Consultorio] filtrado y ordenado por nombre.
    """
    qs: QuerySet[Consultorio] = Consultorio.objects.select_related("sucursal")

    if only_active:
        qs = qs.filter(is_active=True)

    if sucursal_ids is not None:
        qs = qs.filter(sucursal_id__in=sucursal_ids)
    elif sucursal_id is not None:
        qs = qs.filter(sucursal_id=sucursal_id)

    return qs.order_by("name")


def schedule_get(
    *,
    schedule_id: uuid.UUID,
    sucursal_ids: list[uuid.UUID] | None = None,
) -> DoctorSchedule:
    """Retorna un DoctorSchedule por su UUID.

    Usa el TenantManager (objects), que filtra automáticamente por tenant
    del contexto activo. Garantiza aislamiento multi-tenant: un schedule de
    otro tenant lanza DoesNotExist → la vista devuelve 404 (no 403).

    Args:
        schedule_id:  UUID del DoctorSchedule a recuperar.
        sucursal_ids: Alcance de sucursales del actor (multi-sede — Fase 3,
                      seguridad, A4; ver `sucursal_scope_ids`). Si se provee,
                      el horario debe pertenecer a una de esas sedes o
                      `DoesNotExist` (404) — mismo criterio que
                      `schedule_list_for_doctor`, para que el DELETE por id
                      acote EXACTAMENTE igual que el listado. None = sin
                      filtro (compatibilidad retro).

    Returns:
        Instancia de DoctorSchedule.

    Raises:
        DoctorSchedule.DoesNotExist: si el schedule no existe en el tenant
            activo, o no pertenece a ninguna de las sedes de `sucursal_ids`.
    """
    # FIX-F2: usar TenantManager (.objects) en lugar de query directa al modelo.
    # El TenantManager filtra por tenant activo, previniendo IDOR cross-tenant.
    qs = DoctorSchedule.objects.select_related("consultorio", "doctor", "sucursal")
    if sucursal_ids is not None:
        qs = qs.filter(sucursal_id__in=sucursal_ids)
    return qs.get(id=schedule_id)


def schedule_list_for_doctor(
    *,
    doctor: Doctor,
    sucursal_ids: list[uuid.UUID] | None = None,
) -> QuerySet[DoctorSchedule]:
    """Retorna los horarios activos de un médico, ordenados por día y hora.

    Incluye select_related("consultorio") para evitar N+1 al serializar
    el consultorio asociado a cada bloque de horario.

    El TenantManager ya filtra por tenant del contexto activo. Los horarios
    pertenecen al mismo tenant que el doctor, así que el filtro es coherente.

    Args:
        doctor:       Instancia Doctor cuyos horarios se listan.
        sucursal_ids: Alcance de sucursales del actor (multi-sede — Fase 3,
                      seguridad, A4; ver `sucursal_scope_ids`). Si se
                      provee, solo se listan los horarios de esas sedes. Un
                      médico puede tener horarios en varias sucursales; un
                      actor acotado a una sola sede ya no ve los horarios de
                      las otras solo porque conoce el `doctor_id`. None =
                      sin filtro (compatibilidad retro).

    Returns:
        QuerySet[DoctorSchedule] activos, ordenados por day_of_week, start_time.
    """
    qs = (
        DoctorSchedule.objects.select_related("consultorio", "sucursal")
        .filter(doctor=doctor, is_active=True)
        .order_by("day_of_week", "start_time")
    )
    if sucursal_ids is not None:
        qs = qs.filter(sucursal_id__in=sucursal_ids)
    return qs


def doctor_get_for_user(
    *,
    user: "_User",  # type: ignore[valid-type]
    tenant_id: uuid.UUID,
) -> Doctor | None:
    """Retorna el Doctor activo del usuario en el tenant dado, o None.

    Busca a través de la FK membership → TenantMembership → user, filtrando
    por tenant_id explícitamente. Usa all_objects (no el TenantManager) porque
    esta función puede llamarse sin contexto de tenant activo (p. ej. desde
    appointment_create o desde /me/).

    Solo retorna el Doctor si:
    - La membresía es activa (is_active=True, deleted_at IS NULL).
    - El Doctor no está soft-deleted (deleted_at IS NULL).
    - El Doctor está activo (is_active=True).

    Args:
        user:      Usuario del que se busca el Doctor.
        tenant_id: UUID del tenant en el que buscar.

    Returns:
        Instancia Doctor o None si el usuario no tiene un Doctor activo en
        ese tenant.
    """
    return (
        Doctor.all_objects.filter(
            tenant_id=tenant_id,
            is_active=True,
            deleted_at__isnull=True,
            membership__user=user,
            membership__is_active=True,
            membership__deleted_at__isnull=True,
        )
        .select_related("membership__user")
        .first()
    )
