"""
Tests de los validadores de formato compartidos (apps/core/validators.py).

Cédula profesional: la validación previa solo exigía `isdigit()`, así que "1"
pasaba. Como emitir una receta EXIGE cédula (NOM-004 / Art. 83 LGS) y esta se
imprime en el PDF, una captura basura producía un documento clínico inválido.

El objetivo NO es certificar que la cédula existe —eso solo lo puede decir el
Registro Nacional de Profesionistas de la SEP— sino rechazar lo obviamente falso.

Patrón: AAA. No tocan BD.
"""

import pytest
from rest_framework import serializers

from apps.core.validators import (
    validar_cedula_profesional,
    validar_cedulas_adicionales,
)


class TestValidarCedulaProfesional:
    """Formato de la cédula profesional."""

    @pytest.mark.parametrize(
        "valor",
        ["12345", "123456", "1234567", "12345678", "1234567890"],
    )
    def test_acepta_cedulas_con_longitud_valida(self, valor: str) -> None:
        """De 5 a 10 dígitos: cubre las vigentes (7-8) y las históricas."""
        assert validar_cedula_profesional(valor) == valor

    @pytest.mark.parametrize(
        "valor",
        ["1", "12", "123", "1234", "12345678901"],
    )
    def test_rechaza_longitudes_invalidas(self, valor: str) -> None:
        """Capturas obviamente falsas por muy cortas o muy largas."""
        with pytest.raises(serializers.ValidationError):
            validar_cedula_profesional(valor)

    @pytest.mark.parametrize(
        "valor",
        ["abcdefg", "123-4567", "1234 567", "AB123456", "1234567.", "١٢٣٤٥٦٧"],
    )
    def test_rechaza_caracteres_no_numericos(self, valor: str) -> None:
        """La cédula mexicana es numérica; nada de letras, guiones ni espacios.

        Incluye dígitos arábigo-índicos (١٢٣): tanto `str.isdigit()` como el `\\d`
        de Python los aceptan, y se imprimirían tal cual en la receta. Por eso el
        patrón usa el rango explícito [0-9].
        """
        with pytest.raises(serializers.ValidationError):
            validar_cedula_profesional(valor)

    def test_vacio_es_valido(self) -> None:
        """La cédula es opcional: sin ella no se puede recetar, pero sí existir."""
        assert validar_cedula_profesional("") == ""
        assert validar_cedula_profesional("   ") == ""

    def test_limpia_espacios_alrededor(self) -> None:
        """Un copiar-pegar con espacios no debe fallar ni guardarse sucio."""
        assert validar_cedula_profesional("  1234567  ") == "1234567"


class TestValidarCedulasAdicionales:
    """Lista de cédulas de especialidad separadas por coma."""

    def test_acepta_lista_valida_y_normaliza(self) -> None:
        """Se guardan con separación uniforme, sin importar cómo se capturaron."""
        assert validar_cedulas_adicionales("1234567,  7654321") == "1234567, 7654321"

    def test_rechaza_si_alguna_es_invalida(self) -> None:
        """Una sola cédula mala invalida la lista, y el error dice cuál."""
        with pytest.raises(serializers.ValidationError, match="99"):
            validar_cedulas_adicionales("1234567, 99")

    def test_vacio_es_valido(self) -> None:
        assert validar_cedulas_adicionales("") == ""

    def test_ignora_comas_sobrantes(self) -> None:
        """'1234567,,' es un descuido de captura, no un error que valga bloquear."""
        assert validar_cedulas_adicionales("1234567,,") == "1234567"
