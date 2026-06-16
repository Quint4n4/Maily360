"""
Tests del campo reschedule_count en Appointment (Fase 1).

Cubre:
- reschedule_count empieza en 0 al crear una cita.
- Se incrementa a 1 tras un reagendamiento exitoso.
- Se incrementa a 2 tras dos reagendamientos sobre la misma cita.
- Reagendar una cita CANCELADA (la reactiva + mueve) también incrementa el contador.
- appointment_reactivate NO incrementa reschedule_count.
- El contador se persiste en BD correctamente.

Patrón: AAA (Arrange-Act-Assert). Todas tocan BD → fixture db.
Contexto: services reciben tenant explícito; activamos set_current_tenant donde
los selectors internos de appointment_create lo necesitan.
"""

import datetime

import pytest

from apps.agenda.models import Appointment
from apps.agenda.services import appointment_reactivate, appointment_reschedule
from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from tests.factories import AppointmentFactory, DoctorFactory, PatientFactory, TenantFactory, UserFactory

# Horario base en el futuro para evitar choques con citas de otros tests.
_BASE_DT = datetime.datetime(2035, 3, 10, 9, 0, 0, tzinfo=datetime.timezone.utc)


# ===========================================================================
# reschedule_count — valor inicial
# ===========================================================================


class TestRescheduleCountInitialValue:
    """La cita nace siempre con reschedule_count == 0."""

    def test_new_appointment_has_reschedule_count_zero(self, db: None) -> None:
        """Una cita recién creada con AppointmentFactory tiene reschedule_count=0."""
        # Arrange & Act
        tenant = TenantFactory()
        appt = AppointmentFactory(
            tenant=tenant,
            consultorio=None,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + datetime.timedelta(hours=1),
        )

        # Assert
        assert appt.reschedule_count == 0

    def test_reschedule_count_is_zero_in_database(self, db: None) -> None:
        """El valor inicial 0 se persiste correctamente en BD."""
        # Arrange
        tenant = TenantFactory()
        appt = AppointmentFactory(
            tenant=tenant,
            consultorio=None,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + datetime.timedelta(hours=1),
        )

        # Act — verificar directo desde BD
        appt.refresh_from_db()

        # Assert
        assert appt.reschedule_count == 0


# ===========================================================================
# reschedule_count — incremento por reagendamiento
# ===========================================================================


class TestRescheduleCountIncrement:
    """El contador sube exactamente en 1 por cada reagendamiento exitoso."""

    def test_reschedule_count_increments_to_one_after_first_reschedule(
        self, db: None
    ) -> None:
        """Tras el primer reagendamiento, reschedule_count vale 1."""
        # Arrange
        tenant = TenantFactory()
        appt = AppointmentFactory(
            tenant=tenant,
            consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + datetime.timedelta(hours=1),
        )
        user = UserFactory()
        new_starts = _BASE_DT + datetime.timedelta(days=1)

        # Act
        updated = appointment_reschedule(
            appointment=appt, user=user, starts_at=new_starts
        )

        # Assert
        assert updated.reschedule_count == 1
        updated.refresh_from_db()
        assert updated.reschedule_count == 1

    def test_reschedule_count_increments_to_two_after_second_reschedule(
        self, db: None
    ) -> None:
        """Tras el segundo reagendamiento, reschedule_count vale 2."""
        # Arrange
        tenant = TenantFactory()
        appt = AppointmentFactory(
            tenant=tenant,
            consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + datetime.timedelta(hours=1),
        )
        user = UserFactory()

        # Primer reagendamiento
        appointment_reschedule(
            appointment=appt,
            user=user,
            starts_at=_BASE_DT + datetime.timedelta(days=1),
        )

        # Act — segundo reagendamiento
        updated = appointment_reschedule(
            appointment=appt,
            user=user,
            starts_at=_BASE_DT + datetime.timedelta(days=2),
        )

        # Assert
        assert updated.reschedule_count == 2
        updated.refresh_from_db()
        assert updated.reschedule_count == 2

    def test_reschedule_count_persists_to_database(self, db: None) -> None:
        """El incremento de reschedule_count se guarda correctamente en BD."""
        # Arrange
        tenant = TenantFactory()
        appt = AppointmentFactory(
            tenant=tenant,
            consultorio=None,
            status=Appointment.Status.CONFIRMED,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + datetime.timedelta(hours=1),
        )
        user = UserFactory()

        # Act
        appointment_reschedule(
            appointment=appt,
            user=user,
            starts_at=_BASE_DT + datetime.timedelta(days=3),
        )

        # Assert — leer desde BD para confirmar persistencia
        appt.refresh_from_db()
        assert appt.reschedule_count == 1

    def test_reschedule_of_cancelled_appointment_increments_count(
        self, db: None
    ) -> None:
        """Reagendar una cita CANCELADA (reactiva + mueve) también incrementa reschedule_count."""
        # Arrange
        tenant = TenantFactory()
        appt = AppointmentFactory(
            tenant=tenant,
            consultorio=None,
            status=Appointment.Status.CANCELLED,
            cancellation_reason="cancelada por error",
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + datetime.timedelta(hours=1),
        )
        user = UserFactory()

        # Precondición: la cita cancelada empieza con count=0
        assert appt.reschedule_count == 0

        # Act — reagendar (también la reactiva)
        updated = appointment_reschedule(
            appointment=appt,
            user=user,
            starts_at=_BASE_DT + datetime.timedelta(days=2),
        )

        # Assert — el status volvió a SCHEDULED Y el contador subió
        assert updated.status == Appointment.Status.SCHEDULED
        assert updated.reschedule_count == 1
        updated.refresh_from_db()
        assert updated.reschedule_count == 1


# ===========================================================================
# appointment_reactivate — NO debe incrementar reschedule_count
# ===========================================================================


class TestReactivateDoesNotIncrementRescheduleCount:
    """appointment_reactivate NO debe tocar reschedule_count."""

    def test_reactivate_does_not_increment_reschedule_count(self, db: None) -> None:
        """Reactivar (mismo horario, status=SCHEDULED) NO sube reschedule_count."""
        # Arrange
        tenant = TenantFactory()
        appt = AppointmentFactory(
            tenant=tenant,
            consultorio=None,
            status=Appointment.Status.CANCELLED,
            cancellation_reason="error",
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + datetime.timedelta(hours=1),
            reschedule_count=0,
        )
        user = UserFactory()

        # Act — reactivar (no reagendar)
        reactivated = appointment_reactivate(appointment=appt, user=user)

        # Assert — status cambió pero el contador permanece en 0
        assert reactivated.status == Appointment.Status.SCHEDULED
        assert reactivated.reschedule_count == 0
        reactivated.refresh_from_db()
        assert reactivated.reschedule_count == 0

    def test_reactivate_after_reschedule_does_not_increase_count_further(
        self, db: None
    ) -> None:
        """Cita reagendada (count=1), luego cancelada y reactivada mantiene count=1."""
        # Arrange
        tenant = TenantFactory()
        appt = AppointmentFactory(
            tenant=tenant,
            consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + datetime.timedelta(hours=1),
            reschedule_count=0,
        )
        user = UserFactory()

        # Reagendar (sube count a 1)
        appointment_reschedule(
            appointment=appt,
            user=user,
            starts_at=_BASE_DT + datetime.timedelta(days=1),
        )
        assert appt.reschedule_count == 1

        # Cancelar
        from apps.agenda.services import appointment_change_status
        appointment_change_status(
            appointment=appt,
            user=user,
            new_status=Appointment.Status.CANCELLED,
        )
        assert appt.status == Appointment.Status.CANCELLED

        # Act — reactivar (debe quedarse en count=1, no subir a 2)
        reactivated = appointment_reactivate(appointment=appt, user=user)

        # Assert
        assert reactivated.status == Appointment.Status.SCHEDULED
        assert reactivated.reschedule_count == 1
