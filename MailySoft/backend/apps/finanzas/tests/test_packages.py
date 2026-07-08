"""
Tests del catálogo de Paquetes de tratamientos (Fase 3 — Calendarización).

Cubre:
  - package_create / package_replace / package_delete (services.py):
    unicidad de nombre por tenant, validación de items, reemplazo
    destructivo, baja lógica.
  - Selectors: package_get / package_list (aislamiento por tenant, filtro
    only_active).
  - Serializers: precio calculado EN VIVO desde ServiceConcept.base_price.
  - APIs: matriz de permisos de TreatmentPackagePermission (GET → owner,
    admin, doctor, reception; POST/PATCH/DELETE → owner, admin) y 404 IDOR
    cross-tenant.
  - RLS: cubierto por el test guardián apps/core/tests/test_rls_coverage.py
    (descubre automáticamente finanzas_treatment_packages/_items vía
    TenantAwareModel).

Patrón: AAA. factory_boy para datos. Tenant context parcheado igual que el
resto de la app finanzas (ver test_apis.py / test_cotizaciones.py).
"""

from collections.abc import Generator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.finanzas.models import TreatmentPackage, TreatmentPackageItem
from apps.finanzas.selectors import package_get, package_list
from apps.finanzas.serializers import (
    TreatmentPackageListItemSerializer,
    TreatmentPackageOutputSerializer,
)
from apps.finanzas.services import package_create, package_delete, package_replace
from tests.factories import (
    ServiceConceptFactory,
    TenantFactory,
    TenantMembershipFactory,
    TreatmentPackageFactory,
    TreatmentPackageItemFactory,
    UserFactory,
)

PACKAGES_URL = "/api/v1/finanzas/paquetes/"


def _package_detail_url(package_id: Any) -> str:
    return f"/api/v1/finanzas/paquetes/{package_id}/"


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
    """APIClient autenticado como miembro con rol indicado."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ===========================================================================
# Services — package_create
# ===========================================================================


class TestPackageCreate:
    def test_creates_package_with_items(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        concept = ServiceConceptFactory(tenant=tenant, base_price=Decimal("300.00"))

        package = package_create(
            tenant=tenant,
            user=user,
            name="Paquete Rejuvenecimiento",
            description="6 sesiones",
            is_active=True,
            items=[{"concept_id": str(concept.id), "sessions": 6}],
        )

        assert package.id is not None
        assert package.items.count() == 1
        item = package.items.first()
        assert item.service_concept_id == concept.id
        assert item.sessions == 6
        assert item.order == 0

    def test_duplicate_name_in_tenant_raises(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        concept = ServiceConceptFactory(tenant=tenant)
        package_create(
            tenant=tenant,
            user=user,
            name="Paquete X",
            items=[{"concept_id": str(concept.id), "sessions": 1}],
        )

        with pytest.raises(ValidationError, match="Ya existe un paquete"):
            package_create(
                tenant=tenant,
                user=user,
                name="Paquete X",
                items=[{"concept_id": str(concept.id), "sessions": 1}],
            )

    def test_same_name_different_tenant_allowed(self, db: None) -> None:
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user = UserFactory()
        concept_a = ServiceConceptFactory(tenant=tenant_a)
        concept_b = ServiceConceptFactory(tenant=tenant_b)
        package_create(
            tenant=tenant_a,
            user=user,
            name="Paquete Compartido",
            items=[{"concept_id": str(concept_a.id), "sessions": 1}],
        )

        package_b = package_create(
            tenant=tenant_b,
            user=user,
            name="Paquete Compartido",
            items=[{"concept_id": str(concept_b.id), "sessions": 1}],
        )
        assert package_b.tenant_id == tenant_b.id

    def test_without_items_raises(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()

        with pytest.raises(ValidationError, match="al menos un tratamiento"):
            package_create(tenant=tenant, user=user, name="Vacío", items=[])

    def test_missing_concept_id_raises(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()

        with pytest.raises(ValidationError, match="concepto del catálogo"):
            package_create(tenant=tenant, user=user, name="Sin concepto", items=[{"sessions": 1}])

    def test_unknown_concept_raises(self, db: None) -> None:
        import uuid

        tenant = TenantFactory()
        user = UserFactory()

        with pytest.raises(ValidationError, match="Concepto no encontrado"):
            package_create(
                tenant=tenant,
                user=user,
                name="Concepto inexistente",
                items=[{"concept_id": str(uuid.uuid4()), "sessions": 1}],
            )

    def test_concept_of_other_tenant_raises(self, db: None) -> None:
        tenant = TenantFactory()
        other_tenant = TenantFactory()
        user = UserFactory()
        other_concept = ServiceConceptFactory(tenant=other_tenant)

        with pytest.raises(ValidationError, match="no pertenece a esta clínica"):
            package_create(
                tenant=tenant,
                user=user,
                name="Cross tenant",
                items=[{"concept_id": str(other_concept.id), "sessions": 1}],
            )

    def test_inactive_concept_raises(self, db: None) -> None:
        """FIX 3: un concepto desactivado no puede usarse en un paquete nuevo."""
        tenant = TenantFactory()
        user = UserFactory()
        inactive_concept = ServiceConceptFactory(tenant=tenant, is_active=False)

        with pytest.raises(ValidationError, match="está desactivado"):
            package_create(
                tenant=tenant,
                user=user,
                name="Paquete con concepto inactivo",
                items=[{"concept_id": str(inactive_concept.id), "sessions": 1}],
            )

    def test_invalid_sessions_raises(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        concept = ServiceConceptFactory(tenant=tenant)

        with pytest.raises(ValidationError, match="al menos una sesión"):
            package_create(
                tenant=tenant,
                user=user,
                name="Sesiones inválidas",
                items=[{"concept_id": str(concept.id), "sessions": 0}],
            )

    def test_default_order_follows_item_position(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        concept_1 = ServiceConceptFactory(tenant=tenant)
        concept_2 = ServiceConceptFactory(tenant=tenant)

        package = package_create(
            tenant=tenant,
            user=user,
            name="Paquete ordenado",
            items=[
                {"concept_id": str(concept_1.id), "sessions": 1},
                {"concept_id": str(concept_2.id), "sessions": 2},
            ],
        )

        items = list(package.items.order_by("order"))
        assert [i.service_concept_id for i in items] == [concept_1.id, concept_2.id]
        assert [i.order for i in items] == [0, 1]


# ===========================================================================
# Services — package_replace
# ===========================================================================


class TestPackageReplace:
    def test_replaces_name_description_and_items(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        package = TreatmentPackageFactory(tenant=tenant, name="Original")
        old_concept = ServiceConceptFactory(tenant=tenant)
        TreatmentPackageItemFactory(package=package, service_concept=old_concept, sessions=1)
        new_concept = ServiceConceptFactory(tenant=tenant, base_price=Decimal("800.00"))

        updated = package_replace(
            package=package,
            user=user,
            name="Renombrado",
            description="Nueva descripción",
            is_active=False,
            items=[{"concept_id": str(new_concept.id), "sessions": 4}],
        )

        assert updated.name == "Renombrado"
        assert updated.description == "Nueva descripción"
        assert updated.is_active is False
        assert updated.items.count() == 1
        assert updated.items.first().service_concept_id == new_concept.id
        assert updated.items.first().sessions == 4

    def test_replace_destroys_old_items(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        package = TreatmentPackageFactory(tenant=tenant)
        old_item = TreatmentPackageItemFactory(package=package)
        new_concept = ServiceConceptFactory(tenant=tenant)

        package_replace(
            package=package,
            user=user,
            name=package.name,
            items=[{"concept_id": str(new_concept.id), "sessions": 1}],
        )

        assert not TreatmentPackageItem.objects.filter(id=old_item.id).exists()

    def test_replace_without_items_raises(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        package = TreatmentPackageFactory(tenant=tenant)

        with pytest.raises(ValidationError, match="al menos un tratamiento"):
            package_replace(package=package, user=user, name=package.name, items=[])

    def test_replace_name_collision_raises(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        concept = ServiceConceptFactory(tenant=tenant)
        TreatmentPackageFactory(tenant=tenant, name="Ya existe")
        package = TreatmentPackageFactory(tenant=tenant, name="Original")

        with pytest.raises(ValidationError, match="Ya existe un paquete"):
            package_replace(
                package=package,
                user=user,
                name="Ya existe",
                items=[{"concept_id": str(concept.id), "sessions": 1}],
            )

    def test_replace_keeping_same_name_does_not_raise(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        concept = ServiceConceptFactory(tenant=tenant)
        package = TreatmentPackageFactory(tenant=tenant, name="Mismo nombre")

        updated = package_replace(
            package=package,
            user=user,
            name="Mismo nombre",
            items=[{"concept_id": str(concept.id), "sessions": 2}],
        )
        assert updated.name == "Mismo nombre"


# ===========================================================================
# Services — package_delete
# ===========================================================================


class TestPackageDelete:
    def test_soft_deletes_package(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        package = TreatmentPackageFactory(tenant=tenant)

        package_delete(package=package, user=user)

        package.refresh_from_db()
        assert package.deleted_at is not None
        assert not TreatmentPackage.objects.filter(id=package.id).exists()
        assert TreatmentPackage.all_objects.filter(id=package.id).exists()


# ===========================================================================
# Selectors
# ===========================================================================


class TestPackageSelectors:
    def test_package_list_only_active_default(self, db: None) -> None:
        tenant = TenantFactory()
        TreatmentPackageFactory(tenant=tenant, is_active=True)
        TreatmentPackageFactory(tenant=tenant, is_active=False)

        with (
            patch("apps.core.managers.get_current_tenant", return_value=tenant),
            patch("apps.core.managers.is_tenant_context_active", return_value=True),
        ):
            active_only = list(package_list())
            all_packages = list(package_list(only_active=False))

        assert len(active_only) == 1
        assert len(all_packages) == 2

    def test_package_get_isolation_cross_tenant(self, db: None) -> None:
        tenant = TenantFactory()
        other_tenant = TenantFactory()
        other_package = TreatmentPackageFactory(tenant=other_tenant)

        with (
            patch("apps.core.managers.get_current_tenant", return_value=tenant),
            patch("apps.core.managers.is_tenant_context_active", return_value=True),
        ):
            with pytest.raises(TreatmentPackage.DoesNotExist):
                package_get(package_id=other_package.id)


# ===========================================================================
# Serializers — precio en vivo
# ===========================================================================


class TestPackageSerializers:
    def test_detail_price_sums_base_price_times_sessions(self, db: None) -> None:
        tenant = TenantFactory()
        package = TreatmentPackageFactory(tenant=tenant)
        concept_1 = ServiceConceptFactory(tenant=tenant, base_price=Decimal("500.00"))
        concept_2 = ServiceConceptFactory(tenant=tenant, base_price=Decimal("250.50"))
        TreatmentPackageItemFactory(package=package, service_concept=concept_1, sessions=3)
        TreatmentPackageItemFactory(package=package, service_concept=concept_2, sessions=2)

        loaded = package_get(package_id=package.id)
        data = TreatmentPackageOutputSerializer(loaded).data

        # 500.00*3 + 250.50*2 = 1500.00 + 501.00 = 2001.00
        assert data["price"] == "2001.00"
        assert len(data["items"]) == 2

    def test_list_item_reports_counts_and_price(self, db: None) -> None:
        tenant = TenantFactory()
        package = TreatmentPackageFactory(tenant=tenant)
        concept = ServiceConceptFactory(tenant=tenant, base_price=Decimal("100.00"))
        TreatmentPackageItemFactory(package=package, service_concept=concept, sessions=5)

        loaded = package_list(only_active=False).get(id=package.id)
        data = TreatmentPackageListItemSerializer(loaded).data

        assert data["items_count"] == 1
        assert data["sessions_total"] == 5
        assert data["price"] == "500.00"


# ===========================================================================
# APIs — matriz de permisos (TreatmentPackagePermission)
# ===========================================================================


class TestPackageApiPermissions:
    def test_unauthenticated_rejected(self, db: None) -> None:
        tenant = TenantFactory()
        with _tenant_context(tenant):
            resp = APIClient().get(PACKAGES_URL)
        assert resp.status_code == 401

    def test_doctor_can_list_packages(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "doctor")
        with _tenant_context(tenant):
            resp = client.get(PACKAGES_URL)
        assert resp.status_code == 200

    def test_reception_can_list_packages(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "reception")
        with _tenant_context(tenant):
            resp = client.get(PACKAGES_URL)
        assert resp.status_code == 200

    def test_nurse_cannot_list_packages(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "nurse")
        with _tenant_context(tenant):
            resp = client.get(PACKAGES_URL)
        assert resp.status_code == 403

    def test_doctor_cannot_create_package(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "doctor")
        with _tenant_context(tenant):
            resp = client.post(PACKAGES_URL, data={"name": "X", "items": []}, format="json")
        assert resp.status_code == 403

    def test_owner_can_create_package(self, db: None) -> None:
        tenant = TenantFactory()
        concept = ServiceConceptFactory(tenant=tenant)
        client = _member_client(tenant, "owner")
        with _tenant_context(tenant):
            resp = client.post(
                PACKAGES_URL,
                data={
                    "name": "Paquete API",
                    "description": "desc",
                    "items": [{"concept_id": str(concept.id), "sessions": 3}],
                },
                format="json",
            )
        assert resp.status_code == 201, resp.content
        assert resp.json()["name"] == "Paquete API"
        assert len(resp.json()["items"]) == 1

    def test_admin_can_patch_package(self, db: None) -> None:
        tenant = TenantFactory()
        package = TreatmentPackageFactory(tenant=tenant, name="Antes")
        concept = ServiceConceptFactory(tenant=tenant)
        TreatmentPackageItemFactory(package=package, service_concept=concept)
        client = _member_client(tenant, "admin")

        with _tenant_context(tenant):
            resp = client.patch(
                _package_detail_url(package.id),
                data={"name": "Después"},
                format="json",
            )
        assert resp.status_code == 200, resp.content
        assert resp.json()["name"] == "Después"
        # items preservados porque no se enviaron en el PATCH.
        assert len(resp.json()["items"]) == 1

    def test_reception_cannot_patch_package(self, db: None) -> None:
        tenant = TenantFactory()
        package = TreatmentPackageFactory(tenant=tenant)
        client = _member_client(tenant, "reception")
        with _tenant_context(tenant):
            resp = client.patch(_package_detail_url(package.id), data={"name": "X"}, format="json")
        assert resp.status_code == 403

    def test_owner_can_delete_package(self, db: None) -> None:
        tenant = TenantFactory()
        package = TreatmentPackageFactory(tenant=tenant)
        client = _member_client(tenant, "owner")
        with _tenant_context(tenant):
            resp = client.delete(_package_detail_url(package.id))
        assert resp.status_code == 204
        package.refresh_from_db()
        assert package.deleted_at is not None

    def test_get_package_from_other_tenant_returns_404(self, db: None) -> None:
        tenant = TenantFactory()
        other_tenant = TenantFactory()
        other_package = TreatmentPackageFactory(tenant=other_tenant)
        client = _member_client(tenant, "owner")

        with _tenant_context(tenant):
            resp = client.get(_package_detail_url(other_package.id))
        assert resp.status_code == 404

    def test_create_without_items_returns_400(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "owner")
        with _tenant_context(tenant):
            resp = client.post(PACKAGES_URL, data={"name": "Vacío", "items": []}, format="json")
        assert resp.status_code == 400
