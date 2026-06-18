"""
Validadores de schema para los bloques JSON del expediente clínico (A2 y A4).

Implementa la decisión D-EC-7 (whitelist de claves y tipos) y D-EC-8
(respuestas precargadas / choices para campos que lo permiten).

Cada bloque JSON acepta SOLO las claves declaradas en su schema; cualquier
clave no reconocida provoca un ValidationError. Los tipos se validan de forma
explícita (str, int, etc.) para evitar que el cliente inyecte tipos inesperados.

API pública (A2):
    validate_heredo_familiares(data)        — Antecedentes heredo-familiares.
    validate_personales_patologicos(data)   — Antecedentes personales patológicos.
    validate_no_patologicos(data)           — Antecedentes no patológicos (núcleo).
    validate_habitos_alimenticios(data)     — Hábitos alimenticios (versión corta).
    validate_gineco_obstetricos(data)       — Antecedentes gineco-obstétricos.
    validate_exploracion_fisica_basal(data) — Exploración física basal por sistema.

API pública (A4):
    validate_exploracion_evolucion(data)    — Exploración física de la nota de evolución.
                                              Mismos sistemas que la basal; estados de
                                              semáforo: no_evaluado, normal, observacion,
                                              alterado.
"""

from typing import Any

from rest_framework import serializers

# ---------------------------------------------------------------------------
# Choices internos (D-EC-8: respuestas precargadas)
# ---------------------------------------------------------------------------

_VIVIENDA_CHOICES: frozenset[str] = frozenset(
    {"propia", "rentada", "prestada", "otro"}
)

_EXPLORACION_ESTADO_CHOICES: frozenset[str] = frozenset(
    {"sin_alteraciones", "con_alteraciones"}
)

# Estados del semáforo de la exploración de la nota de evolución (A4).
# Más granular que la basal: agrega no_evaluado (default), normal y observacion.
_EXPLORACION_EVOLUCION_ESTADO_CHOICES: frozenset[str] = frozenset(
    {"no_evaluado", "normal", "observacion", "alterado"}
)

_EXPLORACION_SISTEMAS: frozenset[str] = frozenset(
    {
        "cerebro",
        "sistema_nervioso",
        "ocular",
        "endocrino",
        "corazon",
        "circulatorio",
        "respiratorio",
        "hepatico",
        "pancreas",
        "renal",
        "gastrointestinal",
        "osteoarticular",
        "tendomuscular",
        "reproductor",
        "inmunologico",
        "extremidades",
        "piel_tegumentos",
        "otros",
    }
)

# ---------------------------------------------------------------------------
# Helper privado
# ---------------------------------------------------------------------------

# M4: longitud máxima por valor de string en bloques JSON de historia clínica.
# 2000 caracteres ≈ una página clínica densa; suficiente para cualquier campo.
_STR_BLOCK_MAX_LEN: int = 2000


def _validate_string_block(
    data: dict[str, Any],
    allowed_keys: frozenset[str],
    block_name: str,
) -> dict[str, Any]:
    """Valida un bloque JSON donde todas las claves son strings opcionales.

    Rechaza:
      - Claves no declaradas en `allowed_keys`.
      - Valores que no sean str o None.
      - Valores string que superen _STR_BLOCK_MAX_LEN caracteres (M4 anti-DoS).

    Args:
        data:         Diccionario del bloque JSON recibido del cliente.
        allowed_keys: Conjunto de claves permitidas (whitelist).
        block_name:   Nombre del bloque para mensajes de error.

    Returns:
        El mismo dict si es válido.

    Raises:
        serializers.ValidationError: si hay claves desconocidas, tipos inválidos
            o strings que superan el límite de longitud.
    """
    unknown = set(data.keys()) - allowed_keys
    if unknown:
        raise serializers.ValidationError(
            {
                block_name: (
                    f"Claves no permitidas: {', '.join(sorted(unknown))}. "
                    f"Claves válidas: {', '.join(sorted(allowed_keys))}."
                )
            }
        )

    for key, value in data.items():
        if value is not None and not isinstance(value, str):
            raise serializers.ValidationError(
                {block_name: f"El campo '{key}' debe ser un string o null."}
            )
        if isinstance(value, str) and len(value) > _STR_BLOCK_MAX_LEN:
            raise serializers.ValidationError(
                {
                    block_name: (
                        f"El campo '{key}' no puede superar los "
                        f"{_STR_BLOCK_MAX_LEN} caracteres."
                    )
                }
            )

    return data


# ---------------------------------------------------------------------------
# Claves permitidas por bloque (constantes)
# ---------------------------------------------------------------------------

_AHF_STRING_KEYS: frozenset[str] = frozenset(
    {
        "diabetes",
        "hipertension_arterial",
        "cardiopatias",
        "hepatopatias",
        "urologicos",
        "neurologicos",
        "respiratorias",
        "cancer",
        "alergicas",
        "metabolicas",
        "sanguineas",
        "articulares",
        "inmunologicas",
        "malformaciones",
        "dermatologicas",
        "otros",
    }
)
_AHF_ALL_KEYS: frozenset[str] = _AHF_STRING_KEYS | frozenset({"numero_hermanos"})

_APP_KEYS: frozenset[str] = frozenset(
    {
        "enfermedades_infancia",
        "diabetes",
        "hipertension",
        "respiratorias",
        "oftalmico",
        "cardiovasculares",
        "neurologicos",
        "gastrointestinales",
        "hepatopatias",
        "metabolicas",
        "urologicos",
        "circulatorio",
        "traumaticas",
        "articulares",
        "dermatologicas",
        "quirurgicos",
        "transfusionales",
        "vectores",
        "autoinmunes",
        "emocionales",
        "adicciones",
        "hospitalizaciones_previas",
        "pesticidas",
        "dx_cancer",
        "otros",
    }
)

_APNP_STRING_KEYS: frozenset[str] = frozenset(
    {
        "servicios_basicos",
        "actividad_fisica",
        "tabaquismo",
        "alcoholismo",
        "otras_toxicomanias",
        "inmunizaciones",
        "ultima_desparasitacion",
        "otros",
    }
)
_APNP_ALL_KEYS: frozenset[str] = _APNP_STRING_KEYS | frozenset({"casa_habitacion"})

_HABITOS_STRING_KEYS: frozenset[str] = frozenset(
    {
        "dieta_especial",
        "intolerancias_alimentarias",
        "consumo_agua_litros",
        "suplementos",
    }
)
_HABITOS_ALL_KEYS: frozenset[str] = _HABITOS_STRING_KEYS | frozenset(
    {"numero_comidas_dia"}
)

_AGO_KEYS: frozenset[str] = frozenset(
    {
        "menarca",
        "ritmo_menstrual",
        "alteraciones",
        "fum",
        "ivsa",
        "numero_parejas",
        "gestas",
        "abortos",
        "partos",
        "cesareas",
        "fup",
        "metodo_planificacion",
        "citologia_vaginal",
        "colposcopia",
        "usg_pelvico",
        "mastografia",
        "usg_mamas",
        "menopausia_climaterio",
        "tratamientos_hormonales",
    }
)

# ---------------------------------------------------------------------------
# Validadores públicos
# ---------------------------------------------------------------------------


def validate_heredo_familiares(data: dict[str, Any]) -> dict[str, Any]:
    """Valida el bloque de antecedentes heredo-familiares (AHF).

    Claves de string (default 'Negado'): diabetes, hipertension_arterial,
    cardiopatias, hepatopatias, urologicos, neurologicos, respiratorias,
    cancer, alergicas, metabolicas, sanguineas, articulares, inmunologicas,
    malformaciones, dermatologicas, otros.

    Clave especial: numero_hermanos (int >= 0, opcional).

    Args:
        data: Diccionario recibido del cliente para este bloque.

    Returns:
        El mismo dict si es válido.

    Raises:
        serializers.ValidationError: si hay claves desconocidas, tipos inválidos
            o numero_hermanos negativo.
    """
    if not isinstance(data, dict):
        raise serializers.ValidationError(
            {"heredo_familiares": "Debe ser un objeto JSON."}
        )

    unknown = set(data.keys()) - _AHF_ALL_KEYS
    if unknown:
        raise serializers.ValidationError(
            {
                "heredo_familiares": (
                    f"Claves no permitidas: {', '.join(sorted(unknown))}. "
                    f"Claves válidas: {', '.join(sorted(_AHF_ALL_KEYS))}."
                )
            }
        )

    # Validar numero_hermanos (int >= 0).
    if "numero_hermanos" in data:
        val = data["numero_hermanos"]
        if val is not None:
            if not isinstance(val, int) or isinstance(val, bool):
                raise serializers.ValidationError(
                    {
                        "heredo_familiares": (
                            "El campo 'numero_hermanos' debe ser un entero >= 0."
                        )
                    }
                )
            if val < 0:
                raise serializers.ValidationError(
                    {"heredo_familiares": "El campo 'numero_hermanos' debe ser >= 0."}
                )

    # Validar las claves de string (tipo y longitud máxima — M4 anti-DoS).
    for key in _AHF_STRING_KEYS:
        if key in data:
            value = data[key]
            if value is not None and not isinstance(value, str):
                raise serializers.ValidationError(
                    {
                        "heredo_familiares": (
                            f"El campo '{key}' debe ser un string o null."
                        )
                    }
                )
            if isinstance(value, str) and len(value) > _STR_BLOCK_MAX_LEN:
                raise serializers.ValidationError(
                    {
                        "heredo_familiares": (
                            f"El campo '{key}' no puede superar los "
                            f"{_STR_BLOCK_MAX_LEN} caracteres."
                        )
                    }
                )

    return data


def validate_personales_patologicos(data: dict[str, Any]) -> dict[str, Any]:
    """Valida el bloque de antecedentes personales patológicos (APP).

    Todas las claves son strings opcionales (default 'Negado').
    No incluye 'alergias': la fuente de verdad es el modelo Allergy de A1.

    Args:
        data: Diccionario recibido del cliente para este bloque.

    Returns:
        El mismo dict si es válido.

    Raises:
        serializers.ValidationError: si hay claves desconocidas o tipos inválidos.
    """
    if not isinstance(data, dict):
        raise serializers.ValidationError(
            {"personales_patologicos": "Debe ser un objeto JSON."}
        )
    return _validate_string_block(data, _APP_KEYS, "personales_patologicos")


def validate_no_patologicos(data: dict[str, Any]) -> dict[str, Any]:
    """Valida el bloque de antecedentes no patológicos (APNP) — núcleo universal.

    Lo dental se mueve a la extensión Odontología (plan §3.2).

    casa_habitacion: choice en {propia, rentada, prestada, otro} o null/vacío.
    El resto de claves: strings opcionales.

    Args:
        data: Diccionario recibido del cliente para este bloque.

    Returns:
        El mismo dict si es válido.

    Raises:
        serializers.ValidationError: si hay claves desconocidas, tipos inválidos
            o casa_habitacion fuera de los choices.
    """
    if not isinstance(data, dict):
        raise serializers.ValidationError(
            {"no_patologicos": "Debe ser un objeto JSON."}
        )

    unknown = set(data.keys()) - _APNP_ALL_KEYS
    if unknown:
        raise serializers.ValidationError(
            {
                "no_patologicos": (
                    f"Claves no permitidas: {', '.join(sorted(unknown))}. "
                    f"Claves válidas: {', '.join(sorted(_APNP_ALL_KEYS))}."
                )
            }
        )

    # Validar casa_habitacion (choice).
    if "casa_habitacion" in data:
        val = data["casa_habitacion"]
        if val is not None and val != "" and val not in _VIVIENDA_CHOICES:
            raise serializers.ValidationError(
                {
                    "no_patologicos": (
                        f"Valor inválido para 'casa_habitacion': '{val}'. "
                        f"Debe ser uno de: {', '.join(sorted(_VIVIENDA_CHOICES))}."
                    )
                }
            )

    # Validar las demás claves como strings (tipo y longitud máxima — M4 anti-DoS).
    for key in _APNP_STRING_KEYS:
        if key in data:
            value = data[key]
            if value is not None and not isinstance(value, str):
                raise serializers.ValidationError(
                    {"no_patologicos": f"El campo '{key}' debe ser un string o null."}
                )
            if isinstance(value, str) and len(value) > _STR_BLOCK_MAX_LEN:
                raise serializers.ValidationError(
                    {
                        "no_patologicos": (
                            f"El campo '{key}' no puede superar los "
                            f"{_STR_BLOCK_MAX_LEN} caracteres."
                        )
                    }
                )

    return data


def validate_habitos_alimenticios(data: dict[str, Any]) -> dict[str, Any]:
    """Valida el bloque de hábitos alimenticios — versión corta del núcleo.

    La encuesta de 32 alimentos va a la extensión Nutrición.

    numero_comidas_dia: int >= 0 o null/ausente.
    El resto: strings opcionales.

    Args:
        data: Diccionario recibido del cliente para este bloque.

    Returns:
        El mismo dict si es válido.

    Raises:
        serializers.ValidationError: si hay claves desconocidas, tipos inválidos
            o numero_comidas_dia negativo.
    """
    if not isinstance(data, dict):
        raise serializers.ValidationError(
            {"habitos_alimenticios": "Debe ser un objeto JSON."}
        )

    unknown = set(data.keys()) - _HABITOS_ALL_KEYS
    if unknown:
        raise serializers.ValidationError(
            {
                "habitos_alimenticios": (
                    f"Claves no permitidas: {', '.join(sorted(unknown))}. "
                    f"Claves válidas: {', '.join(sorted(_HABITOS_ALL_KEYS))}."
                )
            }
        )

    # Validar numero_comidas_dia (int >= 0).
    if "numero_comidas_dia" in data:
        val = data["numero_comidas_dia"]
        if val is not None:
            if not isinstance(val, int) or isinstance(val, bool):
                raise serializers.ValidationError(
                    {
                        "habitos_alimenticios": (
                            "El campo 'numero_comidas_dia' debe ser un entero >= 0."
                        )
                    }
                )
            if val < 0:
                raise serializers.ValidationError(
                    {
                        "habitos_alimenticios": (
                            "El campo 'numero_comidas_dia' debe ser >= 0."
                        )
                    }
                )

    # Validar las demás claves como strings (tipo y longitud máxima — M4 anti-DoS).
    for key in _HABITOS_STRING_KEYS:
        if key in data:
            value = data[key]
            if value is not None and not isinstance(value, str):
                raise serializers.ValidationError(
                    {
                        "habitos_alimenticios": (
                            f"El campo '{key}' debe ser un string o null."
                        )
                    }
                )
            if isinstance(value, str) and len(value) > _STR_BLOCK_MAX_LEN:
                raise serializers.ValidationError(
                    {
                        "habitos_alimenticios": (
                            f"El campo '{key}' no puede superar los "
                            f"{_STR_BLOCK_MAX_LEN} caracteres."
                        )
                    }
                )

    return data


def validate_gineco_obstetricos(data: dict[str, Any]) -> dict[str, Any]:
    """Valida el bloque de antecedentes gineco-obstétricos (AGO).

    NOTA: la validación condicional por sexo (solo aplica a pacientes F) se hace
    en el serializer, que tiene acceso al paciente. Este validador solo valida
    estructura y tipos del bloque.

    Todas las claves son strings opcionales.

    Args:
        data: Diccionario recibido del cliente para este bloque.

    Returns:
        El mismo dict si es válido.

    Raises:
        serializers.ValidationError: si hay claves desconocidas o tipos inválidos.
    """
    if not isinstance(data, dict):
        raise serializers.ValidationError(
            {"gineco_obstetricos": "Debe ser un objeto JSON."}
        )
    return _validate_string_block(data, _AGO_KEYS, "gineco_obstetricos")


def validate_exploracion_fisica_basal(data: dict[str, Any]) -> dict[str, Any]:
    """Valida el bloque de exploración física basal por sistema.

    Estructura esperada:
        {
            "<sistema>": {
                "estado": "sin_alteraciones" | "con_alteraciones",
                "detalle": "<str>"
            }
        }

    Sistemas permitidos: cerebro, sistema_nervioso, ocular, endocrino, corazon,
    circulatorio, respiratorio, hepatico, pancreas, renal, gastrointestinal,
    osteoarticular, tendomuscular, reproductor, inmunologico, extremidades,
    piel_tegumentos, otros.

    Estado: solo "sin_alteraciones" (default) o "con_alteraciones".
    Detalle: string opcional (puede ser "" o null).

    Args:
        data: Diccionario recibido del cliente para este bloque.

    Returns:
        El mismo dict si es válido.

    Raises:
        serializers.ValidationError: si hay sistemas fuera de la whitelist,
            estados fuera de choices, o tipos inválidos.
    """
    if not isinstance(data, dict):
        raise serializers.ValidationError(
            {"exploracion_fisica_basal": "Debe ser un objeto JSON."}
        )

    unknown_sistemas = set(data.keys()) - _EXPLORACION_SISTEMAS
    if unknown_sistemas:
        raise serializers.ValidationError(
            {
                "exploracion_fisica_basal": (
                    f"Sistemas no permitidos: {', '.join(sorted(unknown_sistemas))}. "
                    f"Sistemas válidos: {', '.join(sorted(_EXPLORACION_SISTEMAS))}."
                )
            }
        )

    for sistema, valor in data.items():
        if not isinstance(valor, dict):
            raise serializers.ValidationError(
                {
                    "exploracion_fisica_basal": (
                        f"El sistema '{sistema}' debe ser un objeto con "
                        "'estado' y/o 'detalle'."
                    )
                }
            )

        # Claves del objeto de sistema: solo 'estado' y 'detalle'.
        unknown_keys = set(valor.keys()) - {"estado", "detalle"}
        if unknown_keys:
            raise serializers.ValidationError(
                {
                    "exploracion_fisica_basal": (
                        f"Claves no permitidas en el sistema '{sistema}': "
                        f"{', '.join(sorted(unknown_keys))}. "
                        "Solo se permiten 'estado' y 'detalle'."
                    )
                }
            )

        # Validar estado (choice).
        if "estado" in valor:
            estado = valor["estado"]
            if estado not in _EXPLORACION_ESTADO_CHOICES:
                raise serializers.ValidationError(
                    {
                        "exploracion_fisica_basal": (
                            f"Estado inválido para el sistema '{sistema}': '{estado}'. "
                            f"Debe ser uno de: "
                            f"{', '.join(sorted(_EXPLORACION_ESTADO_CHOICES))}."
                        )
                    }
                )

        # Validar detalle (string o null, max 2000 chars — MEDIO-1 anti-DoS).
        if "detalle" in valor:
            detalle = valor["detalle"]
            if detalle is not None and not isinstance(detalle, str):
                raise serializers.ValidationError(
                    {
                        "exploracion_fisica_basal": (
                            f"El campo 'detalle' del sistema '{sistema}' "
                            "debe ser un string o null."
                        )
                    }
                )
            if isinstance(detalle, str) and len(detalle) > 2000:
                raise serializers.ValidationError(
                    {
                        "exploracion_fisica_basal": (
                            f"El campo 'detalle' del sistema '{sistema}' "
                            "no puede superar los 2000 caracteres."
                        )
                    }
                )

    return data


# ---------------------------------------------------------------------------
# validate_exploracion_evolucion — Exploración física de nota de evolución (A4)
# ---------------------------------------------------------------------------


def validate_exploracion_evolucion(data: dict[str, Any]) -> dict[str, Any]:
    """Valida el bloque de exploración física de la nota de evolución (A4).

    Mismos sistemas que la exploración basal de MedicalHistory.
    Los estados usan el semáforo clínico del legacy (4 valores):
        no_evaluado (default), normal, observacion, alterado.

    Estructura esperada:
        {
            "<sistema>": {
                "estado": "no_evaluado" | "normal" | "observacion" | "alterado",
                "detalle": "<str>"
            }
        }

    Sistemas permitidos: cerebro, sistema_nervioso, ocular, endocrino, corazon,
    circulatorio, respiratorio, hepatico, pancreas, renal, gastrointestinal,
    osteoarticular, tendomuscular, reproductor, inmunologico, extremidades,
    piel_tegumentos, otros.

    Args:
        data: Diccionario recibido del cliente para este bloque.

    Returns:
        El mismo dict si es válido.

    Raises:
        serializers.ValidationError: si hay sistemas fuera de la whitelist,
            estados fuera de los 4 choices del semáforo, o tipos inválidos.
    """
    if not isinstance(data, dict):
        raise serializers.ValidationError(
            {"exploracion_fisica": "Debe ser un objeto JSON."}
        )

    unknown_sistemas = set(data.keys()) - _EXPLORACION_SISTEMAS
    if unknown_sistemas:
        raise serializers.ValidationError(
            {
                "exploracion_fisica": (
                    f"Sistemas no permitidos: {', '.join(sorted(unknown_sistemas))}. "
                    f"Sistemas válidos: {', '.join(sorted(_EXPLORACION_SISTEMAS))}."
                )
            }
        )

    for sistema, valor in data.items():
        if not isinstance(valor, dict):
            raise serializers.ValidationError(
                {
                    "exploracion_fisica": (
                        f"El sistema '{sistema}' debe ser un objeto con "
                        "'estado' y/o 'detalle'."
                    )
                }
            )

        # Claves del objeto de sistema: solo 'estado' y 'detalle'.
        unknown_keys = set(valor.keys()) - {"estado", "detalle"}
        if unknown_keys:
            raise serializers.ValidationError(
                {
                    "exploracion_fisica": (
                        f"Claves no permitidas en el sistema '{sistema}': "
                        f"{', '.join(sorted(unknown_keys))}. "
                        "Solo se permiten 'estado' y 'detalle'."
                    )
                }
            )

        # Validar estado (semáforo de 4 valores — D-EC-8).
        if "estado" in valor:
            estado = valor["estado"]
            if estado not in _EXPLORACION_EVOLUCION_ESTADO_CHOICES:
                raise serializers.ValidationError(
                    {
                        "exploracion_fisica": (
                            f"Estado inválido para el sistema '{sistema}': '{estado}'. "
                            f"Debe ser uno de: "
                            f"{', '.join(sorted(_EXPLORACION_EVOLUCION_ESTADO_CHOICES))}."
                        )
                    }
                )

        # Validar detalle (string o null, max 2000 chars — MEDIO-1 anti-DoS).
        if "detalle" in valor:
            detalle = valor["detalle"]
            if detalle is not None and not isinstance(detalle, str):
                raise serializers.ValidationError(
                    {
                        "exploracion_fisica": (
                            f"El campo 'detalle' del sistema '{sistema}' "
                            "debe ser un string o null."
                        )
                    }
                )
            if isinstance(detalle, str) and len(detalle) > 2000:
                raise serializers.ValidationError(
                    {
                        "exploracion_fisica": (
                            f"El campo 'detalle' del sistema '{sistema}' "
                            "no puede superar los 2000 caracteres."
                        )
                    }
                )

    return data
