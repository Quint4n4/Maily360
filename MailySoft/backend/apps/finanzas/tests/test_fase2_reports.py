"""
Tests de la Fase 2 — Reportes financieros + PDF.

Cubre:
  - finance_period_report: KPIs, comparativa, aging por cubetas, por método/servicio,
    por doctor, series temporales.
  - finance_daily_sheet: producción, cobranza, desglose por método, movimientos.
  - PeriodReportApi (GET /finanzas/reporte/): permisos, rangos, group.
  - PeriodReportPdfApi (GET /finanzas/reporte/pdf/): 200 con Accept PDF, 406 sin él.
  - DailySheetApi (GET /finanzas/cierre-diario/): permiso de caja, fecha default.
  - Aislamiento multi-tenant: tenant A no ve datos de tenant B.

Patrón: AAA + factory_boy + set_current_tenant/set_tenant_context_active.
"""

import datetime
from contextlib import contextmanager
from decimal import Decimal
from typing import Any, Generator
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from apps.finanzas.selectors import finance_daily_sheet, finance_period_report
from tests.factories import (
    ChargeFactory,
    DoctorFactory,
    PaymentFactory,
    PatientFactory,
    ServiceConceptFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
    AppointmentFactory,
)

ZERO = Decimal("0.00")

REPORT_URL = "/api/v1/finanzas/reporte/"
REPORT_PDF_URL = "/api/v1/finanzas/reporte/pdf/"
DAILY_URL = "/api/v1/finanzas/cierre-diario/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _activate(tenant: Any) -> None:
    """Activa el contexto de tenant para que el TenantManager filtre correctamente."""
    set_current_tenant(tenant)
    set_tenant_context_active(True)


@contextmanager
def _tenant_ctx(tenant: Any) -> Generator[None, None, None]:
    """Context manager que simula el efecto del TenantMiddleware en los tests de API."""
    with (
        patch("apps.finanzas.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
    ):
        yield


def _member_client(tenant: Any, role: str) -> APIClient:
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _date(days_ago: int = 0) -> datetime.date:
    """Devuelve la fecha de hoy menos `days_ago` días."""
    return datetime.date.today() - datetime.timedelta(days=days_ago)


def _dt(date: datetime.date) -> Any:
    """Convierte date a datetime aware (UTC noon) para issued_at / received_at."""
    return datetime.datetime(date.year, date.month, date.day, 12, 0, 0,
                              tzinfo=datetime.timezone.utc)


# ===========================================================================
# Selector: finance_period_report
# ===========================================================================


class TestFinancePeriodReport:
    """Tests del selector finance_period_report."""

    def test_production_excludes_cancelled(self, db: None) -> None:
        """Los cargos CANCELLED no entran en producción."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        today = _date()

        # Cargo normal = $500 → entra en producción
        ChargeFactory(
            tenant=tenant, patient=patient, amount=Decimal("500.00"),
            status="pending", issued_at=_dt(today)
        )
        # Cargo cancelado = $200 → NO entra
        ChargeFactory(
            tenant=tenant, patient=patient, amount=Decimal("200.00"),
            status="cancelled", issued_at=_dt(today)
        )

        _activate(tenant)
        report = finance_period_report(date_from=today, date_to=today)

        assert report["production"] == Decimal("500.00")
        assert report["charges_count"] == 1

    def test_collection_sums_payments_in_range(self, db: None) -> None:
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        today = _date()

        PaymentFactory(tenant=tenant, patient=patient,
                       amount=Decimal("300.00"), received_at=_dt(today))
        PaymentFactory(tenant=tenant, patient=patient,
                       amount=Decimal("150.00"), received_at=_dt(today))

        _activate(tenant)
        report = finance_period_report(date_from=today, date_to=today)

        assert report["collection"] == Decimal("450.00")

    def test_collection_pct_calculation(self, db: None) -> None:
        """collection_pct = collection / production."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        today = _date()

        ChargeFactory(tenant=tenant, patient=patient, amount=Decimal("1000.00"),
                      issued_at=_dt(today))
        PaymentFactory(tenant=tenant, patient=patient, amount=Decimal("800.00"),
                       received_at=_dt(today))

        _activate(tenant)
        report = finance_period_report(date_from=today, date_to=today)

        assert report["collection_pct"] == Decimal("0.8")

    def test_average_ticket_is_production_over_charges(self, db: None) -> None:
        """average_ticket = producción / nº cargos del periodo."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        today = _date()

        ChargeFactory(tenant=tenant, patient=patient, amount=Decimal("600.00"),
                      issued_at=_dt(today))
        ChargeFactory(tenant=tenant, patient=patient, amount=Decimal("400.00"),
                      issued_at=_dt(today))

        _activate(tenant)
        report = finance_period_report(date_from=today, date_to=today)

        assert report["production"] == Decimal("1000.00")
        assert report["charges_count"] == 2
        assert report["average_ticket"] == Decimal("500.00")

    def test_comparativa_periodo_anterior(self, db: None) -> None:
        """El periodo anterior se calcula automáticamente (mismo tamaño, inmediatamente antes)."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        today = _date()
        yesterday = _date(1)

        # Periodo actual: hoy — producción $1000
        ChargeFactory(tenant=tenant, patient=patient, amount=Decimal("1000.00"),
                      issued_at=_dt(today))
        # Periodo anterior: ayer — producción $500
        ChargeFactory(tenant=tenant, patient=patient, amount=Decimal("500.00"),
                      issued_at=_dt(yesterday))

        _activate(tenant)
        report = finance_period_report(date_from=today, date_to=today)

        assert report["prev_production"] == Decimal("500.00")
        # Δ% = (1000 - 500) / 500 * 100 = 100%
        assert report["delta_production_pct"] == Decimal("100.00")

    def test_delta_none_when_no_prev_production(self, db: None) -> None:
        """delta_production_pct es None cuando el periodo anterior no tiene cargos."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        today = _date()

        ChargeFactory(tenant=tenant, patient=patient, amount=Decimal("500.00"),
                      issued_at=_dt(today))

        _activate(tenant)
        report = finance_period_report(date_from=today, date_to=today)

        assert report["prev_production"] == ZERO
        assert report["delta_production_pct"] is None

    def test_aging_buckets_0_30(self, db: None) -> None:
        """Un cargo de hoy cae en el bucket 0-30."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        today = _date()

        ChargeFactory(
            tenant=tenant, patient=patient, amount=Decimal("400.00"),
            amount_paid=Decimal("0.00"), status="pending",
            issued_at=_dt(today)
        )

        _activate(tenant)
        report = finance_period_report(date_from=today, date_to=today)

        aging = {row["bucket"]: row for row in report["aging"]}
        assert aging["0-30"]["amount"] == Decimal("400.00")
        assert aging["0-30"]["count"] == 1
        # Los otros buckets deben ser 0
        assert aging["31-60"]["amount"] == ZERO
        assert aging["61-90"]["amount"] == ZERO
        assert aging["90+"]["amount"] == ZERO

    def test_aging_buckets_90_plus(self, db: None) -> None:
        """Un cargo de 91 días atrás cae en el bucket 90+."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        today = _date()
        old_date = _date(91)

        ChargeFactory(
            tenant=tenant, patient=patient, amount=Decimal("999.00"),
            amount_paid=Decimal("0.00"), status="pending",
            issued_at=_dt(old_date)
        )

        _activate(tenant)
        report = finance_period_report(date_from=today, date_to=today)

        aging = {row["bucket"]: row for row in report["aging"]}
        assert aging["90+"]["amount"] == Decimal("999.00")
        assert aging["0-30"]["amount"] == ZERO

    def test_aging_paid_charges_not_included(self, db: None) -> None:
        """Los cargos PAID no aparecen en el A/R aging."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        today = _date()

        ChargeFactory(
            tenant=tenant, patient=patient, amount=Decimal("600.00"),
            amount_paid=Decimal("600.00"), status="paid",
            issued_at=_dt(today)
        )

        _activate(tenant)
        report = finance_period_report(date_from=today, date_to=today)

        total = sum(row["amount"] for row in report["aging"])
        assert total == ZERO
        assert report["ar_total"] == ZERO

    def test_by_method_groups_correctly(self, db: None) -> None:
        """Los pagos se agrupan por método de pago."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        today = _date()

        PaymentFactory(tenant=tenant, patient=patient,
                       amount=Decimal("100.00"), method="cash", received_at=_dt(today))
        PaymentFactory(tenant=tenant, patient=patient,
                       amount=Decimal("200.00"), method="card", received_at=_dt(today))
        PaymentFactory(tenant=tenant, patient=patient,
                       amount=Decimal("50.00"), method="cash", received_at=_dt(today))

        _activate(tenant)
        report = finance_period_report(date_from=today, date_to=today)

        by_method = {row["method"]: row for row in report["by_method"]}
        assert by_method["cash"]["amount"] == Decimal("150.00")
        assert by_method["cash"]["count"] == 2
        assert by_method["card"]["amount"] == Decimal("200.00")

    def test_by_service_top_services(self, db: None) -> None:
        """Se agrupan cargos por descripción (snapshot del servicio)."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        today = _date()

        ChargeFactory(tenant=tenant, patient=patient,
                      description="Consulta", amount=Decimal("800.00"),
                      issued_at=_dt(today))
        ChargeFactory(tenant=tenant, patient=patient,
                      description="Consulta", amount=Decimal("800.00"),
                      issued_at=_dt(today))
        ChargeFactory(tenant=tenant, patient=patient,
                      description="Radiografía", amount=Decimal("300.00"),
                      issued_at=_dt(today))

        _activate(tenant)
        report = finance_period_report(date_from=today, date_to=today)

        by_service = {row["name"]: row for row in report["by_service"]}
        assert by_service["Consulta"]["amount"] == Decimal("1600.00")
        assert by_service["Consulta"]["count"] == 2
        assert by_service["Radiografía"]["amount"] == Decimal("300.00")

    def test_by_doctor_from_appointment(self, db: None) -> None:
        """Los cargos con appointment se agrupan por doctor del appointment."""
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        today = _date()

        from apps.agenda.models import Appointment
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            starts_at=_dt(today),
            ends_at=_dt(today) + datetime.timedelta(minutes=30),
        )

        ChargeFactory(
            tenant=tenant, patient=patient, amount=Decimal("700.00"),
            appointment=appt, issued_at=_dt(today)
        )

        _activate(tenant)
        report = finance_period_report(date_from=today, date_to=today)

        by_doctor = [r for r in report["by_doctor"] if r["doctor_id"] is not None]
        assert len(by_doctor) == 1
        assert by_doctor[0]["amount"] == Decimal("700.00")
        assert by_doctor[0]["count"] == 1

    def test_by_doctor_manual_charge_no_appointment(self, db: None) -> None:
        """Cargos sin appointment aparecen en la entrada 'Sin cita'."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        today = _date()

        ChargeFactory(
            tenant=tenant, patient=patient, amount=Decimal("200.00"),
            appointment=None, issued_at=_dt(today)
        )

        _activate(tenant)
        report = finance_period_report(date_from=today, date_to=today)

        no_doctor = [r for r in report["by_doctor"] if r["doctor_id"] is None]
        assert len(no_doctor) == 1
        assert no_doctor[0]["amount"] == Decimal("200.00")

    def test_series_day_group(self, db: None) -> None:
        """La serie con group=day agrupa producción y cobranza por fecha."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        today = _date()
        yesterday = _date(1)

        ChargeFactory(tenant=tenant, patient=patient,
                      amount=Decimal("500.00"), issued_at=_dt(today))
        ChargeFactory(tenant=tenant, patient=patient,
                      amount=Decimal("300.00"), issued_at=_dt(yesterday))
        PaymentFactory(tenant=tenant, patient=patient,
                       amount=Decimal("400.00"), received_at=_dt(today))

        _activate(tenant)
        report = finance_period_report(
            date_from=yesterday, date_to=today, group="day"
        )

        series = {row["period"]: row for row in report["series"]}
        assert series[today.isoformat()]["production"] == Decimal("500.00")
        assert series[today.isoformat()]["collection"] == Decimal("400.00")
        assert series[yesterday.isoformat()]["production"] == Decimal("300.00")
        assert series[yesterday.isoformat()]["collection"] == ZERO

    def test_adjustments_note_present(self, db: None) -> None:
        """El reporte incluye nota de ajustes (0, sin modelo Adjustment aún)."""
        tenant = TenantFactory()
        _activate(tenant)
        report = finance_period_report(date_from=_date(), date_to=_date())
        assert report["adjustments_total"] == ZERO
        assert "adjustments_note" in report
        assert isinstance(report["adjustments_note"], str)

    def test_tenant_isolation(self, db: None) -> None:
        """El reporte del tenant A no incluye datos del tenant B."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        patient_a = PatientFactory(tenant=tenant_a)
        patient_b = PatientFactory(tenant=tenant_b)
        today = _date()

        ChargeFactory(tenant=tenant_a, patient=patient_a,
                      amount=Decimal("1000.00"), issued_at=_dt(today))
        ChargeFactory(tenant=tenant_b, patient=patient_b,
                      amount=Decimal("9999.00"), issued_at=_dt(today))

        _activate(tenant_a)
        report = finance_period_report(date_from=today, date_to=today)

        assert report["production"] == Decimal("1000.00")


# ===========================================================================
# Selector: finance_daily_sheet
# ===========================================================================


class TestFinanceDailySheet:
    def test_daily_sheet_production_and_collection(self, db: None) -> None:
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        today = _date()

        ChargeFactory(tenant=tenant, patient=patient,
                      amount=Decimal("500.00"), issued_at=_dt(today))
        PaymentFactory(tenant=tenant, patient=patient,
                       amount=Decimal("300.00"), received_at=_dt(today))

        _activate(tenant)
        sheet = finance_daily_sheet(date=today)

        assert sheet["production"] == Decimal("500.00")
        assert sheet["collection"] == Decimal("300.00")
        assert sheet["adjustments_total"] == ZERO

    def test_daily_sheet_excludes_other_days(self, db: None) -> None:
        """Los movimientos de ayer no aparecen en el cierre de hoy."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        today = _date()
        yesterday = _date(1)

        ChargeFactory(tenant=tenant, patient=patient,
                      amount=Decimal("1000.00"), issued_at=_dt(yesterday))
        PaymentFactory(tenant=tenant, patient=patient,
                       amount=Decimal("999.00"), received_at=_dt(yesterday))

        _activate(tenant)
        sheet = finance_daily_sheet(date=today)

        assert sheet["production"] == ZERO
        assert sheet["collection"] == ZERO
        assert sheet["movements"] == []

    def test_daily_sheet_by_method(self, db: None) -> None:
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        today = _date()

        PaymentFactory(tenant=tenant, patient=patient,
                       amount=Decimal("200.00"), method="cash", received_at=_dt(today))
        PaymentFactory(tenant=tenant, patient=patient,
                       amount=Decimal("150.00"), method="transfer", received_at=_dt(today))

        _activate(tenant)
        sheet = finance_daily_sheet(date=today)

        methods = {row["method"]: row for row in sheet["by_method"]}
        assert methods["cash"]["amount"] == Decimal("200.00")
        assert methods["transfer"]["amount"] == Decimal("150.00")

    def test_daily_sheet_movements_are_chronological(self, db: None) -> None:
        """Los movimientos del día están ordenados cronológicamente."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        today = _date()

        dt_early = datetime.datetime(today.year, today.month, today.day,
                                     9, 0, 0, tzinfo=datetime.timezone.utc)
        dt_late = datetime.datetime(today.year, today.month, today.day,
                                    16, 0, 0, tzinfo=datetime.timezone.utc)

        ChargeFactory(tenant=tenant, patient=patient,
                      amount=Decimal("300.00"), issued_at=dt_late)
        PaymentFactory(tenant=tenant, patient=patient,
                       amount=Decimal("100.00"), received_at=dt_early)

        _activate(tenant)
        sheet = finance_daily_sheet(date=today)

        ats = [m["at"] for m in sheet["movements"]]
        assert ats == sorted(ats)

    def test_daily_sheet_cancelled_excluded(self, db: None) -> None:
        """Los cargos CANCELLED no entran en producción del cierre."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        today = _date()

        ChargeFactory(tenant=tenant, patient=patient,
                      amount=Decimal("500.00"), status="cancelled",
                      issued_at=_dt(today))

        _activate(tenant)
        sheet = finance_daily_sheet(date=today)

        assert sheet["production"] == ZERO
        assert sheet["totals"]["charges_count"] == 0

    def test_daily_sheet_tenant_isolation(self, db: None) -> None:
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        patient_a = PatientFactory(tenant=tenant_a)
        patient_b = PatientFactory(tenant=tenant_b)
        today = _date()

        ChargeFactory(tenant=tenant_a, patient=patient_a,
                      amount=Decimal("100.00"), issued_at=_dt(today))
        ChargeFactory(tenant=tenant_b, patient=patient_b,
                      amount=Decimal("5000.00"), issued_at=_dt(today))

        _activate(tenant_a)
        sheet = finance_daily_sheet(date=today)

        assert sheet["production"] == Decimal("100.00")


# ===========================================================================
# API: PeriodReportApi  GET /api/v1/finanzas/reporte/
# ===========================================================================


class TestPeriodReportApi:
    def test_requires_auth(self, db: None) -> None:
        resp = APIClient().get(REPORT_URL)
        assert resp.status_code == 401

    def test_finance_role_can_access(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "finance")
        with _tenant_ctx(tenant):
            resp = client.get(REPORT_URL)
        assert resp.status_code == 200

    def test_owner_can_access(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "owner")
        with _tenant_ctx(tenant):
            resp = client.get(REPORT_URL)
        assert resp.status_code == 200

    def test_admin_can_access(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "admin")
        with _tenant_ctx(tenant):
            resp = client.get(REPORT_URL)
        assert resp.status_code == 200

    def test_readonly_can_access(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "readonly")
        with _tenant_ctx(tenant):
            resp = client.get(REPORT_URL)
        assert resp.status_code == 200

    def test_reception_cannot_access_report(self, db: None) -> None:
        """Reception NO puede ver el panel analítico (solo cierre diario)."""
        tenant = TenantFactory()
        client = _member_client(tenant, "reception")
        with _tenant_ctx(tenant):
            resp = client.get(REPORT_URL)
        assert resp.status_code == 403

    def test_doctor_cannot_access_report(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "doctor")
        with _tenant_ctx(tenant):
            resp = client.get(REPORT_URL)
        assert resp.status_code == 403

    def test_nurse_cannot_access_report(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "nurse")
        with _tenant_ctx(tenant):
            resp = client.get(REPORT_URL)
        assert resp.status_code == 403

    def test_invalid_date_from_after_date_to_returns_400(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "finance")
        with _tenant_ctx(tenant):
            resp = client.get(
                REPORT_URL, {"date_from": "2026-06-30", "date_to": "2026-06-01"}
            )
        assert resp.status_code == 400

    def test_invalid_group_returns_400(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "finance")
        with _tenant_ctx(tenant):
            resp = client.get(REPORT_URL, {"group": "quarter"})
        assert resp.status_code == 400

    def test_valid_group_day(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "finance")
        with _tenant_ctx(tenant):
            resp = client.get(REPORT_URL, {"group": "day"})
        assert resp.status_code == 200
        assert resp.data["group"] == "day"

    def test_valid_group_month(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "finance")
        with _tenant_ctx(tenant):
            resp = client.get(REPORT_URL, {"group": "month"})
        assert resp.status_code == 200
        assert resp.data["group"] == "month"

    def test_response_contains_expected_keys(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "owner")
        with _tenant_ctx(tenant):
            resp = client.get(REPORT_URL)
        data = resp.data
        assert resp.status_code == 200
        for key in [
            "range", "prev_range", "group", "production", "collection",
            "collection_pct", "ar_total", "aging", "average_ticket",
            "charges_count", "prev_production", "prev_collection",
            "prev_collection_pct", "delta_production_pct", "delta_collection_pct",
            "by_method", "by_service", "by_doctor", "series",
            "adjustments_total", "adjustments_note",
        ]:
            assert key in data, f"Falta la clave '{key}' en la respuesta"


# ===========================================================================
# API: PeriodReportPdfApi  GET /api/v1/finanzas/reporte/pdf/
# ===========================================================================


class TestPeriodReportPdfApi:
    def test_requires_auth(self, db: None) -> None:
        resp = APIClient().get(REPORT_PDF_URL, HTTP_ACCEPT="application/pdf")
        assert resp.status_code == 401

    def test_pdf_200_with_accept_header(self, db: None) -> None:
        """Accept: application/pdf → 200 con Content-Type application/pdf."""
        tenant = TenantFactory()
        client = _member_client(tenant, "finance")
        with _tenant_ctx(tenant):
            resp = client.get(
                REPORT_PDF_URL,
                HTTP_ACCEPT="application/pdf",
            )
        assert resp.status_code == 200
        assert "application/pdf" in resp.get("Content-Type", "")

    def test_pdf_406_without_accept_header(self, db: None) -> None:
        """Sin Accept: application/pdf → 406 Not Acceptable."""
        tenant = TenantFactory()
        client = _member_client(tenant, "finance")
        with _tenant_ctx(tenant):
            resp = client.get(REPORT_PDF_URL, HTTP_ACCEPT="application/json")
        assert resp.status_code == 406

    def test_reception_cannot_access_pdf(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "reception")
        with _tenant_ctx(tenant):
            resp = client.get(
                REPORT_PDF_URL,
                HTTP_ACCEPT="application/pdf",
            )
        assert resp.status_code == 403

    def test_pdf_contains_bytes(self, db: None) -> None:
        """El PDF devuelve bytes (no vacío)."""
        tenant = TenantFactory()
        client = _member_client(tenant, "owner")
        with _tenant_ctx(tenant):
            resp = client.get(
                REPORT_PDF_URL,
                HTTP_ACCEPT="application/pdf",
            )
        assert resp.status_code == 200
        assert len(resp.content) > 100  # Al menos 100 bytes de PDF

    def test_pdf_content_disposition_inline(self, db: None) -> None:
        """El PDF devuelve Content-Disposition: inline (no fuerza descarga)."""
        tenant = TenantFactory()
        client = _member_client(tenant, "finance")
        with _tenant_ctx(tenant):
            resp = client.get(REPORT_PDF_URL, HTTP_ACCEPT="application/pdf")
        assert resp.status_code == 200
        assert "inline" in resp.get("Content-Disposition", "")


# ===========================================================================
# API: DailySheetApi  GET /api/v1/finanzas/cierre-diario/
# ===========================================================================


class TestDailySheetApi:
    def test_requires_auth(self, db: None) -> None:
        resp = APIClient().get(DAILY_URL)
        assert resp.status_code == 401

    def test_reception_can_access(self, db: None) -> None:
        """Reception ES parte de FINANCE_DESK_ROLES → puede ver el cierre diario."""
        tenant = TenantFactory()
        client = _member_client(tenant, "reception")
        with _tenant_ctx(tenant):
            resp = client.get(DAILY_URL)
        assert resp.status_code == 200

    def test_finance_can_access(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "finance")
        with _tenant_ctx(tenant):
            resp = client.get(DAILY_URL)
        assert resp.status_code == 200

    def test_owner_can_access(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "owner")
        with _tenant_ctx(tenant):
            resp = client.get(DAILY_URL)
        assert resp.status_code == 200

    def test_doctor_cannot_access(self, db: None) -> None:
        """Doctor NO accede a finanzas (ni al cierre diario)."""
        tenant = TenantFactory()
        client = _member_client(tenant, "doctor")
        with _tenant_ctx(tenant):
            resp = client.get(DAILY_URL)
        assert resp.status_code == 403

    def test_readonly_cannot_access_daily_sheet(self, db: None) -> None:
        """Readonly NO puede ver el cierre diario (es exclusivo de caja)."""
        tenant = TenantFactory()
        client = _member_client(tenant, "readonly")
        with _tenant_ctx(tenant):
            resp = client.get(DAILY_URL)
        assert resp.status_code == 403

    def test_date_defaults_to_today(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "finance")
        today = datetime.date.today()
        with _tenant_ctx(tenant):
            resp = client.get(DAILY_URL)
        assert resp.status_code == 200
        assert resp.data["date"] == today.isoformat()

    def test_explicit_date_parameter(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "finance")
        target = "2026-01-15"
        with _tenant_ctx(tenant):
            resp = client.get(DAILY_URL, {"date": target})
        assert resp.status_code == 200
        assert resp.data["date"] == target

    def test_invalid_date_returns_400(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "finance")
        with _tenant_ctx(tenant):
            resp = client.get(DAILY_URL, {"date": "not-a-date"})
        assert resp.status_code == 400

    def test_response_keys(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "owner")
        with _tenant_ctx(tenant):
            resp = client.get(DAILY_URL)
        for key in ["date", "production", "collection", "adjustments_total",
                    "collection_pct", "by_method", "movements", "totals"]:
            assert key in resp.data, f"Falta la clave '{key}'"
