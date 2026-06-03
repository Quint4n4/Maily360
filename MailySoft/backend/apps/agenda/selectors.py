"""
Selectors de la app agenda.

Lecturas/queries: NUNCA modifican datos.
El TenantManager (objects) filtra automáticamente por el tenant activo en el
thread-local cuando context_active=True.

Convención: keyword-only args, nombrado acción+entidad.

Regla (arquitectura): toda lectura de un objeto por id pasa por un selector.
NUNCA usar Appointment.objects.get() directo en vistas.
"""

import datetime
import uuid
from typing import Optional

from django.db.models import QuerySet

from apps.agenda.models import Appointment, AppointmentReminder, TenantAgendaConfig
from apps.tenancy.models import Tenant


def appointment_get(*, appointment_id: uuid.UUID) -> Appointment:
    """Retorna una cita por su UUID.

    Usa el TenantManager (filtra por tenant del contexto activo).
    Lanza Appointment.DoesNotExist si no existe o no pertenece al tenant activo.
    Las vistas deben capturar DoesNotExist y devolver 404 (nunca 403).

    Args:
        appointment_id: UUID de la cita a recuperar.

    Returns:
        Instancia de Appointment con relaciones pre-cargadas para evitar N+1.

    Raises:
        Appointment.DoesNotExist: si la cita no existe en el tenant activo.
    """
    return (
        Appointment.objects
        .select_related(
            "patient",
            "doctor__membership__user",
            "consultorio",
            "cancelled_by",
            "no_show_registered_by",
        )
        .prefetch_related("reminders")
        .get(id=appointment_id)
    )


def appointment_list(
    *,
    doctor_id: Optional[uuid.UUID] = None,
    patient_id: Optional[uuid.UUID] = None,
    consultorio_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
    date_from: Optional[datetime.datetime] = None,
    date_to: Optional[datetime.datetime] = None,
) -> QuerySet[Appointment]:
    """Retorna el QuerySet de citas del tenant actual con filtros opcionales.

    Todos los filtros son opcionales y se aplican acumulativamente (AND).
    El TenantManager ya filtra por tenant activo — no necesita argumento tenant.
    La paginación la aplica la vista.

    Filtros:
        doctor_id:      UUID del médico (calendar view por doctor).
        patient_id:     UUID del paciente (historial del paciente).
        consultorio_id: UUID del consultorio (calendar view por consultorio).
        status:         Valor del Status.choices (p.ej. "scheduled").
        date_from:      Citas que empiezan en o después de esta fecha/hora UTC.
        date_to:        Citas que empiezan antes de esta fecha/hora UTC.

    Returns:
        QuerySet[Appointment] filtrado, con select_related para evitar N+1,
        ordenado por starts_at ASC (útil para calendarios).

    Performance: select_related cubre doctor→membership→user, patient, consultorio.
    """
    qs: QuerySet[Appointment] = (
        Appointment.objects
        .select_related(
            "patient",
            "doctor__membership__user",
            "consultorio",
        )
        .prefetch_related("reminders")
    )

    if doctor_id is not None:
        qs = qs.filter(doctor_id=doctor_id)

    if patient_id is not None:
        qs = qs.filter(patient_id=patient_id)

    if consultorio_id is not None:
        qs = qs.filter(consultorio_id=consultorio_id)

    if status is not None:
        qs = qs.filter(status=status)

    if date_from is not None:
        qs = qs.filter(starts_at__gte=date_from)

    if date_to is not None:
        qs = qs.filter(starts_at__lt=date_to)

    return qs.order_by("starts_at")


def agenda_config_get(*, tenant: Tenant) -> TenantAgendaConfig:
    """Retorna la configuración de agenda de un tenant, creándola con defaults si no existe.

    Se usa all_objects para que funcione fuera de contexto de request
    (Celery, management commands) sin depender del TenantManager.

    Args:
        tenant: Instancia del Tenant cuya config se busca/crea.

    Returns:
        Instancia TenantAgendaConfig del tenant. Siempre existe (get_or_create).
    """
    config, _ = TenantAgendaConfig.all_objects.get_or_create(
        tenant=tenant,
        defaults={
            "created_by": None,
            "record_number_format": "EXP-{year}-{seq:05d}",
            "record_number_reset_yearly": False,
            "default_appointment_duration": 30,
            "reminder_offsets_minutes": [1440],
            "reminders_enabled": True,
        },
    )
    return config


def reminder_list_for_appointment(
    *, appointment: Appointment
) -> "QuerySet[AppointmentReminder]":
    """Retorna los recordatorios de una cita, ordenados por momento de envío.

    Args:
        appointment: Cita cuyos recordatorios se listan.

    Returns:
        QuerySet de AppointmentReminder de la cita (ascendente por scheduled_at).
    """
    # order_by omitted: Meta.ordering already sorts by scheduled_at ASC
    return AppointmentReminder.objects.filter(appointment=appointment)
