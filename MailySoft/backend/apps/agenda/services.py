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
from django.db.models import Q
from django.db.utils import IntegrityError
from django.utils import timezone

from apps.agenda.models import (
    ACTIVE_STATUSES,
    VALID_TRANSITIONS,
    AgendaBlock,
    AgendaItemNote,
    Appointment,
    AppointmentReminder,
    AppointmentType,
    TenantAgendaConfig,
)
from apps.agenda.selectors import (
    agenda_block_get,
    agenda_config_get,
    appointment_get,
    appointment_type_get,
)
from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.pacientes.models import Patient
from apps.pacientes.selectors import patient_get
from apps.pacientes.services import patient_create_quick
from apps.personal.models import Consultorio, Doctor
from apps.personal.selectors import consultorio_get, doctor_get, doctor_get_for_user
from apps.tenancy.models import Tenant, TenantMembership

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


def _check_block_overlap(
    *,
    tenant: Tenant,
    doctor_id: uuid.UUID,
    consultorio_id: Optional[uuid.UUID],
    starts_at: datetime.datetime,
    ends_at: datetime.datetime,
) -> None:
    """Verifica que la cita no caiga sobre un evento (reunión/bloqueo) que le aplique.

    Un AgendaBlock aplica si: es de toda la clínica (doctor y consultorio en null),
    o su doctor es el de la cita, o su consultorio es el de la cita.

    Raises:
        ValidationError: si existe un evento que solapa y aplica.
    """
    aplica = Q(doctor__isnull=True, consultorio__isnull=True) | Q(doctor_id=doctor_id)
    if consultorio_id is not None:
        aplica |= Q(consultorio_id=consultorio_id)

    overlapping = AgendaBlock.objects.filter(
        tenant=tenant,
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
    ).filter(aplica)

    if overlapping.exists():
        raise ValidationError(
            "Ese horario está bloqueado por un evento de agenda. Elige otro horario."
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
    appointment_type_id: Optional[uuid.UUID] = None,
    modality: str = Appointment.Modality.OFFICE,
    reason: str = "",
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

    # -- 2c. Regla A — un médico con rol 'doctor' solo puede agendar para sí mismo.
    #
    # Resolución del rol del usuario en ESTE tenant: buscamos su TenantMembership
    # con is_active=True para el tenant dado. No usamos el contexto thread-local
    # (que puede no estar poblado si el service se llama desde Celery/commands).
    # Si no tiene membresía activa en este tenant, se asume que es un staff de
    # plataforma (is_platform_staff) y se salta la restricción.
    try:
        caller_membership = TenantMembership.objects.get(
            user=user,
            tenant=tenant,
            is_active=True,
            deleted_at__isnull=True,
        )
        caller_role: Optional[str] = caller_membership.role
    except TenantMembership.DoesNotExist:
        caller_role = None

    if caller_role == TenantMembership.Role.DOCTOR:
        # Buscar el Doctor activo de este usuario en este tenant.
        caller_doctor = doctor_get_for_user(user=user, tenant_id=tenant.id)
        if caller_doctor is None:
            raise ValidationError(
                "No se encontró un perfil de médico activo para tu usuario en esta clínica."
            )
        if caller_doctor.id != doctor.id:
            raise ValidationError(
                "Como médico, solo puedes agendar citas para ti."
            )

    # -- 2d. Regla B — el consultorio de la cita debe estar asignado al médico.
    #
    # Si el doctor tiene consultorios asignados (M2M no vacío) y se pasó un
    # consultorio_id, ese consultorio DEBE estar entre los del médico.
    # Si el doctor no tiene consultorios asignados → sin restricción.
    # Si consultorio_id es None (telemedicina/fuera) → regla no aplica.
    if consultorio is not None:
        # Evaluamos la existencia de asignaciones sin traer objetos completos.
        assigned_ids = set(
            doctor.consultorios.values_list("id", flat=True)
        )
        if assigned_ids and consultorio.id not in assigned_ids:
            raise ValidationError(
                "Ese consultorio no está asignado al médico."
            )

    # -- 2f. Resolver y validar el tipo de cita (opcional)
    appointment_type = None
    if appointment_type_id is not None:
        try:
            appointment_type = appointment_type_get(type_id=appointment_type_id)
        except AppointmentType.DoesNotExist:
            raise ValidationError("Tipo de cita no encontrado en esta clínica.")
        if appointment_type.tenant_id != tenant.id:
            raise ValidationError("El tipo de cita no pertenece a esta clínica.")

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

            # -- 5b. Anti-empalme contra eventos (reuniones/bloqueos)
            _check_block_overlap(
                tenant=tenant,
                doctor_id=doctor_id,
                consultorio_id=consultorio_id,
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
                appointment_type=appointment_type,
                modality=modality,
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

    audit_record(
        action=ActionType.APPOINTMENT_CREATE,
        resource_type="Appointment",
        actor=user,
        tenant=tenant,
        resource_id=appointment.id,
        resource_repr=str(appointment),
        metadata={
            "doctor_id": str(doctor_id),
            "patient_id": str(patient_id),
        },
    )
    return appointment


def appointment_create_with_new_patient(
    *,
    tenant: Tenant,
    user: "User",  # type: ignore[valid-type]
    new_patient: dict,
    **cita_kwargs: object,
) -> Appointment:
    """Crea un expediente PROVISIONAL y su cita en UNA sola transacción.

    Si la creación de la cita falla (empalme, reglas de médico/consultorio, etc.),
    el expediente provisional NO se crea (rollback). Esto evita expedientes
    huérfanos cuando se agenda "paciente nuevo" desde la agenda.
    """
    with transaction.atomic():
        patient = patient_create_quick(tenant=tenant, user=user, **new_patient)
        appointment = appointment_create(
            tenant=tenant,
            user=user,
            patient_id=patient.id,
            **cita_kwargs,  # type: ignore[arg-type]
        )
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

    audit_record(
        action=ActionType.APPOINTMENT_STATUS,
        resource_type="Appointment",
        actor=user,
        tenant=appointment.tenant,
        resource_id=appointment.id,
        resource_repr=str(appointment),
        metadata={
            "old_status": current,
            "new_status": new_status,
        },
    )
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
    # Se puede reagendar una cita activa (Agendada/Confirmada) o una CANCELADA
    # (reagendar una cancelada = reactivarla en el nuevo horario).
    reagendable_statuses = {
        Appointment.Status.SCHEDULED,
        Appointment.Status.CONFIRMED,
        Appointment.Status.CANCELLED,
    }
    if appointment.status not in reagendable_statuses:
        raise ValidationError(
            f"No se puede reagendar una cita en estado "
            f"'{appointment.get_status_display()}'."
        )
    was_cancelled = appointment.status == Appointment.Status.CANCELLED

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

            # Anti-empalme contra eventos (reuniones/bloqueos) en el nuevo horario.
            _check_block_overlap(
                tenant=appointment.tenant,
                doctor_id=appointment.doctor_id,  # type: ignore[arg-type]
                consultorio_id=new_consultorio_id,
                starts_at=starts_at,
                ends_at=ends_at,
            )

            appointment.starts_at = starts_at
            appointment.ends_at = ends_at
            if consultorio_id is not None:
                appointment.consultorio_id = consultorio_id  # type: ignore[assignment]

            update_fields = ["starts_at", "ends_at", "updated_at"]
            if consultorio_id is not None:
                update_fields.append("consultorio")

            # Si venía CANCELADA, reagendar la reactiva (vuelve a Agendada).
            if was_cancelled:
                appointment.status = Appointment.Status.SCHEDULED
                appointment.cancelled_by = None
                appointment.cancellation_reason = ""
                update_fields += ["status", "cancelled_by", "cancellation_reason"]

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

    audit_record(
        action=ActionType.APPOINTMENT_RESCHEDULE,
        resource_type="Appointment",
        actor=user,
        tenant=appointment.tenant,
        resource_id=appointment.id,
        resource_repr=str(appointment),
        metadata={
            "new_starts_at": appointment.starts_at.isoformat() if appointment.starts_at else "",
            "new_ends_at": appointment.ends_at.isoformat() if appointment.ends_at else "",
        },
    )
    return appointment


def appointment_reactivate(
    *,
    appointment: Appointment,
    user: "User",  # type: ignore[valid-type]
) -> Appointment:
    """Reactiva una cita CANCELADA: vuelve a 'Agendada' en su MISMO horario.

    Revalida el anti-empalme (médico, consultorio y eventos) porque el hueco
    pudo haberse ocupado mientras la cita estuvo cancelada. Si ya está ocupado,
    lanza ValidationError (el usuario deberá reagendar a otro horario).

    Raises:
        ValidationError: si la cita no está cancelada o el horario ya está ocupado.
    """
    if appointment.status != Appointment.Status.CANCELLED:
        raise ValidationError(
            f"Solo se puede reactivar una cita cancelada. "
            f"La cita está en estado '{appointment.get_status_display()}'."
        )

    with transaction.atomic():
        _check_doctor_overlap(
            tenant=appointment.tenant,
            doctor_id=appointment.doctor_id,  # type: ignore[arg-type]
            starts_at=appointment.starts_at,
            ends_at=appointment.ends_at,
            exclude_appointment_id=appointment.id,
        )
        if appointment.consultorio_id is not None:
            _check_consultorio_overlap(
                tenant=appointment.tenant,
                consultorio_id=appointment.consultorio_id,
                starts_at=appointment.starts_at,
                ends_at=appointment.ends_at,
                exclude_appointment_id=appointment.id,
            )
        _check_block_overlap(
            tenant=appointment.tenant,
            doctor_id=appointment.doctor_id,  # type: ignore[arg-type]
            consultorio_id=appointment.consultorio_id,
            starts_at=appointment.starts_at,
            ends_at=appointment.ends_at,
        )

        appointment.status = Appointment.Status.SCHEDULED
        appointment.cancelled_by = None
        appointment.cancellation_reason = ""
        appointment.save(
            update_fields=["status", "cancelled_by", "cancellation_reason", "updated_at"]
        )

    # Reprogramar recordatorios (best-effort, fuera del atomic).
    try:
        schedule_reminders_for_appointment(appointment=appointment)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "appointment_reactivate: error reprogramando recordatorios para cita %s — %s",
            appointment.id, exc, exc_info=True,
        )

    audit_record(
        action=ActionType.APPOINTMENT_REACTIVATE,
        resource_type="Appointment",
        actor=user,
        tenant=appointment.tenant,
        resource_id=appointment.id,
        resource_repr=str(appointment),
    )
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

    audit_record(
        action=ActionType.APPOINTMENT_UPDATE,
        resource_type="Appointment",
        actor=user,
        tenant=appointment.tenant,
        resource_id=appointment.id,
        resource_repr=str(appointment),
        metadata={"changed_fields": sorted(fields.keys())},
    )
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

    audit_record(
        action=ActionType.CONFIG_UPDATE,
        resource_type="TenantAgendaConfig",
        actor=user,
        tenant=tenant,
        resource_id=config.id,
        resource_repr=str(config),
        metadata={"changed_fields": sorted(fields.keys())},
    )
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


# ---------------------------------------------------------------------------
# AppointmentType — tipos de cita configurables por clínica
# ---------------------------------------------------------------------------

_APPOINTMENT_TYPE_EDITABLE: frozenset[str] = frozenset({"name", "color_hex"})


def appointment_type_create(
    *,
    tenant: Tenant,
    user: "User",  # type: ignore[valid-type]
    name: str,
    color_hex: str = "",
) -> AppointmentType:
    """Crea un tipo de cita (categoría con color) para el tenant."""
    appointment_type = AppointmentType.objects.create(
        tenant=tenant,
        created_by=user,
        name=name,
        color_hex=color_hex,
        is_active=True,
    )
    audit_record(
        action=ActionType.APPOINTMENT_TYPE_CREATE,
        resource_type="AppointmentType",
        actor=user,
        tenant=tenant,
        resource_id=appointment_type.id,
        resource_repr=appointment_type.name,
    )
    return appointment_type


def appointment_type_update(
    *,
    appointment_type: AppointmentType,
    user: "User",  # type: ignore[valid-type]
    **fields: object,
) -> AppointmentType:
    """Actualiza nombre y/o color de un tipo de cita."""
    changed = [f for f in fields if f in _APPOINTMENT_TYPE_EDITABLE]
    for field_name in changed:
        setattr(appointment_type, field_name, fields[field_name])
    if changed:
        appointment_type.save(update_fields=[*changed, "updated_at"])
        audit_record(
            action=ActionType.APPOINTMENT_TYPE_UPDATE,
            resource_type="AppointmentType",
            actor=user,
            tenant=appointment_type.tenant,
            resource_id=appointment_type.id,
            resource_repr=appointment_type.name,
            metadata={"changed": sorted(changed)},
        )
    return appointment_type


def appointment_type_deactivate(
    *,
    appointment_type: AppointmentType,
    user: "User",  # type: ignore[valid-type]
) -> AppointmentType:
    """Desactiva (soft) un tipo de cita: deja de aparecer al agendar."""
    appointment_type.is_active = False
    appointment_type.save(update_fields=["is_active", "updated_at"])
    audit_record(
        action=ActionType.APPOINTMENT_TYPE_DEACTIVATE,
        resource_type="AppointmentType",
        actor=user,
        tenant=appointment_type.tenant,
        resource_id=appointment_type.id,
        resource_repr=appointment_type.name,
    )
    return appointment_type


# ---------------------------------------------------------------------------
# AgendaBlock — reuniones y bloqueos (eventos sin paciente)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# AgendaItemNote — notas colaborativas de la agenda
# ---------------------------------------------------------------------------

#: Roles que pueden borrar cualquier nota (no solo la suya propia).
_NOTE_PRIVILEGED_ROLES: frozenset[str] = frozenset(
    {TenantMembership.Role.OWNER, TenantMembership.Role.ADMIN}
)


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
