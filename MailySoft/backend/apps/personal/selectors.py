"""
Selectors de la app personal.

Lecturas/queries: NUNCA modifican datos.
El TenantManager (objects) filtra automáticamente por el tenant activo en el
thread-local cuando context_active=True.

Convención: keyword-only args, nombrado acción+entidad.
"""

import uuid

from django.db.models import Q, QuerySet

from apps.personal.models import Consultorio, Doctor, DoctorSchedule


def doctor_get(*, doctor_id: uuid.UUID) -> Doctor:
    """Retorna un Doctor por su UUID.

    Usa el TenantManager (filtra por tenant del contexto activo).
    Lanza Doctor.DoesNotExist si no existe o no pertenece al tenant activo.
    Las vistas deben capturar DoesNotExist y devolver 404.

    Args:
        doctor_id: UUID del Doctor a recuperar.

    Returns:
        Instancia de Doctor con membership__user pre-cargado.

    Raises:
        Doctor.DoesNotExist: si el doctor no existe en el tenant activo.
    """
    return Doctor.objects.select_related("membership__user").get(id=doctor_id)


def doctor_list(*, search: str = "", only_active: bool = True) -> QuerySet[Doctor]:
    """Retorna el QuerySet de doctores del tenant actual.

    Evita N+1 con select_related("membership__user") para poder acceder
    al full_name sin queries adicionales al serializar la lista.

    Args:
        search:      Término libre. Filtra por specialty, nombre, apellido o email
                     del usuario asociado (OR icontains). Si es vacío, sin filtro.
        only_active: Si True (default), retorna solo doctores con is_active=True.

    Returns:
        QuerySet[Doctor] filtrado y ordenado. Sin paginar (paginación en la vista).
    """
    qs: QuerySet[Doctor] = Doctor.objects.select_related("membership__user")

    if only_active:
        qs = qs.filter(is_active=True)

    if search:
        qs = qs.filter(
            Q(specialty__icontains=search)
            | Q(membership__user__first_name__icontains=search)
            | Q(membership__user__last_name__icontains=search)
            | Q(membership__user__email__icontains=search)
        )

    return qs.order_by("-created_at")


def consultorio_get(*, consultorio_id: uuid.UUID) -> Consultorio:
    """Retorna un Consultorio por su UUID.

    Usa el TenantManager (filtra por tenant del contexto activo).
    Lanza Consultorio.DoesNotExist si no existe o no pertenece al tenant activo.

    Args:
        consultorio_id: UUID del Consultorio a recuperar.

    Returns:
        Instancia de Consultorio.

    Raises:
        Consultorio.DoesNotExist: si el consultorio no existe en el tenant activo.
    """
    return Consultorio.objects.get(id=consultorio_id)


def consultorio_list(*, only_active: bool = True) -> QuerySet[Consultorio]:
    """Retorna el QuerySet de consultorios del tenant actual.

    Args:
        only_active: Si True (default), retorna solo consultorios con is_active=True.

    Returns:
        QuerySet[Consultorio] filtrado y ordenado por nombre.
    """
    qs: QuerySet[Consultorio] = Consultorio.objects.all()

    if only_active:
        qs = qs.filter(is_active=True)

    return qs.order_by("name")


def schedule_get(*, schedule_id: uuid.UUID) -> DoctorSchedule:
    """Retorna un DoctorSchedule por su UUID.

    Usa el TenantManager (objects), que filtra automáticamente por tenant
    del contexto activo. Garantiza aislamiento multi-tenant: un schedule de
    otro tenant lanza DoesNotExist → la vista devuelve 404 (no 403).

    Args:
        schedule_id: UUID del DoctorSchedule a recuperar.

    Returns:
        Instancia de DoctorSchedule.

    Raises:
        DoctorSchedule.DoesNotExist: si el schedule no existe en el tenant activo.
    """
    # FIX-F2: usar TenantManager (.objects) en lugar de query directa al modelo.
    # El TenantManager filtra por tenant activo, previniendo IDOR cross-tenant.
    return DoctorSchedule.objects.select_related("consultorio", "doctor").get(
        id=schedule_id
    )


def schedule_list_for_doctor(*, doctor: Doctor) -> QuerySet[DoctorSchedule]:
    """Retorna los horarios activos de un médico, ordenados por día y hora.

    Incluye select_related("consultorio") para evitar N+1 al serializar
    el consultorio asociado a cada bloque de horario.

    El TenantManager ya filtra por tenant del contexto activo. Los horarios
    pertenecen al mismo tenant que el doctor, así que el filtro es coherente.

    Args:
        doctor: Instancia Doctor cuyos horarios se listan.

    Returns:
        QuerySet[DoctorSchedule] activos, ordenados por day_of_week, start_time.
    """
    return (
        DoctorSchedule.objects
        .select_related("consultorio")
        .filter(doctor=doctor, is_active=True)
        .order_by("day_of_week", "start_time")
    )
