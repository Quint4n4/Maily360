"""
Tests de los guards de entitlements (apps/core/entitlement_guards.py).

Sin estos guards, ocultar módulos en el frontend es cosmético: cualquiera con la
URL entra. Aquí se prueba que el backend bloquea de verdad, y que los límites del
plan frenan las altas.

Patrón: AAA. factory_boy. Fixtures: db.
"""

import pytest
from django.core.exceptions import ValidationError
from rest_framework.exceptions import NotFound

from apps.clinica.services import sucursal_create
from apps.core.entitlement_guards import assert_within_limit, require_module
from apps.core.modules import Module
from apps.core.tenant_context import clear_current_tenant, set_current_tenant
from apps.personal.services import consultorio_create
from apps.tenancy.services import member_create
from tests.factories import (
    ConsultorioFactory,
    PlanFactory,
    SucursalFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

_CLINICO = [Module.AGENDA, Module.EXPEDIENTE, Module.RECETAS, Module.NOTAS]


@pytest.fixture(autouse=True)
def _limpiar_tenant():
    """El contexto de tenant es thread-local: dejarlo sucio contamina otros tests."""
    yield
    clear_current_tenant()


@pytest.mark.django_db
class TestRequireModule:
    def test_pasa_si_la_clinica_tiene_el_modulo(self) -> None:
        tenant = TenantFactory(plan=PlanFactory(modules=_CLINICO))

        require_module(tenant=tenant, module=Module.AGENDA)  # no lanza

    def test_bloquea_si_no_lo_tiene(self) -> None:
        """404, no 403: un módulo no contratado no debe delatar que existe."""
        tenant = TenantFactory(plan=PlanFactory(modules=_CLINICO))

        with pytest.raises(NotFound):
            require_module(tenant=tenant, module=Module.COBRANZA)

    def test_clinica_sin_plan_no_tiene_nada(self) -> None:
        tenant = TenantFactory(sin_plan=True)

        with pytest.raises(NotFound):
            require_module(tenant=tenant, module=Module.AGENDA)


@pytest.mark.django_db
class TestAssertWithinLimit:
    def test_deja_pasar_si_hay_cupo(self) -> None:
        tenant = TenantFactory(plan=PlanFactory(modules=_CLINICO, max_usuarios=3))

        assert_within_limit(tenant=tenant, limite="max_usuarios", actual=2)

    def test_bloquea_al_llegar_al_tope(self) -> None:
        tenant = TenantFactory(plan=PlanFactory(modules=_CLINICO, max_usuarios=3))

        with pytest.raises(ValidationError):
            assert_within_limit(tenant=tenant, limite="max_usuarios", actual=3)

    def test_limite_nulo_nunca_bloquea(self) -> None:
        tenant = TenantFactory(plan=PlanFactory(modules=_CLINICO, max_usuarios=None))

        assert_within_limit(tenant=tenant, limite="max_usuarios", actual=9999)

    def test_el_mensaje_dice_el_tope_y_que_hacer(self) -> None:
        """Un error accionable evita una llamada a soporte."""
        tenant = TenantFactory(plan=PlanFactory(modules=_CLINICO, max_usuarios=3))

        with pytest.raises(ValidationError) as exc:
            assert_within_limit(tenant=tenant, limite="max_usuarios", actual=3)

        mensaje = str(exc.value)
        assert "3" in mensaje
        assert "soporte" in mensaje


@pytest.mark.django_db
class TestLimiteDeSucursales:
    """max_sucursales = 1 ES el modo sede única: esta guarda lo hace cumplir."""

    def test_no_se_puede_crear_la_segunda_sede(self) -> None:
        tenant = TenantFactory(plan=PlanFactory(modules=_CLINICO, max_sucursales=1))
        user = UserFactory()
        set_current_tenant(tenant)
        SucursalFactory(tenant=tenant, name="Principal")

        with pytest.raises(ValidationError, match="sucursales"):
            sucursal_create(tenant=tenant, user=user, name="Segunda")

    def test_con_limite_mayor_si_se_puede(self) -> None:
        tenant = TenantFactory(plan=PlanFactory(modules=_CLINICO, max_sucursales=3))
        user = UserFactory()
        set_current_tenant(tenant)
        SucursalFactory(tenant=tenant, name="Principal")

        sucursal = sucursal_create(tenant=tenant, user=user, name="Segunda")

        assert sucursal.pk is not None


@pytest.mark.django_db
class TestLimiteDeConsultorios:
    def test_bloquea_al_llegar_al_tope(self) -> None:
        tenant = TenantFactory(plan=PlanFactory(modules=_CLINICO, max_consultorios=1))
        user = UserFactory()
        set_current_tenant(tenant)
        ConsultorioFactory(tenant=tenant, name="Consultorio 1")

        with pytest.raises(ValidationError, match="consultorios"):
            consultorio_create(tenant=tenant, user=user, name="Consultorio 2")


@pytest.mark.django_db
class TestRolesYUsuariosDelPlan:
    """Los roles se derivan del plan; el límite de usuarios frena las altas."""

    def _owner(self, tenant):
        membership = TenantMembershipFactory(tenant=tenant, role="owner")
        set_current_tenant(tenant)
        return membership.user

    def test_rechaza_un_rol_que_el_plan_no_incluye(self) -> None:
        """Sin cobranza, un usuario 'finanzas' no podría hacer su trabajo."""
        tenant = TenantFactory(plan=PlanFactory(modules=_CLINICO, max_usuarios=None))
        actor = self._owner(tenant)

        with pytest.raises(ValidationError, match="rol"):
            member_create(
                tenant=tenant, actor=actor, email="caja@test.mx",
                first_name="Ana", last_name="López",
                password="Contrasena-Segura-123", role="finance",
            )

    def test_acepta_un_rol_que_el_plan_si_incluye(self) -> None:
        tenant = TenantFactory(plan=PlanFactory(modules=_CLINICO, max_usuarios=None))
        actor = self._owner(tenant)

        membership = member_create(
            tenant=tenant, actor=actor, email="doc@test.mx",
            first_name="Luis", last_name="Ruiz",
            password="Contrasena-Segura-123", role="doctor",
        )

        assert membership.pk is not None

    def test_bloquea_al_llegar_al_tope_de_usuarios(self) -> None:
        tenant = TenantFactory(plan=PlanFactory(modules=_CLINICO, max_usuarios=1))
        actor = self._owner(tenant)  # ya es 1 usuario

        with pytest.raises(ValidationError, match="usuarios"):
            member_create(
                tenant=tenant, actor=actor, email="otro@test.mx",
                first_name="Otro", last_name="Usuario",
                password="Contrasena-Segura-123", role="doctor",
            )

    def test_bajar_de_plan_no_borra_a_nadie(self) -> None:
        """Estar por encima del tope bloquea altas, pero conserva lo existente.

        Una clínica que baja de plan no debe perder usuarios: eso sería destruir
        datos del cliente por una decisión comercial.
        """
        from apps.tenancy.models import TenantMembership

        tenant = TenantFactory(plan=PlanFactory(modules=_CLINICO, max_usuarios=None))
        actor = self._owner(tenant)
        member_create(
            tenant=tenant, actor=actor, email="dos@test.mx",
            first_name="Dos", last_name="Usuario",
            password="Contrasena-Segura-123", role="doctor",
        )

        # Baja de plan: ahora el tope es 1 y ya hay 2.
        tenant.subscription.plan = PlanFactory(modules=_CLINICO, max_usuarios=1)
        tenant.subscription.save()

        assert TenantMembership.objects.filter(tenant=tenant, is_active=True).count() == 2
        with pytest.raises(ValidationError):
            member_create(
                tenant=tenant, actor=actor, email="tres@test.mx",
                first_name="Tres", last_name="Usuario",
                password="Contrasena-Segura-123", role="doctor",
            )
