"""
Tests del catálogo de módulos y sus dependencias (apps/core/modules.py).

Las dependencias duras salieron del mapa verificado contra el código
(docs/design/planes-modulos-mapa-dependencias.md). Si una cambia aquí sin
cambiar el código real, se venden planes rotos: por eso se prueban explícitas.

Patrón: AAA. No tocan BD.
"""

import pytest
from django.core.exceptions import ValidationError

from apps.core.modules import (
    ALL_MODULES,
    MODULE_GROUPS,
    Module,
    dependencias_faltantes,
    expandir_dependencias,
    modulos_desconocidos,
    roles_disponibles,
    validar_modulos,
)


class TestExpandirDependencias:
    """Encender un módulo arrastra lo que necesita."""

    def test_recordatorios_arrastra_agenda(self) -> None:
        assert expandir_dependencias({Module.RECORDATORIOS}) == {
            Module.RECORDATORIOS,
            Module.AGENDA,
        }

    def test_cotizaciones_arrastra_servicios(self) -> None:
        assert expandir_dependencias({Module.COTIZACIONES}) == {
            Module.COTIZACIONES,
            Module.SERVICIOS,
        }

    def test_cfdi_arrastra_cobranza(self) -> None:
        assert expandir_dependencias({Module.CFDI}) == {Module.CFDI, Module.COBRANZA}

    def test_calendarizacion_expande_en_cascada(self) -> None:
        """Calendarización → cotizaciones → servicios: la cascada es transitiva.

        Es el caso que justifica el algoritmo iterativo: cotizaciones no está en
        la lista original, y aun así hay que resolver SU dependencia.
        """
        assert expandir_dependencias({Module.CALENDARIZACION}) == {
            Module.CALENDARIZACION,
            Module.EXPEDIENTE,
            Module.SERVICIOS,
            Module.COTIZACIONES,
        }

    def test_modulo_sin_dependencias_no_cambia(self) -> None:
        assert expandir_dependencias({Module.NOTAS}) == {Module.NOTAS}

    def test_conjunto_vacio(self) -> None:
        assert expandir_dependencias(set()) == set()


class TestValidarModulos:
    """La validación señala el error en vez de adivinar."""

    def test_acepta_conjunto_consistente(self) -> None:
        validar_modulos([Module.AGENDA, Module.RECORDATORIOS])

    def test_rechaza_slug_desconocido(self) -> None:
        with pytest.raises(ValidationError, match="desconocidos"):
            validar_modulos(["agenda", "telepatia"])

    def test_rechaza_dependencia_faltante(self) -> None:
        """Cotizaciones sin servicios: plan roto que no debe poder guardarse."""
        with pytest.raises(ValidationError, match="requiere"):
            validar_modulos([Module.COTIZACIONES])

    def test_mensaje_nombra_lo_que_falta(self) -> None:
        """El error dice QUÉ falta, no solo que algo está mal."""
        with pytest.raises(ValidationError) as exc:
            validar_modulos([Module.CFDI])
        assert "Cobranza" in str(exc.value)

    def test_no_expande_silenciosamente(self) -> None:
        """Validar no modifica: guardar un plan incompleto debe fallar, no arreglarse solo."""
        modulos = [Module.COTIZACIONES]
        with pytest.raises(ValidationError):
            validar_modulos(modulos)
        assert modulos == [Module.COTIZACIONES]


class TestDependenciasFaltantes:
    def test_reporta_por_modulo(self) -> None:
        faltantes = dependencias_faltantes([Module.CALENDARIZACION, Module.EXPEDIENTE])
        assert faltantes[Module.CALENDARIZACION] == {
            Module.SERVICIOS,
            Module.COTIZACIONES,
        }

    def test_conjunto_consistente_no_reporta_nada(self) -> None:
        assert dependencias_faltantes(expandir_dependencias([Module.CALENDARIZACION])) == {}


class TestRolesDisponibles:
    """Los roles se derivan de los módulos: ninguno aparece sin su herramienta."""

    def test_plan_clinico_no_ofrece_finanzas(self) -> None:
        """Sin cobranza, el rol finanzas no tendría nada que administrar."""
        roles = roles_disponibles(
            [Module.AGENDA, Module.EXPEDIENTE, Module.RECETAS, Module.NOTAS]
        )
        assert "finance" not in roles
        assert {"owner", "admin", "readonly", "doctor", "nurse", "reception"} <= roles

    def test_cobranza_habilita_finanzas(self) -> None:
        assert "finance" in roles_disponibles([Module.COBRANZA])

    def test_sin_expediente_no_hay_medico_ni_enfermeria(self) -> None:
        """Enfermería existe para capturar signos; médico para el expediente."""
        roles = roles_disponibles([Module.AGENDA])
        assert "doctor" not in roles
        assert "nurse" not in roles
        assert "reception" in roles

    def test_dueno_siempre_disponible(self) -> None:
        """Sin módulos no hay clínica, pero el dueño nunca desaparece."""
        assert "owner" in roles_disponibles([])


class TestCatalogo:
    def test_no_hay_slugs_desconocidos_en_el_propio_catalogo(self) -> None:
        assert modulos_desconocidos(ALL_MODULES) == set()

    def test_dependencias_apuntan_a_modulos_reales(self) -> None:
        """Un typo en MODULE_REQUIRES rompería el gating en silencio."""
        from apps.core.modules import MODULE_REQUIRES

        for modulo, requeridos in MODULE_REQUIRES.items():
            assert modulo in ALL_MODULES
            assert not modulos_desconocidos(requeridos)

    def test_los_grupos_cubren_todo_el_catalogo(self) -> None:
        """Un módulo fuera de MODULE_GROUPS sería invisible en el super-admin."""
        agrupados = {m for _, mods in MODULE_GROUPS for m in mods}
        assert agrupados == ALL_MODULES

    def test_multisede_no_es_modulo(self) -> None:
        """Multi-sucursal se gobierna con max_sucursales, no con un flag aparte.

        Dos fuentes de verdad podrían contradecirse (flag ON con límite 1).
        """
        assert "multisede" not in ALL_MODULES
