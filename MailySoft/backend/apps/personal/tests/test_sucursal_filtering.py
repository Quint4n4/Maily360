"""
Tests de scoping por sucursal en la app personal (multi-sede — Fase 1).

Cubre:
1. Selectors: consultorio_list/doctor_list con sucursal_id filtran correctamente;
   sin sucursal_id → sin filtro (compatibilidad retro, todas las sedes).
2. Endpoints HTTP: X-Sucursal-Id filtra consultorios/doctores; header de una
   sede NO permitida → 403; sin header → todas (compat. retro).
3. Aislamiento operativo: un usuario acotado a la Sucursal A (vía
   MembershipSucursal) NO ve consultorios de la Sucursal B, ni siquiera
   pidiéndolos sin header (su propio listado ya no aplica ahí porque el
   scoping real lo hace el header explícito — este test cubre el caso de uso
   real: recepción de A manda X-Sucursal-Id=A y nunca puede pedir B).
4. Backfill (migración de datos 0009): tras aplicar, cada tenant preexistente
   tiene una única "Sucursal Principal" con todo el consultorio/doctor/
   membresía existente asignado. Se invoca la función de la migración
   directamente contra el registro de apps real (patrón estándar para probar
   RunPython sin depender de infraestructura de test de migraciones).

Patrón: AAA. Mismo helper _api_tenant_ctx que apps/personal/tests/test_apis.py.
"""

import importlib
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

from django.apps import apps as real_apps
from rest_framework.test import APIClient

from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from apps.personal.selectors import consultorio_list, doctor_list
from apps.tenancy.models import TenantMembership
from tests.factories import (
    ConsultorioFactory,
    DoctorFactory,
    MembershipSucursalFactory,
    SucursalFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

CONSULTORIOS_URL = "/api/v1/personal/consultorios/"
DOCTORES_URL = "/api/v1/personal/doctores/"


@contextmanager
def _tenant_ctx(tenant: Any) -> Generator[None, None, None]:
    set_current_tenant(tenant)
    set_tenant_context_active(True)
    try:
        yield
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)


@contextmanager
def _api_tenant_ctx(tenant: Any) -> Generator[None, None, None]:
    """Inyecta tenant en el middleware/TenantManager para tests HTTP.

    Parchea get_current_tenant en TODOS los módulos de vistas que lo llaman
    directamente para este flujo: apps.personal.views (consultorios/doctores)
    y apps.clinica.sucursal_scope (resolve_active_sucursal).
    """
    with (
        patch("apps.personal.views.get_current_tenant", return_value=tenant),
        patch("apps.clinica.sucursal_scope.get_current_tenant", return_value=tenant),
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
# Selectors
# ---------------------------------------------------------------------------


class TestConsultorioListSucursalFilter:
    def test_filtra_por_sucursal_id(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant)
        norte = SucursalFactory(tenant=tenant)
        ConsultorioFactory(tenant=tenant, sucursal=centro)
        ConsultorioFactory(tenant=tenant, sucursal=norte)

        with _tenant_ctx(tenant):
            qs = consultorio_list(sucursal_id=centro.id)

        assert qs.count() == 1
        assert qs.first().sucursal_id == centro.id

    def test_sin_sucursal_id_no_filtra(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant)
        norte = SucursalFactory(tenant=tenant)
        ConsultorioFactory(tenant=tenant, sucursal=centro)
        ConsultorioFactory(tenant=tenant, sucursal=norte)
        ConsultorioFactory(tenant=tenant, sucursal=None)

        with _tenant_ctx(tenant):
            qs = consultorio_list()

        assert qs.count() == 3


class TestDoctorListSucursalFilter:
    def test_filtra_por_sucursal_id(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant)
        norte = SucursalFactory(tenant=tenant)
        doc_centro = DoctorFactory(tenant=tenant)
        doc_norte = DoctorFactory(tenant=tenant)
        doc_centro.sucursales.add(centro)
        doc_norte.sucursales.add(norte)

        with _tenant_ctx(tenant):
            qs = doctor_list(sucursal_id=centro.id)

        assert list(qs.values_list("id", flat=True)) == [doc_centro.id]

    def test_sin_sucursal_id_no_filtra(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant)
        doc_a = DoctorFactory(tenant=tenant)
        DoctorFactory(tenant=tenant)  # sin sucursal asignada (compat. retro).
        doc_a.sucursales.add(centro)

        with _tenant_ctx(tenant):
            qs = doctor_list()

        assert qs.count() == 2


# ---------------------------------------------------------------------------
# Endpoints HTTP — X-Sucursal-Id
# ---------------------------------------------------------------------------


class TestConsultorioApiSucursalHeader:
    def test_sin_header_devuelve_todos(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant)
        norte = SucursalFactory(tenant=tenant)
        ConsultorioFactory(tenant=tenant, sucursal=centro)
        ConsultorioFactory(tenant=tenant, sucursal=norte)
        client = _auth_client(_member(tenant, TenantMembership.Role.OWNER))

        with _api_tenant_ctx(tenant):
            resp = client.get(CONSULTORIOS_URL)

        assert resp.status_code == 200, resp.content
        assert resp.json()["count"] == 2

    def test_header_de_sede_permitida_filtra(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant)
        norte = SucursalFactory(tenant=tenant)
        ConsultorioFactory(tenant=tenant, sucursal=centro, name="Consultorio A")
        ConsultorioFactory(tenant=tenant, sucursal=norte, name="Consultorio B")
        client = _auth_client(_member(tenant, TenantMembership.Role.OWNER))

        with _api_tenant_ctx(tenant):
            resp = client.get(CONSULTORIOS_URL, headers={"X-Sucursal-Id": str(centro.id)})

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["count"] == 1
        assert body["results"][0]["name"] == "Consultorio A"

    def test_header_de_sede_no_permitida_403(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")

        user = UserFactory()
        membership = TenantMembershipFactory(
            user=user, tenant=tenant, role=TenantMembership.Role.RECEPTION, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)
        client = _auth_client(user)

        with _api_tenant_ctx(tenant):
            resp = client.get(CONSULTORIOS_URL, headers={"X-Sucursal-Id": str(norte.id)})

        assert resp.status_code == 403

    def test_aislamiento_recepcion_acotada_no_ve_consultorios_de_otra_sede(self, db: Any) -> None:
        """Caso de uso real: recepción de Centro pide su sede y nunca ve Norte."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        ConsultorioFactory(tenant=tenant, sucursal=centro, name="Sala Centro")
        ConsultorioFactory(tenant=tenant, sucursal=norte, name="Sala Norte")

        user = UserFactory()
        membership = TenantMembershipFactory(
            user=user, tenant=tenant, role=TenantMembership.Role.RECEPTION, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)
        client = _auth_client(user)

        with _api_tenant_ctx(tenant):
            resp = client.get(CONSULTORIOS_URL, headers={"X-Sucursal-Id": str(centro.id)})

        assert resp.status_code == 200, resp.content
        names = [c["name"] for c in resp.json()["results"]]
        assert names == ["Sala Centro"]
        assert "Sala Norte" not in names


class TestDoctorApiSucursalHeader:
    def test_header_de_sede_permitida_filtra_doctores(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant)
        norte = SucursalFactory(tenant=tenant)
        doc_centro = DoctorFactory(tenant=tenant)
        doc_norte = DoctorFactory(tenant=tenant)
        doc_centro.sucursales.add(centro)
        doc_norte.sucursales.add(norte)
        client = _auth_client(_member(tenant, TenantMembership.Role.OWNER))

        with _api_tenant_ctx(tenant):
            resp = client.get(DOCTORES_URL, headers={"X-Sucursal-Id": str(centro.id)})

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["count"] == 1
        assert body["results"][0]["id"] == str(doc_centro.id)


# ---------------------------------------------------------------------------
# Objetivo A — cierre del hueco de seguridad (Fase 3): sin header YA NO fuga
# ---------------------------------------------------------------------------


class TestSinHeaderYaNoFugaOtraSede:
    """Antes de este fix: un usuario acotado a la Sucursal A veía datos de la
    Sucursal B con solo OMITIR el header X-Sucursal-Id (el filtro solo se
    aplicaba si el header venía explícito). Ahora `sucursal_scope_ids` acota
    SIEMPRE al alcance real del usuario, con o sin header."""

    def test_recepcion_acotada_a_centro_no_ve_consultorios_de_norte_sin_header(
        self, db: Any
    ) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        ConsultorioFactory(tenant=tenant, sucursal=centro, name="Sala Centro")
        ConsultorioFactory(tenant=tenant, sucursal=norte, name="Sala Norte")

        user = UserFactory()
        membership = TenantMembershipFactory(
            user=user, tenant=tenant, role=TenantMembership.Role.RECEPTION, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)
        client = _auth_client(user)

        with _api_tenant_ctx(tenant):
            resp = client.get(CONSULTORIOS_URL)  # SIN X-Sucursal-Id

        assert resp.status_code == 200, resp.content
        names = [c["name"] for c in resp.json()["results"]]
        assert names == ["Sala Centro"]
        assert "Sala Norte" not in names

    def test_recepcion_acotada_a_centro_no_ve_doctores_de_norte_sin_header(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        doc_centro = DoctorFactory(tenant=tenant)
        doc_norte = DoctorFactory(tenant=tenant)
        doc_centro.sucursales.add(centro)
        doc_norte.sucursales.add(norte)

        user = UserFactory()
        membership = TenantMembershipFactory(
            user=user, tenant=tenant, role=TenantMembership.Role.RECEPTION, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)
        client = _auth_client(user)

        with _api_tenant_ctx(tenant):
            resp = client.get(DOCTORES_URL)  # SIN X-Sucursal-Id

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["count"] == 1
        assert body["results"][0]["id"] == str(doc_centro.id)

    def test_owner_sin_header_sigue_viendo_todo_consolidado(self, db: Any) -> None:
        """El dueño (alcance total) NO se ve afectado por el fix: sin header
        sigue viendo todas las sedes."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        ConsultorioFactory(tenant=tenant, sucursal=centro)
        ConsultorioFactory(tenant=tenant, sucursal=norte)
        client = _auth_client(_member(tenant, TenantMembership.Role.OWNER))

        with _api_tenant_ctx(tenant):
            resp = client.get(CONSULTORIOS_URL)

        assert resp.status_code == 200, resp.content
        assert resp.json()["count"] == 2


# ---------------------------------------------------------------------------
# "Admin de sucursal" — un admin acotado a UNA sede vía MembershipSucursal
# (bug corregido: antes cualquier admin veía TODAS las sedes sin importar su
# MembershipSucursal; ver docs/design/sucursales-arquitectura-analisis.md §12)
# ---------------------------------------------------------------------------


class TestAdminDeSucursalAislamiento:
    """Un admin con UNA SOLA MembershipSucursal (p. ej. "Admin de Centro")
    debe comportarse exactamente igual que un rol operativo acotado (como
    reception): NO ve la otra sede ni con header, ni omitiéndolo."""

    def test_admin_acotado_a_centro_no_ve_consultorios_de_norte_con_header(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        ConsultorioFactory(tenant=tenant, sucursal=centro, name="Sala Centro")
        ConsultorioFactory(tenant=tenant, sucursal=norte, name="Sala Norte")

        user = UserFactory()
        membership = TenantMembershipFactory(
            user=user, tenant=tenant, role=TenantMembership.Role.ADMIN, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)
        client = _auth_client(user)

        with _api_tenant_ctx(tenant):
            resp = client.get(CONSULTORIOS_URL, headers={"X-Sucursal-Id": str(centro.id)})

        assert resp.status_code == 200, resp.content
        names = [c["name"] for c in resp.json()["results"]]
        assert names == ["Sala Centro"]

    def test_admin_acotado_a_centro_no_ve_consultorios_de_norte_sin_header(self, db: Any) -> None:
        """CRÍTICO — el bug original: antes de este fix, un admin acotado a
        Centro veía Norte igual con solo OMITIR el header X-Sucursal-Id."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        ConsultorioFactory(tenant=tenant, sucursal=centro, name="Sala Centro")
        ConsultorioFactory(tenant=tenant, sucursal=norte, name="Sala Norte")

        user = UserFactory()
        membership = TenantMembershipFactory(
            user=user, tenant=tenant, role=TenantMembership.Role.ADMIN, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)
        client = _auth_client(user)

        with _api_tenant_ctx(tenant):
            resp = client.get(CONSULTORIOS_URL)  # SIN X-Sucursal-Id

        assert resp.status_code == 200, resp.content
        names = [c["name"] for c in resp.json()["results"]]
        assert names == ["Sala Centro"]
        assert "Sala Norte" not in names

    def test_admin_acotado_a_centro_no_ve_doctores_de_norte_sin_header(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        doc_centro = DoctorFactory(tenant=tenant)
        doc_norte = DoctorFactory(tenant=tenant)
        doc_centro.sucursales.add(centro)
        doc_norte.sucursales.add(norte)

        user = UserFactory()
        membership = TenantMembershipFactory(
            user=user, tenant=tenant, role=TenantMembership.Role.ADMIN, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)
        client = _auth_client(user)

        with _api_tenant_ctx(tenant):
            resp = client.get(DOCTORES_URL)  # SIN X-Sucursal-Id

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["count"] == 1
        assert body["results"][0]["id"] == str(doc_centro.id)

    def test_admin_acotado_a_centro_pide_header_de_norte_403(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")

        user = UserFactory()
        membership = TenantMembershipFactory(
            user=user, tenant=tenant, role=TenantMembership.Role.ADMIN, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)
        client = _auth_client(user)

        with _api_tenant_ctx(tenant):
            resp = client.get(CONSULTORIOS_URL, headers={"X-Sucursal-Id": str(norte.id)})

        assert resp.status_code == 403

    def test_admin_asignado_a_todas_las_sedes_ve_consolidado(self, db: Any) -> None:
        """Un admin con MembershipSucursal para CADA sede activa = "admin de
        negocio": ve consolidado, igual que el dueño."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        ConsultorioFactory(tenant=tenant, sucursal=centro)
        ConsultorioFactory(tenant=tenant, sucursal=norte)

        user = UserFactory()
        membership = TenantMembershipFactory(
            user=user, tenant=tenant, role=TenantMembership.Role.ADMIN, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=norte)
        client = _auth_client(user)

        with _api_tenant_ctx(tenant):
            resp = client.get(CONSULTORIOS_URL)  # SIN X-Sucursal-Id

        assert resp.status_code == 200, resp.content
        assert resp.json()["count"] == 2


# ---------------------------------------------------------------------------
# Backfill — migración de datos 0009_backfill_sucursal_principal
# ---------------------------------------------------------------------------


def _load_backfill_function() -> Any:
    """Importa la función RunPython de la migración por su path completo.

    El nombre del módulo empieza con un dígito (0009_...), por lo que no se
    puede importar con `import ... from ...` normal — se usa importlib.
    """
    module = importlib.import_module("apps.personal.migrations.0009_backfill_sucursal_principal")
    return module.backfill_sucursal_principal


class TestBackfillSucursalPrincipal:
    """Invoca la función de la migración directamente contra el app registry
    real (mismos modelos que en producción; la función solo usa el ORM
    estándar, sin operaciones de schema_editor) para verificar su lógica de
    negocio con datos de prueba creados en el test.
    """

    def test_crea_sucursal_principal_y_asigna_todo(self, db: Any) -> None:
        tenant = TenantFactory()
        consultorio = ConsultorioFactory(tenant=tenant, sucursal=None)
        doctor = DoctorFactory(tenant=tenant)
        membership = doctor.membership

        backfill = _load_backfill_function()
        backfill(real_apps, None)

        consultorio.refresh_from_db()
        doctor.refresh_from_db()

        from apps.clinica.models import MembershipSucursal, Sucursal

        principal = Sucursal.all_objects.get(tenant=tenant, is_default=True)
        assert principal.name == "Sucursal Principal"
        assert principal.is_active is True

        assert consultorio.sucursal_id == principal.id
        assert doctor.sucursales.filter(id=principal.id).exists()
        assert MembershipSucursal.all_objects.filter(
            membership=membership, sucursal=principal
        ).exists()

    def test_idempotente_no_duplica_al_correr_dos_veces(self, db: Any) -> None:
        tenant = TenantFactory()
        ConsultorioFactory(tenant=tenant, sucursal=None)
        DoctorFactory(tenant=tenant)

        backfill = _load_backfill_function()
        backfill(real_apps, None)
        backfill(real_apps, None)

        from apps.clinica.models import Sucursal

        assert Sucursal.all_objects.filter(tenant=tenant, is_default=True).count() == 1

    def test_no_reasigna_consultorio_ya_asignado_a_otra_sede(self, db: Any) -> None:
        tenant = TenantFactory()
        otra_sede = SucursalFactory(tenant=tenant, is_default=False)
        consultorio = ConsultorioFactory(tenant=tenant, sucursal=otra_sede)

        backfill = _load_backfill_function()
        backfill(real_apps, None)

        consultorio.refresh_from_db()
        assert consultorio.sucursal_id == otra_sede.id
