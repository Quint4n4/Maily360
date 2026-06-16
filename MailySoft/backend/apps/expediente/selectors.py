"""
Selectors de la app expediente (sub-fases A1, A2, A3 y A4).

Lecturas/queries: NUNCA modifican datos.
El TenantManager (objects) filtra por tenant activo + excluye soft-deleted.

Convención: keyword-only args, nombrado acción+entidad.

REGLA: toda lectura por id usa un selector; NUNCA Model.objects.get inline en la view.

Funciones públicas (A1):
    allergy_get        — una alergia por id (con validación de tenant del paciente).
    allergy_list       — alergias de un paciente (filtradas por vigencia opcional).

Funciones públicas (A2):
    medical_history_get_for_patient — HC del paciente (None si no existe aún).

Funciones públicas (A3):
    vital_signs_list         — tomas del paciente, orden -measured_at.
    vital_signs_series       — datos de series temporales para gráficas (una sola query,
                               arma las series en Python).

Funciones públicas (A4):
    evolution_note_get       — una nota de evolución por id (con aislamiento de tenant).
    evolution_note_list      — notas de evolución de un paciente, orden -created_at.
    addendum_list            — addenda de una nota de evolución.
    diagnosis_get            — un diagnóstico por id (con aislamiento de tenant).
    diagnosis_list           — diagnósticos de un paciente (filtrado por status opcional).
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from django.db.models import QuerySet

from apps.expediente.models import (
    Addendum,
    Allergy,
    Diagnosis,
    DiagnosisStatus,
    EvolutionNote,
    MedicalHistory,
    VitalSignsRecord,
)
from apps.pacientes.models import Patient


def allergy_get(*, allergy_id: uuid.UUID) -> Allergy:
    """Retorna una alergia por su UUID.

    Usa el TenantManager (filtra por tenant del contexto activo).
    Lanza Allergy.DoesNotExist si no existe o no pertenece al tenant activo.
    Las vistas deben capturar DoesNotExist y devolver 404.

    Se precarga el paciente para evitar N+1 al acceder a allergy.patient.

    Args:
        allergy_id: UUID de la alergia a recuperar.

    Returns:
        Instancia de Allergy con patient precargado.

    Raises:
        Allergy.DoesNotExist: si la alergia no existe en el tenant activo.
    """
    return Allergy.objects.select_related("patient").get(id=allergy_id)


def allergy_list(
    *,
    patient: Patient,
    only_active: bool = True,
) -> QuerySet[Allergy]:
    """Retorna el QuerySet de alergias de un paciente en el tenant activo.

    Defensa en profundidad: filtra explícitamente por patient además del
    filtrado automático del TenantManager sobre el tenant.

    Args:
        patient:     Paciente cuyas alergias se recuperan.
        only_active: Si True (default), solo las alergias vigentes (is_active=True).
                     Si False, retorna todas (vigentes + resueltas).

    Returns:
        QuerySet[Allergy] ordenado por -created_at (Meta.ordering).
    """
    qs: QuerySet[Allergy] = Allergy.objects.filter(patient=patient)
    if only_active:
        qs = qs.filter(is_active=True)
    return qs


# ---------------------------------------------------------------------------
# MedicalHistory selectors (A2)
# ---------------------------------------------------------------------------


def medical_history_get_for_patient(
    *, patient: Patient
) -> Optional[MedicalHistory]:
    """Retorna la historia clínica activa del paciente, o None si no existe aún.

    Usa el TenantManager (filtra por tenant del contexto activo + excluye
    soft-deleted). La HC es un documento único por paciente (UniqueConstraint
    parcial en el modelo).

    Se precarga el paciente para evitar N+1 en la vista (acceso a patient.sex
    para validación condicional gineco y a patient_id en el output).

    Args:
        patient: Paciente cuya HC se recupera.

    Returns:
        Instancia de MedicalHistory, o None si el paciente aún no tiene HC.
    """
    return (
        MedicalHistory.objects.select_related("patient")
        .filter(patient=patient)
        .first()
    )


# ---------------------------------------------------------------------------
# VitalSignsRecord selectors (A3)
# ---------------------------------------------------------------------------


def vital_signs_list(*, patient: Patient) -> QuerySet[VitalSignsRecord]:
    """Retorna el QuerySet de tomas de signos vitales del paciente, orden -measured_at.

    Filtra por tenant del contexto activo (TenantManager) y por patient en
    defensa en profundidad. Precarga created_by y appointment para evitar N+1.

    Args:
        patient: Paciente cuyas tomas se recuperan.

    Returns:
        QuerySet[VitalSignsRecord] ordenado por -measured_at.
    """
    return (
        VitalSignsRecord.objects.select_related("created_by", "appointment")
        .filter(patient=patient)
        .order_by("-measured_at")
    )


# Campos numéricos "planos" que se exponen como series.
_SERIES_FIELDS: tuple[str, ...] = (
    "weight_kg",
    "heart_rate",
    "resp_rate",
    "systolic",
    "diastolic",
    "temperature_c",
    "oxygen_saturation",
    "glucose",
)

# Claves de extra_params que se incluyen en las series.
_EXTRA_SERIES_KEYS: tuple[str, ...] = (
    "colesterol",
    "trigliceridos",
    "urea",
    "creatinina",
    "hemoglobina",
)


# Tope interno de registros procesados por vital_signs_series (MEDIO-3).
# Protege contra historiales enormes que carguen toda la tabla en memoria.
# 730 ≈ 2 años de tomas diarias; suficiente para gráficas de tendencia clínica.
_SERIES_MAX_RECORDS: int = 730


def vital_signs_series(
    *,
    patient: Patient,
    since: Optional[date] = None,
) -> dict[str, list[dict[str, Any]]]:
    """Datos de series temporales para gráficas de tendencia.

    Ejecuta UNA sola query con los campos necesarios y construye las series en
    Python, evitando múltiples round-trips a la BD.

    Para cada parámetro numérico (weight_kg, heart_rate, resp_rate, systolic,
    diastolic, temperature_c, oxygen_saturation, glucose, imc, más los de
    extra_params) devuelve una lista de `{measured_at: <ISO>, value: <número>}`
    en orden ascendente por measured_at. Se omiten los valores nulos.

    El IMC se calcula en Python usando los mismos valores de la query (no un
    campo almacenado — D-EC-6).

    MEDIO-3 — limitación de carga:
        - `since` filtra registros con measured_at >= since (fecha ISO).
          Permite al cliente limitar el rango temporal sin necesidad de paginar.
        - Se aplica un tope interno de _SERIES_MAX_RECORDS (730) registros por
          paciente para evitar cargar historiales completos en memoria. El tope
          selecciona los más recientes (orden descendente) y luego reordena ASC
          para la presentación en gráficas.

    Args:
        patient: Paciente cuyas series se construyen.
        since:   Fecha de inicio del rango (opcional). Filtra measured_at >= since.

    Returns:
        Dict {nombre_parametro: [{measured_at, value}, ...]} ordenado ASC.
    """
    # Una sola query: solo los campos necesarios. El tope se aplica sobre los
    # más recientes para no descartar datos históricos relevantes cuando el
    # paciente tiene > 730 tomas antiguas.
    base_qs = VitalSignsRecord.objects.filter(patient=patient)
    if since is not None:
        base_qs = base_qs.filter(measured_at__date__gte=since)

    # Aplicar tope interno: tomar los _SERIES_MAX_RECORDS más recientes.
    # Se reordena a ASC en Python para que las series queden cronológicas.
    qs = (
        base_qs.order_by("-measured_at")[: _SERIES_MAX_RECORDS]
        .values(
            "measured_at",
            "weight_kg",
            "height_m",
            "heart_rate",
            "resp_rate",
            "systolic",
            "diastolic",
            "temperature_c",
            "oxygen_saturation",
            "glucose",
            "extra_params",
        )
    )

    # Inicializar las series con listas vacías.
    series: dict[str, list[dict[str, Any]]] = {
        field: [] for field in _SERIES_FIELDS
    }
    series["imc"] = []
    for key in _EXTRA_SERIES_KEYS:
        series[key] = []

    # La query viene en DESC; convertir a lista y reordenar a ASC para que
    # las series queden en orden cronológico (requerido por las gráficas).
    rows = sorted(list(qs), key=lambda r: r["measured_at"])

    for row in rows:
        ts: str = row["measured_at"].isoformat()

        # Campos planos.
        for field in _SERIES_FIELDS:
            val = row[field]
            if val is not None:
                series[field].append({"measured_at": ts, "value": float(val)})

        # IMC derivado en Python.
        w = row["weight_kg"]
        h = row["height_m"]
        if w is not None and h is not None and h != 0:
            imc_val = Decimal(str(w)) / (Decimal(str(h)) ** 2)
            series["imc"].append(
                {"measured_at": ts, "value": float(imc_val.quantize(Decimal("0.01")))}
            )

        # Parámetros extensibles (extra_params).
        extra: dict[str, Any] = row["extra_params"] or {}
        for key in _EXTRA_SERIES_KEYS:
            val = extra.get(key)
            if val is not None:
                series[key].append({"measured_at": ts, "value": float(val)})

    return series


# ---------------------------------------------------------------------------
# EvolutionNote selectors (A4)
# ---------------------------------------------------------------------------


def evolution_note_get(*, evolution_id: uuid.UUID) -> EvolutionNote:
    """Retorna una nota de evolución por su UUID.

    Usa el TenantManager (filtra por tenant del contexto activo).
    Lanza EvolutionNote.DoesNotExist si no existe o no pertenece al tenant.
    Las vistas capturan DoesNotExist y devuelven 404 (anti-IDOR).

    Se precarga appointment, doctor (con membership) y addenda para evitar N+1.

    Args:
        evolution_id: UUID de la nota de evolución.

    Returns:
        Instancia de EvolutionNote con relaciones precargadas.

    Raises:
        EvolutionNote.DoesNotExist: si la nota no existe en el tenant activo.
    """
    return (
        EvolutionNote.objects.select_related(
            "patient",
            "appointment",
            "doctor",
            "doctor__membership",
            "vital_signs",
        )
        .prefetch_related("addenda", "diagnoses")
        .get(id=evolution_id)
    )


def evolution_note_list(*, patient: Patient) -> QuerySet[EvolutionNote]:
    """Retorna el QuerySet de notas de evolución del paciente, orden -created_at.

    Filtra por tenant del contexto activo (TenantManager) y por patient en
    defensa en profundidad. Precarga relaciones para evitar N+1.

    Args:
        patient: Paciente cuyas notas se recuperan.

    Returns:
        QuerySet[EvolutionNote] ordenado por -created_at.
    """
    return (
        EvolutionNote.objects.select_related(
            "appointment",
            "doctor",
            "doctor__membership",
            "vital_signs",
        )
        .prefetch_related("addenda", "diagnoses")
        .filter(patient=patient)
        .order_by("-created_at")
    )


# ---------------------------------------------------------------------------
# Addendum selectors (A4)
# ---------------------------------------------------------------------------


def addendum_list(*, evolution: EvolutionNote) -> QuerySet[Addendum]:
    """Retorna el QuerySet de addenda de una nota de evolución, orden created_at.

    Filtra por tenant del contexto activo (TenantManager) y por evolution.
    Se precarga author para evitar N+1.

    Args:
        evolution: Nota de evolución cuyos addenda se recuperan.

    Returns:
        QuerySet[Addendum] ordenado por created_at (orden cronológico).
    """
    return (
        Addendum.objects.select_related("author")
        .filter(evolution=evolution)
        .order_by("created_at")
    )


# ---------------------------------------------------------------------------
# Diagnosis selectors (A4)
# ---------------------------------------------------------------------------


def diagnosis_get(*, diagnosis_id: uuid.UUID) -> Diagnosis:
    """Retorna un diagnóstico por su UUID.

    Usa el TenantManager (filtra por tenant del contexto activo).
    Lanza Diagnosis.DoesNotExist si no existe o no pertenece al tenant.
    Las vistas capturan DoesNotExist y devuelven 404 (anti-IDOR).

    Se precarga patient para evitar N+1.

    Args:
        diagnosis_id: UUID del diagnóstico.

    Returns:
        Instancia de Diagnosis con patient precargado.

    Raises:
        Diagnosis.DoesNotExist: si el diagnóstico no existe en el tenant activo.
    """
    return Diagnosis.objects.select_related("patient", "evolution").get(
        id=diagnosis_id
    )


def diagnosis_list(
    *,
    patient: Patient,
    only_active: bool = False,
) -> QuerySet[Diagnosis]:
    """Retorna el QuerySet de diagnósticos del paciente.

    Filtra por tenant del contexto activo (TenantManager) y por patient.
    Se precarga evolution para evitar N+1.

    Args:
        patient:     Paciente cuyos diagnósticos se recuperan.
        only_active: Si True, solo los activos (status=activo).
                     Si False (default), devuelve todos (activos + resueltos).

    Returns:
        QuerySet[Diagnosis] ordenado por -created_at.
    """
    qs: QuerySet[Diagnosis] = Diagnosis.objects.select_related(
        "evolution"
    ).filter(patient=patient)
    if only_active:
        qs = qs.filter(status=DiagnosisStatus.ACTIVO)
    return qs.order_by("-created_at")
