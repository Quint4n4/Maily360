"""
Tests del catálogo del equipo/departamentos de la clínica (Plan Integral — Fase 4).

Cubre:
1. Services: create/update/activate/deactivate/delete (soft-delete vía
   deleted_at), validación de campos inmutables (is_active) en update.
2. Selectors: filtro only_active, orden por `order`, aislamiento multi-tenant.
3. Endpoints HTTP: permisos por rol (GET owner/admin/doctor; escritura
   owner/admin), 404 IDOR cross-tenant, paginación.

RLS de clinica_team_members: cubierto por el test guardián
apps/core/tests/test_rls_coverage.py.

Patrón: AAA. Mismo helper _tenant_context que test_apis.py (parchea
get_current_tenant en apps.clinica.views, el único módulo de vistas de esta app).
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.test import APIClient

from apps.clinica.models import ClinicTeamMember
from apps.clinica.selectors import clinic_team_get, clinic_team_list
from apps.clinica.services import (
    clinic_team_member_activate,
    clinic_team_member_create,
    clinic_team_member_deactivate,
    clinic_team_member_delete,
    clinic_team_member_update,
)
from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from apps.tenancy.models import TenantMembership
from tests.factories import (
    ClinicTeamMemberFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

_LIST_URL = "/api/v1/clinica/equipo/"


def _detail_url(pk: Any) -> str:
    return f"/api/v1/clinica/equipo/{pk}/"


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


def _member(tenant: Any, role: str) -> Any:
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    return user


def _auth_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------


class TestClinicTeamServices:
    def test_create_ok(self, db: Any) -> None:
        tenant = TenantFactory()
        user = UserFactory()

        with _tenant_ctx(tenant):
            member = clinic_team_member_create(
                tenant=tenant, user=user, departamento="Nutrición", nombre="Dra. López"
            )

        assert member.departamento == "Nutrición"
        assert member.nombre == "Dra. López"
        assert member.is_active is True

    def test_update_rechaza_is_active(self, db: Any) -> None:
        tenant = TenantFactory()
        member = ClinicTeamMemberFactory(tenant=tenant)

        with _tenant_ctx(tenant), pytest.raises(DjangoValidationError):
            clinic_team_member_update(member=member, user=UserFactory(), is_active=False)

    def test_update_cambia_campos_permitidos(self, db: Any) -> None:
        tenant = TenantFactory()
        member = ClinicTeamMemberFactory(tenant=tenant, nombre="Original")

        with _tenant_ctx(tenant):
            updated = clinic_team_member_update(member=member, user=UserFactory(), nombre="Nuevo")

        assert updated.nombre == "Nuevo"

    def test_activate_deactivate_toggle(self, db: Any) -> None:
        tenant = TenantFactory()
        member = ClinicTeamMemberFactory(tenant=tenant, is_active=True)

        with _tenant_ctx(tenant):
            clinic_team_member_deactivate(member=member, user=UserFactory())
            member.refresh_from_db()
            assert member.is_active is False

            clinic_team_member_activate(member=member, user=UserFactory())
            member.refresh_from_db()
            assert member.is_active is True

    def test_delete_soft_deletes(self, db: Any) -> None:
        tenant = TenantFactory()
        member = ClinicTeamMemberFactory(tenant=tenant)

        with _tenant_ctx(tenant):
            clinic_team_member_delete(member=member, user=UserFactory())
            assert not clinic_team_list(only_active=False).filter(id=member.id).exists()
            assert ClinicTeamMember.all_objects.get(id=member.id).deleted_at is not None


# ---------------------------------------------------------------------------
# Selectors
# ---------------------------------------------------------------------------


class TestClinicTeamSelectors:
    def test_list_ordena_por_order(self, db: Any) -> None:
        tenant = TenantFactory()
        ClinicTeamMemberFactory(tenant=tenant, order=2, departamento="B")
        ClinicTeamMemberFactory(tenant=tenant, order=1, departamento="A")

        with _tenant_ctx(tenant):
            qs = list(clinic_team_list())

        assert [m.departamento for m in qs] == ["A", "B"]

    def test_list_only_active_excluye_inactivos(self, db: Any) -> None:
        tenant = TenantFactory()
        ClinicTeamMemberFactory(tenant=tenant, is_active=True)
        ClinicTeamMemberFactory(tenant=tenant, is_active=False)

        with _tenant_ctx(tenant):
            assert clinic_team_list(only_active=True).count() == 1
            assert clinic_team_list(only_active=False).count() == 2

    def test_get_aislamiento_multi_tenant(self, db: Any) -> None:
        tenant1 = TenantFactory()
        tenant2 = TenantFactory()
        other = ClinicTeamMemberFactory(tenant=tenant2)

        with _tenant_ctx(tenant1), pytest.raises(ClinicTeamMember.DoesNotExist):
            clinic_team_get(member_id=other.id)


# ---------------------------------------------------------------------------
# Endpoints HTTP
# ---------------------------------------------------------------------------


class TestClinicTeamApi:
    def test_401_sin_autenticacion(self, db: Any) -> None:
        tenant = TenantFactory()
        client = APIClient()

        with _api_tenant_ctx(tenant):
            resp = client.get(_LIST_URL)

        assert resp.status_code == 401

    @pytest.mark.parametrize(
        "role",
        [TenantMembership.Role.OWNER, TenantMembership.Role.ADMIN, TenantMembership.Role.DOCTOR],
    )
    def test_get_200_roles_permitidos(self, db: Any, role: str) -> None:
        tenant = TenantFactory()
        ClinicTeamMemberFactory(tenant=tenant)
        client = _auth_client(_member(tenant, role))

        with _api_tenant_ctx(tenant):
            resp = client.get(_LIST_URL)

        assert resp.status_code == 200, (role, resp.content)
        assert resp.json()["count"] == 1

    @pytest.mark.parametrize(
        "role",
        [
            TenantMembership.Role.RECEPTION,
            TenantMembership.Role.FINANCE,
            TenantMembership.Role.NURSE,
            TenantMembership.Role.READONLY,
        ],
    )
    def test_get_403_roles_no_permitidos(self, db: Any, role: str) -> None:
        tenant = TenantFactory()
        client = _auth_client(_member(tenant, role))

        with _api_tenant_ctx(tenant):
            resp = client.get(_LIST_URL)

        assert resp.status_code == 403

    def test_post_201_owner(self, db: Any) -> None:
        tenant = TenantFactory()
        client = _auth_client(_member(tenant, TenantMembership.Role.OWNER))

        with _api_tenant_ctx(tenant):
            resp = client.post(
                _LIST_URL,
                data={"departamento": "Enfermería", "nombre": "Enf. Pérez", "order": 1},
                format="json",
            )

        assert resp.status_code == 201, resp.content
        assert ClinicTeamMember.all_objects.filter(id=resp.json()["id"]).exists()

    def test_post_403_doctor_no_puede_crear(self, db: Any) -> None:
        tenant = TenantFactory()
        client = _auth_client(_member(tenant, TenantMembership.Role.DOCTOR))

        with _api_tenant_ctx(tenant):
            resp = client.post(_LIST_URL, data={"departamento": "X", "nombre": "Y"}, format="json")

        assert resp.status_code == 403

    def test_post_400_campo_no_declarado(self, db: Any) -> None:
        tenant = TenantFactory()
        client = _auth_client(_member(tenant, TenantMembership.Role.OWNER))

        with _api_tenant_ctx(tenant):
            resp = client.post(
                _LIST_URL,
                data={"departamento": "X", "nombre": "Y", "campo_invalido": 1},
                format="json",
            )

        assert resp.status_code == 400

    def test_patch_200_admin(self, db: Any) -> None:
        tenant = TenantFactory()
        member = ClinicTeamMemberFactory(tenant=tenant, nombre="Original")
        client = _auth_client(_member(tenant, TenantMembership.Role.ADMIN))

        with _api_tenant_ctx(tenant):
            resp = client.patch(_detail_url(member.id), data={"nombre": "Editado"}, format="json")

        assert resp.status_code == 200, resp.content
        assert resp.json()["nombre"] == "Editado"

    def test_patch_toggle_is_active(self, db: Any) -> None:
        tenant = TenantFactory()
        member = ClinicTeamMemberFactory(tenant=tenant, is_active=True)
        client = _auth_client(_member(tenant, TenantMembership.Role.OWNER))

        with _api_tenant_ctx(tenant):
            resp = client.patch(_detail_url(member.id), data={"is_active": False}, format="json")

        assert resp.status_code == 200, resp.content
        assert resp.json()["is_active"] is False

    def test_delete_204_y_no_reaparece_en_listado(self, db: Any) -> None:
        tenant = TenantFactory()
        member = ClinicTeamMemberFactory(tenant=tenant)
        client = _auth_client(_member(tenant, TenantMembership.Role.OWNER))

        with _api_tenant_ctx(tenant):
            resp = client.delete(_detail_url(member.id))
            assert resp.status_code == 204

            list_resp = client.get(_LIST_URL)

        assert list_resp.json()["count"] == 0

    def test_delete_403_reception(self, db: Any) -> None:
        tenant = TenantFactory()
        member = ClinicTeamMemberFactory(tenant=tenant)
        client = _auth_client(_member(tenant, TenantMembership.Role.RECEPTION))

        with _api_tenant_ctx(tenant):
            resp = client.delete(_detail_url(member.id))

        assert resp.status_code == 403

    def test_404_idor_get_otro_tenant(self, db: Any) -> None:
        tenant1 = TenantFactory()
        tenant2 = TenantFactory()
        other = ClinicTeamMemberFactory(tenant=tenant2)
        client = _auth_client(_member(tenant1, TenantMembership.Role.OWNER))

        with _api_tenant_ctx(tenant1):
            resp = client.get(_detail_url(other.id))

        assert resp.status_code == 404

    def test_404_idor_patch_otro_tenant(self, db: Any) -> None:
        tenant1 = TenantFactory()
        tenant2 = TenantFactory()
        other = ClinicTeamMemberFactory(tenant=tenant2)
        client = _auth_client(_member(tenant1, TenantMembership.Role.OWNER))

        with _api_tenant_ctx(tenant1):
            resp = client.patch(_detail_url(other.id), data={"nombre": "hack"}, format="json")

        assert resp.status_code == 404

    def test_404_idor_delete_otro_tenant(self, db: Any) -> None:
        tenant1 = TenantFactory()
        tenant2 = TenantFactory()
        other = ClinicTeamMemberFactory(tenant=tenant2)
        client = _auth_client(_member(tenant1, TenantMembership.Role.OWNER))

        with _api_tenant_ctx(tenant1):
            resp = client.delete(_detail_url(other.id))

        assert resp.status_code == 404
        assert ClinicTeamMember.all_objects.get(id=other.id).deleted_at is None
