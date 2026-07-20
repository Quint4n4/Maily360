"""
Tests de Sucursal / MembershipSucursal (multi-sede — Fase 1).

Cubre:
1. Services: create/update/activate/deactivate/set_default, validación de
   campos inmutables (is_active/is_default), unicidad de nombre, unicidad de
   is_default por tenant, guardas de negocio (no desactivar la default, no
   marcar default una sucursal inactiva).
2. Selectors: sucursal_get (404 IDOR cross-tenant), sucursal_list (only_active).
3. apps.clinica.sucursal_scope: allowed_sucursales (owner SIEMPRE ve todas;
   cualquier otro rol, admin incluido, solo lo asignado vía
   MembershipSucursal — así se modela el "admin de sucursal"; sin ninguna
   asignación, fallback anti-lockout a la sucursal default) y
   resolve_active_sucursal (header X-Sucursal-Id: ausente → None, inválido o
   no permitido → 403, permitido → Sucursal).
4. Endpoints HTTP: permisos por rol, CRUD, 404 IDOR cross-tenant, paginación.

RLS de clinica_sucursales y tenancy_membership_sucursales: cubierto
genéricamente por el test guardián apps/core/tests/test_rls_coverage.py
(recorre TODOS los modelos TenantAwareModel, incluidos estos dos).

Patrón: AAA. Mismo helper _api_tenant_ctx que test_clinic_team.py (parchea
get_current_tenant en apps.clinica.views).
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient, APIRequestFactory

from apps.clinica.models import MembershipSucursal, Sucursal
from apps.clinica.selectors import sucursal_get, sucursal_list
from apps.clinica.services import (
    sucursal_activate,
    sucursal_create,
    sucursal_deactivate,
    sucursal_set_default,
    sucursal_update,
)
from apps.clinica.sucursal_scope import (
    actor_sucursal_ids,
    allowed_sucursales,
    resolve_active_sucursal,
    sucursal_scope_ids,
)
from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from apps.tenancy.models import TenantMembership
from tests.factories import (
    MembershipSucursalFactory,
    SucursalFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

_LIST_URL = "/api/v1/clinica/sucursales/"


def _detail_url(pk: Any) -> str:
    return f"/api/v1/clinica/sucursales/{pk}/"


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


class TestSucursalServices:
    def test_create_ok(self, db: Any) -> None:
        tenant = TenantFactory()
        user = UserFactory()

        with _tenant_ctx(tenant):
            sucursal = sucursal_create(
                tenant=tenant, user=user, name="Sucursal Centro", address="Calle 1", phone="555"
            )

        assert sucursal.name == "Sucursal Centro"
        assert sucursal.is_active is True
        assert sucursal.is_default is False

    def test_create_duplicate_name_rechaza(self, db: Any) -> None:
        tenant = TenantFactory()
        SucursalFactory(tenant=tenant, name="Centro")

        with _tenant_ctx(tenant), pytest.raises(DjangoValidationError):
            sucursal_create(tenant=tenant, user=UserFactory(), name="Centro")

    def test_create_con_is_default_true_la_marca_default(self, db: Any) -> None:
        tenant = TenantFactory()

        with _tenant_ctx(tenant):
            sucursal = sucursal_create(
                tenant=tenant, user=UserFactory(), name="Centro", is_default=True
            )

        assert sucursal.is_default is True

    def test_update_rechaza_is_active(self, db: Any) -> None:
        tenant = TenantFactory()
        sucursal = SucursalFactory(tenant=tenant)

        with _tenant_ctx(tenant), pytest.raises(DjangoValidationError):
            sucursal_update(sucursal=sucursal, user=UserFactory(), is_active=False)

    def test_update_rechaza_is_default(self, db: Any) -> None:
        tenant = TenantFactory()
        sucursal = SucursalFactory(tenant=tenant)

        with _tenant_ctx(tenant), pytest.raises(DjangoValidationError):
            sucursal_update(sucursal=sucursal, user=UserFactory(), is_default=True)

    def test_update_cambia_campos_permitidos(self, db: Any) -> None:
        tenant = TenantFactory()
        sucursal = SucursalFactory(tenant=tenant, name="Original")

        with _tenant_ctx(tenant):
            updated = sucursal_update(sucursal=sucursal, user=UserFactory(), name="Nuevo")

        assert updated.name == "Nuevo"

    def test_update_nombre_duplicado_rechaza(self, db: Any) -> None:
        tenant = TenantFactory()
        SucursalFactory(tenant=tenant, name="Norte")
        sucursal = SucursalFactory(tenant=tenant, name="Centro")

        with _tenant_ctx(tenant), pytest.raises(DjangoValidationError):
            sucursal_update(sucursal=sucursal, user=UserFactory(), name="Norte")

    def test_activate_deactivate_toggle(self, db: Any) -> None:
        tenant = TenantFactory()
        sucursal = SucursalFactory(tenant=tenant, is_active=True, is_default=False)

        with _tenant_ctx(tenant):
            sucursal_deactivate(sucursal=sucursal, user=UserFactory())
            sucursal.refresh_from_db()
            assert sucursal.is_active is False

            sucursal_activate(sucursal=sucursal, user=UserFactory())
            sucursal.refresh_from_db()
            assert sucursal.is_active is True

    def test_deactivate_default_rechaza(self, db: Any) -> None:
        tenant = TenantFactory()
        sucursal = SucursalFactory(tenant=tenant, is_active=True, is_default=True)

        with _tenant_ctx(tenant), pytest.raises(DjangoValidationError):
            sucursal_deactivate(sucursal=sucursal, user=UserFactory())

    def test_set_default_desmarca_la_anterior(self, db: Any) -> None:
        tenant = TenantFactory()
        vieja = SucursalFactory(tenant=tenant, is_default=True)
        nueva = SucursalFactory(tenant=tenant, is_default=False)

        with _tenant_ctx(tenant):
            sucursal_set_default(sucursal=nueva, user=UserFactory())

        vieja.refresh_from_db()
        nueva.refresh_from_db()
        assert nueva.is_default is True
        assert vieja.is_default is False
        # Solo una fila con is_default=True por tenant (constraint + lógica).
        assert Sucursal.all_objects.filter(tenant=tenant, is_default=True).count() == 1

    def test_set_default_sucursal_inactiva_rechaza(self, db: Any) -> None:
        tenant = TenantFactory()
        sucursal = SucursalFactory(tenant=tenant, is_active=False, is_default=False)

        with _tenant_ctx(tenant), pytest.raises(DjangoValidationError):
            sucursal_set_default(sucursal=sucursal, user=UserFactory())


# ---------------------------------------------------------------------------
# Selectors
# ---------------------------------------------------------------------------


class TestSucursalSelectors:
    def test_get_aislamiento_multi_tenant(self, db: Any) -> None:
        tenant1 = TenantFactory()
        tenant2 = TenantFactory()
        other = SucursalFactory(tenant=tenant2)

        with _tenant_ctx(tenant1), pytest.raises(Sucursal.DoesNotExist):
            sucursal_get(sucursal_id=other.id)

    def test_list_only_active_excluye_inactivas(self, db: Any) -> None:
        tenant = TenantFactory()
        SucursalFactory(tenant=tenant, is_active=True)
        SucursalFactory(tenant=tenant, is_active=False)

        with _tenant_ctx(tenant):
            assert sucursal_list(only_active=True).count() == 1
            assert sucursal_list(only_active=False).count() == 2

    def test_list_ordena_por_nombre(self, db: Any) -> None:
        tenant = TenantFactory()
        SucursalFactory(tenant=tenant, name="Zeta")
        SucursalFactory(tenant=tenant, name="Alfa")

        with _tenant_ctx(tenant):
            names = [s.name for s in sucursal_list()]

        assert names == ["Alfa", "Zeta"]


# ---------------------------------------------------------------------------
# sucursal_scope: allowed_sucursales
# ---------------------------------------------------------------------------


class TestAllowedSucursales:
    def test_owner_ve_todas_las_activas(self, db: Any) -> None:
        tenant = TenantFactory()
        owner = _member(tenant, TenantMembership.Role.OWNER)
        SucursalFactory(tenant=tenant, is_active=True)
        SucursalFactory(tenant=tenant, is_active=True)
        SucursalFactory(tenant=tenant, is_active=False)

        qs = allowed_sucursales(user=owner, tenant=tenant)

        assert qs.count() == 2

    def test_admin_sin_membershipsucursal_solo_ve_la_default(self, db: Any) -> None:
        """Admin de sucursal (Objetivo §12): sin asignación explícita, un
        admin YA NO ve todas las sedes — solo la default (fallback
        anti-lockout, fail-closed)."""
        tenant = TenantFactory()
        admin = _member(tenant, TenantMembership.Role.ADMIN)
        default = SucursalFactory(tenant=tenant, is_active=True, is_default=True)
        SucursalFactory(tenant=tenant, is_active=True)

        qs = allowed_sucursales(user=admin, tenant=tenant)

        assert list(qs) == [default]

    def test_admin_asignado_solo_a_una_sede_es_admin_de_sucursal(self, db: Any) -> None:
        """Un admin con UNA MembershipSucursal es un "admin de sucursal": ve
        SOLO esa sede, aunque el tenant tenga más."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_active=True)
        SucursalFactory(tenant=tenant, name="Norte", is_active=True)

        user = UserFactory()
        membership = TenantMembershipFactory(
            user=user, tenant=tenant, role=TenantMembership.Role.ADMIN, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)

        qs = allowed_sucursales(user=user, tenant=tenant)

        assert list(qs) == [centro]

    def test_admin_asignado_a_todas_las_sedes_es_admin_de_negocio(self, db: Any) -> None:
        """Un admin con MembershipSucursal explícita para CADA sede activa
        del tenant equivale a un "admin de negocio": ve todo, igual que el
        dueño, pero por asignación explícita (no por rol)."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_active=True)
        norte = SucursalFactory(tenant=tenant, name="Norte", is_active=True)

        user = UserFactory()
        membership = TenantMembershipFactory(
            user=user, tenant=tenant, role=TenantMembership.Role.ADMIN, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=norte)

        qs = allowed_sucursales(user=user, tenant=tenant)

        assert set(qs) == {centro, norte}

    def test_doctor_sin_membershipsucursal_solo_ve_la_default(self, db: Any) -> None:
        """Fallback anti-lockout: cualquier rol (no solo admin) sin ninguna
        MembershipSucursal cae a la sucursal default, nunca a todas."""
        tenant = TenantFactory()
        doctor_user = _member(tenant, TenantMembership.Role.DOCTOR)
        default = SucursalFactory(tenant=tenant, is_active=True, is_default=True)
        SucursalFactory(tenant=tenant, is_active=True)

        qs = allowed_sucursales(user=doctor_user, tenant=tenant)

        assert list(qs) == [default]

    def test_doctor_sin_membershipsucursal_ni_default_no_ve_ninguna(self, db: Any) -> None:
        """Sin MembershipSucursal y sin sucursal default configurada: el
        fallback no tiene a dónde caer, resultado vacío (fail-closed)."""
        tenant = TenantFactory()
        doctor_user = _member(tenant, TenantMembership.Role.DOCTOR)
        SucursalFactory(tenant=tenant, is_active=True, is_default=False)

        qs = allowed_sucursales(user=doctor_user, tenant=tenant)

        assert qs.count() == 0

    def test_reception_solo_ve_su_sucursal_asignada(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_active=True)
        SucursalFactory(tenant=tenant, name="Norte", is_active=True)

        user = UserFactory()
        membership = TenantMembershipFactory(
            user=user, tenant=tenant, role=TenantMembership.Role.RECEPTION, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)

        qs = allowed_sucursales(user=user, tenant=tenant)

        assert list(qs) == [centro]

    def test_asignacion_a_sucursal_inactiva_no_se_ve(self, db: Any) -> None:
        tenant = TenantFactory()
        inactiva = SucursalFactory(tenant=tenant, is_active=False)

        user = UserFactory()
        membership = TenantMembershipFactory(
            user=user, tenant=tenant, role=TenantMembership.Role.NURSE, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=inactiva)

        qs = allowed_sucursales(user=user, tenant=tenant)

        assert qs.count() == 0

    def test_usuario_sin_membresia_en_tenant_no_ve_nada(self, db: Any) -> None:
        tenant = TenantFactory()
        otro_tenant = TenantFactory()
        SucursalFactory(tenant=tenant, is_active=True)
        # El usuario tiene membresía en OTRO tenant, no en `tenant`.
        user = _member(otro_tenant, TenantMembership.Role.OWNER)

        qs = allowed_sucursales(user=user, tenant=tenant)

        assert qs.count() == 0


# ---------------------------------------------------------------------------
# sucursal_scope: actor_sucursal_ids — autorización "dura" (Clúster B y C)
# ---------------------------------------------------------------------------


class TestActorSucursalIds:
    """`actor_sucursal_ids` es la variante de `allowed_sucursales` para
    AUTORIZACIÓN: mismo criterio de rol/membresía, pero NO excluye sedes
    desactivadas del lado del candidato (a propósito — ver docstring)."""

    def test_owner_devuelve_none_sin_importar_sedes_inactivas(self, db: Any) -> None:
        tenant = TenantFactory()
        owner = _member(tenant, TenantMembership.Role.OWNER)
        SucursalFactory(tenant=tenant, is_active=True)
        SucursalFactory(tenant=tenant, is_active=False)

        assert actor_sucursal_ids(user=owner, tenant=tenant) is None

    def test_admin_acotado_a_centro_incluye_su_id_aunque_este_inactiva(self, db: Any) -> None:
        """La propia sede del admin sigue en su alcance aunque esté
        desactivada (necesario para poder reactivarla)."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_active=False)
        user = UserFactory()
        membership = TenantMembershipFactory(
            user=user, tenant=tenant, role=TenantMembership.Role.ADMIN, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)

        assert actor_sucursal_ids(user=user, tenant=tenant) == {centro.id}

    def test_admin_acotado_a_centro_no_incluye_norte_desactivada(self, db: Any) -> None:
        """El punto central del Clúster B: desactivar una sede AJENA nunca
        debe aparecer en el alcance de un admin que no la tiene asignada."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_active=True)
        norte = SucursalFactory(tenant=tenant, name="Norte", is_active=False)
        user = UserFactory()
        membership = TenantMembershipFactory(
            user=user, tenant=tenant, role=TenantMembership.Role.ADMIN, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)

        ids = actor_sucursal_ids(user=user, tenant=tenant)

        assert ids == {centro.id}
        assert norte.id not in ids

    def test_sin_asignacion_cae_al_fallback_de_la_default(self, db: Any) -> None:
        tenant = TenantFactory()
        default = SucursalFactory(tenant=tenant, is_active=True, is_default=True)
        SucursalFactory(tenant=tenant, is_active=True, is_default=False)
        admin = _member(tenant, TenantMembership.Role.ADMIN)

        assert actor_sucursal_ids(user=admin, tenant=tenant) == {default.id}

    def test_usuario_sin_membresia_devuelve_set_vacio(self, db: Any) -> None:
        tenant = TenantFactory()
        SucursalFactory(tenant=tenant, is_active=True)
        user = UserFactory()

        assert actor_sucursal_ids(user=user, tenant=tenant) == set()


# ---------------------------------------------------------------------------
# sucursal_scope: resolve_active_sucursal
# ---------------------------------------------------------------------------


class TestResolveActiveSucursal:
    def test_sin_header_retorna_none(self, db: Any) -> None:
        tenant = TenantFactory()
        owner = _member(tenant, TenantMembership.Role.OWNER)
        factory = APIRequestFactory()
        request = factory.get("/api/v1/personal/consultorios/")
        request.user = owner

        with _tenant_ctx(tenant):
            assert resolve_active_sucursal(request) is None

    def test_header_invalido_levanta_403(self, db: Any) -> None:
        tenant = TenantFactory()
        owner = _member(tenant, TenantMembership.Role.OWNER)
        factory = APIRequestFactory()
        request = factory.get(
            "/api/v1/personal/consultorios/", headers={"X-Sucursal-Id": "no-es-un-uuid"}
        )
        request.user = owner

        with _tenant_ctx(tenant), pytest.raises(PermissionDenied):
            resolve_active_sucursal(request)

    def test_sucursal_no_permitida_levanta_403(self, db: Any) -> None:
        tenant = TenantFactory()
        ajena = SucursalFactory(tenant=tenant, is_active=True)
        # doctor sin MembershipSucursal → no tiene acceso a ninguna sede.
        doctor_user = _member(tenant, TenantMembership.Role.DOCTOR)
        factory = APIRequestFactory()
        request = factory.get(
            "/api/v1/personal/consultorios/", headers={"X-Sucursal-Id": str(ajena.id)}
        )
        request.user = doctor_user

        with _tenant_ctx(tenant), pytest.raises(PermissionDenied):
            resolve_active_sucursal(request)

    def test_sucursal_permitida_se_resuelve(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, is_active=True)
        owner = _member(tenant, TenantMembership.Role.OWNER)
        factory = APIRequestFactory()
        request = factory.get(
            "/api/v1/personal/consultorios/", headers={"X-Sucursal-Id": str(centro.id)}
        )
        request.user = owner

        with _tenant_ctx(tenant):
            resolved = resolve_active_sucursal(request)

        assert resolved is not None
        assert resolved.id == centro.id


# ---------------------------------------------------------------------------
# sucursal_scope_ids — Objetivo A (cierre del hueco de seguridad, Fase 3)
# ---------------------------------------------------------------------------


class TestSucursalScopeIds:
    """`sucursal_scope_ids` SIEMPRE acota, a diferencia de `resolve_active_sucursal`
    (donde "sin header" significaba "sin filtro" incluso para un usuario
    acotado a una sola sede)."""

    def test_header_presente_y_permitido_devuelve_una_id(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, is_active=True)
        SucursalFactory(tenant=tenant, is_active=True)  # otra sede, no pedida
        owner = _member(tenant, TenantMembership.Role.OWNER)
        factory = APIRequestFactory()
        request = factory.get("/x/", headers={"X-Sucursal-Id": str(centro.id)})
        request.user = owner

        with _tenant_ctx(tenant):
            ids = sucursal_scope_ids(request)

        assert ids == [centro.id]

    def test_header_no_permitido_levanta_403(self, db: Any) -> None:
        tenant = TenantFactory()
        ajena = SucursalFactory(tenant=tenant, is_active=True)
        doctor_user = _member(tenant, TenantMembership.Role.DOCTOR)
        factory = APIRequestFactory()
        request = factory.get("/x/", headers={"X-Sucursal-Id": str(ajena.id)})
        request.user = doctor_user

        with _tenant_ctx(tenant), pytest.raises(PermissionDenied):
            sucursal_scope_ids(request)

    def test_sin_header_usuario_acotado_devuelve_sus_sedes(self, db: Any) -> None:
        """CRÍTICO (Objetivo A): antes de este fix, omitir el header devolvía
        None (sin filtro) incluso para un usuario limitado a una sola sede."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, is_active=True)
        SucursalFactory(tenant=tenant, is_active=True)  # Norte: NO asignada al user
        user = UserFactory()
        membership = TenantMembershipFactory(
            user=user, tenant=tenant, role=TenantMembership.Role.RECEPTION, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)
        factory = APIRequestFactory()
        request = factory.get("/x/")
        request.user = user

        with _tenant_ctx(tenant):
            ids = sucursal_scope_ids(request)

        assert ids == [centro.id]

    def test_sin_header_owner_devuelve_none_consolidado(self, db: Any) -> None:
        tenant = TenantFactory()
        SucursalFactory(tenant=tenant, is_active=True)
        SucursalFactory(tenant=tenant, is_active=True)
        owner = _member(tenant, TenantMembership.Role.OWNER)
        factory = APIRequestFactory()
        request = factory.get("/x/")
        request.user = owner

        with _tenant_ctx(tenant):
            ids = sucursal_scope_ids(request)

        assert ids is None

    def test_sin_header_rol_acotado_a_todas_las_sedes_devuelve_none(self, db: Any) -> None:
        """Un rol NO owner/admin cuyas MembershipSucursal cubren TODAS las
        sedes activas también obtiene la vista consolidada (None)."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, is_active=True)
        norte = SucursalFactory(tenant=tenant, is_active=True)
        user = UserFactory()
        membership = TenantMembershipFactory(
            user=user, tenant=tenant, role=TenantMembership.Role.FINANCE, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=norte)
        factory = APIRequestFactory()
        request = factory.get("/x/")
        request.user = user

        with _tenant_ctx(tenant):
            ids = sucursal_scope_ids(request)

        assert ids is None

    def test_tenant_sin_sucursales_devuelve_none(self, db: Any) -> None:
        """Tenant que nunca adoptó multi-sede: sin filtro (compatibilidad retro)."""
        tenant = TenantFactory()
        owner = _member(tenant, TenantMembership.Role.OWNER)
        factory = APIRequestFactory()
        request = factory.get("/x/")
        request.user = owner

        with _tenant_ctx(tenant):
            ids = sucursal_scope_ids(request)

        assert ids is None

    def test_usuario_sin_membresia_devuelve_lista_vacia(self, db: Any) -> None:
        """Sin membresía activa en el tenant: alcance vacío (nunca consolidado)."""
        tenant = TenantFactory()
        SucursalFactory(tenant=tenant, is_active=True)
        user = UserFactory()  # sin TenantMembership en `tenant`
        factory = APIRequestFactory()
        request = factory.get("/x/")
        request.user = user

        with _tenant_ctx(tenant):
            ids = sucursal_scope_ids(request)

        assert ids == []

    # -----------------------------------------------------------------
    # Clúster B (hallazgos de seguridad, docs/design/sucursales-hallazgos-
    # seguridad.md): desactivar una sede AJENA no debe ampliar el alcance
    # de un admin acotado a las demás. Antes del fix, `sucursal_scope_ids`
    # comparaba `len(allowed_ids) >= total_sucursales_ACTIVAS`: al bajar el
    # denominador (Norte desactivada), un admin de Centro pasaba a "cubrir
    # todas las activas" y recibía `None` (vista consolidada) — PoC
    # verificado (0.00 con Norte activa → 7777.00 tras desactivarla).
    # -----------------------------------------------------------------

    def test_admin_acotado_no_gana_alcance_total_al_desactivar_sede_ajena(self, db: Any) -> None:
        """Regresión del PoC del Clúster B."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True, is_active=True)
        norte = SucursalFactory(tenant=tenant, name="Norte", is_default=False, is_active=True)
        user = UserFactory()
        membership = TenantMembershipFactory(
            user=user, tenant=tenant, role=TenantMembership.Role.ADMIN, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)
        factory = APIRequestFactory()
        request = factory.get("/x/")
        request.user = user

        with _tenant_ctx(tenant):
            baseline = sucursal_scope_ids(request)
            assert baseline == [centro.id]

            # Norte se desactiva (p. ej. por el owner) — NO es la sede del admin.
            sucursal_deactivate(sucursal=norte, user=UserFactory())

            post_ids = sucursal_scope_ids(request)

        assert post_ids == [centro.id], f"el alcance se amplió indebidamente: {post_ids}"

    def test_owner_con_sede_desactivada_sigue_consolidado(self, db: Any) -> None:
        tenant = TenantFactory()
        SucursalFactory(tenant=tenant, is_default=True, is_active=True)
        norte = SucursalFactory(tenant=tenant, name="Norte", is_active=True)
        owner = _member(tenant, TenantMembership.Role.OWNER)
        factory = APIRequestFactory()
        request = factory.get("/x/")
        request.user = owner

        with _tenant_ctx(tenant):
            sucursal_deactivate(sucursal=norte, user=UserFactory())
            ids = sucursal_scope_ids(request)

        assert ids is None

    def test_admin_asignado_a_todas_incluida_inactiva_sigue_consolidado(self, db: Any) -> None:
        """Un admin que SÍ tiene MembershipSucursal para TODAS las sedes
        (incluida la que se desactivó) sigue siendo "admin de negocio"."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True, is_active=True)
        norte = SucursalFactory(tenant=tenant, name="Norte", is_active=True)
        user = UserFactory()
        membership = TenantMembershipFactory(
            user=user, tenant=tenant, role=TenantMembership.Role.ADMIN, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=norte)
        factory = APIRequestFactory()
        request = factory.get("/x/")
        request.user = user

        with _tenant_ctx(tenant):
            sucursal_deactivate(sucursal=norte, user=UserFactory())
            ids = sucursal_scope_ids(request)

        assert ids is None


# ---------------------------------------------------------------------------
# Endpoints HTTP
# ---------------------------------------------------------------------------


class TestSucursalApi:
    def test_401_sin_autenticacion(self, db: Any) -> None:
        tenant = TenantFactory()
        client = APIClient()

        with _api_tenant_ctx(tenant):
            resp = client.get(_LIST_URL)

        assert resp.status_code == 401

    def test_get_owner_ve_todas(self, db: Any) -> None:
        tenant = TenantFactory()
        SucursalFactory(tenant=tenant, is_active=True)
        SucursalFactory(tenant=tenant, is_active=True)
        client = _auth_client(_member(tenant, TenantMembership.Role.OWNER))

        with _api_tenant_ctx(tenant):
            resp = client.get(_LIST_URL)

        assert resp.status_code == 200, resp.content
        assert resp.json()["count"] == 2

    def test_get_reception_solo_ve_su_sede(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_active=True)
        SucursalFactory(tenant=tenant, name="Norte", is_active=True)

        user = UserFactory()
        membership = TenantMembershipFactory(
            user=user, tenant=tenant, role=TenantMembership.Role.RECEPTION, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)
        client = _auth_client(user)

        with _api_tenant_ctx(tenant):
            resp = client.get(_LIST_URL)

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["count"] == 1
        assert body["results"][0]["id"] == str(centro.id)

    def test_post_201_owner(self, db: Any) -> None:
        tenant = TenantFactory()
        client = _auth_client(_member(tenant, TenantMembership.Role.OWNER))

        with _api_tenant_ctx(tenant):
            resp = client.post(_LIST_URL, data={"name": "Sucursal Sur"}, format="json")

        assert resp.status_code == 201, resp.content
        assert Sucursal.all_objects.filter(id=resp.json()["id"]).exists()

    def test_post_403_reception_no_puede_crear(self, db: Any) -> None:
        tenant = TenantFactory()
        client = _auth_client(_member(tenant, TenantMembership.Role.RECEPTION))

        with _api_tenant_ctx(tenant):
            resp = client.post(_LIST_URL, data={"name": "X"}, format="json")

        assert resp.status_code == 403

    def test_post_403_admin_no_puede_crear(self, db: Any) -> None:
        """Multi-sede (2026-07-16): dar de alta sucursales es SOLO del dueño.
        El admin (incluido el admin de sucursal) recibe 403."""
        tenant = TenantFactory()
        client = _auth_client(_member(tenant, TenantMembership.Role.ADMIN))

        with _api_tenant_ctx(tenant):
            resp = client.post(_LIST_URL, data={"name": "Sucursal Sur"}, format="json")

        assert resp.status_code == 403

    def test_post_400_campo_no_declarado(self, db: Any) -> None:
        tenant = TenantFactory()
        client = _auth_client(_member(tenant, TenantMembership.Role.OWNER))

        with _api_tenant_ctx(tenant):
            resp = client.post(_LIST_URL, data={"name": "X", "campo_invalido": 1}, format="json")

        assert resp.status_code == 400

    def test_patch_403_admin_ya_no_edita_sucursal(self, db: Any) -> None:
        """Multi-sede (2026-07-16): gestionar sucursales es SOLO del dueño.

        Antes, un admin con la sede asignada (MembershipSucursal) podía
        editarla (Clúster C acotó a su propia sede). Ahora ningún admin puede
        editar sucursales — es dominio exclusivo del owner: recibe 403 aunque
        tenga la sede asignada. El nombre NO cambia.
        """
        tenant = TenantFactory()
        sucursal = SucursalFactory(tenant=tenant, name="Original")
        user = UserFactory()
        membership = TenantMembershipFactory(
            user=user, tenant=tenant, role=TenantMembership.Role.ADMIN, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=sucursal)
        client = _auth_client(user)

        with _api_tenant_ctx(tenant):
            resp = client.patch(_detail_url(sucursal.id), data={"name": "Editada"}, format="json")

        assert resp.status_code == 403, resp.content
        sucursal.refresh_from_db()
        assert sucursal.name == "Original"

    def test_patch_toggle_is_active_no_default(self, db: Any) -> None:
        tenant = TenantFactory()
        sucursal = SucursalFactory(tenant=tenant, is_active=True, is_default=False)
        client = _auth_client(_member(tenant, TenantMembership.Role.OWNER))

        with _api_tenant_ctx(tenant):
            resp = client.patch(_detail_url(sucursal.id), data={"is_active": False}, format="json")

        assert resp.status_code == 200, resp.content
        assert resp.json()["is_active"] is False

    def test_patch_desactivar_default_400(self, db: Any) -> None:
        tenant = TenantFactory()
        sucursal = SucursalFactory(tenant=tenant, is_active=True, is_default=True)
        client = _auth_client(_member(tenant, TenantMembership.Role.OWNER))

        with _api_tenant_ctx(tenant):
            resp = client.patch(_detail_url(sucursal.id), data={"is_active": False}, format="json")

        assert resp.status_code == 400

    def test_patch_set_default_desmarca_la_anterior(self, db: Any) -> None:
        tenant = TenantFactory()
        vieja = SucursalFactory(tenant=tenant, is_default=True)
        nueva = SucursalFactory(tenant=tenant, is_default=False)
        client = _auth_client(_member(tenant, TenantMembership.Role.OWNER))

        with _api_tenant_ctx(tenant):
            resp = client.patch(_detail_url(nueva.id), data={"is_default": True}, format="json")

        assert resp.status_code == 200, resp.content
        assert resp.json()["is_default"] is True
        vieja.refresh_from_db()
        assert vieja.is_default is False

    def test_delete_204_no_default(self, db: Any) -> None:
        tenant = TenantFactory()
        sucursal = SucursalFactory(tenant=tenant, is_default=False)
        client = _auth_client(_member(tenant, TenantMembership.Role.OWNER))

        with _api_tenant_ctx(tenant):
            resp = client.delete(_detail_url(sucursal.id))

        assert resp.status_code == 204
        sucursal.refresh_from_db()
        assert sucursal.is_active is False

    def test_delete_403_admin_de_sucursal_no_owner(self, db: Any) -> None:
        tenant = TenantFactory()
        sucursal = SucursalFactory(tenant=tenant, is_default=False)
        client = _auth_client(_member(tenant, TenantMembership.Role.RECEPTION))

        with _api_tenant_ctx(tenant):
            resp = client.delete(_detail_url(sucursal.id))

        assert resp.status_code == 403

    def test_404_idor_get_otro_tenant(self, db: Any) -> None:
        tenant1 = TenantFactory()
        tenant2 = TenantFactory()
        other = SucursalFactory(tenant=tenant2)
        client = _auth_client(_member(tenant1, TenantMembership.Role.OWNER))

        with _api_tenant_ctx(tenant1):
            resp = client.get(_detail_url(other.id))

        assert resp.status_code == 404

    def test_404_idor_patch_otro_tenant(self, db: Any) -> None:
        tenant1 = TenantFactory()
        tenant2 = TenantFactory()
        other = SucursalFactory(tenant=tenant2)
        client = _auth_client(_member(tenant1, TenantMembership.Role.OWNER))

        with _api_tenant_ctx(tenant1):
            resp = client.patch(_detail_url(other.id), data={"name": "hack"}, format="json")

        assert resp.status_code == 404

    def test_404_idor_delete_otro_tenant(self, db: Any) -> None:
        tenant1 = TenantFactory()
        tenant2 = TenantFactory()
        other = SucursalFactory(tenant=tenant2, is_default=False)
        client = _auth_client(_member(tenant1, TenantMembership.Role.OWNER))

        with _api_tenant_ctx(tenant1):
            resp = client.delete(_detail_url(other.id))

        assert resp.status_code == 404
        other.refresh_from_db()
        assert other.is_active is True

    # -----------------------------------------------------------------
    # Clúster C-clínica (hallazgos de seguridad): SucursalDetailApi no
    # validaba la sede permitida. Un admin acotado a Centro podía
    # PATCH/DELETE (renombrar, marcar default, DESACTIVAR) la sucursal
    # Norte con solo conocer su id (el id se obtiene del estado de cuenta
    # compartido del paciente). Ahora `_get_or_404` resuelve contra
    # `actor_sucursal_ids`: 404 si la sucursal está fuera del alcance.
    # -----------------------------------------------------------------

    def _admin_de_centro(self, tenant: Any, centro: Any) -> Any:
        user = UserFactory()
        membership = TenantMembershipFactory(
            user=user, tenant=tenant, role=TenantMembership.Role.ADMIN, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)
        return user

    def test_get_404_admin_de_centro_sede_ajena(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True, is_active=True)
        norte = SucursalFactory(tenant=tenant, name="Norte", is_active=True)
        client = _auth_client(self._admin_de_centro(tenant, centro))

        with _api_tenant_ctx(tenant):
            resp = client.get(_detail_url(norte.id))

        assert resp.status_code == 404

    def test_patch_404_admin_de_centro_no_puede_renombrar_norte(self, db: Any) -> None:
        """Regresión del PoC del Clúster C (ATAQUE 2: PATCH renombrar sede ajena)."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True, is_active=True)
        norte = SucursalFactory(tenant=tenant, name="Norte", is_active=True)
        client = _auth_client(self._admin_de_centro(tenant, centro))

        with _api_tenant_ctx(tenant):
            resp = client.patch(_detail_url(norte.id), data={"name": "HACKEADA"}, format="json")

        # Multi-sede (2026-07-16): gestionar sucursales es SOLO del dueño, así
        # que el admin queda bloqueado por PERMISO (403) antes del scoping (404).
        # Cualquiera de los dos deja a Norte intacta.
        assert resp.status_code in (403, 404)
        norte.refresh_from_db()
        assert norte.name == "Norte"

    def test_patch_404_admin_de_centro_no_puede_marcar_norte_default(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True, is_active=True)
        norte = SucursalFactory(tenant=tenant, name="Norte", is_active=True, is_default=False)
        client = _auth_client(self._admin_de_centro(tenant, centro))

        with _api_tenant_ctx(tenant):
            resp = client.patch(_detail_url(norte.id), data={"is_default": True}, format="json")

        # Multi-sede (2026-07-16): owner-only → 403 (permiso) o 404 (scoping).
        assert resp.status_code in (403, 404)
        norte.refresh_from_db()
        assert norte.is_default is False

    def test_delete_404_admin_de_centro_no_puede_desactivar_norte(self, db: Any) -> None:
        """Regresión del PoC del Clúster C (ATAQUE: DELETE de la sede ajena),
        que a su vez disparaba el bug del Clúster B (fuga de lectura total)."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True, is_active=True)
        norte = SucursalFactory(tenant=tenant, name="Norte", is_active=True)
        client = _auth_client(self._admin_de_centro(tenant, centro))

        with _api_tenant_ctx(tenant):
            resp = client.delete(_detail_url(norte.id))

        # Multi-sede (2026-07-16): owner-only → 403 (permiso) o 404 (scoping).
        assert resp.status_code in (403, 404)
        norte.refresh_from_db()
        assert norte.is_active is True

    def test_patch_403_admin_ya_no_edita_ni_su_propia_sede(self, db: Any) -> None:
        """Multi-sede (2026-07-16): gestionar sucursales es SOLO del dueño.

        Antes el admin podía editar su PROPIA sede (Clúster C acotaba a su sede);
        ahora ni siquiera eso — es dominio exclusivo del owner: recibe 403 y el
        nombre NO cambia.
        """
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True, is_active=True)
        client = _auth_client(self._admin_de_centro(tenant, centro))

        with _api_tenant_ctx(tenant):
            resp = client.patch(
                _detail_url(centro.id), data={"name": "Centro Editado"}, format="json"
            )

        assert resp.status_code == 403, resp.content
        centro.refresh_from_db()
        assert centro.name == "Centro"

    def test_delete_204_owner_sigue_pudiendo_cualquier_sede(self, db: Any) -> None:
        """Regresión: el owner NO se ve afectado por el scoping de sede."""
        tenant = TenantFactory()
        SucursalFactory(tenant=tenant, name="Centro", is_default=True, is_active=True)
        norte = SucursalFactory(tenant=tenant, name="Norte", is_active=True)
        client = _auth_client(_member(tenant, TenantMembership.Role.OWNER))

        with _api_tenant_ctx(tenant):
            resp = client.delete(_detail_url(norte.id))

        assert resp.status_code == 204
        norte.refresh_from_db()
        assert norte.is_active is False

    def test_patch_200_owner_reactiva_sede_ya_desactivada(self, db: Any) -> None:
        """Guarda de regresión propia del fix: el scoping por `_get_or_404`
        NO debe impedir reactivar una sede (ni siquiera al owner) — si se
        usara `allowed_sucursales` (que excluye inactivas) para esta
        validación, nadie podría reactivar una sede nunca más."""
        tenant = TenantFactory()
        SucursalFactory(tenant=tenant, name="Centro", is_default=True, is_active=True)
        norte = SucursalFactory(tenant=tenant, name="Norte", is_active=False)
        client = _auth_client(_member(tenant, TenantMembership.Role.OWNER))

        with _api_tenant_ctx(tenant):
            resp = client.patch(_detail_url(norte.id), data={"is_active": True}, format="json")

        assert resp.status_code == 200, resp.content
        assert resp.json()["is_active"] is True

    def test_patch_403_admin_ya_no_reactiva_su_propia_sede(self, db: Any) -> None:
        """Multi-sede (2026-07-16): owner-only. El admin ya no puede reactivar
        ni su propia sede — recibe 403 y la sede sigue inactiva."""
        tenant = TenantFactory()
        SucursalFactory(tenant=tenant, name="Principal", is_default=True, is_active=True)
        centro = SucursalFactory(tenant=tenant, name="Centro", is_active=False, is_default=False)
        client = _auth_client(self._admin_de_centro(tenant, centro))

        with _api_tenant_ctx(tenant):
            resp = client.patch(_detail_url(centro.id), data={"is_active": True}, format="json")

        assert resp.status_code == 403, resp.content
        centro.refresh_from_db()
        assert centro.is_active is False


# ---------------------------------------------------------------------------
# MembershipSucursal — aislamiento multi-tenant (RLS delegada al guardián)
# ---------------------------------------------------------------------------


class TestMembershipSucursalIsolation:
    def test_all_objects_no_filtra_por_tenant(self, db: Any) -> None:
        tenant1 = TenantFactory()
        tenant2 = TenantFactory()
        m1 = MembershipSucursalFactory(
            tenant=tenant1,
            membership=TenantMembershipFactory(tenant=tenant1),
            sucursal=SucursalFactory(tenant=tenant1),
        )
        m2 = MembershipSucursalFactory(
            tenant=tenant2,
            membership=TenantMembershipFactory(tenant=tenant2),
            sucursal=SucursalFactory(tenant=tenant2),
        )

        ids = set(MembershipSucursal.all_objects.values_list("id", flat=True))
        assert m1.id in ids
        assert m2.id in ids

    def test_tenant_manager_filtra_por_contexto_activo(self, db: Any) -> None:
        tenant1 = TenantFactory()
        tenant2 = TenantFactory()
        m1 = MembershipSucursalFactory(
            tenant=tenant1,
            membership=TenantMembershipFactory(tenant=tenant1),
            sucursal=SucursalFactory(tenant=tenant1),
        )
        MembershipSucursalFactory(
            tenant=tenant2,
            membership=TenantMembershipFactory(tenant=tenant2),
            sucursal=SucursalFactory(tenant=tenant2),
        )

        with _tenant_ctx(tenant1):
            visible_ids = set(MembershipSucursal.objects.values_list("id", flat=True))

        assert visible_ids == {m1.id}
