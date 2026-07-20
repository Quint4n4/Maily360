"""
Tests de multi-sede aplicada al catálogo (ServiceConcept / TreatmentPackage) —
decisión del dueño, 2026-07-16.

Cubre:
1. Permisos: solo el owner gestiona (POST/PATCH/DELETE) servicios y paquetes;
   admin (y el resto de roles) quedan fuera de la escritura pero SIGUEN
   viendo el catálogo completo (GET) para cobrar/cotizar.
2. Disponibilidad por sede (M2M `sucursales`, PRECIO sin cambios):
   - M2M vacío = disponible en TODAS las sedes.
   - M2M con sedes explícitas = solo visible/asignado en esas sedes.
   - El listado (`concept_list`/`package_list`) se acota por
     `sucursal_scope_ids(request)`, igual que cargos/pagos/cotizaciones.
3. Validación de aislamiento: crear un servicio/paquete con una sucursal de
   OTRO tenant se rechaza (400).

Patrón: AAA + factory_boy. HTTP: mismo patrón de 3 parches que
apps/finanzas/tests/test_sucursal_finanzas.py.
"""

from collections.abc import Generator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any
from unittest.mock import patch

from rest_framework.test import APIClient

from apps.tenancy.models import TenantMembership
from tests.factories import (
    ServiceConceptFactory,
    SucursalFactory,
    TenantFactory,
    TenantMembershipFactory,
    TreatmentPackageFactory,
    UserFactory,
)

CONCEPTS_URL = "/api/v1/finanzas/conceptos/"
PACKAGES_URL = "/api/v1/finanzas/paquetes/"


def _concept_url(concept_id: Any) -> str:
    return f"{CONCEPTS_URL}{concept_id}/"


def _package_url(package_id: Any) -> str:
    return f"{PACKAGES_URL}{package_id}/"


@contextmanager
def _api_tenant_ctx(tenant: Any) -> Generator[None, None, None]:
    """Inyecta el tenant para requests HTTP reales (mismo patrón que
    apps/finanzas/tests/test_sucursal_finanzas.py)."""
    with (
        patch("apps.finanzas.views.get_current_tenant", return_value=tenant),
        patch("apps.clinica.sucursal_scope.get_current_tenant", return_value=tenant),
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


def _owner_client(tenant: Any) -> APIClient:
    return _member_client(tenant, TenantMembership.Role.OWNER)


# ===========================================================================
# 1. Permisos — solo owner gestiona; el resto SOLO lee
# ===========================================================================


class TestSoloOwnerGestionaConceptos:
    def test_admin_no_puede_crear_concepto(self, db: Any) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "admin")
        with _api_tenant_ctx(tenant):
            resp = client.post(
                CONCEPTS_URL, data={"name": "Consulta", "base_price": "500.00"}, format="json"
            )
        assert resp.status_code == 403

    def test_admin_puede_listar_conceptos(self, db: Any) -> None:
        """El admin y el staff SIGUEN viendo el catálogo (GET) para cobrar/cotizar."""
        tenant = TenantFactory()
        ServiceConceptFactory(tenant=tenant)
        client = _member_client(tenant, "admin")
        with _api_tenant_ctx(tenant):
            resp = client.get(CONCEPTS_URL)
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_owner_puede_crear_concepto(self, db: Any) -> None:
        tenant = TenantFactory()
        client = _owner_client(tenant)
        with _api_tenant_ctx(tenant):
            resp = client.post(
                CONCEPTS_URL, data={"name": "Consulta", "base_price": "500.00"}, format="json"
            )
        assert resp.status_code == 201, resp.content


class TestSoloOwnerGestionaPaquetes:
    def test_admin_no_puede_crear_paquete(self, db: Any) -> None:
        tenant = TenantFactory()
        concept = ServiceConceptFactory(tenant=tenant)
        client = _member_client(tenant, "admin")
        with _api_tenant_ctx(tenant):
            resp = client.post(
                PACKAGES_URL,
                data={"name": "Paquete", "items": [{"concept_id": str(concept.id), "sessions": 1}]},
                format="json",
            )
        assert resp.status_code == 403

    def test_admin_puede_listar_paquetes(self, db: Any) -> None:
        tenant = TenantFactory()
        TreatmentPackageFactory(tenant=tenant)
        client = _member_client(tenant, "admin")
        with _api_tenant_ctx(tenant):
            resp = client.get(PACKAGES_URL)
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_owner_puede_crear_paquete(self, db: Any) -> None:
        tenant = TenantFactory()
        concept = ServiceConceptFactory(tenant=tenant)
        client = _owner_client(tenant)
        with _api_tenant_ctx(tenant):
            resp = client.post(
                PACKAGES_URL,
                data={"name": "Paquete", "items": [{"concept_id": str(concept.id), "sessions": 1}]},
                format="json",
            )
        assert resp.status_code == 201, resp.content


# ===========================================================================
# 2. Disponibilidad por sede — servicios
# ===========================================================================


class TestDisponibilidadPorSedeConceptos:
    def test_concepto_con_sucursal_norte_visible_con_header_norte(self, db: Any) -> None:
        tenant = TenantFactory()
        norte = SucursalFactory(tenant=tenant, name="Norte")
        SucursalFactory(tenant=tenant, name="Centro")
        client = _owner_client(tenant)

        with _api_tenant_ctx(tenant):
            create_resp = client.post(
                CONCEPTS_URL,
                data={
                    "name": "Botox Norte",
                    "base_price": "1000.00",
                    "sucursal_ids": [str(norte.id)],
                },
                format="json",
            )
            assert create_resp.status_code == 201, create_resp.content
            assert create_resp.json()["sucursales"] == [{"id": str(norte.id), "name": "Norte"}]

            list_resp = client.get(CONCEPTS_URL, headers={"X-Sucursal-Id": str(norte.id)})

        assert list_resp.status_code == 200, list_resp.content
        names = {c["name"] for c in list_resp.json()["results"]}
        assert "Botox Norte" in names

    def test_concepto_con_sucursal_norte_no_visible_con_header_centro(self, db: Any) -> None:
        tenant = TenantFactory()
        norte = SucursalFactory(tenant=tenant, name="Norte")
        centro = SucursalFactory(tenant=tenant, name="Centro")
        client = _owner_client(tenant)

        with _api_tenant_ctx(tenant):
            client.post(
                CONCEPTS_URL,
                data={
                    "name": "Botox Norte",
                    "base_price": "1000.00",
                    "sucursal_ids": [str(norte.id)],
                },
                format="json",
            )
            list_resp = client.get(CONCEPTS_URL, headers={"X-Sucursal-Id": str(centro.id)})

        assert list_resp.status_code == 200, list_resp.content
        names = {c["name"] for c in list_resp.json()["results"]}
        assert "Botox Norte" not in names

    def test_concepto_con_sucursal_norte_visible_para_owner_sin_header(self, db: Any) -> None:
        """El owner sin header ve el consolidado (todas las sedes)."""
        tenant = TenantFactory()
        norte = SucursalFactory(tenant=tenant, name="Norte")
        SucursalFactory(tenant=tenant, name="Centro")
        client = _owner_client(tenant)

        with _api_tenant_ctx(tenant):
            client.post(
                CONCEPTS_URL,
                data={
                    "name": "Botox Norte",
                    "base_price": "1000.00",
                    "sucursal_ids": [str(norte.id)],
                },
                format="json",
            )
            list_resp = client.get(CONCEPTS_URL)

        assert list_resp.status_code == 200, list_resp.content
        names = {c["name"] for c in list_resp.json()["results"]}
        assert "Botox Norte" in names

    def test_concepto_sin_sucursales_visible_en_cualquier_sede(self, db: Any) -> None:
        """M2M vacío = disponible en TODAS las sedes (convención)."""
        tenant = TenantFactory()
        norte = SucursalFactory(tenant=tenant, name="Norte")
        centro = SucursalFactory(tenant=tenant, name="Centro")
        client = _owner_client(tenant)

        with _api_tenant_ctx(tenant):
            create_resp = client.post(
                CONCEPTS_URL,
                data={"name": "Consulta general", "base_price": "300.00"},
                format="json",
            )
            assert create_resp.json()["sucursales"] == []

            resp_norte = client.get(CONCEPTS_URL, headers={"X-Sucursal-Id": str(norte.id)})
            resp_centro = client.get(CONCEPTS_URL, headers={"X-Sucursal-Id": str(centro.id)})

        assert {c["name"] for c in resp_norte.json()["results"]} == {"Consulta general"}
        assert {c["name"] for c in resp_centro.json()["results"]} == {"Consulta general"}

    def test_owner_asigna_sucursales_con_patch(self, db: Any) -> None:
        tenant = TenantFactory()
        norte = SucursalFactory(tenant=tenant, name="Norte")
        client = _owner_client(tenant)

        with _api_tenant_ctx(tenant):
            create_resp = client.post(
                CONCEPTS_URL,
                data={"name": "Consulta general", "base_price": "300.00"},
                format="json",
            )
            concept_id = create_resp.json()["id"]

            patch_resp = client.patch(
                _concept_url(concept_id),
                data={"sucursal_ids": [str(norte.id)]},
                format="json",
            )

        assert patch_resp.status_code == 200, patch_resp.content
        assert patch_resp.json()["sucursales"] == [{"id": str(norte.id), "name": "Norte"}]

    def test_patch_sin_sucursal_ids_no_modifica_disponibilidad(self, db: Any) -> None:
        tenant = TenantFactory()
        norte = SucursalFactory(tenant=tenant, name="Norte")
        client = _owner_client(tenant)

        with _api_tenant_ctx(tenant):
            create_resp = client.post(
                CONCEPTS_URL,
                data={
                    "name": "Consulta",
                    "base_price": "300.00",
                    "sucursal_ids": [str(norte.id)],
                },
                format="json",
            )
            concept_id = create_resp.json()["id"]

            patch_resp = client.patch(
                _concept_url(concept_id), data={"base_price": "350.00"}, format="json"
            )

        assert patch_resp.status_code == 200, patch_resp.content
        assert patch_resp.json()["sucursales"] == [{"id": str(norte.id), "name": "Norte"}]
        assert patch_resp.json()["base_price"] == "350.00"

    def test_crear_concepto_con_sucursal_de_otro_tenant_rechazado(self, db: Any) -> None:
        tenant = TenantFactory()
        otro_tenant = TenantFactory()
        sucursal_ajena = SucursalFactory(tenant=otro_tenant, name="Ajena")
        client = _owner_client(tenant)

        with _api_tenant_ctx(tenant):
            resp = client.post(
                CONCEPTS_URL,
                data={
                    "name": "Consulta",
                    "base_price": "300.00",
                    "sucursal_ids": [str(sucursal_ajena.id)],
                },
                format="json",
            )

        assert resp.status_code == 400, resp.content
        from apps.finanzas.models import ServiceConcept

        assert not ServiceConcept.all_objects.filter(tenant=tenant, name="Consulta").exists()


# ===========================================================================
# 3. Disponibilidad por sede — paquetes (mismo criterio)
# ===========================================================================


class TestDisponibilidadPorSedePaquetes:
    def test_paquete_con_sucursal_norte_visible_con_header_norte(self, db: Any) -> None:
        tenant = TenantFactory()
        norte = SucursalFactory(tenant=tenant, name="Norte")
        SucursalFactory(tenant=tenant, name="Centro")
        concept = ServiceConceptFactory(tenant=tenant, base_price=Decimal("100.00"))
        client = _owner_client(tenant)

        with _api_tenant_ctx(tenant):
            create_resp = client.post(
                PACKAGES_URL,
                data={
                    "name": "Paquete Norte",
                    "items": [{"concept_id": str(concept.id), "sessions": 2}],
                    "sucursal_ids": [str(norte.id)],
                },
                format="json",
            )
            assert create_resp.status_code == 201, create_resp.content
            assert create_resp.json()["sucursales"] == [{"id": str(norte.id), "name": "Norte"}]

            list_resp = client.get(PACKAGES_URL, headers={"X-Sucursal-Id": str(norte.id)})

        assert list_resp.status_code == 200, list_resp.content
        assert {p["name"] for p in list_resp.json()["results"]} == {"Paquete Norte"}

    def test_paquete_con_sucursal_norte_no_visible_con_header_centro(self, db: Any) -> None:
        tenant = TenantFactory()
        norte = SucursalFactory(tenant=tenant, name="Norte")
        centro = SucursalFactory(tenant=tenant, name="Centro")
        concept = ServiceConceptFactory(tenant=tenant, base_price=Decimal("100.00"))
        client = _owner_client(tenant)

        with _api_tenant_ctx(tenant):
            client.post(
                PACKAGES_URL,
                data={
                    "name": "Paquete Norte",
                    "items": [{"concept_id": str(concept.id), "sessions": 2}],
                    "sucursal_ids": [str(norte.id)],
                },
                format="json",
            )
            list_resp = client.get(PACKAGES_URL, headers={"X-Sucursal-Id": str(centro.id)})

        assert list_resp.status_code == 200, list_resp.content
        assert list_resp.json()["count"] == 0

    def test_paquete_sin_sucursales_visible_en_cualquier_sede(self, db: Any) -> None:
        tenant = TenantFactory()
        norte = SucursalFactory(tenant=tenant, name="Norte")
        centro = SucursalFactory(tenant=tenant, name="Centro")
        concept = ServiceConceptFactory(tenant=tenant, base_price=Decimal("100.00"))
        client = _owner_client(tenant)

        with _api_tenant_ctx(tenant):
            create_resp = client.post(
                PACKAGES_URL,
                data={
                    "name": "Paquete Universal",
                    "items": [{"concept_id": str(concept.id), "sessions": 1}],
                },
                format="json",
            )
            assert create_resp.json()["sucursales"] == []

            resp_norte = client.get(PACKAGES_URL, headers={"X-Sucursal-Id": str(norte.id)})
            resp_centro = client.get(PACKAGES_URL, headers={"X-Sucursal-Id": str(centro.id)})

        assert {p["name"] for p in resp_norte.json()["results"]} == {"Paquete Universal"}
        assert {p["name"] for p in resp_centro.json()["results"]} == {"Paquete Universal"}

    def test_crear_paquete_con_sucursal_de_otro_tenant_rechazado(self, db: Any) -> None:
        tenant = TenantFactory()
        otro_tenant = TenantFactory()
        sucursal_ajena = SucursalFactory(tenant=otro_tenant, name="Ajena")
        concept = ServiceConceptFactory(tenant=tenant, base_price=Decimal("100.00"))
        client = _owner_client(tenant)

        with _api_tenant_ctx(tenant):
            resp = client.post(
                PACKAGES_URL,
                data={
                    "name": "Paquete",
                    "items": [{"concept_id": str(concept.id), "sessions": 1}],
                    "sucursal_ids": [str(sucursal_ajena.id)],
                },
                format="json",
            )

        assert resp.status_code == 400, resp.content
        from apps.finanzas.models import TreatmentPackage

        assert not TreatmentPackage.all_objects.filter(tenant=tenant, name="Paquete").exists()

    def test_patch_paquete_sin_sucursal_ids_no_modifica_disponibilidad(self, db: Any) -> None:
        tenant = TenantFactory()
        norte = SucursalFactory(tenant=tenant, name="Norte")
        concept = ServiceConceptFactory(tenant=tenant, base_price=Decimal("100.00"))
        client = _owner_client(tenant)

        with _api_tenant_ctx(tenant):
            create_resp = client.post(
                PACKAGES_URL,
                data={
                    "name": "Paquete Norte",
                    "items": [{"concept_id": str(concept.id), "sessions": 1}],
                    "sucursal_ids": [str(norte.id)],
                },
                format="json",
            )
            package_id = create_resp.json()["id"]

            patch_resp = client.patch(
                _package_url(package_id),
                data={
                    "name": "Paquete Norte renombrado",
                    "items": [{"concept_id": str(concept.id), "sessions": 1}],
                },
                format="json",
            )

        assert patch_resp.status_code == 200, patch_resp.content
        assert patch_resp.json()["sucursales"] == [{"id": str(norte.id), "name": "Norte"}]
