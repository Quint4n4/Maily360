"""
Tests del comando `seed_planes`.

Lo importante que se prueba aquí no es que cree planes, sino que NO reescriba
los que ya existen: cambiar los módulos de un plan vivo le quita funciones a las
clínicas suscritas. Restringir a un cliente que ya paga tiene que ser una
decisión deliberada (--actualizar), nunca el efecto de correr un comando.

Patrón: AAA. Fixtures: db.
"""

from io import StringIO

import pytest
from django.core.management import call_command

from apps.core.modules import Module, dependencias_faltantes, modulos_desconocidos
from apps.tenancy.models import Plan


def _seed(**kwargs: bool) -> str:
    out = StringIO()
    call_command("seed_planes", stdout=out, **kwargs)
    return out.getvalue()


@pytest.mark.django_db
class TestSeedPlanes:
    def test_crea_los_cinco_planes(self) -> None:
        _seed()

        slugs = set(Plan.objects.values_list("slug", flat=True))
        assert {"solo", "basico", "pro", "premium", "enterprise"} <= slugs

    def test_es_idempotente(self) -> None:
        """Correrlo dos veces no duplica ni cambia nada."""
        _seed()
        antes = Plan.objects.count()

        salida = _seed()

        assert Plan.objects.count() == antes
        assert "0 creados" in salida

    def test_no_reescribe_planes_con_modulos(self) -> None:
        """Un plan vivo con módulos propios NO se toca sin --actualizar.

        Es la protección central: correr el seed no debe quitarle funciones a
        una clínica que ya está operando. (El plan 'pro' ya existe desde
        0005_seed_plans, así que se ajusta el existente en vez de crearlo.)
        """
        Plan.objects.filter(slug="pro").update(
            name="Pro (negociado)",
            modules=[Module.AGENDA, Module.EXPEDIENTE, Module.CFDI, Module.COBRANZA],
            max_usuarios=99,
        )

        _seed()

        pro = Plan.objects.get(slug="pro")
        assert pro.name == "Pro (negociado)"
        assert Module.CFDI in pro.modules
        assert pro.max_usuarios == 99

    def test_completa_plan_sin_modulos(self) -> None:
        """Un plan sin módulos está sin estrenar: completarlo no le quita nada a nadie.

        Es el caso de una instalación nueva, donde 0005_seed_plans deja
        Básico/Pro/Premium creados pero sin módulos.
        """
        Plan.objects.filter(slug="pro").update(modules=[], max_usuarios=99)

        _seed()

        pro = Plan.objects.get(slug="pro")
        assert Module.COBRANZA in pro.modules
        assert pro.max_usuarios is None

    def test_actualizar_si_reescribe(self) -> None:
        """Con la bandera explícita sí se aplica el empaquetado estándar."""
        Plan.objects.filter(slug="pro").update(
            name="Pro viejo", modules=[Module.AGENDA], max_usuarios=99
        )

        _seed(actualizar=True)

        pro = Plan.objects.get(slug="pro")
        assert pro.name == "Pro"
        assert Module.COBRANZA in pro.modules
        assert pro.max_usuarios is None


@pytest.mark.django_db
class TestCoherenciaDelCatalogo:
    """Los planes sembrados deben ser vendibles, no solo guardables."""

    def test_ningun_plan_tiene_dependencias_sin_cubrir(self) -> None:
        _seed()

        for plan in Plan.objects.all():
            assert dependencias_faltantes(plan.modules) == {}, plan.slug

    def test_ningun_plan_referencia_modulos_inexistentes(self) -> None:
        _seed()

        for plan in Plan.objects.all():
            assert modulos_desconocidos(plan.modules) == set(), plan.slug

    def test_todos_los_planes_sirven_para_dar_consulta(self) -> None:
        """Lo clínico completo desde el primer plan: es la promesa del empaquetado."""
        _seed()

        clinico = {Module.AGENDA, Module.EXPEDIENTE, Module.RECETAS}
        for plan in Plan.objects.all():
            assert clinico <= set(plan.modules), plan.slug

    def test_solo_nace_apagado(self) -> None:
        """Se construye pero no se ofrece hasta tener casos reales que fijen el precio."""
        _seed()

        assert Plan.objects.get(slug="solo").is_active is False

    def test_cfdi_solo_desde_premium(self) -> None:
        _seed()

        assert Module.CFDI not in Plan.objects.get(slug="basico").modules
        assert Module.CFDI not in Plan.objects.get(slug="pro").modules
        assert Module.CFDI in Plan.objects.get(slug="premium").modules

    def test_calendarizacion_no_va_en_ningun_plan(self) -> None:
        """Nació de un requerimiento puntual: se concede por override, no por plan."""
        _seed()

        for plan in Plan.objects.all():
            assert Module.CALENDARIZACION not in plan.modules, plan.slug

    def test_solo_premium_y_enterprise_permiten_varias_sedes(self) -> None:
        _seed()

        assert Plan.objects.get(slug="basico").max_sucursales == 1
        assert Plan.objects.get(slug="pro").max_sucursales == 1
        assert Plan.objects.get(slug="premium").max_sucursales is None
