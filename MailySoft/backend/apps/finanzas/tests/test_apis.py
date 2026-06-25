"""
Tests de las APIs del dominio finanzas (views.py).

Foco principal: la MATRIZ DE ROLES (sección 2 del plan) y el aislamiento por
tenant. Se mockea el contexto de tenant igual que en apps/pacientes/tests
(force_authenticate solo afecta el DRF Request, no el HttpRequest del middleware).

Patrón: AAA. Todas tocan BD → fixture db.
"""

from contextlib import contextmanager
from decimal import Decimal
from typing import Any, Generator
from unittest.mock import patch

from rest_framework.test import APIClient

from tests.factories import (
    ChargeFactory,
    PatientFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

DASHBOARD_URL = "/api/v1/finanzas/dashboard/"
CONCEPTS_URL = "/api/v1/finanzas/conceptos/"
CHARGES_URL = "/api/v1/finanzas/cargos/"
PAYMENTS_URL = "/api/v1/finanzas/pagos/"
CFDI_URL = "/api/v1/finanzas/cfdi/"


@contextmanager
def _tenant_context(tenant: Any) -> Generator[None, None, None]:
    """Simula el efecto del TenantMiddleware para un tenant durante el request."""
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


# ===========================================================================
# Dashboard — matriz de roles
# ===========================================================================


class TestDashboardPermissions:
    def test_dashboard_requires_auth(self, db: None) -> None:
        assert APIClient().get(DASHBOARD_URL).status_code == 401

    def test_finance_can_view_dashboard(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "finance")
        with _tenant_context(tenant):
            assert client.get(DASHBOARD_URL).status_code == 200

    def test_owner_can_view_dashboard(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "owner")
        with _tenant_context(tenant):
            assert client.get(DASHBOARD_URL).status_code == 200

    def test_readonly_can_view_dashboard(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "readonly")
        with _tenant_context(tenant):
            assert client.get(DASHBOARD_URL).status_code == 200

    def test_reception_cannot_view_dashboard(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "reception")
        with _tenant_context(tenant):
            assert client.get(DASHBOARD_URL).status_code == 403

    def test_doctor_cannot_view_dashboard(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "doctor")
        with _tenant_context(tenant):
            assert client.get(DASHBOARD_URL).status_code == 403


# ===========================================================================
# Conceptos — lectura amplia, escritura admin
# ===========================================================================


class TestConceptPermissions:
    def test_reception_can_list_concepts(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "reception")
        with _tenant_context(tenant):
            assert client.get(CONCEPTS_URL).status_code == 200

    def test_finance_cannot_create_concept(self, db: None) -> None:
        """El catálogo es administrativo: finance no crea conceptos (solo owner/admin)."""
        tenant = TenantFactory()
        client = _member_client(tenant, "finance")
        with _tenant_context(tenant):
            resp = client.post(CONCEPTS_URL, data={"name": "Consulta", "base_price": "500.00"}, format="json")
        assert resp.status_code == 403

    def test_admin_can_create_concept(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "admin")
        with _tenant_context(tenant):
            resp = client.post(CONCEPTS_URL, data={"name": "Consulta", "base_price": "500.00"}, format="json")
        assert resp.status_code == 201
        assert resp.json()["name"] == "Consulta"


# ===========================================================================
# Cargos — escritura solo finance/owner/admin
# ===========================================================================


class TestChargePermissions:
    def test_finance_can_create_charge(self, db: None) -> None:
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = _member_client(tenant, "finance")
        with _tenant_context(tenant):
            resp = client.post(
                CHARGES_URL,
                data={"patient_id": str(patient.id), "description": "Consulta", "amount": "500.00"},
                format="json",
            )
        assert resp.status_code == 201

    def test_reception_cannot_create_charge(self, db: None) -> None:
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = _member_client(tenant, "reception")
        with _tenant_context(tenant):
            resp = client.post(
                CHARGES_URL,
                data={"patient_id": str(patient.id), "description": "Consulta", "amount": "500.00"},
                format="json",
            )
        assert resp.status_code == 403

    def test_charge_other_tenant_returns_404(self, db: None) -> None:
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        charge_b = ChargeFactory(tenant=tenant_b)
        client = _member_client(tenant_a, "finance")
        with _tenant_context(tenant_a):
            resp = client.get(f"{CHARGES_URL}{charge_b.id}/")
        assert resp.status_code == 404


# ===========================================================================
# Pagos — caja (incluye recepción)
# ===========================================================================


class TestPaymentPermissions:
    def test_reception_can_register_payment(self, db: None) -> None:
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = _member_client(tenant, "reception")
        with _tenant_context(tenant):
            resp = client.post(
                PAYMENTS_URL,
                data={"patient_id": str(patient.id), "amount": "300.00", "method": "cash"},
                format="json",
            )
        assert resp.status_code == 201

    def test_readonly_cannot_register_payment(self, db: None) -> None:
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = _member_client(tenant, "readonly")
        with _tenant_context(tenant):
            resp = client.post(
                PAYMENTS_URL,
                data={"patient_id": str(patient.id), "amount": "300.00"},
                format="json",
            )
        assert resp.status_code == 403


# ===========================================================================
# CFDI — recepción no factura
# ===========================================================================


class TestCfdiPermissions:
    def test_reception_cannot_list_cfdi(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "reception")
        with _tenant_context(tenant):
            assert client.get(CFDI_URL).status_code == 403

    def test_finance_can_list_cfdi(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "finance")
        with _tenant_context(tenant):
            assert client.get(CFDI_URL).status_code == 200
