"""
Tests de selectors.py del dominio finanzas.

Cubre:
- account_statement_build: movimientos cronológicos + saldo corriente + totales.
- finance_dashboard_metrics: KPIs, series (por día/concepto/método), aging y embudo.
- Aislamiento por tenant con contexto activo.

Patrón: AAA. Tenant context activado explícitamente con
set_current_tenant + set_tenant_context_active (igual que pacientes).
"""

from decimal import Decimal

import pytest

from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from apps.finanzas.selectors import account_statement_build, finance_dashboard_metrics
from apps.finanzas.services import (
    charge_create,
    payment_register,
    quote_create,
    quote_accept,
)
from tests.factories import PatientFactory, TenantFactory, UserFactory


def _activate(tenant) -> None:
    set_current_tenant(tenant)
    set_tenant_context_active(True)


# ===========================================================================
# Estado de cuenta
# ===========================================================================


class TestAccountStatement:
    def test_statement_running_balance(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        charge_create(tenant=tenant, user=user, patient=patient, amount=Decimal("500.00"), description="A")
        charge_create(tenant=tenant, user=user, patient=patient, amount=Decimal("300.00"), description="B")
        payment_register(tenant=tenant, user=user, patient=patient, amount=Decimal("400.00"))

        _activate(tenant)
        statement = account_statement_build(patient_id=patient.id)

        assert statement["total_charged"] == Decimal("800.00")
        assert statement["total_paid"] == Decimal("400.00")
        assert statement["balance"] == Decimal("400.00")
        assert len(statement["movements"]) == 3
        # El saldo del último movimiento coincide con el balance global.
        assert statement["movements"][-1]["balance"] == Decimal("400.00")

    def test_statement_empty_patient(self, db: None) -> None:
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)

        _activate(tenant)
        statement = account_statement_build(patient_id=patient.id)

        assert statement["balance"] == Decimal("0.00")
        assert statement["movements"] == []


# ===========================================================================
# Dashboard
# ===========================================================================


class TestDashboardMetrics:
    def test_kpis_reflect_payments_and_charges(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        charge_create(tenant=tenant, user=user, patient=patient, amount=Decimal("1000.00"), description="A")
        payment_register(
            tenant=tenant, user=user, patient=patient, amount=Decimal("600.00"),
            method="card",
        )

        _activate(tenant)
        metrics = finance_dashboard_metrics()

        assert metrics["kpis"]["total_income"] == Decimal("600.00")
        assert metrics["kpis"]["total_charged"] == Decimal("1000.00")
        # Saldo pendiente global = 1000 (sin pagos aplicados al cargo).
        assert metrics["kpis"]["outstanding"] == Decimal("1000.00")
        assert metrics["kpis"]["payments_count"] == 1

    def test_income_by_method_groups(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        payment_register(tenant=tenant, user=user, patient=patient, amount=Decimal("100.00"), method="cash")
        payment_register(tenant=tenant, user=user, patient=patient, amount=Decimal("200.00"), method="card")

        _activate(tenant)
        metrics = finance_dashboard_metrics()

        methods = {row["method"]: row["amount"] for row in metrics["income_by_method"]}
        assert methods["cash"] == Decimal("100.00")
        assert methods["card"] == Decimal("200.00")

    def test_quotes_funnel_conversion(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        accepted = quote_create(
            tenant=tenant, user=user, patient=patient,
            items=[{"description": "X", "unit_price": "100"}],
        )
        quote_accept(quote=accepted, user=user)
        # Una segunda cotización que queda enviada (no aceptada).
        from apps.finanzas.services import quote_send

        sent = quote_create(
            tenant=tenant, user=user, patient=patient,
            items=[{"description": "Y", "unit_price": "100"}],
        )
        quote_send(quote=sent, user=user)

        _activate(tenant)
        metrics = finance_dashboard_metrics()

        funnel = metrics["quotes_funnel"]
        assert funnel["accepted"] == 1
        assert funnel["sent"] == 1
        # 1 aceptada de 2 decididas (sent + accepted) → 0.5
        assert funnel["conversion_rate"] == 0.5

    def test_dashboard_isolated_by_tenant(self, db: None) -> None:
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user = UserFactory()
        pa = PatientFactory(tenant=tenant_a)
        pb = PatientFactory(tenant=tenant_b)
        payment_register(tenant=tenant_a, user=user, patient=pa, amount=Decimal("100.00"))
        payment_register(tenant=tenant_b, user=user, patient=pb, amount=Decimal("999.00"))

        _activate(tenant_a)
        metrics = finance_dashboard_metrics()

        # Solo debe ver el ingreso del tenant A.
        assert metrics["kpis"]["total_income"] == Decimal("100.00")
