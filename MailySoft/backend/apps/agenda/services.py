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
from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.db.utils import IntegrityError

from apps.agenda.appointment_types import (  # noqa: F401
    appointment_type_create,
    appointment_type_deactivate,
    appointment_type_update,
)
from apps.agenda.blocks import (  # noqa: F401
    agenda_block_create,
    agenda_block_delete,
    agenda_block_update,
)
from apps.agenda.models import (
    ACTIVE_STATUSES,
    VALID_TRANSITIONS,
    AgendaBlock,
    Appointment,
    AppointmentType,
    TenantAgendaConfig,
)
from apps.agenda.notes import (  # noqa: F401
    agenda_item_note_create,
    agenda_item_note_delete,
)
from apps.agenda.reminders import (  # noqa: F401
    cancel_reminders_for_appointment,
    schedule_reminders_for_appointment,
)
from apps.agenda.selectors import (
    agenda_config_get,
    appointment_type_get,
)
from apps.agenda.series import (
    _SERIES_MAX_OCCURRENCES,
    _generate_series_starts,
)
from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.clinica.models import Sucursal
from apps.clinica.sucursal_scope import allowed_sucursales, resolve_write_sucursal
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
        # Multi-sede — Fase 2: la sucursal solo cambia vía appointment_reschedule
        # (sigue al consultorio), nunca por PATCH genérico.
        "sucursal",
        "sucursal_id",
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
    ends_at: datetime.datetime | None,
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
    exclude_appointment_id: uuid.UUID | None = None,
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
            "El médico ya tiene una cita en ese horario. " "Por favor elija otro horario o médico."
        )


def _check_consultorio_overlap(
    *,
    tenant: Tenant,
    consultorio_id: uuid.UUID,
    starts_at: datetime.datetime,
    ends_at: datetime.datetime,
    exclude_appointment_id: uuid.UUID | None = None,
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
    consultorio_id: uuid.UUID | None,
    sucursal_id: uuid.UUID | None,
    starts_at: datetime.datetime,
    ends_at: datetime.datetime,
) -> None:
    """Verifica que la cita no caiga sobre un evento (reunión/bloqueo) que le aplique.

    Alcance de un AgendaBlock (multi-sede — Fase 2 — REGLA CRÍTICA):
      - Con `doctor` asignado: aplica en TODAS las sedes de ese médico. Un
        médico no puede estar en dos lados a la vez — mismo principio que el
        anti-empalme global de `_check_doctor_overlap`. NO se filtra por sede.
      - Con `consultorio` asignado: aplica solo a ese consultorio (que ya
        pertenece a una única sucursal por diseño).
      - SIN doctor NI consultorio: es un bloqueo "de sucursal" (antes de la
        Fase 2 era "de toda la clínica"). Aplica SOLO si su `sucursal_id`
        coincide EXACTAMENTE con la sede de la cita que se está creando/
        reagendando — un cierre en Centro ya NO bloquea Norte.
        Compatibilidad retro: en un tenant que aún no adopta multi-sede (sin
        ninguna Sucursal configurada), tanto el bloqueo como la cita resuelven
        `sucursal_id=None`; `sucursal_id=None` en el filtro de Django se
        traduce a `sucursal_id IS NULL`, así que el bloqueo sigue aplicando a
        TODA la clínica exactamente como antes de la Fase 2.

    Args:
        sucursal_id: sucursal resuelta de la cita (puede ser None — tenant sin
                     sucursales configuradas); determina qué bloqueos "de
                     sede" aplican.

    Raises:
        ValidationError: si existe un evento que solapa y aplica.
    """
    aplica = Q(doctor_id=doctor_id) | Q(
        doctor__isnull=True, consultorio__isnull=True, sucursal_id=sucursal_id
    )
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
    ends_at: datetime.datetime | None = None,
    consultorio_id: uuid.UUID | None = None,
    appointment_type_id: uuid.UUID | None = None,
    modality: str = Appointment.Modality.OFFICE,
    reason: str = "",
    specialty: str = "",
    notes: str = "",
    series_id: uuid.UUID | None = None,
    quote_id: uuid.UUID | None = None,
    sucursal_id: uuid.UUID | None = None,
    active_sucursal_id: uuid.UUID | None = None,
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
        quote_id:       UUID de la cotización a vincular (C-3, opcional). Si se provee,
                        la Quote debe pertenecer al mismo paciente y estar en estado ACCEPTED.
        sucursal_id:        Sucursal EXPLÍCITA de la cita (multi-sede — Fase 2,
                            opcional). Máxima precedencia en la resolución.
        active_sucursal_id: Sucursal activa del request (header X-Sucursal-Id),
                            que la vista resuelve con resolve_active_sucursal y
                            pasa aquí. Precedencia menor que sucursal_id y que
                            consultorio.sucursal. Ver resolve_write_sucursal.

    Returns:
        Instancia Appointment recién creada con status=SCHEDULED.

    Raises:
        ValidationError: si el paciente/doctor/consultorio no son del tenant,
                         si ends_at <= starts_at, si hay solapamiento, o si la
                         cotización no es del paciente o no está aceptada (C-3),
                         o si la sucursal resuelta es incoherente con el
                         consultorio, o el médico no atiende en esa sede.
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
        caller_role: str | None = caller_membership.role
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
            raise ValidationError("Como médico, solo puedes agendar citas para ti.")

    # -- 2d. Regla B — el consultorio de la cita debe estar asignado al médico.
    #
    # Si el doctor tiene consultorios asignados (M2M no vacío) y se pasó un
    # consultorio_id, ese consultorio DEBE estar entre los del médico.
    # Si el doctor no tiene consultorios asignados → sin restricción.
    # Si consultorio_id es None (telemedicina/fuera) → regla no aplica.
    if consultorio is not None:
        # Evaluamos la existencia de asignaciones sin traer objetos completos.
        assigned_ids = set(doctor.consultorios.values_list("id", flat=True))
        if assigned_ids and consultorio.id not in assigned_ids:
            raise ValidationError("Ese consultorio no está asignado al médico.")

    # -- 2e. Resolver la sucursal (multi-sede — Fase 2).
    #
    # Precedencia: sucursal_id explícita > consultorio.sucursal > sucursal
    # activa del request > sucursal predeterminada del tenant. Puede ser None
    # (compatibilidad retro: tenant sin sucursales configuradas todavía — ver
    # docstring de resolve_write_sucursal).
    sucursal: Sucursal | None = resolve_write_sucursal(
        tenant=tenant,
        user=user,
        sucursal_id=sucursal_id,
        consultorio_sucursal_id=consultorio.sucursal_id if consultorio is not None else None,
        active_sucursal_id=active_sucursal_id,
    )

    # Coherencia consultorio↔sucursal: solo puede fallar si `sucursal_id` fue
    # EXPLÍCITO y contradice la sede del consultorio (si no fue explícito,
    # resolve_write_sucursal ya usó consultorio.sucursal y siempre coinciden).
    if (
        consultorio is not None
        and consultorio.sucursal_id is not None
        and (sucursal is None or consultorio.sucursal_id != sucursal.id)
    ):
        raise ValidationError("El consultorio pertenece a otra sucursal distinta de la indicada.")

    # Regla C — el médico debe atender en la sucursal resuelta.
    # Mismo patrón que la Regla B (consultorios): si el doctor tiene
    # sucursales asignadas (M2M no vacío) y la sede resuelta no está entre
    # ellas (o no se pudo resolver ninguna) → error. Sin restricciones
    # asignadas → sin restricción (compat. retro: clínicas de una sola sede
    # no necesitan asignar nada).
    assigned_sucursal_ids = set(doctor.sucursales.values_list("id", flat=True))
    if assigned_sucursal_ids and (sucursal is None or sucursal.id not in assigned_sucursal_ids):
        raise ValidationError("El médico no atiende en esa sucursal.")

    # -- 2f. Resolver y validar el tipo de cita (opcional)
    appointment_type = None
    if appointment_type_id is not None:
        try:
            appointment_type = appointment_type_get(type_id=appointment_type_id)
        except AppointmentType.DoesNotExist:
            raise ValidationError("Tipo de cita no encontrado en esta clínica.")
        if appointment_type.tenant_id != tenant.id:
            raise ValidationError("El tipo de cita no pertenece a esta clínica.")

    # -- 2g. Validar cotización vinculada (C-3 — opcional)
    quote = None
    if quote_id is not None:
        # Importación tardía para evitar circular imports (agenda ← finanzas).
        from apps.finanzas.models import Quote  # noqa: PLC0415

        try:
            quote = Quote.objects.get(id=quote_id)
        except Quote.DoesNotExist:
            raise ValidationError("Cotización no encontrada en esta clínica.")

        # Defensa multi-tenant: la cotización debe ser del mismo tenant.
        if quote.tenant_id != tenant.id:
            raise ValidationError("La cotización no pertenece a esta clínica.")

        # La cotización debe pertenecer al mismo paciente de la cita.
        if quote.patient_id != patient.id:
            raise ValidationError("La cotización no corresponde al paciente de esta cita.")

        # Solo se puede vincular una cotización aceptada.
        if quote.status != Quote.Status.ACCEPTED:
            raise ValidationError(
                "Solo se puede vincular una cotización aceptada. "
                f"El estado actual es '{quote.get_status_display()}'."
            )

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
        raise ValidationError("La hora de fin debe ser posterior a la hora de inicio.")

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
                sucursal_id=sucursal.id if sucursal is not None else None,
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
                sucursal=sucursal,
                appointment_type=appointment_type,
                modality=modality,
                starts_at=starts_at,
                ends_at=ends_at,
                status=Appointment.Status.SCHEDULED,
                reason=reason,
                specialty=specialty,
                notes=notes,
                series_id=series_id,
                quote=quote,
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
            "sucursal_id": str(sucursal.id) if sucursal is not None else "",
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
# appointment_create_series — citas recurrentes (multi-cita)
# ---------------------------------------------------------------------------


def appointment_create_series(
    *,
    tenant: Tenant,
    user: "User",  # type: ignore[valid-type]
    starts_at: datetime.datetime,
    ends_at: datetime.datetime,
    doctor_id: uuid.UUID,
    frequency: str | None = None,
    explicit_starts: list[datetime.datetime] | None = None,
    patient_id: uuid.UUID | None = None,
    new_patient: dict | None = None,
    interval_days: int | None = None,
    count: int | None = None,
    until: datetime.date | None = None,
    consultorio_id: uuid.UUID | None = None,
    appointment_type_id: uuid.UUID | None = None,
    modality: str = Appointment.Modality.OFFICE,
    reason: str = "",
    specialty: str = "",
    notes: str = "",
    sucursal_id: uuid.UUID | None = None,
    active_sucursal_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Crea una SERIE de citas recurrentes (multi-cita), best-effort.

    Genera las fechas según la regla de repetición y crea una cita por fecha,
    todas con el MISMO `series_id`. Cada cita conserva la misma duración, médico,
    consultorio, modalidad, motivo, etc.; solo cambia la fecha.

    Best-effort (decisión de producto): las citas que choquen (empalme, bloqueo,
    festivo, reglas de médico/consultorio) se SALTAN y se reportan; el resto se
    crea. Si el paciente es NUEVO y NINGUNA cita pudo crearse, se hace rollback
    del expediente provisional para no dejarlo huérfano.

    Args:
        tenant/user:        contexto.
        starts_at/ends_at:  primera cita (la duración se deriva de la diferencia).
        doctor_id:          médico de toda la serie.
        frequency:          weekly | biweekly | monthly | custom.
        patient_id:         paciente existente (XOR new_patient).
        new_patient:        datos de un expediente provisional (XOR patient_id).
        interval_days:      días entre citas cuando frequency=custom.
        count / until:      tope de la serie (exactamente uno).
        sucursal_id/active_sucursal_id: se propagan a cada cita de la serie
                            (misma resolución de precedencia que appointment_create).
        resto:              mismos campos que appointment_create.

    Returns:
        {"series_id": UUID, "created": [Appointment, ...],
         "skipped": [{"starts_at": datetime, "error": str}, ...]}

    Raises:
        ValidationError: parámetros inválidos, o paciente nuevo sin ninguna cita creada.
    """
    if (patient_id is None) == (new_patient is None):
        raise ValidationError("Indica un paciente existente o uno nuevo, no ambos ni ninguno.")

    duracion = ends_at - starts_at
    if duracion <= datetime.timedelta(0):
        raise ValidationError("La hora de fin debe ser posterior a la de inicio.")

    # Dos modos: lista explícita de fechas (Personalizado / vista previa editada),
    # o regla de recurrencia (semanal/quincenal/mensual + count/until).
    if explicit_starts:
        starts = sorted(set(explicit_starts))
        if len(starts) < 2:
            raise ValidationError("Una serie debe tener al menos 2 citas.")
        if len(starts) > _SERIES_MAX_OCCURRENCES:
            raise ValidationError(
                f"Una serie no puede tener más de {_SERIES_MAX_OCCURRENCES} citas."
            )
    elif frequency:
        starts = _generate_series_starts(
            starts_at=starts_at,
            frequency=frequency,
            interval_days=interval_days,
            count=count,
            until=until,
        )
    else:
        raise ValidationError("Indica una frecuencia de repetición o una lista de fechas.")

    series_id = uuid.uuid4()
    created: list[Appointment] = []
    skipped: list[dict[str, Any]] = []

    with transaction.atomic():
        # Resolver el paciente una sola vez (nuevo provisional o existente).
        if new_patient is not None:
            patient = patient_create_quick(tenant=tenant, user=user, **new_patient)
            pid: uuid.UUID = patient.id
        else:
            pid = patient_id  # type: ignore[assignment]

        for s in starts:
            try:
                appt = appointment_create(
                    tenant=tenant,
                    user=user,
                    patient_id=pid,
                    doctor_id=doctor_id,
                    starts_at=s,
                    ends_at=s + duracion,
                    consultorio_id=consultorio_id,
                    appointment_type_id=appointment_type_id,
                    modality=modality,
                    reason=reason,
                    specialty=specialty,
                    notes=notes,
                    series_id=series_id,
                    sucursal_id=sucursal_id,
                    active_sucursal_id=active_sucursal_id,
                )
                created.append(appt)
            except ValidationError as exc:
                skipped.append({"starts_at": s, "error": " ".join(exc.messages)})

        # No dejar un expediente provisional huérfano si nada se pudo agendar.
        if new_patient is not None and not created:
            raise ValidationError(
                "Ninguna de las citas pudo agendarse (los horarios elegidos están ocupados)."
            )

    logger.info(
        "appointment_create_series: serie %s — %d creadas, %d saltadas",
        series_id,
        len(created),
        len(skipped),
    )
    return {"series_id": series_id, "created": created, "skipped": skipped}


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
    ends_at: datetime.datetime | None = None,
    consultorio_id: uuid.UUID | None = None,
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
                         si ends_at <= starts_at, si hay solapamiento, o si
                         el actor no tiene acceso a la sucursal ACTUAL de la
                         cita o a la sucursal DESTINO resuelta (hallazgo A1
                         — ver docs/design/sucursales-hallazgos-seguridad.md).
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
            f"No se puede reagendar una cita en estado " f"'{appointment.get_status_display()}'."
        )
    was_cancelled = appointment.status == Appointment.Status.CANCELLED

    # -- Autorización de sede ORIGEN — hallazgo A1 (CRÍTICO, ver docs/design/
    # sucursales-hallazgos-seguridad.md, clúster A). appointment_reschedule
    # era el ÚNICO write de agenda que nunca validaba sede: la cita adoptaba
    # la sede del consultorio nuevo sin comprobar nada. La sede ACTUAL de la
    # cita debe estar entre las permitidas del actor ANTES de tocar nada —
    # sin esto, un admin acotado a Centro podía reagendar (y de paso mover)
    # una cita cuya sede es Norte con solo conocer su id (obtenible del
    # estado de cuenta compartido del paciente). Compatibilidad retro: si la
    # cita no tiene sucursal (tenant sin multi-sede), no aplica el chequeo.
    if appointment.sucursal_id is not None and not (
        allowed_sucursales(user=user, tenant=appointment.tenant)
        .filter(id=appointment.sucursal_id)
        .exists()
    ):
        raise ValidationError("No tienes acceso a la sucursal actual de esta cita.")

    # Resolver consultorio: usar el nuevo si se provee, o mantener el actual
    consultorio: Consultorio | None = None
    if consultorio_id is not None:
        try:
            consultorio = consultorio_get(consultorio_id=consultorio_id)
        except Exception:
            raise ValidationError("Consultorio no encontrado en esta clínica.")

        if consultorio.tenant_id != appointment.tenant_id:
            raise ValidationError("El consultorio no pertenece a esta clínica.")
        new_consultorio_id: uuid.UUID | None = consultorio_id
    else:
        new_consultorio_id = appointment.consultorio_id  # type: ignore[assignment]

    # -- Sucursal (multi-sede — Fase 2): coherencia sucursal↔consultorio.
    # Si cambia el consultorio Y ese consultorio tiene sede asignada, la
    # sucursal de la cita LO SIGUE. Si no hay cambio de consultorio, o el
    # nuevo consultorio no tiene sede asignada, la sucursal de la cita se
    # conserva sin tocar.
    #
    # Autorización de sede DESTINO (hallazgo A1): se resuelve con
    # `resolve_write_sucursal`, que valida la sede resultante contra
    # `allowed_sucursales(user, tenant)` y levanta ValidationError si el
    # actor no tiene acceso — cierra la ruta "mover una cita de Centro a un
    # consultorio de Norte" aunque el actor sí tuviera acceso a la sede de
    # origen de la cita.
    sucursal_destino: Sucursal | None = resolve_write_sucursal(
        tenant=appointment.tenant,
        user=user,
        sucursal_id=None,
        consultorio_sucursal_id=consultorio.sucursal_id if consultorio is not None else None,
        active_sucursal_id=appointment.sucursal_id,
    )
    new_sucursal_id: uuid.UUID | None = (
        sucursal_destino.id if sucursal_destino is not None else None
    )

    # Regla C revalidada: si la sede resultante cambió y el médico tiene
    # sucursales asignadas, debe seguir atendiendo en la nueva sede.
    if new_sucursal_id is not None and new_sucursal_id != appointment.sucursal_id:
        assigned_sucursal_ids = set(
            appointment.doctor.sucursales.values_list("id", flat=True)  # type: ignore[union-attr]
        )
        if assigned_sucursal_ids and new_sucursal_id not in assigned_sucursal_ids:
            raise ValidationError("El médico no atiende en esa sucursal.")

    # Calcular ends_at
    config = agenda_config_get(tenant=appointment.tenant)
    ends_at = _resolve_ends_at(
        starts_at=starts_at,
        ends_at=ends_at,
        doctor=appointment.doctor,
        config=config,
    )

    if ends_at <= starts_at:
        raise ValidationError("La hora de fin debe ser posterior a la hora de inicio.")

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
                sucursal_id=new_sucursal_id,
                starts_at=starts_at,
                ends_at=ends_at,
            )

            appointment.starts_at = starts_at
            appointment.ends_at = ends_at
            if consultorio_id is not None:
                appointment.consultorio_id = consultorio_id  # type: ignore[assignment]

            # Incrementar el contador de reagendamientos (aplica tanto a citas
            # activas como a las canceladas que se reactivan vía reschedule).
            appointment.reschedule_count += 1

            update_fields = ["starts_at", "ends_at", "reschedule_count", "updated_at"]
            if consultorio_id is not None:
                update_fields.append("consultorio")
            if new_sucursal_id != appointment.sucursal_id:
                appointment.sucursal_id = new_sucursal_id  # type: ignore[assignment]
                update_fields.append("sucursal")

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
            "sucursal_id": str(appointment.sucursal_id) if appointment.sucursal_id else "",
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

    También revalida la Regla C (multi-sede — Fase 2): si el médico tiene
    sucursales asignadas, sigue debiendo atender en la sede de la cita —
    pudo haber cambiado mientras la cita estuvo cancelada.

    Raises:
        ValidationError: si la cita no está cancelada, el horario ya está
                         ocupado, o el médico ya no atiende en esa sucursal.
    """
    if appointment.status != Appointment.Status.CANCELLED:
        raise ValidationError(
            f"Solo se puede reactivar una cita cancelada. "
            f"La cita está en estado '{appointment.get_status_display()}'."
        )

    if appointment.sucursal_id is not None:
        assigned_sucursal_ids = set(
            appointment.doctor.sucursales.values_list("id", flat=True)  # type: ignore[union-attr]
        )
        if assigned_sucursal_ids and appointment.sucursal_id not in assigned_sucursal_ids:
            raise ValidationError("El médico no atiende en esa sucursal.")

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
            sucursal_id=appointment.sucursal_id,
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
            appointment.id,
            exc,
            exc_info=True,
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


#: Granularidades válidas para slot_interval_minutes (defensa en profundidad;
#: el InputSerializer ya restringe con ChoiceField, pero el service puede
#: llamarse directo desde commands/Celery/tests sin pasar por el serializer).
_VALID_SLOT_INTERVALS: frozenset[int] = frozenset(
    value for value, _label in TenantAgendaConfig.SLOT_INTERVAL_CHOICES
)


def agenda_config_update(
    *,
    tenant: Tenant,
    user: "User",  # type: ignore[valid-type]
    **fields: object,
) -> TenantAgendaConfig:
    """Actualiza la configuración de agenda de una clínica.

    Obtiene (o crea con defaults) la config del tenant y aplica los campos
    recibidos, rechazando los inmutables. Valida la coherencia del horario
    de la agenda (agenda_start_hour/agenda_end_hour) contra el estado final
    resultante, ya que el PATCH es parcial y un solo campo puede volver
    inválida la combinación con el valor ya guardado.

    Args:
        tenant: Clínica cuya config se actualiza.
        user:   Usuario que realiza el cambio (para futura auditoría).
        **fields: Campos a actualizar. Los inmutables se rechazan.

    Returns:
        Instancia TenantAgendaConfig actualizada.

    Raises:
        ValidationError: si se intenta modificar un campo inmutable, si
            slot_interval_minutes no es un valor permitido, o si el horario
            resultante tiene agenda_end_hour <= agenda_start_hour.
    """
    attempted_immutable = _CONFIG_IMMUTABLE_FIELDS.intersection(fields.keys())
    if attempted_immutable:
        raise ValidationError(
            f"No se pueden modificar los campos: {', '.join(sorted(attempted_immutable))}."
        )

    if "slot_interval_minutes" in fields:
        if fields["slot_interval_minutes"] not in _VALID_SLOT_INTERVALS:
            valid_values = ", ".join(str(v) for v in sorted(_VALID_SLOT_INTERVALS))
            raise ValidationError(f"slot_interval_minutes debe ser uno de: {valid_values}.")

    config = agenda_config_get(tenant=tenant)

    for field_name, value in fields.items():
        setattr(config, field_name, value)

    if "agenda_start_hour" in fields or "agenda_end_hour" in fields:
        if config.agenda_end_hour <= config.agenda_start_hour:
            raise ValidationError("La hora de cierre debe ser posterior a la de apertura.")

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
