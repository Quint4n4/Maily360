"""
Tests del override por clínica (Fase 6 — cierre comercial).

Es lo que hace VENDIBLE el caso dental: una clínica que quiere expediente pero no
recetas no cabe en ningún plan fijo. Sin el override habría que crear un plan por
cada forma rara de clínica.

Cubre el servicio, el endpoint y su efecto real sobre los derechos.

Patrón: AAA. factory_boy. Fixtures: db.
"""

from typing import Any

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.core.modules import Module
from apps.plataforma.services import tenant_entitlements_set
from apps.tenancy.entitlements import entitlements_for_tenant
from apps.tenancy.models import TenantEntitlements
from tests.factories import PlanFactory, TenantFactory, UserFactory

_PLAN_COMPLETO = [
    Module.AGENDA, Module.RECORDATORIOS, Module.EXPEDIENTE,
    Module.RECETAS, Module.NOTAS,
]


@pytest.fixture
def super_admin(db: Any) -> Any:
    return UserFactory(is_platform_staff=True, is_staff=True, platform_role="super_admin")


@pytest.mark.django_db
class TestServicioOverride:
    def test_revoca_un_modulo_del_plan(self, super_admin: Any) -> None:
        """El caso dental: apagar recetas aunque el plan las traiga."""
        tenant = TenantFactory(plan=PlanFactory(modules=_PLAN_COMPLETO))

        tenant_entitlements_set(
            tenant=tenant, actor=super_admin,
            modules_off=[Module.RECETAS], notes="Clínica dental",
        )

        ent = entitlements_for_tenant(tenant=tenant)
        assert not ent.tiene(Module.RECETAS)
        assert ent.tiene(Module.EXPEDIENTE)

    def test_concede_un_modulo_extra(self, super_admin: Any) -> None:
        tenant = TenantFactory(plan=PlanFactory(modules=_PLAN_COMPLETO))

        tenant_entitlements_set(
            tenant=tenant, actor=super_admin,
            modules_on=[Module.COBRANZA], notes="Cortesía por lanzamiento",
        )

        assert entitlements_for_tenant(tenant=tenant).tiene(Module.COBRANZA)

    def test_sube_un_limite(self, super_admin: Any) -> None:
        tenant = TenantFactory(plan=PlanFactory(modules=_PLAN_COMPLETO, max_usuarios=3))

        tenant_entitlements_set(
            tenant=tenant, actor=super_admin, max_usuarios=10, notes="Ampliación vendida",
        )

        assert entitlements_for_tenant(tenant=tenant).max_usuarios == 10

    def test_rechaza_modulo_desconocido(self, super_admin: Any) -> None:
        tenant = TenantFactory(plan=PlanFactory(modules=_PLAN_COMPLETO))

        with pytest.raises(DjangoValidationError, match="desconocidos"):
            tenant_entitlements_set(
                tenant=tenant, actor=super_admin, modules_on=["telepatia"],
            )

    def test_solo_super_admin(self, db: Any) -> None:
        """Sales asigna planes, pero los tratos a la medida son del super admin."""
        sales = UserFactory(is_platform_staff=True, platform_role="sales")
        tenant = TenantFactory(plan=PlanFactory(modules=_PLAN_COMPLETO))

        with pytest.raises(DjangoValidationError, match="super"):
            tenant_entitlements_set(
                tenant=tenant, actor=sales, modules_off=[Module.RECETAS],
            )

    def test_es_idempotente(self, super_admin: Any) -> None:
        """Guardar dos veces actualiza la misma fila, no crea duplicados."""
        tenant = TenantFactory(plan=PlanFactory(modules=_PLAN_COMPLETO))

        tenant_entitlements_set(tenant=tenant, actor=super_admin, modules_off=[Module.RECETAS])
        tenant_entitlements_set(tenant=tenant, actor=super_admin, modules_off=[Module.NOTAS])

        assert TenantEntitlements.objects.filter(tenant=tenant).count() == 1
        ent = entitlements_for_tenant(tenant=tenant)
        assert ent.tiene(Module.RECETAS)  # el segundo guardado reemplazó al primero
        assert not ent.tiene(Module.NOTAS)


@pytest.mark.django_db
class TestEndpointOverride:
    def test_super_admin_guarda_y_recibe_la_ficha(self, super_admin: Any) -> None:
        tenant = TenantFactory(plan=PlanFactory(modules=_PLAN_COMPLETO))
        client = APIClient()
        client.force_authenticate(user=super_admin)

        response = client.post(
            reverse("platform-clinica-entitlements", kwargs={"tenant_id": tenant.id}),
            {"modules_off": [Module.RECETAS], "notes": "Dental"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        modules = response.data["entitlements"]["modules"]
        assert Module.RECETAS not in modules
        assert Module.EXPEDIENTE in modules

    def test_sales_no_puede(self, db: Any) -> None:
        sales = UserFactory(is_platform_staff=True, platform_role="sales")
        tenant = TenantFactory(plan=PlanFactory(modules=_PLAN_COMPLETO))
        client = APIClient()
        client.force_authenticate(user=sales)

        response = client.post(
            reverse("platform-clinica-entitlements", kwargs={"tenant_id": tenant.id}),
            {"modules_off": [Module.RECETAS]},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_la_ficha_muestra_consumo_vs_limite(self, super_admin: Any) -> None:
        """El super-admin ve usuarios 1/3 para detectar upsell."""
        tenant = TenantFactory(plan=PlanFactory(modules=_PLAN_COMPLETO, max_usuarios=3))
        from tests.factories import TenantMembershipFactory
        TenantMembershipFactory(tenant=tenant, role="owner")
        client = APIClient()
        client.force_authenticate(user=super_admin)

        response = client.get(
            reverse("platform-clinica-detail", kwargs={"tenant_id": tenant.id})
        )

        usuarios = response.data["entitlements"]["usuarios"]
        assert usuarios["actual"] == 1
        assert usuarios["limite"] == 3
