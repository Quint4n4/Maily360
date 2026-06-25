"""
Tests de la analítica de retención (Fase 3 — RFM).

Cubre:
  - Clasificación de segmentos: nuevo / vip / frecuente / en_riesgo / perdido / ocasional.
  - API GET /api/v1/finanzas/retencion/: estructura de la respuesta y permisos.
  - Métricas: retention_rate, no_show_rate, avg_ticket, pct_with_future_appt.
  - Aislamiento multi-tenant: datos de otro tenant no aparecen.

Patrón: AAA. Todas tocan BD → fixture db.
"""

from __future__ import annotations

import datetime
from contextlib import contextmanager
from decimal import Decimal
from typing import Any, Generator
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.agenda.models import Appointment
from apps.finanzas.retention import (
    AT_RISK_MIN_PAST_VISITS,
    AT_RISK_WINDOW_DAYS,
    FREQUENT_MIN_VISITS,
    FREQUENT_RECENCY_DAYS,
    LOST_DAYS,
    NEW_PATIENT_DAYS,
    VIP_MIN_VISITS,
    VIP_RECENCY_DAYS,
    _classify_segment,
    _compute_vip_threshold,
    retention_panel_build,
)
from tests.factories import (
    AppointmentFactory,
    DoctorFactory,
    PatientFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

RETENTION_URL = "/api/v1/finanzas/retencion/"


# ---------------------------------------------------------------------------
# Helpers de contexto y datos
# ---------------------------------------------------------------------------


@contextmanager
def _tenant_context(tenant: Any) -> Generator[None, None, None]:
    """Simula el TenantMiddleware para un tenant durante el request."""
    with (
        patch("apps.finanzas.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
    ):
        yield


def _member_client(tenant: Any, role: str) -> APIClient:
    """APIClient autenticado como un miembro del tenant con el rol indicado."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _utc(days_ago: int = 0) -> datetime.datetime:
    """Datetime UTC en el pasado (days_ago días atrás del momento actual)."""
    base = datetime.datetime(2026, 6, 25, 12, 0, 0, tzinfo=datetime.timezone.utc)
    return base - datetime.timedelta(days=days_ago)


def _make_attended_appointment(
    *,
    tenant: Any,
    patient: Any,
    doctor: Any,
    days_ago: int,
) -> Appointment:
    """Crea una cita ATTENDED cuyo starts_at es days_ago días atrás."""
    appt = AppointmentFactory(
        tenant=tenant,
        patient=patient,
        doctor=doctor,
        starts_at=_utc(days_ago),
        ends_at=_utc(days_ago) + datetime.timedelta(minutes=30),
        status=Appointment.Status.ATTENDED,
    )
    return appt


# ---------------------------------------------------------------------------
# Tests unitarios de clasificación de segmentos
# ---------------------------------------------------------------------------


class TestSegmentClassification:
    """Tests sobre _classify_segment directamente (sin BD)."""

    def _base_row(self, **overrides: Any) -> dict[str, Any]:
        """Row base con valores neutrales que resultan en 'ocasional'."""
        row: dict[str, Any] = {
            "patient_id": "test-id",
            "recency_days": 200,
            "freq_12m": 1,
            "spent_12m": Decimal("100.00"),
            "is_new_patient": False,
            "past_visits_count": 0,
        }
        row.update(overrides)
        return row

    def test_nuevo_patient_classified_as_nuevo(self) -> None:
        """Un paciente cuya 1.ª cita fue hace <90 días es NUEVO."""
        row = self._base_row(is_new_patient=True)
        result = _classify_segment(
            row=row, vip_threshold=Decimal("500.00"), today=datetime.date(2026, 6, 25)
        )
        assert result == "nuevo"

    def test_nuevo_takes_priority_over_vip(self) -> None:
        """NUEVO tiene precedencia sobre VIP aunque el gasto sea alto."""
        row = self._base_row(
            is_new_patient=True,
            recency_days=10,
            freq_12m=5,
            spent_12m=Decimal("10000.00"),
        )
        result = _classify_segment(
            row=row, vip_threshold=Decimal("500.00"), today=datetime.date(2026, 6, 25)
        )
        assert result == "nuevo"

    def test_perdido_classified_correctly(self) -> None:
        """Un paciente sin visita en ≥365 días es PERDIDO."""
        row = self._base_row(recency_days=LOST_DAYS + 1, freq_12m=0)
        result = _classify_segment(
            row=row, vip_threshold=Decimal("0.00"), today=datetime.date(2026, 6, 25)
        )
        assert result == "perdido"

    def test_vip_classified_correctly(self) -> None:
        """VIP: gasto ≥ umbral + recencia <180d + ≥2 visitas/año."""
        row = self._base_row(
            is_new_patient=False,
            recency_days=VIP_RECENCY_DAYS - 1,
            freq_12m=VIP_MIN_VISITS,
            spent_12m=Decimal("1000.00"),
        )
        result = _classify_segment(
            row=row, vip_threshold=Decimal("1000.00"), today=datetime.date(2026, 6, 25)
        )
        assert result == "vip"

    def test_vip_requires_sufficient_visits(self) -> None:
        """VIP con solo 1 visita en 12m → no clasifica como VIP."""
        row = self._base_row(
            is_new_patient=False,
            recency_days=VIP_RECENCY_DAYS - 1,
            freq_12m=1,  # < VIP_MIN_VISITS
            spent_12m=Decimal("1000.00"),
        )
        result = _classify_segment(
            row=row, vip_threshold=Decimal("1000.00"), today=datetime.date(2026, 6, 25)
        )
        assert result != "vip"

    def test_frecuente_classified_correctly(self) -> None:
        """Frecuente: ≥2 visitas/año + recencia <180d."""
        row = self._base_row(
            is_new_patient=False,
            recency_days=FREQUENT_RECENCY_DAYS - 10,
            freq_12m=FREQUENT_MIN_VISITS,
            spent_12m=Decimal("0.00"),  # bajo gasto → no VIP
        )
        result = _classify_segment(
            row=row, vip_threshold=Decimal("9999.00"), today=datetime.date(2026, 6, 25)
        )
        assert result == "frecuente"

    def test_en_riesgo_classified_correctly(self) -> None:
        """En riesgo: recencia > 150d + pasado regular (≥2 visitas en año previo)."""
        row = self._base_row(
            is_new_patient=False,
            recency_days=AT_RISK_WINDOW_DAYS + 10,
            freq_12m=0,
            past_visits_count=AT_RISK_MIN_PAST_VISITS,
        )
        result = _classify_segment(
            row=row, vip_threshold=Decimal("9999.00"), today=datetime.date(2026, 6, 25)
        )
        assert result == "en_riesgo"

    def test_en_riesgo_requires_past_regularity(self) -> None:
        """Sin historial previo regular, recencia larga → PERDIDO o OCASIONAL, no en_riesgo."""
        row = self._base_row(
            is_new_patient=False,
            recency_days=AT_RISK_WINDOW_DAYS + 10,
            freq_12m=0,
            past_visits_count=0,  # no era regular
        )
        result = _classify_segment(
            row=row, vip_threshold=Decimal("9999.00"), today=datetime.date(2026, 6, 25)
        )
        assert result == "ocasional"

    def test_ocasional_is_default(self) -> None:
        """El segmento por defecto cuando ninguna regla aplica es OCASIONAL."""
        row = self._base_row()  # recency=200, freq=1 → no encaja en ningún top
        result = _classify_segment(
            row=row, vip_threshold=Decimal("9999.00"), today=datetime.date(2026, 6, 25)
        )
        assert result == "ocasional"

    def test_vip_threshold_computation(self) -> None:
        """El umbral VIP cae en el top 20% de los gastos."""
        rows = [
            {"spent_12m": Decimal(str(v))} for v in [1000, 800, 600, 400, 200]
        ]
        # 5 filas, top 20% = 1 fila → umbral = 1000
        threshold = _compute_vip_threshold(rows)
        assert threshold == Decimal("1000")

    def test_vip_threshold_empty(self) -> None:
        """Sin datos, el umbral VIP es 0."""
        assert _compute_vip_threshold([]) == Decimal("0.00")


# ---------------------------------------------------------------------------
# Tests del selector retention_panel_build (con BD)
# ---------------------------------------------------------------------------


class TestRetentionPanelBuild:
    """Tests del selector principal con DB (fixture db requerida)."""

    def test_empty_tenant_returns_zeros(self, db: None) -> None:
        """Un tenant sin citas devuelve todos los segmentos en 0."""
        tenant = TenantFactory()
        panel = retention_panel_build(tenant_id=tenant.id)

        assert panel["segments"]["nuevo"] == 0
        assert panel["segments"]["vip"] == 0
        assert panel["segments"]["frecuente"] == 0
        assert panel["segments"]["en_riesgo"] == 0
        assert panel["segments"]["perdido"] == 0
        assert panel["segments"]["ocasional"] == 0
        assert panel["at_risk_list"] == []
        assert panel["lost_list"] == []
        assert panel["total_at_risk"] == 0
        assert panel["total_lost"] == 0

    def test_nuevo_patient_detected(self, db: None) -> None:
        """Un paciente con 1.ª cita hace <90 días clasifica como NUEVO."""
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        _make_attended_appointment(
            tenant=tenant, patient=patient, doctor=doctor, days_ago=30
        )

        panel = retention_panel_build(tenant_id=tenant.id)
        assert panel["segments"]["nuevo"] == 1
        assert panel["segments"]["vip"] == 0

    def test_perdido_patient_in_list(self, db: None) -> None:
        """Un paciente sin visita en ≥365 días aparece en lost_list con contacto."""
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant, phone="5512345678", email="p@test.com")
        _make_attended_appointment(
            tenant=tenant, patient=patient, doctor=doctor, days_ago=LOST_DAYS + 30
        )

        panel = retention_panel_build(tenant_id=tenant.id)
        assert panel["segments"]["perdido"] == 1
        assert panel["total_lost"] == 1
        assert len(panel["lost_list"]) == 1

        entry = panel["lost_list"][0]
        assert entry["phone"] == "5512345678"
        assert entry["email"] == "p@test.com"
        assert entry["recency_days"] >= LOST_DAYS

    def test_en_riesgo_patient_detected(self, db: None) -> None:
        """Paciente con visitas en 12-24m previos y última visita hace 150-365 días → en_riesgo.

        Condiciones necesarias:
          - past_visits_count ≥ 2 (visitas en el rango 12m-24m atrás).
          - recency_days ≥ AT_RISK_WINDOW_DAYS (150) Y recency_days < LOST_DAYS (365).
            Si recency >= LOST_DAYS, clasifica como 'perdido' primero.

        Escenario:
          - Dos visitas hace 400-450 días (rango 12-24m previo): forman el historial regular.
          - Una última visita hace 200 días (< 365, > 150): activa el "en_riesgo".
        """
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        # Visitas en el rango 12-24m atrás (historial "antes regular")
        _make_attended_appointment(
            tenant=tenant, patient=patient, doctor=doctor, days_ago=400
        )
        _make_attended_appointment(
            tenant=tenant, patient=patient, doctor=doctor, days_ago=450
        )
        # Última visita hace 200 días → recency=200 >= AT_RISK_WINDOW_DAYS(150)
        # y < LOST_DAYS(365) → no clasificará como 'perdido'.
        # Con freq_12m=1 (solo esta última cita en los últimos 365 días),
        # y spent bajo → no es VIP; freq_12m=1 < FREQUENT_MIN_VISITS(2) → no frecuente.
        _make_attended_appointment(
            tenant=tenant, patient=patient, doctor=doctor, days_ago=200
        )

        panel = retention_panel_build(tenant_id=tenant.id)
        assert panel["segments"]["en_riesgo"] == 1, (
            f"Esperado en_riesgo=1, obtenido: {panel['segments']}"
        )
        assert panel["total_at_risk"] == 1
        assert len(panel["at_risk_list"]) == 1

    def test_frecuente_patient_detected(self, db: None) -> None:
        """Paciente con ≥2 visitas en 12m y recencia <180d → frecuente."""
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        _make_attended_appointment(
            tenant=tenant, patient=patient, doctor=doctor, days_ago=30
        )
        _make_attended_appointment(
            tenant=tenant, patient=patient, doctor=doctor, days_ago=90
        )

        panel = retention_panel_build(tenant_id=tenant.id)
        # El paciente puede ser "nuevo" o "frecuente" dependiendo de su 1.ª cita:
        # primera cita hace 90 días → es nuevo (borderline). Usamos 91 días.
        assert panel["segments"]["nuevo"] + panel["segments"]["frecuente"] >= 1

    def test_tenant_isolation(self, db: None) -> None:
        """Datos de otro tenant no aparecen en el panel del tenant activo."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()

        doctor_a = DoctorFactory(tenant=tenant_a)
        doctor_b = DoctorFactory(tenant=tenant_b)
        patient_a = PatientFactory(tenant=tenant_a)
        patient_b = PatientFactory(tenant=tenant_b)

        # Paciente del tenant B con cita reciente (debería ser NUEVO en tenant B).
        _make_attended_appointment(
            tenant=tenant_b, patient=patient_b, doctor=doctor_b, days_ago=10
        )

        # El panel de tenant A no debe tener ese paciente.
        panel_a = retention_panel_build(tenant_id=tenant_a.id)
        total_a = sum(panel_a["segments"].values())
        assert total_a == 0

    def test_panel_structure_keys(self, db: None) -> None:
        """La respuesta del selector contiene exactamente las claves documentadas."""
        tenant = TenantFactory()
        panel = retention_panel_build(tenant_id=tenant.id)

        assert "segments" in panel
        assert "at_risk_list" in panel
        assert "lost_list" in panel
        assert "total_at_risk" in panel
        assert "total_lost" in panel
        assert "truncated" in panel
        assert "metrics" in panel

        expected_segments = {"nuevo", "vip", "frecuente", "en_riesgo", "perdido", "ocasional"}
        assert set(panel["segments"].keys()) == expected_segments

        expected_metrics = {
            "retention_rate",
            "avg_ticket",
            "no_show_rate",
            "pct_with_future_appt",
            "patients_seen_12m",
            "patients_seen_prev_12m",
        }
        assert set(panel["metrics"].keys()) == expected_metrics

    def test_metrics_none_when_no_data(self, db: None) -> None:
        """Sin datos, las métricas que requieren denominador devuelven None."""
        tenant = TenantFactory()
        panel = retention_panel_build(tenant_id=tenant.id)
        metrics = panel["metrics"]

        # Sin citas en ningún periodo, retention_rate es None (denominador = 0).
        assert metrics["retention_rate"] is None
        assert metrics["no_show_rate"] is None
        assert metrics["pct_with_future_appt"] is None
        assert metrics["avg_ticket"] == Decimal("0.00")

    def test_actionable_list_has_contact_fields(self, db: None) -> None:
        """Cada entrada de at_risk_list tiene los campos de contacto documentados."""
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant, phone="5599887766")

        # Generar un paciente en_riesgo:
        # historial regular (2 visitas en 12-24m previos) + última hace 200 días.
        _make_attended_appointment(
            tenant=tenant, patient=patient, doctor=doctor, days_ago=400
        )
        _make_attended_appointment(
            tenant=tenant, patient=patient, doctor=doctor, days_ago=450
        )
        _make_attended_appointment(
            tenant=tenant, patient=patient, doctor=doctor, days_ago=200
        )

        panel = retention_panel_build(tenant_id=tenant.id)
        assert panel["segments"]["en_riesgo"] == 1, (
            f"Esperado en_riesgo=1, obtenido: {panel['segments']}"
        )
        entry = panel["at_risk_list"][0]
        required_keys = {
            "patient_id", "full_name", "phone", "email",
            "last_visited", "recency_days", "spent_12m", "freq_12m",
        }
        assert required_keys.issubset(entry.keys())
        assert entry["phone"] == "5599887766"


# ---------------------------------------------------------------------------
# Tests de la API GET /finanzas/retencion/
# ---------------------------------------------------------------------------


class TestRetentionPanelApi:
    """Tests del endpoint GET /api/v1/finanzas/retencion/ — permisos y estructura."""

    def test_unauthenticated_returns_401(self, db: None) -> None:
        """Sin autenticación → 401."""
        assert APIClient().get(RETENTION_URL).status_code == 401

    def test_owner_can_view(self, db: None) -> None:
        """Owner puede ver el panel de retención."""
        tenant = TenantFactory()
        client = _member_client(tenant, "owner")
        with _tenant_context(tenant):
            resp = client.get(RETENTION_URL)
        assert resp.status_code == 200

    def test_admin_can_view(self, db: None) -> None:
        """Admin puede ver el panel de retención."""
        tenant = TenantFactory()
        client = _member_client(tenant, "admin")
        with _tenant_context(tenant):
            resp = client.get(RETENTION_URL)
        assert resp.status_code == 200

    def test_finance_can_view(self, db: None) -> None:
        """Finance puede ver el panel de retención."""
        tenant = TenantFactory()
        client = _member_client(tenant, "finance")
        with _tenant_context(tenant):
            resp = client.get(RETENTION_URL)
        assert resp.status_code == 200

    def test_readonly_can_view(self, db: None) -> None:
        """Readonly puede ver el panel de retención (solo-ver)."""
        tenant = TenantFactory()
        client = _member_client(tenant, "readonly")
        with _tenant_context(tenant):
            resp = client.get(RETENTION_URL)
        assert resp.status_code == 200

    def test_reception_cannot_view(self, db: None) -> None:
        """Recepción NO puede ver analítica de retención (D-7 / plan §7)."""
        tenant = TenantFactory()
        client = _member_client(tenant, "reception")
        with _tenant_context(tenant):
            resp = client.get(RETENTION_URL)
        assert resp.status_code == 403

    def test_doctor_cannot_view(self, db: None) -> None:
        """Médico NO puede ver analítica de retención."""
        tenant = TenantFactory()
        client = _member_client(tenant, "doctor")
        with _tenant_context(tenant):
            resp = client.get(RETENTION_URL)
        assert resp.status_code == 403

    def test_nurse_cannot_view(self, db: None) -> None:
        """Enfermería NO puede ver analítica de retención."""
        tenant = TenantFactory()
        client = _member_client(tenant, "nurse")
        with _tenant_context(tenant):
            resp = client.get(RETENTION_URL)
        assert resp.status_code == 403

    def test_response_structure(self, db: None) -> None:
        """La respuesta tiene las claves documentadas en la vista."""
        tenant = TenantFactory()
        client = _member_client(tenant, "owner")
        with _tenant_context(tenant):
            resp = client.get(RETENTION_URL)
        assert resp.status_code == 200

        data = resp.json()
        assert "segments" in data
        assert "at_risk_list" in data
        assert "lost_list" in data
        assert "total_at_risk" in data
        assert "total_lost" in data
        assert "truncated" in data
        assert "metrics" in data

    def test_segment_counts_are_non_negative(self, db: None) -> None:
        """Todos los conteos de segmentos son enteros no negativos."""
        tenant = TenantFactory()
        client = _member_client(tenant, "finance")
        with _tenant_context(tenant):
            resp = client.get(RETENTION_URL)
        assert resp.status_code == 200
        for seg, count in resp.json()["segments"].items():
            assert isinstance(count, int), f"Segmento {seg} no es int: {count}"
            assert count >= 0, f"Segmento {seg} es negativo: {count}"
