"""
Tests de GET /api/v1/me/ — campo `sucursales` (multi-sede — Fase 1).

Verifica que /me expone la lista de sucursales permitidas del usuario en el
tenant activo (apps.clinica.sucursal_scope.allowed_sucursales), para
inicializar el selector de sucursal del frontend.

MeApi no hereda de TenantAPIView (no hay contexto de tenant en el
thread-local); resuelve todo explícitamente por tenant_id, así que estos
tests NO necesitan parchear get_current_tenant — solo force_authenticate.

Patrón: AAA. Todas tocan BD → fixture db.
"""

from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.tenancy.models import TenantMembership
from tests.factories import (
    MembershipSucursalFactory,
    SucursalFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

ME_URL = "/api/v1/me/"


def _auth_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
class TestMeSucursales:
    def test_owner_ve_todas_las_sucursales_activas(self) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        TenantMembershipFactory(
            user=user, tenant=tenant, role=TenantMembership.Role.OWNER, is_active=True
        )
        principal = SucursalFactory(tenant=tenant, name="Principal", is_default=True)
        SucursalFactory(tenant=tenant, name="Norte", is_default=False)
        SucursalFactory(tenant=tenant, name="Inactiva", is_active=False)

        client = _auth_client(user)
        resp = client.get(ME_URL)

        assert resp.status_code == 200, resp.content
        sucursales = resp.json()["sucursales"]
        assert len(sucursales) == 2
        names = {s["name"] for s in sucursales}
        assert names == {"Principal", "Norte"}
        default_flags = {s["name"]: s["is_default"] for s in sucursales}
        assert default_flags["Principal"] is True
        assert default_flags["Norte"] is False
        assert all("id" in s for s in sucursales)
        assert principal.id is not None  # sanity: la fixture se usó

    def test_recepcion_solo_ve_su_sucursal_asignada(self) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        membership = TenantMembershipFactory(
            user=user, tenant=tenant, role=TenantMembership.Role.RECEPTION, is_active=True
        )
        centro = SucursalFactory(tenant=tenant, name="Centro")
        SucursalFactory(tenant=tenant, name="Norte")
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)

        client = _auth_client(user)
        resp = client.get(ME_URL)

        assert resp.status_code == 200, resp.content
        sucursales = resp.json()["sucursales"]
        assert len(sucursales) == 1
        assert sucursales[0]["name"] == "Centro"

    def test_sin_tenant_activo_sucursales_vacio(self) -> None:
        user = UserFactory()  # sin ninguna membresía

        client = _auth_client(user)
        resp = client.get(ME_URL)

        assert resp.status_code == 200, resp.content
        assert resp.json()["sucursales"] == []
