"""
Tests de los derechos efectivos por clínica (apps/tenancy/entitlements.py).

Este selector es la ÚNICA fuente de verdad del gating: lo leen tanto el backend
(que bloquea) como el endpoint que alimenta al frontend (que oculta). Si se
equivoca, el usuario ve un botón que al presionarlo da 403 — o peor, una clínica
pierde funciones que sí pagó.

Patrón: AAA. factory_boy. Fixtures: db.
"""

import pytest

from apps.core.modules import Module
from apps.tenancy.entitlements import entitlements_for_tenant
from apps.tenancy.models import TenantEntitlements
from tests.factories import PlanFactory, TenantFactory

_CLINICO = [Module.AGENDA, Module.EXPEDIENTE, Module.RECETAS, Module.NOTAS]


@pytest.mark.django_db
class TestResolucionDesdeElPlan:
    """Sin ajustes, los derechos son exactamente los del plan."""

    def test_modulos_y_limites_del_plan(self) -> None:
        plan = PlanFactory(
            modules=_CLINICO, max_sucursales=1, max_consultorios=3, max_usuarios=5
        )
        tenant = TenantFactory(plan=plan)

        ent = entitlements_for_tenant(tenant=tenant)

        assert ent.modules == frozenset(_CLINICO)
        assert ent.max_sucursales == 1
        assert ent.max_consultorios == 3
        assert ent.max_usuarios == 5
        assert ent.plan_slug == plan.slug

    def test_limite_nulo_es_ilimitado(self) -> None:
        tenant = TenantFactory(plan=PlanFactory(modules=_CLINICO, max_usuarios=None))

        assert entitlements_for_tenant(tenant=tenant).max_usuarios is None

    def test_clinica_sin_plan_no_tiene_modulos(self) -> None:
        """Sin suscripción no hay derechos. Por eso la migración asignó Legacy full."""
        ent = entitlements_for_tenant(tenant=TenantFactory(sin_plan=True))

        assert ent.modules == frozenset()
        assert ent.plan_slug == ""

    def test_descarta_modulos_que_ya_no_existen_en_el_codigo(self) -> None:
        """Un módulo retirado del código no debe seguir dando acceso.

        `tiene()` respondería True para algo que ya no tiene implementación.
        """
        tenant = TenantFactory(plan=PlanFactory(modules=[Module.AGENDA, "modulo_fantasma"]))

        ent = entitlements_for_tenant(tenant=tenant)

        assert ent.modules == frozenset({Module.AGENDA})


@pytest.mark.django_db
class TestOverridesPorClinica:
    """Los ajustes a la medida son los que hacen vendible el producto."""

    def test_modules_on_concede_un_modulo_extra(self) -> None:
        """El caso 'el plan no lo trae pero a este cliente se lo damos'."""
        tenant = TenantFactory(plan=PlanFactory(modules=_CLINICO))
        TenantEntitlements.objects.create(
            tenant=tenant, modules_on=[Module.COBRANZA], notes="Cortesía"
        )

        ent = entitlements_for_tenant(tenant=tenant)

        assert ent.tiene(Module.COBRANZA)
        assert ent.tiene(Module.AGENDA)

    def test_modules_off_revoca_un_modulo_del_plan(self) -> None:
        """El caso dental: expediente sí, recetas no, aunque el plan las traiga."""
        tenant = TenantFactory(plan=PlanFactory(modules=_CLINICO))
        TenantEntitlements.objects.create(
            tenant=tenant, modules_off=[Module.RECETAS], notes="Clínica dental"
        )

        ent = entitlements_for_tenant(tenant=tenant)

        assert not ent.tiene(Module.RECETAS)
        assert ent.tiene(Module.EXPEDIENTE)

    def test_off_gana_sobre_on(self) -> None:
        """Si un módulo está en ambas listas, se revoca: lo restrictivo manda."""
        tenant = TenantFactory(plan=PlanFactory(modules=_CLINICO))
        TenantEntitlements.objects.create(
            tenant=tenant,
            modules_on=[Module.COBRANZA],
            modules_off=[Module.COBRANZA],
            notes="Contradictorio a propósito",
        )

        assert not entitlements_for_tenant(tenant=tenant).tiene(Module.COBRANZA)

    def test_override_de_limite_sustituye_al_del_plan(self) -> None:
        tenant = TenantFactory(plan=PlanFactory(modules=_CLINICO, max_usuarios=3))
        TenantEntitlements.objects.create(
            tenant=tenant, max_usuarios=10, notes="Ampliación vendida"
        )

        assert entitlements_for_tenant(tenant=tenant).max_usuarios == 10

    def test_override_nulo_deja_pasar_el_del_plan(self) -> None:
        """NULL significa 'sin override', no 'ilimitado'."""
        tenant = TenantFactory(plan=PlanFactory(modules=_CLINICO, max_usuarios=3))
        TenantEntitlements.objects.create(
            tenant=tenant, max_sucursales=5, notes="Solo sedes"
        )

        ent = entitlements_for_tenant(tenant=tenant)

        assert ent.max_sucursales == 5
        assert ent.max_usuarios == 3


@pytest.mark.django_db
class TestDerivados:
    """Roles y modo sede única salen de los derechos, no se configuran aparte."""

    def test_roles_se_derivan_de_los_modulos(self) -> None:
        tenant = TenantFactory(plan=PlanFactory(modules=_CLINICO))

        roles = entitlements_for_tenant(tenant=tenant).roles

        assert "finance" not in roles
        assert {"owner", "doctor", "nurse", "reception"} <= roles

    def test_sede_unica_cuando_el_limite_es_uno(self) -> None:
        tenant = TenantFactory(plan=PlanFactory(modules=_CLINICO, max_sucursales=1))

        assert entitlements_for_tenant(tenant=tenant).sede_unica is True

    def test_no_es_sede_unica_si_es_ilimitado(self) -> None:
        tenant = TenantFactory(plan=PlanFactory(modules=_CLINICO, max_sucursales=None))

        assert entitlements_for_tenant(tenant=tenant).sede_unica is False


@pytest.mark.django_db
class TestRolesPorPlan:
    """El plan ofrece un subconjunto de roles (decisión comercial), además del
    filtro por módulos. Básico no ofrece admin ni solo-lectura aunque no
    dependan de ningún módulo."""

    def test_plan_sin_restriccion_ofrece_todos_los_derivables(self) -> None:
        """roles=[] significa 'sin restricción extra': valen todos los del módulo."""
        tenant = TenantFactory(plan=PlanFactory(modules=_CLINICO, roles=[]))

        roles = entitlements_for_tenant(tenant=tenant).roles

        # owner/admin/readonly no dependen de módulos → están; finance no (sin cobranza).
        assert {"owner", "admin", "readonly", "doctor", "nurse", "reception"} == roles

    def test_plan_restringido_recorta_la_lista(self) -> None:
        """Básico: solo dueño, médico, enfermería, recepción."""
        tenant = TenantFactory(plan=PlanFactory(
            modules=_CLINICO, roles=["owner", "doctor", "nurse", "reception"],
        ))

        roles = entitlements_for_tenant(tenant=tenant).roles

        assert roles == {"owner", "doctor", "nurse", "reception"}
        assert "admin" not in roles
        assert "readonly" not in roles

    def test_no_ofrece_un_rol_sin_su_modulo_aunque_el_plan_lo_liste(self) -> None:
        """La restricción del plan se INTERSECA con los módulos, no los ignora.

        Si el plan lista 'finance' pero no tiene cobranza, finance NO se ofrece:
        sería un usuario que no puede trabajar.
        """
        tenant = TenantFactory(plan=PlanFactory(
            modules=_CLINICO, roles=["owner", "finance"],
        ))

        roles = entitlements_for_tenant(tenant=tenant).roles

        assert "finance" not in roles
        assert roles == {"owner"}
