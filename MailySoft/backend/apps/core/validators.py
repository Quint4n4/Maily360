"""
Validadores de formato compartidos entre apps.

El backend es la AUTORIDAD de la validación. `web-soft/src/lib/validacion.ts`
replica estos patrones EXACTAMENTE para dar feedback inmediato en el formulario;
si un patrón cambia aquí, hay que sincronizarlo allá.
"""

import re

from rest_framework import serializers

# ---------------------------------------------------------------------------
# Cédula profesional (SEP)
# ---------------------------------------------------------------------------
#
# La cédula profesional mexicana es NUMÉRICA. Las vigentes traen 7 u 8 dígitos;
# las históricas pueden tener menos. Se acepta un rango de 5 a 10 para no
# rechazar cédulas antiguas legítimas — el objetivo NO es certificar que la
# cédula existe (eso solo lo puede decir el Registro Nacional de Profesionistas
# de la SEP), sino impedir capturas obviamente falsas como "1" o "123".
#
# Importa porque emitir una receta EXIGE cédula (NOM-004 / Art. 83 LGS) y se
# imprime en el PDF: un valor basura produce un documento clínico inválido.
#
# Se usa [0-9] y NO \d a propósito: en Python `\d` acepta dígitos Unicode (por
# ejemplo los arábigo-índicos ١٢٣), que se imprimirían tal cual en la receta.
# El rango explícito además coincide con el `\d` de JavaScript, que sí es solo
# ASCII, para que el espejo del frontend valide exactamente lo mismo.
CEDULA_RE = re.compile(r"^[0-9]{5,10}$")

CEDULA_MSG = "La cédula profesional debe tener entre 5 y 10 dígitos (solo números)."


def validar_cedula_profesional(value: str) -> str:
    """Valida el formato de una cédula profesional. Vacío es válido (es opcional).

    Args:
        value: Cédula capturada. Se limpia de espacios alrededor.

    Returns:
        La cédula sin espacios alrededor, o "" si venía vacía.

    Raises:
        serializers.ValidationError: si no cumple el formato.
    """
    limpia = (value or "").strip()
    if not limpia:
        return ""
    if not CEDULA_RE.match(limpia):
        raise serializers.ValidationError(CEDULA_MSG)
    return limpia


def validar_cedulas_adicionales(value: str) -> str:
    """Valida una lista de cédulas separadas por coma (especialidades).

    Args:
        value: Cédulas separadas por coma. Vacío es válido.

    Returns:
        Las cédulas normalizadas, separadas por ", ".

    Raises:
        serializers.ValidationError: si alguna no cumple el formato.
    """
    limpia = (value or "").strip()
    if not limpia:
        return ""
    partes = [p.strip() for p in limpia.split(",") if p.strip()]
    for parte in partes:
        if not CEDULA_RE.match(parte):
            raise serializers.ValidationError(
                f"Cédula adicional inválida ('{parte}'). {CEDULA_MSG}"
            )
    return ", ".join(partes)
