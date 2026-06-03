"""
Services de la app agenda.

Toda escritura/modificación de citas y config de agenda pasa por aquí.
Las vistas son delgadas: parsean el request, llaman al service, devuelven respuesta.

Convención: keyword-only args en toda firma, nombrado acción+entidad.

Reglas críticas:
  1. `status` de una cita SOLO cambia vía `appointment_change_status`.
     NUNCA por PATCH genérico. _APPOINTMENT_IMMUTABLE_FIELDS lo refuerza.
  2. Cada FK (patient, doctor, consultorio) se valida tenant_id == tenant.id
     como defensa en profundidad (el service puede llamarse desde Celery/commands).
  3. Anti-empalme capa 1: verificar solapamiento antes del INSERT.
     Capa 2: exclusion constraints en BD (migración 0002) capturados como IntegrityError.
  4. Recordatorios (schedule_reminders_for_appointment / cancel_reminders_for_appointment):
     - La programación de recordatorios NO puede tumbar la creación de la cita.
       Cualquier falla se captura con try/except + log; la cita ya fue creada.
     - La tarea Celery verifica de nuevo el estado antes de enviar (idempotencia).
     - La revocación de tareas Celery ya encoladas es best-effort (by id es costoso
       y no es garantizado). Lo que importa es que la tarea verifique status=CANCELLED.
"""

import datetime
import logging
import uuid
from typing import Optional

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.utils import IntegrityError
from django.utils import timezone

from apps.agenda.models import (
    ACTIVE_STATUSES,
    VALID_TRANSITIONS,
    Appointment,
    AppointmentReminder,
    TenantAgendaConfig,
)
from apps.agenda.selectors import agenda_config_get
from apps.pacientes.models import Patient
from apps.pacientes.selectors import patient_get
from apps.personal.models import Consultorio, Doctor
from apps.personal.selectors import consultorio_get, doctor_get
from apps.tenancy.models import Tenant

logger = logging.getLogger("apps.agenda.services")

User = get_user_model()


# ---------------------------------------------------------------------------
# Campos inmutables
# ---------------------------------------------------------------------------

#: Campos que NUNCA se pueden modificar vía appointment_update genérico.
#: status requiere appointment_change_status (regla 1).
#: Las FK de identidad (doctor, patient) nunca cambian en una cita existente.
_APPOINTMENT_IMMUTABLE_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "tenant",
        "tenant_id",
        "created_at",
        "updated_at",
        "deleted_at",
        # Regla 1: status NUNCA por update genérico
        "status",
        # FK de identidad — no se reasigna paciente ni médico en v1
        "patient",
        "patient_id",
        "doctor",
        "doctor_id",
        # Campos de cancelación/no-show — solo service los escribe
        "cancelled_by",
        "cancelled_by_id",
        "cancellation_reason",
        "no_show_registered_by",
        "no_show_registered_by_id",
        # Gancho v2 — no exponer
        "series_id",
    }
)

#: Campos que NO se pueden modificar vía agenda_config_update.
_CONFIG_IMMUTABLE_FIELDS: frozenset[str] = frozenset(
    {"id", "tenant", "tenant_id", "created_at", "updated_at", "deleted_at"}
)


# ---------------------------------------------------------------------------
# Helpers privados
# ---------------------------------------------------------------------------


def _resolve_ends_at(
    *,
    starts_at: datetime.datetime,
    ends_at: Optional[datetime.datetime],
    doctor: Doctor,
    config: TenantAgendaConfig,
) -> datetime.datetime:
    """Calcula ends_at si no se provee, usando la duración del médico o la config.

    Precedencia: ends_at explícito → doctor.default_appointment_duration
                 → config.default_appointment_duration → 30 minutos.

    Args:
        starts_at: Inicio de la cita (UTC).
        ends_at:   Fin de la cita (UTC) o None para calcular automáticamente.
        doctor:    Perfil del médico (tiene default_appointment_duration).
        config:    Config de agenda de la clínica.

    Returns:
        datetime con la hora de fin de la cita en UTC.
    """
    if ends_at is not None:
        return ends_at

    # Duración: doctor (override) → config clínica → fallback 30
    # Uso de `is not None` para que duración=0 no caiga al siguiente nivel por falsy.
    if doctor.default_appointment_duration is not None and doctor.default_appointment_duration > 0:
        duration_minutes: int = doctor.default_appointment_duration
    elif config.default_appointment_duration:
        duration_minutes = config.default_appointment_duration
    else:
        duration_minutes = 30
    return starts_at + datetime.timedelta(minutes=duration_minutes)


def _check_doctor_overlap(
    *,
    tenant: Tenant,
    doctor_id: uuid.UUID,
    starts_at: datetime.datetime,
    ends_at: datetime.datetime,
    exclude_appointment_id: Optional[uuid.UUID] = None,
) -> None:
    """Verifica que el médico no tenga una cita activa que se solape.

    Rango [starts_at, ends_at) para permitir citas consecutivas (p.ej. 10-11 y 11-12).

    Args:
        tenant:                 Tenant de la cita a crear.
        doctor_id:              UUID del médico.
        starts_at:              Inicio propuesto de la cita.
        ends_at:                Fin propuesto de la cita.
        exclude_appointment_id: UUID de la cita a excluir (para reagendamiento).

    Raises:
        ValidationError: si el médico ya tiene una cita activa que se solapa.
    """
    qs = Appointment.objects.filter(
        tenant=tenant,
        doctor_id=doctor_id,
        status__in=ACTIVE_STATUSES,
        # Overlap: [A.starts, A.ends) ∩ [B.starts, B.ends) != ∅
        # ↔ A.starts < B.ends AND A.ends > B.starts
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
    )
    if exclude_appointment_id is not None:
        qs = qs.exclude(id=exclude_appointment_id)

    if qs.exists():
        raise ValidationError(
            "El médico ya tiene una cita en ese horario. "
            "Por favor elija otro horario o médico."
        )


def _check_consultorio_overlap(
    *,
    tenant: Tenant,
    consultorio_id: uuid.UUID,
    starts_at: datetime.datetime,
    ends_at: datetime.datetime,
    exclude_appointment_id: Optional[uuid.UUID] = None,
) -> None:
    """Verifica que el consultorio no tenga una cita activa que se solape.

    Solo aplica cuando consultorio_id no es None (consultorio es OPCIONAL).

    Args:
        tenant:                 Tenant de la cita a crear.
        consultorio_id:         UUID del consultorio.
        starts_at:              Inicio propuesto de la cita.
        ends_at:                Fin propuesto de la cita.
        exclude_appointment_id: UUID de la cita a excluir (para reagendamiento).

    Raises:
        ValidationError: si el consultorio ya está ocupado en ese horario.
    """
    qs = Appointment.objects.filter(
        tenant=tenant,
        consultorio_id=consultorio_id,
        status__in=ACTIVE_STATUSES,
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
    )
    if exclude_appointment_id is not None:
        qs = qs.exclude(id=exclude_appointment_id)

    if qs.exists():
        raise ValidationError(
            "El consultorio ya está ocupado en ese horario. "
            "Por favor elija otro horario o consultorio."
        )


# ---------------------------------------------------------------------------
# appointment_create
# ---------------------------------------------------------------------------


def appointment_create(
    *,
    tenant: Tenant,
    user: "User",  # type: ignore[valid-type]
    patient_id: uuid.UUID,
    doctor_id: uuid.UUID,
    starts_at: datetime.datetime,
    ends_at: Optional[datetime.datetime] = None,
    consultorio_id: Optional[uuid.UUID] = None,
    reason: str,
    specialty: str = "",
    notes: str = "",
) -> Appointment:
    """Crea una cita médica validando disponibilidad (anti-empalme doble).

    Flujo:
      1. Resuelve patient, doctor y consultorio via selectors de sus módulos.
      2. Valida que cada objeto pertenezca al tenant (regla 3, defensa en profundidad).
      3. Calcula ends_at si no se provee (doctor.duration → config → 30 min).
      4. Valida ends_at > starts_at.
      5. Anti-empalme capa 1: verifica solapamiento de doctor y consultorio.
      6. INSERT dentro de transaction.atomic(); captura IntegrityError de
         exclusion constraint (capa 2) → ValidationError de dominio.

    Args:
        tenant:         Clínica a la que pertenece la cita.
        user:           Usuario que crea la cita (auditoría).
        patient_id:     UUID del paciente.
        doctor_id:      UUID del médico.
        starts_at:      Inicio de la cita en UTC.
        ends_at:        Fin de la cita en UTC (opcional; se calcula si no se provee).
        consultorio_id: UUID del consultorio (opcional).
        reason:         Motivo de la cita (requerido).
        specialty:      Especialidad (texto libre, opcional).
        notes:          Notas internas (opcional).

    Returns:
        Instancia Appointment recién creada con status=SCHEDULED.

    Raises:
        ValidationError: si el paciente/doctor/consultorio no son del tenant,
                         si ends_at <= starts_at, o si hay solapamiento.
    """
    # -- 1. Resolver FKs (selectors filtran por tenant activo vía TenantManager)
    try:
        patient = patient_get(patient_id=patient_id)
    except Patient.DoesNotExist:
        raise ValidationError("Paciente no encontrado en esta clínica.")

    try:
        doctor = doctor_get(doctor_id=doctor_id)
    except Doctor.DoesNotExist:
        raise ValidationError("Médico no encontrado en esta clínica.")

    consultorio = None
    if consultorio_id is not None:
        try:
            consultorio = consultorio_get(consultorio_id=consultorio_id)
        except Consultorio.DoesNotExist:
            raise ValidationError("Consultorio no encontrado en esta clínica.")

    # -- 2. Validar pertenencia al tenant (regla 3 — defensa en profundidad)
    if patient.tenant_id != tenant.id:
        raise ValidationError("El paciente no pertenece a esta clínica.")

    if doctor.tenant_id != tenant.id:
        raise ValidationError("El médico no pertenece a esta clínica.")

    if consultorio is not None and consultorio.tenant_id != tenant.id:
        raise ValidationError("El consultorio no pertenece a esta clínica.")

    # -- 2b. Validar que doctor y consultorio estén activos (F4)
    if not doctor.is_active:
        raise ValidationError("El médico no está activo en esta clínica.")
    if consultorio is not None and not consultorio.is_active:
        raise ValidationError("El consultorio no está activo.")

    # -- 3. Calcular ends_at si no se provee
    config = agenda_config_get(tenant=tenant)
    ends_at = _resolve_ends_at(
        starts_at=starts_at,
        ends_at=ends_at,
        doctor=doctor,
        config=config,
    )

    # -- 4. Validar rango temporal
    if ends_at <= starts_at:
        raise ValidationError(
            "La hora de fin debe ser posterior a la hora de inicio."
        )

    try:
        with transaction.atomic():
            # -- 5. Anti-empalme capa 1 (service)
            _check_doctor_overlap(
                tenant=tenant,
                doctor_id=doctor_id,
                starts_at=starts_at,
                ends_at=ends_at,
            )
            if consultorio is not None:
                _check_consultorio_overlap(
                    tenant=tenant,
                    consultorio_id=consultorio_id,  # type: ignore[arg-type]
                    starts_at=starts_at,
                    ends_at=ends_at,
                )

            # -- 6. Crear la cita
            appointment = Appointment.objects.create(
                tenant=tenant,
                created_by=user,
                patient=patient,
                doctor=doctor,
                consultorio=consultorio,
                starts_at=starts_at,
                ends_at=ends_at,
                status=Appointment.Status.SCHEDULED,
                reason=reason,
                specialty=specialty,
                notes=notes,
            )

    except IntegrityError as exc:
        # Captura los exclusion constraints de capa 2 (btree_gist).
        # Los nombres de los constraints se definen en la migración 0002.
        exc_str = str(exc).lower()
        if "appointment_no_overlap_doctor" in exc_str:
            raise ValidationError(
                "El médico ya tiene una cita en ese horario (constraint BD). "
                "Por favor elija otro horario o médico."
            ) from exc
        if "appointment_no_overlap_consultorio" in exc_str:
            raise ValidationError(
                "El consultorio ya está ocupado en ese horario (constraint BD). "
                "Por favor elija otro horario o consultorio."
            ) from exc
        # IntegrityError no relacionado con empalme — propagar como dominio genérico
        raise ValidationError(
            "Error de integridad al crear la cita. Por favor intente de nuevo."
        ) from exc

    # -- 7. Programar recordatorios (best-effort: no tumba la creación de la cita)
    try:
        schedule_reminders_for_appointment(appointment=appointment)
    except Exception as exc:
        logger.error(
            "appointment_create: error programando recordatorios para cita %s — %s",
            appointment.id,
            exc,
            exc_info=True,
        )

    # TODO(audit): registrar en apps/audit cuando exista
    return appointment


# ---------------------------------------------------------------------------
# appointment_change_status
# ---------------------------------------------------------------------------


def appointment_change_status(
    *,
    appointment: Appointment,
    user: "User",  # type: ignore[valid-type]
    new_status: str,
    reason: str = "",
) -> Appointment:
    """Cambia el estado de una cita validando la transición permitida.

    Este es el ÚNICO punto de entrada para cambiar status. Las vistas NO deben
    cambiar status por PATCH genérico.

    Transiciones válidas (ver VALID_TRANSITIONS en models.py):
        SCHEDULED  → CONFIRMED, CANCELLED, NO_SHOW
        CONFIRMED  → ARRIVED, CANCELLED, NO_SHOW
        ARRIVED    → IN_PROGRESS, CANCELLED, NO_SHOW
        IN_PROGRESS → ATTENDED
        Terminales (ATTENDED, CANCELLED, NO_SHOW) → ninguna.

    Al cancelar:   setea cancelled_by y cancellation_reason.
    Al no-show:    setea no_show_registered_by.

    Args:
        appointment: Instancia Appointment a modificar.
        user:        Usuario que realiza el cambio de estado.
        new_status:  Nuevo estado (valor de Appointment.Status).
        reason:      Motivo (requerido al cancelar, opcional en otros casos).

    Returns:
        Instancia Appointment con el nuevo estado guardado.

    Raises:
        ValidationError: si la transición no está permitida por la máquina de estados.
    """
    current = appointment.status
    allowed: set[str] = VALID_TRANSITIONS.get(current, set())

    if new_status not in allowed:
        raise ValidationError(
            f"No se puede pasar de '{appointment.get_status_display()}' "
            f"a '{dict(Appointment.Status.choices).get(new_status, new_status)}'. "
            f"Transición no permitida."
        )

    update_fields = ["status", "updated_at"]

    appointment.status = new_status

    if new_status == Appointment.Status.CANCELLED:
        appointment.cancelled_by = user
        appointment.cancellation_reason = reason
        update_fields += ["cancelled_by", "cancellation_reason"]

    if new_status == Appointment.Status.NO_SHOW:
        appointment.no_show_registered_by = user
        update_fields += ["no_show_registered_by"]

    appointment.save(update_fields=update_fields)

    # Cancelar recordatorios pendientes cuando la cita termina de forma negativa
    if new_status in {Appointment.Status.CANCELLED, Appointment.Status.NO_SHOW}:
        cancelled_count = cancel_reminders_for_appointment(appointment=appointment)
        logger.info(
            "appointment_change_status: cancelados %d recordatorios para cita %s (nuevo status=%s)",
            cancelled_count,
            appointment.id,
            new_status,
        )

    # TODO(audit): registrar en apps/audit cuando exista
    return appointment


# ---------------------------------------------------------------------------
# appointment_reschedule
# ---------------------------------------------------------------------------


def appointment_reschedule(
    *,
    appointment: Appointment,
    user: "User",  # type: ignore[valid-type]
    starts_at: datetime.datetime,
    ends_at: Optional[datetime.datetime] = None,
    consultorio_id: Optional[uuid.UUID] = None,
) -> Appointment:
    """Reagenda una cita (cambia horario y/o consultorio).

    Solo aplica a citas en estado SCHEDULED o CONFIRMED.
    Revalida anti-empalme excluyendo la propia cita.

    El diseño (sección 4 del documento) dice:
        "Reagendar = crear una cita nueva (no se reabre la cancelada)."
    Sin embargo, en v1 permitimos modificar el horario de una cita SCHEDULED/CONFIRMED
    (es un reagendamiento, no una cancelación + nueva cita).
    Si el criterio cambia a "siempre nueva cita", este service se depreca.

    Args:
        appointment:    Cita a reagendar.
        user:           Usuario que realiza el reagendamiento.
        starts_at:      Nuevo inicio de la cita en UTC.
        ends_at:        Nuevo fin de la cita en UTC (opcional; se calcula si no se provee).
        consultorio_id: Nuevo consultorio (opcional; None = mantener el actual).

    Returns:
        Instancia Appointment con horario actualizado.

    Raises:
        ValidationError: si la cita no está en un estado reagendable,
                         si ends_at <= starts_at, o si hay solapamiento.
    """
    reagendable_statuses = {Appointment.Status.SCHEDULED, Appointment.Status.CONFIRMED}
    if appointment.status not in reagendable_statuses:
        raise ValidationError(
            f"Solo se pueden reagendar citas en estado 'Agendada' o 'Confirmada'. "
            f"La cita está en estado '{appointment.get_status_display()}'."
        )

    # Resolver consultorio: usar el nuevo si se provee, o mantener el actual
    if consultorio_id is not None:
        try:
            consultorio = consultorio_get(consultorio_id=consultorio_id)
        except Exception:
            raise ValidationError("Consultorio no encontrado en esta clínica.")

        if consultorio.tenant_id != appointment.tenant_id:
            raise ValidationError("El consultorio no pertenece a esta clínica.")
        new_consultorio_id: Optional[uuid.UUID] = consultorio_id
    else:
        new_consultorio_id = (
            appointment.consultorio_id  # type: ignore[assignment]
        )

    # Calcular ends_at
    config = agenda_config_get(tenant=appointment.tenant)
    ends_at = _resolve_ends_at(
        starts_at=starts_at,
        ends_at=ends_at,
        doctor=appointment.doctor,
        config=config,
    )

    if ends_at <= starts_at:
        raise ValidationError(
            "La hora de fin debe ser posterior a la hora de inicio."
        )

    try:
        with transaction.atomic():
            _check_doctor_overlap(
                tenant=appointment.tenant,
                doctor_id=appointment.doctor_id,  # type: ignore[arg-type]
                starts_at=starts_at,
                ends_at=ends_at,
                exclude_appointment_id=appointment.id,
            )
            if new_consultorio_id is not None:
                _check_consultorio_overlap(
                    tenant=appointment.tenant,
                    consultorio_id=new_consultorio_id,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    exclude_appointment_id=appointment.id,
                )

            appointment.starts_at = starts_at
            appointment.ends_at = ends_at
            if consultorio_id is not None:
                appointment.consultorio_id = consultorio_id  # type: ignore[assignment]

            update_fields = ["starts_at", "ends_at", "updated_at"]
            if consultorio_id is not None:
                update_fields.append("consultorio")

            appointment.save(update_fields=update_fields)

    except IntegrityError as exc:
        exc_str = str(exc).lower()
        if "appointment_no_overlap_doctor" in exc_str:
            raise ValidationError(
                "El médico ya tiene una cita en ese horario (constraint BD)."
            ) from exc
        if "appointment_no_overlap_consultorio" in exc_str:
            raise ValidationError(
                "El consultorio ya está ocupado en ese horario (constraint BD)."
            ) from exc
        raise ValidationError(
            "Error de integridad al reagendar la cita. Por favor intente de nuevo."
        ) from exc

    # Cancelar reminders del horario anterior DESPUÉS de confirmar el nuevo horario.
    # Si estuviera dentro del atomic(), un rollback dejaría los reminders cancelados
    # con la cita en su horario viejo — race condition (F5).
    cancel_reminders_for_appointment(appointment=appointment)

    # Reprogramar recordatorios con el nuevo horario (best-effort)
    try:
        schedule_reminders_for_appointment(appointment=appointment)
    except Exception as exc:
        logger.error(
            "appointment_reschedule: error reprogramando recordatorios para cita %s — %s",
            appointment.id,
            exc,
            exc_info=True,
        )

    # TODO(audit): registrar en apps/audit cuando exista
    return appointment


# ---------------------------------------------------------------------------
# appointment_update
# ---------------------------------------------------------------------------


def appointment_update(
    *,
    appointment: Appointment,
    user: "User",  # type: ignore[valid-type]
    **fields: object,
) -> Appointment:
    """Actualiza campos editables de una cita (reason, specialty, notes).

    Protege activamente los campos inmutables rechazando cualquier intento de
    modificarlos, independientemente de lo que filtre el serializer de la vista.
    Esta es la única fuente de verdad para la inmutabilidad — el serializer es
    solo una primera línea de defensa conveniente.

    Campos inmutables (ver _APPOINTMENT_IMMUTABLE_FIELDS):
        id, tenant, tenant_id, created_at, updated_at, deleted_at, status,
        patient, patient_id, doctor, doctor_id, cancelled_by*, cancellation_reason,
        no_show_registered_by*, series_id.

    Args:
        appointment: Instancia Appointment a modificar (ya recuperada vía selector).
        user:        Usuario que realiza el cambio (para futura auditoría).
        **fields:    Campos a actualizar. Los inmutables se rechazan con ValidationError.

    Returns:
        Instancia Appointment con los cambios aplicados y persistidos.

    Raises:
        ValidationError: si alguno de los campos recibidos es inmutable.
    """
    attempted_immutable = _APPOINTMENT_IMMUTABLE_FIELDS.intersection(fields.keys())
    if attempted_immutable:
        raise ValidationError(
            f"No se pueden modificar los campos: {', '.join(sorted(attempted_immutable))}."
        )

    for field_name, value in fields.items():
        setattr(appointment, field_name, value)

    update_fields = list(fields.keys()) + ["updated_at"]
    appointment.save(update_fields=update_fields)

    # TODO(audit): registrar en apps/audit cuando exista
    return appointment


# ---------------------------------------------------------------------------
# agenda_config_update
# ---------------------------------------------------------------------------


def agenda_config_update(
    *,
    tenant: Tenant,
    user: "User",  # type: ignore[valid-type]
    **fields: object,
) -> TenantAgendaConfig:
    """Actualiza la configuración de agenda de una clínica.

    Obtiene (o crea con defaults) la config del tenant y aplica los campos
    recibidos, rechazando los inmutables.

    Args:
        tenant: Clínica cuya config se actualiza.
        user:   Usuario que realiza el cambio (para futura auditoría).
        **fields: Campos a actualizar. Los inmutables se rechazan.

    Returns:
        Instancia TenantAgendaConfig actualizada.

    Raises:
        ValidationError: si se intenta modificar un campo inmutable.
    """
    attempted_immutable = _CONFIG_IMMUTABLE_FIELDS.intersection(fields.keys())
    if attempted_immutable:
        raise ValidationError(
            f"No se pueden modificar los campos: {', '.join(sorted(attempted_immutable))}."
        )

    config = agenda_config_get(tenant=tenant)

    for field_name, value in fields.items():
        setattr(config, field_name, value)

    update_fields = list(fields.keys()) + ["updated_at"]
    config.save(update_fields=update_fields)

    # TODO(audit): registrar en apps/audit cuando exista
    return config


# ---------------------------------------------------------------------------
# Recordatorios (WhatsApp) — programación y cancelación
# ---------------------------------------------------------------------------


def schedule_reminders_for_appointment(
    *,
    appointment: Appointment,
) -> list[AppointmentReminder]:
    """Programa los recordatorios de una cita según la config de la clínica.

    Lee ``reminder_offsets_minutes`` de la config del tenant y crea un
    ``AppointmentReminder`` PENDING por cada offset cuyo ``scheduled_at`` esté en
    el futuro, encolando la tarea Celery ``send_appointment_reminder`` con ``eta``.

    Decisiones de diseño:
      - Si ``reminders_enabled`` es False → no crea nada (devuelve ``[]``).
      - Offsets cuyo ``scheduled_at`` ya pasó (<= ahora) se OMITEN: un recordatorio
        en el pasado no aporta valor (no se crea como SKIPPED, simplemente no se crea).
      - Evita duplicados: no crea otro PENDING para el mismo (cita, scheduled_at).

    NOTA: esta función es best-effort respecto a la creación de la cita —
    quien la llama (appointment_create / appointment_reschedule) la envuelve en
    try/except para que una falla aquí NO tumbe la cita.

    Args:
        appointment: Cita ya persistida (recién creada o reagendada).

    Returns:
        Lista de ``AppointmentReminder`` creados (puede ser vacía).
    """
    config = agenda_config_get(tenant=appointment.tenant)
    if not config.reminders_enabled:
        return []

    # Import local para evitar import circular (tasks importa services indirectamente).
    from apps.agenda.tasks import send_appointment_reminder

    now = timezone.now()
    created: list[AppointmentReminder] = []

    for offset_minutes in config.reminder_offsets_minutes or []:
        scheduled_at = appointment.starts_at - datetime.timedelta(
            minutes=int(offset_minutes)
        )
        if scheduled_at <= now:
            # Recordatorio caería en el pasado: omitir.
            continue

        # Evitar duplicados para el mismo momento de envío.
        duplicate_exists = AppointmentReminder.all_objects.filter(
            appointment=appointment,
            scheduled_at=scheduled_at,
            status=AppointmentReminder.ReminderStatus.PENDING,
        ).exists()
        if duplicate_exists:
            continue

        reminder = AppointmentReminder.objects.create(
            tenant=appointment.tenant,
            created_by=appointment.created_by,
            appointment=appointment,
            channel=AppointmentReminder.Channel.WHATSAPP,
            scheduled_at=scheduled_at,
            status=AppointmentReminder.ReminderStatus.PENDING,
        )
        # Encola el envío para el momento programado. La tarea revalida el estado.
        send_appointment_reminder.apply_async(
            args=[str(reminder.id)],
            eta=scheduled_at,
        )
        created.append(reminder)

    return created


def cancel_reminders_for_appointment(
    *,
    appointment: Appointment,
) -> int:
    """Marca como CANCELLED todos los recordatorios PENDING de una cita.

    Se invoca al cancelar / marcar no-show una cita, o al reagendarla (antes de
    reprogramar con el nuevo horario).

    Usa ``all_objects`` porque puede ejecutarse sin contexto de tenant, pero filtra
    por la cita concreta (que ya está acotada a su tenant). La revocación de las
    tareas Celery encoladas es best-effort: la tarea ``send_appointment_reminder``
    revalida ``status == PENDING`` antes de enviar, por lo que un recordatorio
    CANCELLED nunca se envía aunque su tarea llegue a ejecutarse.

    Args:
        appointment: Cita cuyos recordatorios pendientes se cancelan.

    Returns:
        Número de recordatorios cancelados.
    """
    return AppointmentReminder.all_objects.filter(
        appointment=appointment,
        status=AppointmentReminder.ReminderStatus.PENDING,
    ).update(status=AppointmentReminder.ReminderStatus.CANCELLED)
