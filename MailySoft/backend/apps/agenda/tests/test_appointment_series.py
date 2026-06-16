"""
Tests de citas recurrentes (multi-cita): appointment_create_series + su API.

Cubre:
- Generación de fechas: count, until, custom (cada N días), mensual.
- series_id compartido y misma duración en todas.
- Best-effort: una cita que choca se SALTA y se reporta; el resto se crea.
- Paciente nuevo: crea expediente provisional + serie; si NADA se crea → rollback.
- Validaciones: count<2, count+until juntos, ninguno, custom sin interval_days.
- API POST /agenda/citas/serie/ → 201 con {series_id, created, skipped}.

Patrón: AAA. Fixture `db`. Contexto de tenant activo (servicios usan TenantManager).
"""

import datetime
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.agenda.models import Appointment
from apps.agenda.selectors import agenda_busy_intervals
from apps.agenda.services import appointment_create_series
from apps.tenancy.models import TenantMembership
from tests.factories import (
    AgendaBlockFactory,
    AppointmentFactory,
    DoctorFactory,
    PatientFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

UTC = datetime.UTC
# Lunes 4 de marzo de 2030, 15:00 UTC (9:00 hora central México).
_BASE = datetime.datetime(2030, 3, 4, 15, 0, 0, tzinfo=UTC)
_FIN = _BASE + datetime.timedelta(minutes=30)

SERIE_URL = "/api/v1/agenda/citas/serie/"


@contextmanager
def _ctx(tenant: Any) -> Generator[None, None, None]:
    from apps.core.tenant_context import set_current_tenant, set_tenant_context_active

    set_current_tenant(tenant)  # type: ignore[arg-type]
    set_tenant_context_active(True)
    try:
        yield
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)


@contextmanager
def _api_ctx(tenant: Any) -> Generator[None, None, None]:
    with (
        patch("apps.agenda.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
    ):
        yield


def _owner(tenant: Any) -> Any:
    """Usuario con rol owner (sin la restricción 'médico solo agenda para sí')."""
    user = UserFactory()
    TenantMembershipFactory(
        user=user, tenant=tenant, role=TenantMembership.Role.OWNER, is_active=True
    )
    return user


# ===========================================================================
# Generación de fechas
# ===========================================================================


class TestSeriesGeneracion:
    def test_weekly_count(self, db):
        """Semanal, 4 veces → 4 citas, separadas 7 días, mismo series_id."""
        tenant = TenantFactory()
        user = _owner(tenant)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        with _ctx(tenant):
            res = appointment_create_series(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                doctor_id=doctor.id,
                starts_at=_BASE,
                ends_at=_FIN,
                frequency="weekly",
                count=4,
            )

        assert len(res["created"]) == 4
        assert res["skipped"] == []
        starts = sorted(a.starts_at for a in res["created"])
        assert starts == [_BASE + datetime.timedelta(days=7 * i) for i in range(4)]
        assert len({a.series_id for a in res["created"]}) == 1
        assert res["created"][0].series_id == res["series_id"]

    def test_until_date(self, db):
        """Semanal, hasta el 18-mar → 3 citas (4, 11, 18); el 25 ya no entra."""
        tenant = TenantFactory()
        user = _owner(tenant)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        with _ctx(tenant):
            res = appointment_create_series(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                doctor_id=doctor.id,
                starts_at=_BASE,
                ends_at=_FIN,
                frequency="weekly",
                until=datetime.date(2030, 3, 18),
            )

        assert len(res["created"]) == 3

    def test_custom_interval(self, db):
        """Cada 10 días, 3 veces → 4, 14, 24 de marzo."""
        tenant = TenantFactory()
        user = _owner(tenant)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        with _ctx(tenant):
            res = appointment_create_series(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                doctor_id=doctor.id,
                starts_at=_BASE,
                ends_at=_FIN,
                frequency="custom",
                interval_days=10,
                count=3,
            )

        starts = sorted(a.starts_at.day for a in res["created"])
        assert starts == [4, 14, 24]

    def test_monthly(self, db):
        """Mensual, 3 veces → 4 mar, 4 abr, 4 may."""
        tenant = TenantFactory()
        user = _owner(tenant)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        with _ctx(tenant):
            res = appointment_create_series(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                doctor_id=doctor.id,
                starts_at=_BASE,
                ends_at=_FIN,
                frequency="monthly",
                count=3,
            )

        meses = sorted(a.starts_at.month for a in res["created"])
        assert meses == [3, 4, 5]


# ===========================================================================
# Best-effort: saltar conflictos
# ===========================================================================


class TestSeriesConflictos:
    def test_salta_la_que_choca(self, db):
        """Si la 2ª ocurrencia choca con una cita existente, se salta; las demás se crean."""
        tenant = TenantFactory()
        user = _owner(tenant)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        # Cita que ocupa el horario de la 2ª ocurrencia (BASE + 7 días).
        choque = _BASE + datetime.timedelta(days=7)
        AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            starts_at=choque,
            ends_at=choque + datetime.timedelta(minutes=30),
        )

        with _ctx(tenant):
            res = appointment_create_series(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                doctor_id=doctor.id,
                starts_at=_BASE,
                ends_at=_FIN,
                frequency="weekly",
                count=4,
            )

        assert len(res["created"]) == 3
        assert len(res["skipped"]) == 1
        assert res["skipped"][0]["starts_at"] == choque


# ===========================================================================
# Paciente nuevo
# ===========================================================================


class TestSeriesPacienteNuevo:
    def test_crea_expediente_y_serie(self, db):
        """new_patient → crea el expediente provisional y la serie."""
        tenant = TenantFactory()
        user = _owner(tenant)
        doctor = DoctorFactory(tenant=tenant)

        with _ctx(tenant):
            res = appointment_create_series(
                tenant=tenant,
                user=user,
                doctor_id=doctor.id,
                new_patient={"first_name": "Juan", "paternal_surname": "Pérez"},
                starts_at=_BASE,
                ends_at=_FIN,
                frequency="weekly",
                count=2,
            )

        assert len(res["created"]) == 2
        # todas apuntan al mismo paciente recién creado
        assert len({a.patient_id for a in res["created"]}) == 1

    def test_rollback_si_nada_se_crea(self, db):
        """Paciente nuevo + TODAS las fechas chocan → ValidationError y sin expediente huérfano."""
        from apps.pacientes.models import Patient

        tenant = TenantFactory()
        user = _owner(tenant)
        doctor = DoctorFactory(tenant=tenant)
        # Bloquear las 2 ocurrencias.
        for off in (0, 7):
            t = _BASE + datetime.timedelta(days=off)
            AppointmentFactory(
                tenant=tenant,
                doctor=doctor,
                starts_at=t,
                ends_at=t + datetime.timedelta(minutes=30),
            )
        antes = Patient.all_objects.filter(tenant=tenant).count()

        with _ctx(tenant):
            with pytest.raises(ValidationError, match="Ninguna"):
                appointment_create_series(
                    tenant=tenant,
                    user=user,
                    doctor_id=doctor.id,
                    new_patient={"first_name": "Ana", "paternal_surname": "López"},
                    starts_at=_BASE,
                    ends_at=_FIN,
                    frequency="weekly",
                    count=2,
                )

        # No quedó expediente provisional huérfano.
        assert Patient.all_objects.filter(tenant=tenant).count() == antes


# ===========================================================================
# Validaciones
# ===========================================================================


class TestSeriesValidacion:
    def _args(self, tenant, user, doctor, patient, **over):
        base = {
            "tenant": tenant,
            "user": user,
            "patient_id": patient.id,
            "doctor_id": doctor.id,
            "starts_at": _BASE,
            "ends_at": _FIN,
            "frequency": "weekly",
            "count": 3,
        }
        base.update(over)
        return base

    def test_count_menor_a_2(self, db):
        tenant = TenantFactory()
        user = _owner(tenant)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        with _ctx(tenant), pytest.raises(ValidationError, match="al menos 2"):
            appointment_create_series(**self._args(tenant, user, doctor, patient, count=1))

    def test_count_y_until_juntos(self, db):
        tenant = TenantFactory()
        user = _owner(tenant)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        with _ctx(tenant), pytest.raises(ValidationError, match="exactamente uno"):
            appointment_create_series(
                **self._args(
                    tenant, user, doctor, patient, count=3, until=datetime.date(2030, 4, 1)
                )
            )

    def test_ni_count_ni_until(self, db):
        tenant = TenantFactory()
        user = _owner(tenant)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        with _ctx(tenant), pytest.raises(ValidationError, match="exactamente uno"):
            appointment_create_series(
                **self._args(tenant, user, doctor, patient, count=None, until=None)
            )

    def test_custom_sin_interval(self, db):
        tenant = TenantFactory()
        user = _owner(tenant)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        with _ctx(tenant), pytest.raises(ValidationError, match="cada cuántos días"):
            appointment_create_series(
                **self._args(tenant, user, doctor, patient, frequency="custom", interval_days=None)
            )


# ===========================================================================
# API
# ===========================================================================


class TestSeriesApi:
    def test_post_crea_serie(self, db):
        """POST /agenda/citas/serie/ → 201 con created/skipped."""
        tenant = TenantFactory()
        user = _owner(tenant)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        client = APIClient()
        client.force_authenticate(user=user)
        payload = {
            "patient_id": str(patient.id),
            "doctor_id": str(doctor.id),
            "starts_at": _BASE.isoformat(),
            "ends_at": _FIN.isoformat(),
            "frequency": "weekly",
            "count": 3,
        }
        with _api_ctx(tenant):
            resp = client.post(SERIE_URL, payload, format="json")

        assert resp.status_code == 201
        assert resp.data["created_count"] == 3
        assert resp.data["skipped_count"] == 0
        assert (
            Appointment.all_objects.filter(tenant=tenant, series_id=resp.data["series_id"]).count()
            == 3
        )

    def test_post_requiere_paciente_o_nuevo(self, db):
        """Sin patient_id ni new_patient → 400."""
        tenant = TenantFactory()
        user = _owner(tenant)
        doctor = DoctorFactory(tenant=tenant)

        client = APIClient()
        client.force_authenticate(user=user)
        payload = {
            "doctor_id": str(doctor.id),
            "starts_at": _BASE.isoformat(),
            "ends_at": _FIN.isoformat(),
            "frequency": "weekly",
            "count": 3,
        }
        with _api_ctx(tenant):
            resp = client.post(SERIE_URL, payload, format="json")

        assert resp.status_code == 400


# ===========================================================================
# Lista explícita de fechas (Personalizado / vista previa editada)
# ===========================================================================


class TestSeriesExplicita:
    def test_lista_explicita_crea_cada_fecha(self, db):
        """explicit_starts: crea una cita por cada fecha dada (mismas duración/médico)."""
        tenant = TenantFactory()
        user = _owner(tenant)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        fechas = [
            _BASE,
            _BASE + datetime.timedelta(days=3),
            _BASE + datetime.timedelta(days=10),
        ]

        with _ctx(tenant):
            res = appointment_create_series(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                doctor_id=doctor.id,
                starts_at=_BASE,
                ends_at=_FIN,
                explicit_starts=fechas,
            )

        assert len(res["created"]) == 3
        assert sorted(a.starts_at for a in res["created"]) == sorted(fechas)
        assert len({a.series_id for a in res["created"]}) == 1

    def test_lista_explicita_menor_a_2(self, db):
        tenant = TenantFactory()
        user = _owner(tenant)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        with _ctx(tenant), pytest.raises(ValidationError, match="al menos 2"):
            appointment_create_series(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                doctor_id=doctor.id,
                starts_at=_BASE,
                ends_at=_FIN,
                explicit_starts=[_BASE],
            )

    def test_post_lista_explicita(self, db):
        """POST con explicit_starts → 201 sin necesitar frequency/count."""
        tenant = TenantFactory()
        user = _owner(tenant)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        client = APIClient()
        client.force_authenticate(user=user)
        payload = {
            "patient_id": str(patient.id),
            "doctor_id": str(doctor.id),
            "starts_at": _BASE.isoformat(),
            "ends_at": _FIN.isoformat(),
            "explicit_starts": [
                _BASE.isoformat(),
                (_BASE + datetime.timedelta(days=2)).isoformat(),
            ],
        }
        with _api_ctx(tenant):
            resp = client.post(SERIE_URL, payload, format="json")

        assert resp.status_code == 201
        assert resp.data["created_count"] == 2


# ===========================================================================
# Disponibilidad (horarios ocupados)
# ===========================================================================


class TestDisponibilidad:
    def _rango(self):
        return _BASE - datetime.timedelta(days=1), _BASE + datetime.timedelta(days=1)

    def test_incluye_cita_activa(self, db):
        """Una cita activa del médico aparece como intervalo ocupado."""
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        AppointmentFactory(tenant=tenant, doctor=doctor, starts_at=_BASE, ends_at=_FIN)
        desde, hasta = self._rango()

        with _ctx(tenant):
            busy = agenda_busy_intervals(
                doctor_id=doctor.id, consultorio_id=None, date_from=desde, date_to=hasta
            )

        assert any(b["start"] == _BASE for b in busy)

    def test_excluye_cancelada(self, db):
        """Una cita CANCELADA no cuenta como ocupado."""
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        AppointmentFactory(
            tenant=tenant, doctor=doctor, starts_at=_BASE, ends_at=_FIN,
            status=Appointment.Status.CANCELLED,
        )
        desde, hasta = self._rango()

        with _ctx(tenant):
            busy = agenda_busy_intervals(
                doctor_id=doctor.id, consultorio_id=None, date_from=desde, date_to=hasta
            )

        assert busy == []

    def test_incluye_bloqueo_de_clinica(self, db):
        """Un bloqueo de toda la clínica (sin doctor ni consultorio) ocupa al médico."""
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        AgendaBlockFactory(
            tenant=tenant, doctor=None, consultorio=None,
            starts_at=_BASE, ends_at=_FIN,
        )
        desde, hasta = self._rango()

        with _ctx(tenant):
            busy = agenda_busy_intervals(
                doctor_id=doctor.id, consultorio_id=None, date_from=desde, date_to=hasta
            )

        assert any(b["start"] == _BASE for b in busy)

    def test_api_disponibilidad(self, db):
        """GET /agenda/disponibilidad/ → {busy: [...]}."""
        tenant = TenantFactory()
        user = _owner(tenant)
        doctor = DoctorFactory(tenant=tenant)
        AppointmentFactory(tenant=tenant, doctor=doctor, starts_at=_BASE, ends_at=_FIN)
        desde, hasta = self._rango()

        client = APIClient()
        client.force_authenticate(user=user)
        with _api_ctx(tenant):
            resp = client.get(
                "/api/v1/agenda/disponibilidad/",
                {
                    "doctor_id": str(doctor.id),
                    "date_from": desde.isoformat(),
                    "date_to": hasta.isoformat(),
                },
            )

        assert resp.status_code == 200
        assert len(resp.data["busy"]) == 1
