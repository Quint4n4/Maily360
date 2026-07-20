"""
Tests de asignación de sucursales a un miembro (multi-sede — Fase 4).

Cubre:
1. Selector: membership_sucursales_list (sucursales asignadas a una membresía).
2. Service: membership_sucursales_set —
   - Camino feliz: owner asigna sedes; allowed_sucursales del usuario objetivo
     cambia en consecuencia (así se crea un "administrador de sucursal").
   - Escalada de privilegios: un admin de Centro NO puede otorgar Norte a
     nadie, ni quitarle Norte a otro usuario (solo puede tocar lo que él
     mismo tiene permitido).
   - Validaciones de datos: membership de otro tenant, sucursal de otro tenant.
   - Anti-lockout: owner sin sucursales, admin quitándose a sí mismo todas.
3. Endpoints HTTP: permisos por rol (owner/admin sí, recepción/doctor no),
   404 IDOR cross-tenant de membership, 400 de sucursal cross-tenant,
   contrato de la respuesta ({membership_id, sucursales: [...]})..

Patrón: AAA. Mismo helper _api_tenant_ctx que apps/clinica/tests/test_sucursales.py
(parchea get_current_tenant en apps.clinica.views + apps.core.managers).
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.test import APIClient

from apps.clinica.models import MembershipSucursal
from apps.clinica.selectors import membership_sucursales_list
from apps.clinica.services import membership_sucursales_set
from apps.clinica.sucursal_scope import allowed_sucursales
from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from apps.tenancy.models import TenantMembership
from tests.factories import (
    MembershipSucursalFactory,
    SucursalFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)


def _detail_url(membership_id: Any) -> str:
    return f"/api/v1/clinica/membresias/{membership_id}/sucursales/"


@contextmanager
def _tenant_ctx(tenant: Any) -> Generator[None, None, None]:
    """Activa el thread-local de tenant para llamar services/selectors directo."""
    set_current_tenant(tenant)
    set_tenant_context_active(True)
    try:
        yield
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)


@contextmanager
def _api_tenant_ctx(tenant: Any) -> Generator[None, None, None]:
    """Inyecta tenant en el middleware y TenantManager para tests HTTP."""
    with (
        patch("apps.clinica.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
    ):
        yield


def _member(tenant: Any, role: str) -> tuple[Any, Any]:
    """Crea un usuario con membresía real en el tenant. Devuelve (user, membership)."""
    user = UserFactory()
    membership = TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    return user, membership


def _auth_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ---------------------------------------------------------------------------
# Selector: membership_sucursales_list
# ---------------------------------------------------------------------------


class TestMembershipSucursalesList:
    def test_lista_vacia_sin_asignaciones(self, db: Any) -> None:
        tenant = TenantFactory()
        _, membership = _member(tenant, TenantMembership.Role.ADMIN)

        with _tenant_ctx(tenant):
            qs = membership_sucursales_list(membership=membership)

        assert qs.count() == 0

    def test_lista_las_sucursales_asignadas_ordenadas_por_nombre(self, db: Any) -> None:
        tenant = TenantFactory()
        _, membership = _member(tenant, TenantMembership.Role.ADMIN)
        norte = SucursalFactory(tenant=tenant, name="Norte")
        centro = SucursalFactory(tenant=tenant, name="Centro")
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=norte)
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)

        with _tenant_ctx(tenant):
            names = [s.name for s in membership_sucursales_list(membership=membership)]

        assert names == ["Centro", "Norte"]

    def test_no_incluye_asignaciones_de_otra_membresia(self, db: Any) -> None:
        tenant = TenantFactory()
        _, membership_a = _member(tenant, TenantMembership.Role.ADMIN)
        _, membership_b = _member(tenant, TenantMembership.Role.ADMIN)
        centro = SucursalFactory(tenant=tenant, name="Centro")
        MembershipSucursalFactory(tenant=tenant, membership=membership_b, sucursal=centro)

        with _tenant_ctx(tenant):
            qs = membership_sucursales_list(membership=membership_a)

        assert qs.count() == 0


# ---------------------------------------------------------------------------
# Service: membership_sucursales_set
# ---------------------------------------------------------------------------


class TestMembershipSucursalesSet:
    def test_owner_asigna_una_sede_convierte_en_admin_de_sucursal(self, db: Any) -> None:
        """Camino feliz: el owner asigna SOLO Centro a un admin → ese admin
        queda acotado a Centro (allowed_sucursales cambia en consecuencia)."""
        tenant = TenantFactory()
        owner, _ = _member(tenant, TenantMembership.Role.OWNER)
        target_user, target_membership = _member(tenant, TenantMembership.Role.ADMIN)
        centro = SucursalFactory(tenant=tenant, name="Centro", is_active=True)
        SucursalFactory(tenant=tenant, name="Norte", is_active=True)

        with _tenant_ctx(tenant):
            membership_sucursales_set(
                tenant=tenant, actor=owner, membership=target_membership, sucursal_ids=[centro.id]
            )
            allowed = list(allowed_sucursales(user=target_user, tenant=tenant))

        assert allowed == [centro]

    def test_owner_asigna_todas_las_sedes_convierte_en_admin_de_negocio(self, db: Any) -> None:
        tenant = TenantFactory()
        owner, _ = _member(tenant, TenantMembership.Role.OWNER)
        target_user, target_membership = _member(tenant, TenantMembership.Role.ADMIN)
        centro = SucursalFactory(tenant=tenant, name="Centro", is_active=True)
        norte = SucursalFactory(tenant=tenant, name="Norte", is_active=True)

        with _tenant_ctx(tenant):
            membership_sucursales_set(
                tenant=tenant,
                actor=owner,
                membership=target_membership,
                sucursal_ids=[centro.id, norte.id],
            )
            allowed = set(allowed_sucursales(user=target_user, tenant=tenant))

        assert allowed == {centro, norte}

    def test_reemplaza_el_conjunto_completo_no_lo_amplia(self, db: Any) -> None:
        tenant = TenantFactory()
        owner, _ = _member(tenant, TenantMembership.Role.OWNER)
        _, target_membership = _member(tenant, TenantMembership.Role.ADMIN)
        centro = SucursalFactory(tenant=tenant, name="Centro", is_active=True)
        norte = SucursalFactory(tenant=tenant, name="Norte", is_active=True)
        MembershipSucursalFactory(tenant=tenant, membership=target_membership, sucursal=norte)

        with _tenant_ctx(tenant):
            membership_sucursales_set(
                tenant=tenant, actor=owner, membership=target_membership, sucursal_ids=[centro.id]
            )
            ids = set(
                MembershipSucursal.all_objects.filter(membership=target_membership).values_list(
                    "sucursal_id", flat=True
                )
            )

        assert ids == {centro.id}

    def test_admin_de_centro_no_puede_otorgar_norte_a_nadie(self, db: Any) -> None:
        tenant = TenantFactory()
        admin_user, admin_membership = _member(tenant, TenantMembership.Role.ADMIN)
        centro = SucursalFactory(tenant=tenant, name="Centro", is_active=True)
        norte = SucursalFactory(tenant=tenant, name="Norte", is_active=True)
        MembershipSucursalFactory(tenant=tenant, membership=admin_membership, sucursal=centro)

        _, target_membership = _member(tenant, TenantMembership.Role.RECEPTION)

        with _tenant_ctx(tenant), pytest.raises(DjangoValidationError):
            membership_sucursales_set(
                tenant=tenant,
                actor=admin_user,
                membership=target_membership,
                sucursal_ids=[norte.id],
            )

    def test_admin_de_centro_no_puede_quitar_norte_a_otro_usuario(self, db: Any) -> None:
        tenant = TenantFactory()
        admin_user, admin_membership = _member(tenant, TenantMembership.Role.ADMIN)
        centro = SucursalFactory(tenant=tenant, name="Centro", is_active=True)
        norte = SucursalFactory(tenant=tenant, name="Norte", is_active=True)
        MembershipSucursalFactory(tenant=tenant, membership=admin_membership, sucursal=centro)

        _, target_membership = _member(tenant, TenantMembership.Role.RECEPTION)
        # El owner ya le había dado Norte al target; el admin de Centro no puede quitárselo.
        MembershipSucursalFactory(tenant=tenant, membership=target_membership, sucursal=norte)

        with _tenant_ctx(tenant), pytest.raises(DjangoValidationError):
            membership_sucursales_set(
                tenant=tenant, actor=admin_user, membership=target_membership, sucursal_ids=[]
            )

    def test_admin_de_centro_si_puede_gestionar_centro(self, db: Any) -> None:
        tenant = TenantFactory()
        admin_user, admin_membership = _member(tenant, TenantMembership.Role.ADMIN)
        centro = SucursalFactory(tenant=tenant, name="Centro", is_active=True)
        MembershipSucursalFactory(tenant=tenant, membership=admin_membership, sucursal=centro)

        target_user, target_membership = _member(tenant, TenantMembership.Role.RECEPTION)

        with _tenant_ctx(tenant):
            membership_sucursales_set(
                tenant=tenant,
                actor=admin_user,
                membership=target_membership,
                sucursal_ids=[centro.id],
            )
            allowed = list(allowed_sucursales(user=target_user, tenant=tenant))

        assert allowed == [centro]

    def test_membership_de_otro_tenant_rechaza(self, db: Any) -> None:
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        owner, _ = _member(tenant_a, TenantMembership.Role.OWNER)
        _, membership_b = _member(tenant_b, TenantMembership.Role.ADMIN)

        with _tenant_ctx(tenant_a), pytest.raises(DjangoValidationError):
            membership_sucursales_set(
                tenant=tenant_a, actor=owner, membership=membership_b, sucursal_ids=[]
            )

    def test_sucursal_de_otro_tenant_rechaza(self, db: Any) -> None:
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        owner, _ = _member(tenant_a, TenantMembership.Role.OWNER)
        _, target_membership = _member(tenant_a, TenantMembership.Role.ADMIN)
        ajena = SucursalFactory(tenant=tenant_b, name="Ajena", is_active=True)

        with _tenant_ctx(tenant_a), pytest.raises(DjangoValidationError):
            membership_sucursales_set(
                tenant=tenant_a,
                actor=owner,
                membership=target_membership,
                sucursal_ids=[ajena.id],
            )

    def test_sucursal_inactiva_rechaza(self, db: Any) -> None:
        tenant = TenantFactory()
        owner, _ = _member(tenant, TenantMembership.Role.OWNER)
        _, target_membership = _member(tenant, TenantMembership.Role.ADMIN)
        inactiva = SucursalFactory(tenant=tenant, name="Cerrada", is_active=False)

        with _tenant_ctx(tenant), pytest.raises(DjangoValidationError):
            membership_sucursales_set(
                tenant=tenant,
                actor=owner,
                membership=target_membership,
                sucursal_ids=[inactiva.id],
            )

    def test_anti_lockout_owner_no_puede_quedar_sin_sucursales(self, db: Any) -> None:
        tenant = TenantFactory()
        owner, owner_membership = _member(tenant, TenantMembership.Role.OWNER)
        SucursalFactory(tenant=tenant, name="Centro", is_active=True)

        with _tenant_ctx(tenant), pytest.raises(DjangoValidationError):
            membership_sucursales_set(
                tenant=tenant, actor=owner, membership=owner_membership, sucursal_ids=[]
            )

    def test_anti_lockout_admin_no_puede_quitarse_a_si_mismo_todas(self, db: Any) -> None:
        tenant = TenantFactory()
        admin_user, admin_membership = _member(tenant, TenantMembership.Role.ADMIN)
        centro = SucursalFactory(tenant=tenant, name="Centro", is_active=True)
        MembershipSucursalFactory(tenant=tenant, membership=admin_membership, sucursal=centro)

        with _tenant_ctx(tenant), pytest.raises(DjangoValidationError):
            membership_sucursales_set(
                tenant=tenant,
                actor=admin_user,
                membership=admin_membership,
                sucursal_ids=[],
            )

    def test_admin_puede_dejarse_al_menos_una_sede(self, db: Any) -> None:
        """El anti-lockout solo bloquea vaciar del todo; reducir a una sede sigue permitido."""
        tenant = TenantFactory()
        admin_user, admin_membership = _member(tenant, TenantMembership.Role.ADMIN)
        centro = SucursalFactory(tenant=tenant, name="Centro", is_active=True)
        norte = SucursalFactory(tenant=tenant, name="Norte", is_active=True)
        MembershipSucursalFactory(tenant=tenant, membership=admin_membership, sucursal=centro)
        MembershipSucursalFactory(tenant=tenant, membership=admin_membership, sucursal=norte)

        with _tenant_ctx(tenant):
            membership_sucursales_set(
                tenant=tenant,
                actor=admin_user,
                membership=admin_membership,
                sucursal_ids=[centro.id],
            )
            allowed = list(allowed_sucursales(user=admin_user, tenant=tenant))

        assert allowed == [centro]


# ---------------------------------------------------------------------------
# Endpoints HTTP
# ---------------------------------------------------------------------------


class TestMembershipSucursalesApi:
    def test_401_sin_autenticacion(self, db: Any) -> None:
        tenant = TenantFactory()
        _, target_membership = _member(tenant, TenantMembership.Role.ADMIN)
        client = APIClient()

        with _api_tenant_ctx(tenant):
            resp = client.get(_detail_url(target_membership.id))

        assert resp.status_code == 401

    def test_get_owner_ve_sucursales_asignadas(self, db: Any) -> None:
        tenant = TenantFactory()
        owner, _ = _member(tenant, TenantMembership.Role.OWNER)
        _, target_membership = _member(tenant, TenantMembership.Role.ADMIN)
        centro = SucursalFactory(tenant=tenant, name="Centro", is_active=True)
        MembershipSucursalFactory(tenant=tenant, membership=target_membership, sucursal=centro)
        client = _auth_client(owner)

        with _api_tenant_ctx(tenant):
            resp = client.get(_detail_url(target_membership.id))

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["membership_id"] == str(target_membership.id)
        assert body["sucursales"] == [{"id": str(centro.id), "name": "Centro", "is_default": False}]

    def test_put_200_owner_asigna_sede(self, db: Any) -> None:
        tenant = TenantFactory()
        owner, _ = _member(tenant, TenantMembership.Role.OWNER)
        _, target_membership = _member(tenant, TenantMembership.Role.ADMIN)
        centro = SucursalFactory(tenant=tenant, name="Centro", is_active=True)
        client = _auth_client(owner)

        with _api_tenant_ctx(tenant):
            resp = client.put(
                _detail_url(target_membership.id),
                data={"sucursal_ids": [str(centro.id)]},
                format="json",
            )

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert [s["id"] for s in body["sucursales"]] == [str(centro.id)]

    def test_put_403_reception_no_puede_gestionar(self, db: Any) -> None:
        tenant = TenantFactory()
        _, target_membership = _member(tenant, TenantMembership.Role.ADMIN)
        reception_user, _ = _member(tenant, TenantMembership.Role.RECEPTION)
        client = _auth_client(reception_user)

        with _api_tenant_ctx(tenant):
            resp = client.put(
                _detail_url(target_membership.id), data={"sucursal_ids": []}, format="json"
            )

        assert resp.status_code == 403

    def test_put_403_doctor_no_puede_gestionar(self, db: Any) -> None:
        tenant = TenantFactory()
        _, target_membership = _member(tenant, TenantMembership.Role.ADMIN)
        doctor_user, _ = _member(tenant, TenantMembership.Role.DOCTOR)
        client = _auth_client(doctor_user)

        with _api_tenant_ctx(tenant):
            resp = client.put(
                _detail_url(target_membership.id), data={"sucursal_ids": []}, format="json"
            )

        assert resp.status_code == 403

    def test_put_404_membership_de_otro_tenant(self, db: Any) -> None:
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        owner, _ = _member(tenant_a, TenantMembership.Role.OWNER)
        _, membership_b = _member(tenant_b, TenantMembership.Role.ADMIN)
        client = _auth_client(owner)

        with _api_tenant_ctx(tenant_a):
            resp = client.put(
                _detail_url(membership_b.id), data={"sucursal_ids": []}, format="json"
            )

        assert resp.status_code == 404

    def test_put_400_sucursal_de_otro_tenant(self, db: Any) -> None:
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        owner, _ = _member(tenant_a, TenantMembership.Role.OWNER)
        _, target_membership = _member(tenant_a, TenantMembership.Role.ADMIN)
        ajena = SucursalFactory(tenant=tenant_b, name="Ajena", is_active=True)
        client = _auth_client(owner)

        with _api_tenant_ctx(tenant_a):
            resp = client.put(
                _detail_url(target_membership.id),
                data={"sucursal_ids": [str(ajena.id)]},
                format="json",
            )

        assert resp.status_code == 400

    def test_put_400_admin_intenta_escalar_a_sede_ajena(self, db: Any) -> None:
        tenant = TenantFactory()
        admin_user, admin_membership = _member(tenant, TenantMembership.Role.ADMIN)
        centro = SucursalFactory(tenant=tenant, name="Centro", is_active=True)
        norte = SucursalFactory(tenant=tenant, name="Norte", is_active=True)
        MembershipSucursalFactory(tenant=tenant, membership=admin_membership, sucursal=centro)

        _, target_membership = _member(tenant, TenantMembership.Role.RECEPTION)
        client = _auth_client(admin_user)

        with _api_tenant_ctx(tenant):
            resp = client.put(
                _detail_url(target_membership.id),
                data={"sucursal_ids": [str(norte.id)]},
                format="json",
            )

        assert resp.status_code == 400

    def test_put_400_campo_no_declarado(self, db: Any) -> None:
        tenant = TenantFactory()
        owner, _ = _member(tenant, TenantMembership.Role.OWNER)
        _, target_membership = _member(tenant, TenantMembership.Role.ADMIN)
        client = _auth_client(owner)

        with _api_tenant_ctx(tenant):
            resp = client.put(
                _detail_url(target_membership.id),
                data={"sucursal_ids": [], "campo_invalido": 1},
                format="json",
            )

        assert resp.status_code == 400
