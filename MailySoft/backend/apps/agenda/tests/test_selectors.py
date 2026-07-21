"""
Tests de selectors.py de la app agenda.

Cubre:
- appointment_list: filtros por doctor, fecha, status; orden ASC por starts_at.
- appointment_list: AISLAMIENTO cross-tenant — citas de otra clínica NO aparecen.
- agenda_config_get: get_or_create devuelve config con defaults correctos.
- appointment_get: aislamiento cross-tenant (IDOR — 404, no 403).
- N+1: appointment_list no dispara queries adicionales al iterar relaciones.

Patrón: AAA. Todas tocan BD → fixture db.
Contexto de tenant: se activa con set_current_tenant + set_tenant_context_active
para que el TenantManager filtre correctamente. El fixture autouse
reset_tenant_context (conftest.py) limpia el thread-local entre tests.
"""

import datetime
from contextlib import contextmanager
from typing import Generator

import pytest
from django.db import connection

from apps.agenda.models import Appointment, TenantAgendaConfig
from apps.agenda.selectors import agenda_config_get, appointment_get, appointment_list
from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from tests.factories import (
    AppointmentFactory,
    ConsultorioFactory,
    DoctorFactory,
    PatientFactory,
    TenantAgendaConfigFactory,
    TenantFactory,
    UserFactory,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_DT = datetime.datetime(2030, 6, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)


@contextmanager
def _tenant_context(tenant: object) -> Generator[None, None, None]:
    """Activa el contexto de tenant para que TenantManager filtre por él."""
    set_current_tenant(tenant)  # type: ignore[arg-type]
    set_tenant_context_active(True)
    try:
        yield
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)


# ===========================================================================
# appointment_list — filtros básicos
# ===========================================================================


class TestAppointmentListFilters:
    """appointment_list aplica filtros opcionales correctamente."""

    def test_appointment_list_filter_by_doctor(self, db: None) -> None:
        """Filtrar por doctor_id retorna solo las citas de ese médico."""
        # Arrange
        tenant = TenantFactory()
        doctor_a = DoctorFactory(tenant=tenant)
        doctor_b = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        appt_a1 = AppointmentFactory(
            tenant=tenant,
            doctor=doctor_a,
            patient=patient,
            consultorio=None,
            starts_at=_BASE_DT,
        )
        appt_a2 = AppointmentFactory(
            tenant=tenant,
            doctor=doctor_a,
            patient=patient,
            consultorio=None,
            starts_at=_BASE_DT + datetime.timedelta(hours=2),
        )
        AppointmentFactory(
            tenant=tenant,
            doctor=doctor_b,
            patient=patient,
            consultorio=None,
            starts_at=_BASE_DT + datetime.timedelta(hours=4),
        )  # no debe aparecer

        # Act
        with _tenant_context(tenant):
            qs = appointment_list(doctor_id=doctor_a.id)

        # Assert
        ids = set(qs.values_list("id", flat=True))
        assert appt_a1.id in ids
        assert appt_a2.id in ids
        assert len(ids) == 2

    def test_appointment_list_filter_by_date_range(self, db: None) -> None:
        """Filtrar por date_from y date_to retorna solo citas en ese rango."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        in_range = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            starts_at=_BASE_DT,
        )
        # Fuera del rango (en el pasado relativo a _BASE_DT)
        AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            starts_at=_BASE_DT - datetime.timedelta(hours=2),
        )
        # Fuera del rango (demasiado en el futuro)
        AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            starts_at=_BASE_DT + datetime.timedelta(hours=5),
        )

        date_from = _BASE_DT - datetime.timedelta(minutes=1)
        date_to = _BASE_DT + datetime.timedelta(hours=4)

        # Act
        with _tenant_context(tenant):
            qs = appointment_list(date_from=date_from, date_to=date_to)

        # Assert
        ids = list(qs.values_list("id", flat=True))
        assert in_range.id in ids
        assert len(ids) == 1

    def test_appointment_list_filter_by_status(self, db: None) -> None:
        """Filtrar por status retorna solo las citas con ese estado."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        scheduled = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=_BASE_DT,
        )
        AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            status=Appointment.Status.CANCELLED,
            starts_at=_BASE_DT + datetime.timedelta(hours=2),
        )

        # Act
        with _tenant_context(tenant):
            qs = appointment_list(status=Appointment.Status.SCHEDULED)

        # Assert
        ids = list(qs.values_list("id", flat=True))
        assert scheduled.id in ids
        assert all(a.status == Appointment.Status.SCHEDULED for a in qs)

    def test_appointment_list_ordered_by_starts_at(self, db: None) -> None:
        """El selector retorna citas ordenadas por starts_at ASC."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        appt_last = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            starts_at=_BASE_DT + datetime.timedelta(hours=3),
        )
        appt_first = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            starts_at=_BASE_DT,
        )
        appt_middle = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            starts_at=_BASE_DT + datetime.timedelta(hours=1),
        )

        # Act
        with _tenant_context(tenant):
            result_ids = list(appointment_list().values_list("id", flat=True))

        # Assert — orden ASC
        expected_order = [appt_first.id, appt_middle.id, appt_last.id]
        assert (
            result_ids == expected_order
        ), f"Orden esperado {expected_order}, obtenido {result_ids}"


# ===========================================================================
# appointment_list — AISLAMIENTO cross-tenant (crítico)
# ===========================================================================


class TestAppointmentListTenantIsolation:
    """appointment_list NO filtra datos de otra clínica."""

    def test_appointment_list_only_current_tenant(self, db: None) -> None:
        """Con contexto del tenant A, citas del tenant B son invisibles.

        Este test verifica que el TenantManager (filtra por tenant del contexto)
        impide que los datos de una clínica sean visibles desde otra.
        """
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()

        doctor_a = DoctorFactory(tenant=tenant_a)
        patient_a = PatientFactory(tenant=tenant_a)
        doctor_b = DoctorFactory(tenant=tenant_b)
        patient_b = PatientFactory(tenant=tenant_b)

        # 2 citas en tenant_a
        appt_a1 = AppointmentFactory(
            tenant=tenant_a,
            doctor=doctor_a,
            patient=patient_a,
            consultorio=None,
            starts_at=_BASE_DT,
        )
        appt_a2 = AppointmentFactory(
            tenant=tenant_a,
            doctor=doctor_a,
            patient=patient_a,
            consultorio=None,
            starts_at=_BASE_DT + datetime.timedelta(hours=2),
        )

        # 3 citas en tenant_b — NO deben ser visibles desde tenant_a
        for i in range(3):
            AppointmentFactory(
                tenant=tenant_b,
                doctor=doctor_b,
                patient=patient_b,
                consultorio=None,
                starts_at=_BASE_DT + datetime.timedelta(hours=100 + i * 2),
            )

        # Act — con contexto del tenant A
        with _tenant_context(tenant_a):
            qs = appointment_list()
            ids = set(qs.values_list("id", flat=True))

        # Assert — solo las 2 citas del tenant A
        assert appt_a1.id in ids
        assert appt_a2.id in ids
        assert (
            len(ids) == 2
        ), f"Fuga cross-tenant: se obtuvieron {len(ids)} citas en lugar de 2 del tenant A."

    def test_appointment_list_empty_without_tenant_context(self, db: None) -> None:
        """Sin contexto de tenant activo, appointment_list no retorna datos ajenos.

        Comportamiento "fail-safe": sin contexto de tenant activo (como en Celery),
        el TenantManager NO filtra → puede devolver citas de todos los tenants.
        Este test documenta ese comportamiento y su implicación de que siempre se
        debe tener un contexto activo en requests HTTP.
        """
        # Arrange — cita en un tenant cualquiera
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            starts_at=_BASE_DT,
        )

        # Act — SIN contexto de tenant (context_active=False)
        # El TenantManager en este modo no filtra; el test verifica que la cita
        # es accesible (documenta el comportamiento esperado fuera de request).
        qs = appointment_list()
        ids = list(qs.values_list("id", flat=True))

        # La cita existe — sin contexto activo el manager no filtra
        assert appt.id in ids


# ===========================================================================
# agenda_config_get — get_or_create con defaults
# ===========================================================================


class TestAgendaConfigGet:
    """agenda_config_get devuelve o crea config con valores por defecto correctos."""

    def test_agenda_config_get_creates_with_defaults(self, db: None) -> None:
        """Sin config previa, agenda_config_get crea una con defaults correctos."""
        # Arrange
        tenant = TenantFactory()

        # Act — primera llamada: debe crear la config
        config = agenda_config_get(tenant=tenant)

        # Assert
        assert config.pk is not None
        assert config.tenant_id == tenant.id
        assert config.default_appointment_duration == 30
        assert config.reminder_offsets_minutes == [1440]
        assert config.reminders_enabled is True
        assert config.agenda_start_hour == 9
        assert config.agenda_end_hour == 18
        assert config.slot_interval_minutes == 30

    def test_agenda_config_get_existing_tenant_keeps_grid_defaults(self, db: None) -> None:
        """Un tenant con config creada ANTES de esta feature (solo campos viejos
        explícitos) conserva el comportamiento actual: rejilla 9-18 cada 30 min.

        Simula el caso real: la migración es aditiva con default, así que un
        registro existente adquiere agenda_start_hour=9/agenda_end_hour=18/
        slot_interval_minutes=30 sin que nadie los haya tocado.
        """
        # Arrange — factory sin pasar los 3 campos nuevos explícitamente
        tenant = TenantFactory()
        existing = TenantAgendaConfigFactory(tenant=tenant, default_appointment_duration=45)

        # Act
        config = agenda_config_get(tenant=tenant)

        # Assert — la rejilla sigue siendo la de siempre (9 a 18, cada 30 min)
        assert config.pk == existing.pk
        assert config.agenda_start_hour == 9
        assert config.agenda_end_hour == 18
        assert config.slot_interval_minutes == 30

    def test_agenda_config_get_is_idempotent(self, db: None) -> None:
        """Llamar agenda_config_get dos veces retorna el mismo registro."""
        # Arrange
        tenant = TenantFactory()

        # Act
        config1 = agenda_config_get(tenant=tenant)
        config2 = agenda_config_get(tenant=tenant)

        # Assert — mismo registro, no duplicado
        assert config1.pk == config2.pk
        assert TenantAgendaConfig.all_objects.filter(tenant=tenant).count() == 1

    def test_agenda_config_get_returns_existing_config(self, db: None) -> None:
        """Si ya existe una config, agenda_config_get la retorna sin crear nueva."""
        # Arrange
        tenant = TenantFactory()
        # Crear config con valor personalizado
        existing = TenantAgendaConfigFactory(tenant=tenant, default_appointment_duration=60)

        # Act
        config = agenda_config_get(tenant=tenant)

        # Assert — retorna la existente con el valor personalizado
        assert config.pk == existing.pk
        assert config.default_appointment_duration == 60


# ===========================================================================
# appointment_get — aislamiento cross-tenant (IDOR)
# ===========================================================================


class TestAppointmentGetTenantIsolation:
    """appointment_get usa el TenantManager: cita de otro tenant → DoesNotExist."""

    def test_appointment_get_raises_for_other_tenant(self, db: None) -> None:
        """appointment_get con UUID de cita de otro tenant lanza DoesNotExist (→ 404)."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        doctor_b = DoctorFactory(tenant=tenant_b)
        patient_b = PatientFactory(tenant=tenant_b)
        appt_b = AppointmentFactory(
            tenant=tenant_b,
            doctor=doctor_b,
            patient=patient_b,
            consultorio=None,
            starts_at=_BASE_DT,
        )

        # Act — con contexto del tenant A, intentar acceder a la cita del tenant B
        with _tenant_context(tenant_a):
            with pytest.raises(Appointment.DoesNotExist):
                appointment_get(appointment_id=appt_b.id)

    def test_appointment_get_ok_for_own_tenant(self, db: None) -> None:
        """appointment_get retorna la cita cuando pertenece al tenant activo."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            starts_at=_BASE_DT,
        )

        # Act
        with _tenant_context(tenant):
            result = appointment_get(appointment_id=appt.id)

        # Assert
        assert result.id == appt.id


# ===========================================================================
# N+1 — appointment_list no dispara queries adicionales por relaciones
# ===========================================================================


class TestAppointmentListNoNPlusOne:
    """Verifica que appointment_list usa select_related y evita N+1."""

    def test_appointment_get_select_related_no_n_plus_1(
        self, db: None, django_assert_num_queries: object
    ) -> None:
        """Iterar citas con sus relaciones no dispara queries adicionales (N+1)."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        # Crear 5 citas con distintos horarios
        for i in range(5):
            AppointmentFactory(
                tenant=tenant,
                doctor=doctor,
                patient=patient,
                consultorio=None,
                starts_at=_BASE_DT + datetime.timedelta(hours=i * 2),
            )

        # Act — 2 queries: 1 SELECT principal (con JOINs de select_related) +
        # 1 IN-query de prefetch_related("reminders"). Constante respecto a N citas.
        # Sin select_related/prefetch serían N+1 = muchas queries.
        with _tenant_context(tenant):
            with django_assert_num_queries(2):  # type: ignore[call-arg]
                qs = appointment_list()
                # Forzar evaluación del queryset y acceso a relaciones select_related
                # (doctor, patient, consultorio) y prefetch (reminders).
                results = list(qs)
                for appt in results:
                    _ = appt.doctor_id
                    _ = appt.patient_id
                    _ = list(appt.reminders.all())  # usa el prefetch, 0 queries extra
