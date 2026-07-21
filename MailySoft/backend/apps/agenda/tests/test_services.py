"""
Tests de services.py de la app agenda.

Cubre:
- appointment_create: camino feliz, auto-cálculo de ends_at, anti-empalme (doctor y
  consultorio), citas consecutivas [) permitidas, consultorio opcional, validación
  de pertenencia al tenant (paciente, médico, consultorio).
- appointment_change_status: todas las transiciones válidas e inválidas según
  VALID_TRANSITIONS, campos de cancelación/no-show, estados terminales.
- appointment_reschedule: camino feliz, validación de estado reagendable,
  revalidación de empalme.
- agenda_config_update: camino feliz, campos inmutables rechazados.

Patrón: AAA (Arrange-Act-Assert). Todas tocan BD → fixture db.
Contexto de tenant: los services reciben `tenant` explícito — no necesitan
set_current_tenant. El TenantManager filtrará por lo que esté en thread-local;
los selectors internos que llaman patient_get/doctor_get/consultorio_get usan
el TenantManager, por eso activamos el contexto donde se necesita.
"""

import datetime
import uuid
from contextlib import contextmanager
from typing import Generator

import pytest
from django.core.exceptions import ValidationError

from apps.agenda.models import VALID_TRANSITIONS, Appointment, TenantAgendaConfig
from apps.agenda.selectors import agenda_config_get
from apps.agenda.services import (
    agenda_config_update,
    appointment_change_status,
    appointment_create,
    appointment_reactivate,
    appointment_reschedule,
)
from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from tests.factories import (
    AppointmentFactory,
    ConsultorioFactory,
    DoctorFactory,
    PatientFactory,
    TenantFactory,
    UserFactory,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_DT = datetime.datetime(2030, 6, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)


@contextmanager
def _tenant_context(tenant: object) -> Generator[None, None, None]:
    """Activa el contexto de tenant para que TenantManager filtre por él.

    Necesario cuando appointment_create llama internamente a patient_get,
    doctor_get y consultorio_get, que usan el TenantManager.
    """
    set_current_tenant(tenant)  # type: ignore[arg-type]
    set_tenant_context_active(True)
    try:
        yield
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)


def _make_appointment(
    tenant: object,
    doctor: object,
    patient: object,
    user: object,
    starts_at: datetime.datetime = _BASE_DT,
    ends_at: datetime.datetime | None = None,
    consultorio: object = None,
    reason: str = "Consulta general",
) -> Appointment:
    """Helper: crea una cita vía el service con contexto de tenant activo."""
    with _tenant_context(tenant):
        return appointment_create(
            tenant=tenant,  # type: ignore[arg-type]
            user=user,  # type: ignore[arg-type]
            patient_id=patient.id,  # type: ignore[union-attr]
            doctor_id=doctor.id,  # type: ignore[union-attr]
            starts_at=starts_at,
            ends_at=ends_at,
            consultorio_id=consultorio.id if consultorio else None,  # type: ignore[union-attr]
            reason=reason,
        )


# ===========================================================================
# appointment_create — camino feliz
# ===========================================================================


class TestAppointmentCreateOk:
    """Creación básica de citas — camino feliz."""

    def test_appointment_create_ok(self, db: None) -> None:
        """Cita creada correctamente con status=SCHEDULED y campos básicos."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        starts = _BASE_DT

        # Act
        appt = _make_appointment(tenant, doctor, patient, user, starts_at=starts)

        # Assert
        assert appt.pk is not None
        assert appt.status == Appointment.Status.SCHEDULED
        assert appt.tenant_id == tenant.id
        assert appt.doctor_id == doctor.id
        assert appt.patient_id == patient.id
        assert appt.starts_at == starts

    def test_appointment_create_sets_created_by(self, db: None) -> None:
        """created_by apunta al usuario que llama al service."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()

        # Act
        appt = _make_appointment(tenant, doctor, patient, user)

        # Assert
        assert appt.created_by_id == user.id


# ===========================================================================
# appointment_create — cálculo automático de ends_at
# ===========================================================================


class TestAppointmentCreateEndsAtAutoCalc:
    """Cálculo de ends_at cuando no se provee explícitamente."""

    def test_appointment_create_auto_calculates_ends_at_from_doctor_duration(
        self, db: None
    ) -> None:
        """ends_at se calcula como starts_at + doctor.default_appointment_duration."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant, default_appointment_duration=45)
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        starts = _BASE_DT

        # Act — sin ends_at explícito
        appt = _make_appointment(tenant, doctor, patient, user, starts_at=starts)

        # Assert
        expected_ends = starts + datetime.timedelta(minutes=45)
        assert appt.ends_at == expected_ends

    def test_appointment_create_uses_config_duration_when_doctor_has_zero(self, db: None) -> None:
        """Cuando doctor.default_appointment_duration es 0/falsy, usa config de la clínica."""
        # Arrange
        tenant = TenantFactory()
        # Doctor con duración 0 → falsy → debe caer al config de la clínica
        doctor = DoctorFactory(tenant=tenant, default_appointment_duration=0)
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        # Crear config con duración explícita de 60 min
        config = agenda_config_get(tenant=tenant)
        config.default_appointment_duration = 60
        config.save(update_fields=["default_appointment_duration"])
        starts = _BASE_DT

        # Act
        appt = _make_appointment(tenant, doctor, patient, user, starts_at=starts)

        # Assert — ends_at = starts + 60 min (de la config, no del doctor)
        expected_ends = starts + datetime.timedelta(minutes=60)
        assert appt.ends_at == expected_ends

    def test_appointment_create_uses_explicit_ends_at_when_provided(self, db: None) -> None:
        """Si se provee ends_at explícito, no se sobreescribe con duración del médico."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant, default_appointment_duration=30)
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        starts = _BASE_DT
        explicit_ends = starts + datetime.timedelta(hours=2)  # 120 min, no 30

        # Act
        with _tenant_context(tenant):
            appt = appointment_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                doctor_id=doctor.id,
                starts_at=starts,
                ends_at=explicit_ends,
                reason="Consulta larga",
            )

        # Assert
        assert appt.ends_at == explicit_ends


# ===========================================================================
# appointment_create — validación de rango temporal
# ===========================================================================


class TestAppointmentCreateTemporalValidation:
    """Validaciones de starts_at y ends_at."""

    def test_appointment_create_rejects_ends_before_starts(self, db: None) -> None:
        """ends_at anterior a starts_at lanza ValidationError."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        starts = _BASE_DT
        ends_before = starts - datetime.timedelta(minutes=10)

        # Act & Assert
        with pytest.raises(ValidationError, match="posterior"):
            with _tenant_context(tenant):
                appointment_create(
                    tenant=tenant,
                    user=user,
                    patient_id=patient.id,
                    doctor_id=doctor.id,
                    starts_at=starts,
                    ends_at=ends_before,
                    reason="Inválido",
                )

    def test_appointment_create_rejects_ends_equal_to_starts(self, db: None) -> None:
        """ends_at == starts_at también debe lanzar ValidationError."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        same_dt = _BASE_DT

        # Act & Assert
        with pytest.raises(ValidationError):
            with _tenant_context(tenant):
                appointment_create(
                    tenant=tenant,
                    user=user,
                    patient_id=patient.id,
                    doctor_id=doctor.id,
                    starts_at=same_dt,
                    ends_at=same_dt,
                    reason="Inválido",
                )


# ===========================================================================
# appointment_create — anti-empalme
# ===========================================================================


class TestAppointmentCreateAntiEmpalme:
    """Validación de solapamiento de horarios (anti-empalme doble)."""

    def test_appointment_create_blocks_doctor_overlap(self, db: None) -> None:
        """Crear una cita que solapa con otra del mismo médico lanza ValidationError."""
        # Arrange
        tenant = TenantFactory()
        # doctor con duración 60min para facilitar los solapamientos en el test
        doctor = DoctorFactory(tenant=tenant, default_appointment_duration=60)
        patient1 = PatientFactory(tenant=tenant)
        patient2 = PatientFactory(tenant=tenant)
        user = UserFactory()
        starts = _BASE_DT
        ends = starts + datetime.timedelta(hours=1)  # 10:00-11:00

        # Primera cita ocupa 10:00-11:00
        _make_appointment(tenant, doctor, patient1, user, starts_at=starts, ends_at=ends)

        # Act & Assert — segunda cita 10:15-11:15 solapa dentro del rango
        with pytest.raises(ValidationError, match="médico"):
            with _tenant_context(tenant):
                appointment_create(
                    tenant=tenant,
                    user=user,
                    patient_id=patient2.id,
                    doctor_id=doctor.id,
                    starts_at=starts + datetime.timedelta(minutes=15),
                    ends_at=ends + datetime.timedelta(minutes=15),
                    reason="Solape",
                )

    def test_appointment_create_blocks_consultorio_overlap(self, db: None) -> None:
        """Crear una cita que solapa el mismo consultorio lanza ValidationError."""
        # Arrange
        tenant = TenantFactory()
        doctor1 = DoctorFactory(tenant=tenant)
        doctor2 = DoctorFactory(tenant=tenant)
        patient1 = PatientFactory(tenant=tenant)
        patient2 = PatientFactory(tenant=tenant)
        consultorio = ConsultorioFactory(tenant=tenant)
        user = UserFactory()
        starts = _BASE_DT

        # Primera cita 10:00-11:00 en consultorio
        with _tenant_context(tenant):
            appointment_create(
                tenant=tenant,
                user=user,
                patient_id=patient1.id,
                doctor_id=doctor1.id,
                starts_at=starts,
                ends_at=starts + datetime.timedelta(hours=1),
                consultorio_id=consultorio.id,
                reason="Primera",
            )

        # Act & Assert — segunda cita 10:30-11:30 mismo consultorio → solape
        with pytest.raises(ValidationError, match="consultorio"):
            with _tenant_context(tenant):
                appointment_create(
                    tenant=tenant,
                    user=user,
                    patient_id=patient2.id,
                    doctor_id=doctor2.id,
                    starts_at=starts + datetime.timedelta(minutes=30),
                    ends_at=starts + datetime.timedelta(hours=1, minutes=30),
                    consultorio_id=consultorio.id,
                    reason="Solape consultorio",
                )

    def test_appointment_create_allows_consecutive_appointments(self, db: None) -> None:
        """Citas consecutivas (10:00-11:00 y 11:00-12:00) NO se solapan con rango [)."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient1 = PatientFactory(tenant=tenant)
        patient2 = PatientFactory(tenant=tenant)
        user = UserFactory()
        starts1 = _BASE_DT  # 10:00
        ends1 = starts1 + datetime.timedelta(hours=1)  # 11:00
        starts2 = ends1  # 11:00 — consecutiva exacta
        ends2 = starts2 + datetime.timedelta(hours=1)  # 12:00

        # Act — primera cita 10:00-11:00
        appt1 = _make_appointment(tenant, doctor, patient1, user, starts_at=starts1, ends_at=ends1)
        # Segunda cita 11:00-12:00 (consecutiva, no solapada)
        appt2 = _make_appointment(tenant, doctor, patient2, user, starts_at=starts2, ends_at=ends2)

        # Assert — ambas creadas sin error
        assert appt1.pk is not None
        assert appt2.pk is not None

    def test_appointment_create_allows_null_consultorio(self, db: None) -> None:
        """consultorio_id=None (telemedicina) crea la cita sin FK de consultorio."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()

        # Act
        with _tenant_context(tenant):
            appt = appointment_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                doctor_id=doctor.id,
                starts_at=_BASE_DT,
                consultorio_id=None,
                reason="Telemedicina",
            )

        # Assert
        assert appt.pk is not None
        assert appt.consultorio_id is None

    def test_appointment_create_overlap_only_with_active_statuses(self, db: None) -> None:
        """Una cita cancelada NO bloquea el mismo horario (no está en ACTIVE_STATUSES)."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient1 = PatientFactory(tenant=tenant)
        patient2 = PatientFactory(tenant=tenant)
        user = UserFactory()
        starts = _BASE_DT

        # Primera cita creada y luego cancelada
        appt1 = _make_appointment(tenant, doctor, patient1, user, starts_at=starts)
        appointment_change_status(
            appointment=appt1, user=user, new_status=Appointment.Status.CANCELLED
        )

        # Act — segunda cita en el mismo horario: no debe bloquear (la primera está cancelada)
        appt2 = _make_appointment(tenant, doctor, patient2, user, starts_at=starts)

        # Assert
        assert appt2.pk is not None


# ===========================================================================
# appointment_create — validación de pertenencia al tenant
# ===========================================================================


class TestAppointmentCreateTenantValidation:
    """Defensa en profundidad: FKs deben pertenecer al mismo tenant."""

    def test_appointment_create_rejects_patient_from_other_tenant(self, db: None) -> None:
        """Paciente de otro tenant lanza ValidationError (defensa en profundidad)."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        doctor = DoctorFactory(tenant=tenant_a)
        patient_b = PatientFactory(tenant=tenant_b)  # paciente de otro tenant
        user = UserFactory()

        # Act & Assert — con contexto del tenant_a, el patient_b no se encontrará
        with pytest.raises(ValidationError):
            with _tenant_context(tenant_a):
                appointment_create(
                    tenant=tenant_a,
                    user=user,
                    patient_id=patient_b.id,
                    doctor_id=doctor.id,
                    starts_at=_BASE_DT,
                    reason="Cross-tenant patient",
                )

    def test_appointment_create_rejects_doctor_from_other_tenant(self, db: None) -> None:
        """Médico de otro tenant lanza ValidationError."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        patient = PatientFactory(tenant=tenant_a)
        doctor_b = DoctorFactory(tenant=tenant_b)  # médico de otro tenant
        user = UserFactory()

        # Act & Assert — con contexto del tenant_a, el doctor_b no se encontrará
        with pytest.raises(ValidationError):
            with _tenant_context(tenant_a):
                appointment_create(
                    tenant=tenant_a,
                    user=user,
                    patient_id=patient.id,
                    doctor_id=doctor_b.id,
                    starts_at=_BASE_DT,
                    reason="Cross-tenant doctor",
                )

    def test_appointment_create_rejects_consultorio_from_other_tenant(self, db: None) -> None:
        """Consultorio de otro tenant lanza ValidationError."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        doctor = DoctorFactory(tenant=tenant_a)
        patient = PatientFactory(tenant=tenant_a)
        consultorio_b = ConsultorioFactory(tenant=tenant_b)
        user = UserFactory()

        # Act & Assert — consultorio del tenant_b no se encontrará en contexto tenant_a
        with pytest.raises(ValidationError):
            with _tenant_context(tenant_a):
                appointment_create(
                    tenant=tenant_a,
                    user=user,
                    patient_id=patient.id,
                    doctor_id=doctor.id,
                    starts_at=_BASE_DT,
                    consultorio_id=consultorio_b.id,
                    reason="Cross-tenant consultorio",
                )


# ===========================================================================
# appointment_change_status — máquina de estados
# ===========================================================================

# Transiciones VÁLIDAS según VALID_TRANSITIONS del modelo
_VALID_TRANSITION_CASES = [
    ("scheduled", "confirmed"),
    ("scheduled", "arrived"),  # llegada directa (walk-in, sin confirmar)
    ("scheduled", "cancelled"),
    ("scheduled", "no_show"),
    ("confirmed", "arrived"),
    ("confirmed", "cancelled"),
    ("confirmed", "no_show"),
    ("arrived", "in_progress"),
    ("arrived", "cancelled"),
    ("arrived", "no_show"),
    ("in_progress", "attended"),
]

# Transiciones INVÁLIDAS — origen → destino que no está permitido
_INVALID_TRANSITION_CASES = [
    ("scheduled", "attended"),
    ("scheduled", "in_progress"),
    ("confirmed", "attended"),
    ("confirmed", "in_progress"),
    ("arrived", "confirmed"),
    ("arrived", "scheduled"),
    ("in_progress", "confirmed"),
    ("in_progress", "scheduled"),
    ("in_progress", "cancelled"),
    ("in_progress", "no_show"),
    # Terminales: ninguna transición permitida
    ("attended", "scheduled"),
    ("attended", "confirmed"),
    ("attended", "cancelled"),
    ("cancelled", "scheduled"),
    ("cancelled", "confirmed"),
    ("no_show", "scheduled"),
    ("no_show", "confirmed"),
]


class TestAppointmentChangeStatusValidTransitions:
    """Transiciones válidas — la máquina de estados debe aceptarlas."""

    @pytest.mark.parametrize("from_status,to_status", _VALID_TRANSITION_CASES)
    def test_change_status_valid_transition(
        self, db: None, from_status: str, to_status: str
    ) -> None:
        """Transición válida cambia el status sin lanzar excepción."""
        # Arrange — crear cita y forzar el status inicial
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            status=from_status,
        )
        user = UserFactory()

        # Act
        updated = appointment_change_status(appointment=appt, user=user, new_status=to_status)

        # Assert
        assert updated.status == to_status
        appt.refresh_from_db()
        assert appt.status == to_status


class TestAppointmentChangeStatusInvalidTransitions:
    """Transiciones inválidas — la máquina de estados debe rechazarlas."""

    @pytest.mark.parametrize("from_status,to_status", _INVALID_TRANSITION_CASES)
    def test_change_status_invalid_transition_raises(
        self, db: None, from_status: str, to_status: str
    ) -> None:
        """Transición no permitida lanza ValidationError."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            status=from_status,
        )
        user = UserFactory()

        # Act & Assert
        with pytest.raises(ValidationError, match="[Tt]ransición"):
            appointment_change_status(appointment=appt, user=user, new_status=to_status)


class TestAppointmentChangeStatusSideEffects:
    """Efectos secundarios al cancelar y registrar no-show."""

    def test_change_status_cancelled_sets_cancelled_by_and_reason(self, db: None) -> None:
        """Al cancelar, cancelled_by y cancellation_reason se guardan."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            status=Appointment.Status.SCHEDULED,
        )
        user = UserFactory()
        motivo = "Paciente no puede asistir."

        # Act
        appointment_change_status(
            appointment=appt, user=user, new_status=Appointment.Status.CANCELLED, reason=motivo
        )

        # Assert
        appt.refresh_from_db()
        assert appt.status == Appointment.Status.CANCELLED
        assert appt.cancelled_by_id == user.id
        assert appt.cancellation_reason == motivo

    def test_change_status_no_show_sets_registered_by(self, db: None) -> None:
        """Al registrar no-show, no_show_registered_by apunta al usuario."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            status=Appointment.Status.SCHEDULED,
        )
        user = UserFactory()

        # Act
        appointment_change_status(
            appointment=appt, user=user, new_status=Appointment.Status.NO_SHOW
        )

        # Assert
        appt.refresh_from_db()
        assert appt.status == Appointment.Status.NO_SHOW
        assert appt.no_show_registered_by_id == user.id

    @pytest.mark.parametrize(
        "terminal_status",
        [
            Appointment.Status.ATTENDED,
            Appointment.Status.CANCELLED,
            Appointment.Status.NO_SHOW,
        ],
    )
    def test_terminal_states_cannot_transition(self, db: None, terminal_status: str) -> None:
        """Estados terminales (attended, cancelled, no_show) no permiten ninguna transición."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None, status=terminal_status
        )
        user = UserFactory()

        # Verificar que VALID_TRANSITIONS para este estado es set vacío
        assert VALID_TRANSITIONS[terminal_status] == set()

        # Act & Assert — intentar cualquier transición desde un terminal
        with pytest.raises(ValidationError):
            appointment_change_status(
                appointment=appt, user=user, new_status=Appointment.Status.SCHEDULED
            )

    def test_change_status_cancelled_does_not_set_no_show_fields(self, db: None) -> None:
        """Al cancelar, no_show_registered_by permanece None."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            status=Appointment.Status.SCHEDULED,
        )
        user = UserFactory()

        # Act
        appointment_change_status(
            appointment=appt, user=user, new_status=Appointment.Status.CANCELLED
        )

        # Assert
        appt.refresh_from_db()
        assert appt.no_show_registered_by_id is None

    def test_change_status_no_show_does_not_set_cancelled_fields(self, db: None) -> None:
        """Al registrar no-show, cancelled_by permanece None."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            status=Appointment.Status.SCHEDULED,
        )
        user = UserFactory()

        # Act
        appointment_change_status(
            appointment=appt, user=user, new_status=Appointment.Status.NO_SHOW
        )

        # Assert
        appt.refresh_from_db()
        assert appt.cancelled_by_id is None
        assert appt.cancellation_reason == ""


# ===========================================================================
# appointment_reschedule
# ===========================================================================


class TestAppointmentReschedule:
    """Reagendamiento de citas (servicio appointment_reschedule)."""

    def test_appointment_reschedule_ok_from_scheduled(self, db: None) -> None:
        """Reagendar una cita SCHEDULED a un nuevo horario sin solapamiento."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + datetime.timedelta(hours=1),
        )
        user = UserFactory()
        new_starts = _BASE_DT + datetime.timedelta(days=1)
        new_ends = new_starts + datetime.timedelta(hours=1)

        # Act
        updated = appointment_reschedule(
            appointment=appt, user=user, starts_at=new_starts, ends_at=new_ends
        )

        # Assert
        assert updated.starts_at == new_starts
        assert updated.ends_at == new_ends
        assert updated.status == Appointment.Status.SCHEDULED  # status no cambia

    def test_appointment_reschedule_ok_from_confirmed(self, db: None) -> None:
        """Reagendar una cita CONFIRMED también está permitido."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            status=Appointment.Status.CONFIRMED,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + datetime.timedelta(hours=1),
        )
        user = UserFactory()
        new_starts = _BASE_DT + datetime.timedelta(days=2)

        # Act
        updated = appointment_reschedule(appointment=appt, user=user, starts_at=new_starts)

        # Assert
        assert updated.starts_at == new_starts
        assert updated.status == Appointment.Status.CONFIRMED

    @pytest.mark.parametrize(
        "non_reagendable_status",
        [
            Appointment.Status.ARRIVED,
            Appointment.Status.IN_PROGRESS,
            Appointment.Status.ATTENDED,
            Appointment.Status.NO_SHOW,
        ],
    )
    def test_appointment_reschedule_rejects_non_reagendable(
        self, db: None, non_reagendable_status: str
    ) -> None:
        """Reagendar citas en estado en curso/terminal (no cancelada) lanza ValidationError.

        SCHEDULED/CONFIRMED y CANCELLED sí son reagendables (cancelada = reactivar+mover).
        """
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            status=non_reagendable_status,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + datetime.timedelta(hours=1),
        )
        user = UserFactory()

        # Act & Assert
        with pytest.raises(ValidationError, match="reagendar"):
            appointment_reschedule(
                appointment=appt, user=user, starts_at=_BASE_DT + datetime.timedelta(days=1)
            )

    def test_appointment_reschedule_reactivates_cancelled(self, db: None) -> None:
        """Reagendar una cita CANCELADA la reactiva (vuelve a Agendada) en el nuevo horario."""
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            status=Appointment.Status.CANCELLED,
            cancellation_reason="me equivoqué",
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + datetime.timedelta(hours=1),
        )
        user = UserFactory()

        nuevo = appointment_reschedule(
            appointment=appt,
            user=user,
            starts_at=_BASE_DT + datetime.timedelta(days=1),
        )

        assert nuevo.status == Appointment.Status.SCHEDULED
        assert nuevo.cancellation_reason == ""
        assert nuevo.cancelled_by is None

    def test_appointment_reactivate_ok(self, db: None) -> None:
        """Reactivar una cita cancelada la vuelve a Agendada en su mismo horario."""
        tenant = TenantFactory()
        appt = AppointmentFactory(
            tenant=tenant,
            consultorio=None,
            status=Appointment.Status.CANCELLED,
            cancellation_reason="error",
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + datetime.timedelta(hours=1),
        )
        reactivada = appointment_reactivate(appointment=appt, user=UserFactory())
        assert reactivada.status == Appointment.Status.SCHEDULED
        assert reactivada.starts_at == _BASE_DT  # mismo horario
        assert reactivada.cancellation_reason == ""

    @pytest.mark.parametrize(
        "estado",
        [Appointment.Status.SCHEDULED, Appointment.Status.ATTENDED, Appointment.Status.NO_SHOW],
    )
    def test_appointment_reactivate_rejects_non_cancelled(self, db: None, estado: str) -> None:
        """Solo se reactiva una cita CANCELADA; otros estados lanzan ValidationError."""
        tenant = TenantFactory()
        appt = AppointmentFactory(
            tenant=tenant,
            consultorio=None,
            status=estado,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + datetime.timedelta(hours=1),
        )
        with pytest.raises(ValidationError, match="cancelada"):
            appointment_reactivate(appointment=appt, user=UserFactory())

    def test_appointment_reschedule_revalidates_overlap(self, db: None) -> None:
        """Reagendar a un horario ocupado (por otra cita activa) lanza ValidationError."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient1 = PatientFactory(tenant=tenant)
        patient2 = PatientFactory(tenant=tenant)
        user = UserFactory()

        slot_a = _BASE_DT
        slot_b = _BASE_DT + datetime.timedelta(hours=2)

        # Cita en slot_a (ocupado por el mismo médico)
        _make_appointment(
            tenant,
            doctor,
            patient1,
            user,
            starts_at=slot_a,
            ends_at=slot_a + datetime.timedelta(hours=1),
        )
        # Cita a reagendar (actualmente en slot_b)
        appt_to_move = _make_appointment(
            tenant,
            doctor,
            patient2,
            user,
            starts_at=slot_b,
            ends_at=slot_b + datetime.timedelta(hours=1),
        )

        # Act & Assert — intentar mover la segunda cita al slot_a (ya ocupado)
        with pytest.raises(ValidationError, match="médico"):
            appointment_reschedule(
                appointment=appt_to_move,
                user=user,
                starts_at=slot_a,
                ends_at=slot_a + datetime.timedelta(hours=1),
            )

    def test_appointment_reschedule_self_exclusion_allows_same_slot(self, db: None) -> None:
        """Reagendar a su propio slot no lanza ValidationError (self-exclusion correcto)."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        starts = _BASE_DT
        ends = starts + datetime.timedelta(hours=1)

        appt = _make_appointment(tenant, doctor, patient, user, starts_at=starts, ends_at=ends)

        # Act — "reagendar" al mismo slot (no debe chocar consigo misma)
        updated = appointment_reschedule(
            appointment=appt, user=user, starts_at=starts, ends_at=ends
        )

        # Assert
        assert updated.starts_at == starts

    def test_appointment_reschedule_with_new_consultorio(self, db: None) -> None:
        """Reagendar cambiando el consultorio actualiza consultorio_id."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        consultorio_old = ConsultorioFactory(tenant=tenant)
        consultorio_new = ConsultorioFactory(tenant=tenant)
        user = UserFactory()

        appt = _make_appointment(
            tenant,
            doctor,
            patient,
            user,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + datetime.timedelta(hours=1),
            consultorio=consultorio_old,
        )

        new_starts = _BASE_DT + datetime.timedelta(days=1)
        new_ends = new_starts + datetime.timedelta(hours=1)

        # Act — cambiar horario y consultorio
        updated = appointment_reschedule(
            appointment=appt,
            user=user,
            starts_at=new_starts,
            ends_at=new_ends,
            consultorio_id=consultorio_new.id,
        )

        # Assert
        assert updated.starts_at == new_starts
        assert updated.consultorio_id == consultorio_new.id

    def test_appointment_reschedule_rejects_end_before_start(self, db: None) -> None:
        """Reagendar con ends_at <= starts_at lanza ValidationError."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + datetime.timedelta(hours=1),
        )

        bad_starts = _BASE_DT + datetime.timedelta(days=1)
        bad_ends = bad_starts - datetime.timedelta(minutes=10)  # ends antes que starts

        # Act & Assert
        with pytest.raises(ValidationError, match="posterior"):
            appointment_reschedule(
                appointment=appt, user=user, starts_at=bad_starts, ends_at=bad_ends
            )

    def test_appointment_reschedule_rejects_consultorio_from_other_tenant(self, db: None) -> None:
        """Reagendar con consultorio de otro tenant lanza ValidationError."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        doctor = DoctorFactory(tenant=tenant_a)
        patient = PatientFactory(tenant=tenant_a)
        consultorio_b = ConsultorioFactory(tenant=tenant_b)
        user = UserFactory()

        appt = _make_appointment(
            tenant_a,
            doctor,
            patient,
            user,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + datetime.timedelta(hours=1),
        )

        new_starts = _BASE_DT + datetime.timedelta(days=1)

        # Act & Assert — consultorio del tenant_b en contexto del tenant_a
        with _tenant_context(tenant_a):
            with pytest.raises(ValidationError):
                appointment_reschedule(
                    appointment=appt,
                    user=user,
                    starts_at=new_starts,
                    consultorio_id=consultorio_b.id,
                )

    def test_appointment_reschedule_blocks_consultorio_overlap(self, db: None) -> None:
        """Reagendar a un consultorio ya ocupado lanza ValidationError."""
        # Arrange
        tenant = TenantFactory()
        doctor1 = DoctorFactory(tenant=tenant)
        doctor2 = DoctorFactory(tenant=tenant)
        patient1 = PatientFactory(tenant=tenant)
        patient2 = PatientFactory(tenant=tenant)
        consultorio = ConsultorioFactory(tenant=tenant)
        user = UserFactory()

        slot_a = _BASE_DT
        ends_a = slot_a + datetime.timedelta(hours=1)

        # Cita en slot_a del consultorio (ocupado)
        _make_appointment(
            tenant,
            doctor1,
            patient1,
            user,
            starts_at=slot_a,
            ends_at=ends_a,
            consultorio=consultorio,
        )
        # Segunda cita del mismo doctor2, en otro horario
        slot_b = slot_a + datetime.timedelta(hours=2)
        appt_to_move = _make_appointment(
            tenant,
            doctor2,
            patient2,
            user,
            starts_at=slot_b,
            ends_at=slot_b + datetime.timedelta(hours=1),
            consultorio=None,  # sin consultorio inicialmente
        )

        # Act & Assert — intentar mover al mismo consultorio en slot_a (ocupado)
        with pytest.raises(ValidationError, match="[Cc]onsultorio"):
            appointment_reschedule(
                appointment=appt_to_move,
                user=user,
                starts_at=slot_a,
                ends_at=ends_a,
                consultorio_id=consultorio.id,
            )


# ===========================================================================
# agenda_config_update
# ===========================================================================


class TestAgendaConfigUpdate:
    """Actualización de la configuración de agenda de un tenant."""

    def test_agenda_config_update_applies_allowed_fields(self, db: None) -> None:
        """Campos permitidos se actualizan y persisten en BD."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act
        updated = agenda_config_update(
            tenant=tenant,
            user=user,
            default_appointment_duration=45,
            reminders_enabled=False,
        )

        # Assert
        assert updated.default_appointment_duration == 45
        assert updated.reminders_enabled is False
        updated.refresh_from_db()
        assert updated.default_appointment_duration == 45

    def test_agenda_config_update_rejects_immutable_field_tenant_id(self, db: None) -> None:
        """Intentar cambiar 'tenant_id' lanza ValidationError."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        other_tenant = TenantFactory()

        # Act & Assert — tenant_id es campo inmutable en _CONFIG_IMMUTABLE_FIELDS
        with pytest.raises(ValidationError, match="tenant_id"):
            agenda_config_update(tenant=tenant, user=user, tenant_id=other_tenant.id)

    def test_agenda_config_update_rejects_immutable_field_id(self, db: None) -> None:
        """Intentar cambiar 'id' lanza ValidationError."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act & Assert
        with pytest.raises(ValidationError, match="id"):
            agenda_config_update(tenant=tenant, user=user, id=uuid.uuid4())  # type: ignore[call-arg]

    def test_agenda_config_update_applies_grid_fields(self, db: None) -> None:
        """Cambiar agenda_start_hour/agenda_end_hour/slot_interval_minutes a
        valores válidos (8/20/15) persiste los 3 campos."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act
        updated = agenda_config_update(
            tenant=tenant,
            user=user,
            agenda_start_hour=8,
            agenda_end_hour=20,
            slot_interval_minutes=15,
        )

        # Assert
        assert updated.agenda_start_hour == 8
        assert updated.agenda_end_hour == 20
        assert updated.slot_interval_minutes == 15
        updated.refresh_from_db()
        assert updated.agenda_start_hour == 8
        assert updated.agenda_end_hour == 20
        assert updated.slot_interval_minutes == 15

    def test_agenda_config_update_rejects_end_hour_equal_to_start_hour(self, db: None) -> None:
        """agenda_end_hour == agenda_start_hour lanza ValidationError."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act & Assert
        with pytest.raises(ValidationError, match="posterior"):
            agenda_config_update(tenant=tenant, user=user, agenda_start_hour=9, agenda_end_hour=9)

    def test_agenda_config_update_rejects_end_hour_before_start_hour(self, db: None) -> None:
        """agenda_end_hour < agenda_start_hour lanza ValidationError."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act & Assert
        with pytest.raises(ValidationError, match="posterior"):
            agenda_config_update(tenant=tenant, user=user, agenda_start_hour=15, agenda_end_hour=8)

    def test_agenda_config_update_rejects_new_start_hour_against_saved_end_hour(
        self, db: None
    ) -> None:
        """Un PATCH parcial que solo manda agenda_start_hour, pero que vuelve
        inválida la combinación contra el agenda_end_hour YA GUARDADO, también
        se rechaza (el service valida el estado final, no solo el campo que
        llega)."""
        # Arrange — config con cierre a las 10
        tenant = TenantFactory()
        user = UserFactory()
        agenda_config_update(tenant=tenant, user=user, agenda_end_hour=10)

        # Act & Assert — subir el inicio a 12 deja start(12) >= end(10)
        with pytest.raises(ValidationError, match="posterior"):
            agenda_config_update(tenant=tenant, user=user, agenda_start_hour=12)

    def test_agenda_config_update_rejects_slot_interval_out_of_choices(self, db: None) -> None:
        """slot_interval_minutes fuera de los choices permitidos lanza
        ValidationError (defensa en profundidad; el InputSerializer ya lo
        restringe, pero el service puede llamarse directo)."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act & Assert
        with pytest.raises(ValidationError, match="slot_interval_minutes"):
            agenda_config_update(tenant=tenant, user=user, slot_interval_minutes=45)


# ===========================================================================
# appointment_update (F1)
# ===========================================================================


class TestAppointmentUpdate:
    """appointment_update: protección de campos inmutables y persistencia."""

    def test_appointment_update_applies_allowed_fields(self, db: None) -> None:
        """reason, specialty y notes se actualizan y persisten en BD."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            reason="Motivo original",
            specialty="",
            notes="",
        )

        # Act
        from apps.agenda.services import appointment_update

        updated = appointment_update(
            appointment=appt,
            user=user,
            reason="Motivo corregido",
            specialty="Pediatría",
            notes="Nota adicional",
        )

        # Assert
        assert updated.reason == "Motivo corregido"
        assert updated.specialty == "Pediatría"
        assert updated.notes == "Nota adicional"
        updated.refresh_from_db()
        assert updated.reason == "Motivo corregido"

    def test_appointment_update_rejects_status_field(self, db: None) -> None:
        """Intentar cambiar 'status' por appointment_update lanza ValidationError."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            status=Appointment.Status.SCHEDULED,
        )

        from apps.agenda.services import appointment_update

        # Act & Assert
        with pytest.raises(ValidationError, match="status"):
            appointment_update(
                appointment=appt,
                user=user,
                status=Appointment.Status.CONFIRMED,  # tipo: ignore
            )

    def test_appointment_update_rejects_doctor_id_field(self, db: None) -> None:
        """Intentar cambiar 'doctor_id' lanza ValidationError (FK de identidad)."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        other_doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
        )

        from apps.agenda.services import appointment_update

        # Act & Assert
        with pytest.raises(ValidationError, match="doctor_id"):
            appointment_update(
                appointment=appt,
                user=user,
                doctor_id=other_doctor.id,  # tipo: ignore
            )

    def test_appointment_update_rejects_tenant_id_field(self, db: None) -> None:
        """Intentar cambiar 'tenant_id' lanza ValidationError."""
        # Arrange
        tenant = TenantFactory()
        other_tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
        )

        from apps.agenda.services import appointment_update

        # Act & Assert
        with pytest.raises(ValidationError, match="tenant_id"):
            appointment_update(
                appointment=appt,
                user=user,
                tenant_id=other_tenant.id,  # tipo: ignore
            )

    def test_appointment_update_status_unchanged(self, db: None) -> None:
        """appointment_update NO cambia el status aunque llegue en fields."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            status=Appointment.Status.SCHEDULED,
        )

        from apps.agenda.services import appointment_update

        # Verificar que status no llega a modificarse (lanza ValidationError)
        with pytest.raises(ValidationError):
            appointment_update(
                appointment=appt,
                user=user,
                status=Appointment.Status.ATTENDED,  # tipo: ignore
            )

        appt.refresh_from_db()
        assert appt.status == Appointment.Status.SCHEDULED


# ===========================================================================
# appointment_create — validación de médico/consultorio activos (F4)
# ===========================================================================


class TestAppointmentCreateActiveChecks:
    """Doctor y consultorio inactivos no pueden usarse al crear citas."""

    def test_appointment_create_rejects_inactive_doctor(self, db: None) -> None:
        """Médico inactivo lanza ValidationError al crear cita."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant, is_active=False)
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()

        # Act & Assert
        with pytest.raises(ValidationError, match="[Mm]édico.*activo"):
            with _tenant_context(tenant):
                appointment_create(
                    tenant=tenant,
                    user=user,
                    patient_id=patient.id,
                    doctor_id=doctor.id,
                    starts_at=_BASE_DT,
                    reason="Médico inactivo",
                )

    def test_appointment_create_rejects_inactive_consultorio(self, db: None) -> None:
        """Consultorio inactivo lanza ValidationError al crear cita."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        consultorio = ConsultorioFactory(tenant=tenant, is_active=False)
        user = UserFactory()

        # Act & Assert
        with pytest.raises(ValidationError, match="[Cc]onsultorio.*activo"):
            with _tenant_context(tenant):
                appointment_create(
                    tenant=tenant,
                    user=user,
                    patient_id=patient.id,
                    doctor_id=doctor.id,
                    starts_at=_BASE_DT,
                    consultorio_id=consultorio.id,
                    reason="Consultorio inactivo",
                )

    def test_appointment_create_allows_active_doctor_and_consultorio(self, db: None) -> None:
        """Doctor y consultorio activos crean cita sin error."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant, is_active=True)
        patient = PatientFactory(tenant=tenant)
        consultorio = ConsultorioFactory(tenant=tenant, is_active=True)
        user = UserFactory()

        # Act
        appt = _make_appointment(
            tenant, doctor, patient, user, starts_at=_BASE_DT, consultorio=consultorio
        )

        # Assert
        assert appt.pk is not None


# ===========================================================================
# F2 smoke-test: cita 'attended' no bloquea slot (constraint corregido)
# ===========================================================================


class TestAttendedDoesNotBlockSlot:
    """Una cita 'attended' no debe bloquear el slot (ACTIVE_STATUSES la excluye)."""

    def test_attended_appointment_does_not_block_slot(self, db: None) -> None:
        """Slot de una cita 'attended' puede reutilizarse (capa 1 y capa 2 alineadas)."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient1 = PatientFactory(tenant=tenant)
        patient2 = PatientFactory(tenant=tenant)
        user = UserFactory()
        starts = _BASE_DT
        ends = starts + datetime.timedelta(hours=1)

        # Primera cita: llega a estado 'attended' (in_progress → attended)
        appt1 = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient1,
            consultorio=None,
            status=Appointment.Status.IN_PROGRESS,
            starts_at=starts,
            ends_at=ends,
        )
        appointment_change_status(
            appointment=appt1,
            user=user,
            new_status=Appointment.Status.ATTENDED,
        )

        # Act — nueva cita en el mismo slot con el mismo médico
        appt2 = _make_appointment(tenant, doctor, patient2, user, starts_at=starts, ends_at=ends)

        # Assert — debe crearse sin error
        assert appt2.pk is not None
        assert appt2.status == Appointment.Status.SCHEDULED
