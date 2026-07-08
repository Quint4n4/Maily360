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
    vital_signs_latest       — la toma más reciente del paciente (para snapshot en receta).
    vital_signs_series       — datos de series temporales para gráficas (una sola query,
                               arma las series en Python).

Funciones públicas (A4):
    evolution_note_get       — una nota de evolución por id (con aislamiento de tenant).
    evolution_note_list      — notas de evolución de un paciente, orden -created_at.
    addendum_list            — addenda de una nota de evolución.
    diagnosis_get            — un diagnóstico por id (con aislamiento de tenant).
    diagnosis_list           — diagnósticos de un paciente (filtrado por status opcional).
    evolution_nursing_instructions_for_patient — notas del paciente que tienen indicaciones
                               de enfermería no vacías, ordenadas por -created_at.

Funciones públicas (Libro Clínico — Fase 1):
    book_build               — arma el libro clínico del paciente (portada + HC viva +
                               capítulos paginados). Solo lectura; sin efectos secundarios.
                               Evita N+1 con prefetch_related sobre la página de evoluciones.

Funciones públicas (Libro Clínico — Fase 3):
    book_build_all           — igual que book_build pero sin paginación: trae todos los
                               capítulos (o solo el último / ninguno según el modo).
                               Usado por el generador de PDF para los 3 modos (D-LIB-5).
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from django.core.paginator import InvalidPage, Paginator
from django.db.models import Prefetch, QuerySet

from apps.expediente.models import (
    Addendum,
    Allergy,
    ClinicalSummary,
    Diagnosis,
    DiagnosisStatus,
    EvolutionImage,
    EvolutionNote,
    MedicalHistory,
    MedicalHistoryQuestion,
    TreatmentPlan,
    TreatmentSession,
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


def medical_history_get_for_patient(*, patient: Patient) -> MedicalHistory | None:
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
    return MedicalHistory.objects.select_related("patient").filter(patient=patient).first()


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
    since: date | None = None,
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
    qs = base_qs.order_by("-measured_at")[:_SERIES_MAX_RECORDS].values(
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

    # Inicializar las series con listas vacías.
    series: dict[str, list[dict[str, Any]]] = {field: [] for field in _SERIES_FIELDS}
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
        Addendum.objects.select_related("author").filter(evolution=evolution).order_by("created_at")
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
    return Diagnosis.objects.select_related("patient", "evolution").get(id=diagnosis_id)


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
    qs: QuerySet[Diagnosis] = Diagnosis.objects.select_related("evolution").filter(patient=patient)
    if only_active:
        qs = qs.filter(status=DiagnosisStatus.ACTIVO)
    return qs.order_by("-created_at")


# ---------------------------------------------------------------------------
# Indicaciones de enfermería (A4 — sub-vista especializada)
# ---------------------------------------------------------------------------


def vital_signs_latest(*, patient: Patient) -> VitalSignsRecord | None:
    """Retorna la toma de signos vitales más reciente del paciente, o None.

    Usa el TenantManager (filtra por tenant del contexto activo).
    Usada por `prescription_create` para congelar el snapshot de signos en la
    receta (DR-7: la receta es autocontenida e inmutable).

    El orden es por `measured_at` descendente; toma el primero.
    Si el paciente no tiene tomas, devuelve None (el campo vitals_snapshot de
    Prescription quedará null).

    Args:
        patient: Paciente del que se obtiene la última toma.

    Returns:
        Instancia de VitalSignsRecord más reciente, o None.
    """
    return VitalSignsRecord.objects.filter(patient=patient).order_by("-measured_at").first()


def evolution_nursing_instructions_for_patient(
    *,
    patient: Patient,
    limit: int = 20,
) -> QuerySet[EvolutionNote]:
    """Retorna las notas de evolución del paciente que tienen indicaciones de enfermería.

    Solo incluye las notas con `indicaciones_enfermeria` no vacías (excluye cadenas
    en blanco y valores nulos). Ordena por -created_at (más reciente primero).
    Limita al número indicado por `limit` (default=20) para evitar cargas masivas.

    Usa el TenantManager (filtra por tenant del contexto activo + excluye
    soft-deleted). Filtra explícitamente por patient como defensa en profundidad
    (anti-IDOR adicional al TenantManager).

    Precarga `doctor` y `doctor__membership` para evitar N+1 al serializar
    el nombre del médico autor.

    Args:
        patient: Paciente cuyas notas con indicaciones se recuperan.
        limit:   Máximo de registros devueltos (default=20). Protege contra
                 historiales extensos que carguen toda la tabla en memoria.

    Returns:
        QuerySet[EvolutionNote] con indicaciones_enfermeria no vacías,
        ordenado por -created_at, limitado a `limit` registros.
    """
    return (
        EvolutionNote.objects.select_related(
            "doctor",
            "doctor__membership",
        )
        .filter(
            patient=patient,
            indicaciones_enfermeria__isnull=False,
        )
        .exclude(indicaciones_enfermeria="")
        .order_by("-created_at")[:limit]
    )


# ---------------------------------------------------------------------------
# EvolutionImage selectors
# ---------------------------------------------------------------------------


def evolution_image_get(*, image_id: uuid.UUID) -> EvolutionImage:
    """Retorna una imagen de evolución por su UUID.

    Usa el TenantManager (filtra por tenant del contexto activo + excluye
    soft-deleted). Lanza EvolutionImage.DoesNotExist si no existe o no pertenece
    al tenant activo. Las vistas capturan DoesNotExist y devuelven 404 (anti-IDOR).

    Args:
        image_id: UUID de la imagen a recuperar.

    Returns:
        Instancia de EvolutionImage con evolution precargada.

    Raises:
        EvolutionImage.DoesNotExist: si la imagen no existe en el tenant activo.
    """
    return EvolutionImage.objects.select_related("evolution", "created_by").get(id=image_id)


def evolution_images_list(*, evolution: EvolutionNote) -> "QuerySet[EvolutionImage]":
    """Retorna el QuerySet de imágenes activas de una nota de evolución.

    Filtra por tenant del contexto activo (TenantManager, excluye soft-deleted)
    y por evolution en defensa en profundidad. Ordena por created_at (cronológico).

    Args:
        evolution: Nota de evolución cuyas imágenes se recuperan.

    Returns:
        QuerySet[EvolutionImage] ordenado por created_at.
    """
    return (
        EvolutionImage.objects.select_related("created_by")
        .filter(evolution=evolution)
        .order_by("created_at")
    )


# ---------------------------------------------------------------------------
# Libro Clínico — selector de armado (Fase 1)
# ---------------------------------------------------------------------------

# Tamaño de página por defecto para los capítulos del libro.
BOOK_DEFAULT_PAGE_SIZE: int = 10
# Límite máximo para proteger contra page_size abusivos (DoS).
BOOK_MAX_PAGE_SIZE: int = 50


class PatientBook:
    """Resultado del selector book_build.

    Contenedor inmutable con todos los datos del libro clínico del paciente
    necesarios para serializar la respuesta JSON.

    Atributos:
        patient          Instancia de Patient (portada).
        clinic_settings  Instancia de ClinicSettings o None (portada).
        medical_history  Instancia de MedicalHistory o None (HC viva).
        allergies        QuerySet[Allergy] de alergias vigentes.
        capitulos_count  Número total de evoluciones del paciente.
        capitulos        Lista de EvolutionNote de la página actual.
                         Cada nota tiene precargados:
                           - vital_signs (VitalSignsRecord)
                           - images (EvolutionImage)
                           - prescriptions (Prescription) con items
                           - addenda
                           - diagnoses
                           - doctor + doctor__membership
        page             Número de página actual (1-based).
        total_pages      Número total de páginas.
        page_size        Tamaño de página usado.
    """

    __slots__ = (
        "patient",
        "clinic_settings",
        "medical_history",
        "allergies",
        "capitulos_count",
        "capitulos",
        "page",
        "total_pages",
        "page_size",
    )

    def __init__(
        self,
        *,
        patient: Patient,
        clinic_settings: Any,
        medical_history: MedicalHistory | None,
        allergies: QuerySet[Allergy],
        capitulos_count: int,
        capitulos: list[EvolutionNote],
        page: int,
        total_pages: int,
        page_size: int,
    ) -> None:
        self.patient = patient
        self.clinic_settings = clinic_settings
        self.medical_history = medical_history
        self.allergies = allergies
        self.capitulos_count = capitulos_count
        self.capitulos = capitulos
        self.page = page
        self.total_pages = total_pages
        self.page_size = page_size


def book_build(
    *,
    patient: Patient,
    page: int = 1,
    page_size: int = BOOK_DEFAULT_PAGE_SIZE,
) -> PatientBook:
    """Arma el libro clínico del paciente sin crear ni duplicar datos.

    El libro es una VISTA AGREGADA: reúsa los selectors/modelos existentes
    sin copiar ni desnormalizar información. Todas las secciones se componen
    a partir de tablas ya existentes.

    DECISIONES TOMADAS:

    Diagnósticos por capítulo:
        Diagnosis tiene FK `evolution` nullable (EvolutionNote). Cuando un
        diagnóstico está vinculado a una evolución, se muestra en el capítulo
        de esa evolución (via el prefetch "diagnoses" sobre EvolutionNote).
        Los diagnósticos SIN FK de evolución (creados directamente desde la
        vista de diagnósticos) son diagnósticos del paciente, no de una nota;
        NO se incluyen en capítulos individuales para evitar duplicación — el
        frontend puede mostrarlos en una sección aparte del libro si lo requiere
        (pendiente Fase 2). Este enfoque respeta la realidad del modelo: si el
        médico usó la FK, el diagnóstico pertenece a esa evolución.

    Recetas por capítulo:
        Prescription tiene FK `evolution_note` nullable. Se usa el related_name
        "prescriptions" (definido en Prescription.evolution_note) para precargar
        las recetas vinculadas a cada evolución con prefetch_related. Solo
        se devuelve un resumen ligero (id, folio, status, items_resumen) —
        nunca el PDF ni el contenido completo de la receta.

    Orden:
        Las evoluciones se ordenan por -created_at (más reciente primero, D-LIB-3).

    Anti-N+1:
        Se hace un único queryset de la página de evoluciones con
        prefetch_related para todas las relaciones anidadas (signos vitales,
        imágenes, addenda, diagnósticos, recetas+items). La paginación ocurre
        en Python via Paginator sobre el QuerySet evaluado una sola vez.

    Args:
        patient:   Instancia de Patient del tenant activo.
        page:      Número de página (1-based). Clamped al rango válido.
        page_size: Número de evoluciones por página (max BOOK_MAX_PAGE_SIZE).

    Returns:
        PatientBook con todos los datos listos para serialización.
    """
    from django.db.models import Prefetch  # noqa: PLC0415

    from apps.clinica.models import DoctorCredential  # noqa: PLC0415
    from apps.clinica.selectors import clinic_settings_get  # noqa: PLC0415
    from apps.recetas.models import Prescription  # noqa: PLC0415

    # --- Cota de page_size (anti-DoS) ---
    page_size = min(max(1, page_size), BOOK_MAX_PAGE_SIZE)

    # --- Portada: datos de la clínica ---
    clinic_settings = clinic_settings_get(tenant_id=patient.tenant_id)

    # --- Historia Clínica viva (siempre versión actual — D-LIB-1) ---
    medical_history = medical_history_get_for_patient(patient=patient)

    # --- Alergias vigentes (para el libro siempre activas) ---
    allergies = allergy_list(patient=patient, only_active=True)

    # --- Capítulos: evoluciones paginadas (más reciente primero — D-LIB-3) ---
    # Un solo queryset con TODOS los prefetch necesarios para la página.
    # Anti-N+1: select_related para FKs directas (doctor, vital_signs) y
    # prefetch_related para relaciones inversas (addenda, diagnoses, images, prescriptions).
    # Prescription se precarga via related_name "prescriptions" con sus items en
    # una sola query adicional por página (Prefetch explícito con queryset personalizado).
    evolutions_qs = (
        EvolutionNote.objects.filter(patient=patient)
        .select_related(
            "doctor",
            "doctor__membership",
            "vital_signs",
        )
        .prefetch_related(
            "addenda",
            "addenda__author",
            "diagnoses",
            "images",
            Prefetch(
                "prescriptions",
                queryset=Prescription.objects.filter(deleted_at__isnull=True).prefetch_related(
                    "items"
                ),
            ),
            # Anti-N+1: precarga las cédulas validadas de cada médico autor.
            # Sin esto, BookDoctorSerializer.get_cedulas_validadas dispara una
            # query de credenciales por capítulo. Se filtra aquí (mismo criterio
            # que el serializer) y se expone via to_attr="cedulas_validadas_cache".
            Prefetch(
                "doctor__credentials",
                queryset=DoctorCredential.objects.filter(
                    validation_status="validada",
                    is_active=True,
                    deleted_at__isnull=True,
                ),
                to_attr="cedulas_validadas_cache",
            ),
        )
        .order_by("-created_at")
    )

    # --- Paginación ---
    paginator = Paginator(evolutions_qs, page_size)
    capitulos_count: int = paginator.count
    total_pages: int = paginator.num_pages

    # Clampear la página al rango válido (evitar InvalidPage).
    page = max(1, min(page, total_pages if total_pages > 0 else 1))

    try:
        page_obj = paginator.page(page)
    except InvalidPage:
        page_obj = paginator.page(1)

    capitulos: list[EvolutionNote] = list(page_obj.object_list)

    return PatientBook(
        patient=patient,
        clinic_settings=clinic_settings,
        medical_history=medical_history,
        allergies=allergies,
        capitulos_count=capitulos_count,
        capitulos=capitulos,
        page=page,
        total_pages=total_pages,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# MedicalHistoryQuestion selectors (Fase 2)
# ---------------------------------------------------------------------------


def medical_history_question_get(*, question_id: uuid.UUID) -> MedicalHistoryQuestion:
    """Retorna una pregunta extra de HC por su UUID.

    Usa el TenantManager (filtra por tenant del contexto activo + excluye
    soft-deleted). Lanza MedicalHistoryQuestion.DoesNotExist si no existe
    o no pertenece al tenant activo. Las vistas capturan DoesNotExist y
    devuelven 404 (anti-IDOR).

    Incluye preguntas tanto activas como inactivas (para operaciones admin).

    Args:
        question_id: UUID de la pregunta a recuperar.

    Returns:
        Instancia de MedicalHistoryQuestion del tenant activo.

    Raises:
        MedicalHistoryQuestion.DoesNotExist: si no existe en el tenant activo.
    """
    return MedicalHistoryQuestion.objects.get(id=question_id)


def medical_history_questions_list(*, only_active: bool = True) -> QuerySet[MedicalHistoryQuestion]:
    """Retorna las preguntas extra de HC del tenant activo.

    Usa el TenantManager (filtra por tenant del contexto activo + excluye
    soft-deleted). Ordena por [order, id] (Meta.ordering).

    Args:
        only_active: Si True (default), solo las preguntas activas (is_active=True).
                     Si False, retorna todas (activas + inactivas).

    Returns:
        QuerySet[MedicalHistoryQuestion] ordenado por [order, id].
    """
    qs: QuerySet[MedicalHistoryQuestion] = MedicalHistoryQuestion.objects.all()
    if only_active:
        qs = qs.filter(is_active=True)
    return qs


def book_build_all(
    *,
    patient: Patient,
    modo: str = "completo",
) -> "PatientBook":
    """Arma el libro clínico completo para PDF (sin paginación).

    A diferencia de `book_build`, este selector trae TODOS los capítulos
    en una sola operación, optimizado para la generación del PDF donde no
    hay paginación de usuario. Evita N+1 con el mismo patrón de prefetch.

    Modos (D-LIB-5):
        completo — portada + HC viva + TODOS los capítulos (más reciente primero).
        hc       — portada + HC viva + alergias (sin capítulos).
        ultimo   — portada + el ÚLTIMO capítulo + sus recetas.

    Args:
        patient: Instancia de Patient del tenant activo.
        modo:    "completo" | "hc" | "ultimo". Cualquier valor inválido se trata
                 como "completo" (fallback defensivo).

    Returns:
        PatientBook con capitulos ya resueltos (lista Python, no QuerySet paginado).
        Para modo "hc": capitulos = [].
        Para modo "ultimo": capitulos = [la nota más reciente] o [] si no hay notas.
        capitulos_count refleja el total real del paciente en todos los modos.
        page=1, total_pages=1, page_size=capitulos_count (convención para PDF).
    """
    from django.db.models import Prefetch  # noqa: PLC0415

    from apps.clinica.models import DoctorCredential  # noqa: PLC0415
    from apps.clinica.selectors import clinic_settings_get  # noqa: PLC0415
    from apps.recetas.models import Prescription  # noqa: PLC0415

    # Validar modo; fallback defensivo.
    _VALID_MODOS = {"completo", "hc", "ultimo"}
    if modo not in _VALID_MODOS:
        modo = "completo"

    # --- Portada ---
    clinic_settings = clinic_settings_get(tenant_id=patient.tenant_id)

    # --- Historia Clínica viva (siempre versión actual — D-LIB-1) ---
    medical_history = medical_history_get_for_patient(patient=patient)

    # --- Alergias vigentes ---
    allergies = allergy_list(patient=patient, only_active=True)

    # --- Queryset base de evoluciones (con todos los prefetch) ---
    _evolutions_base = (
        EvolutionNote.objects.filter(patient=patient)
        .select_related(
            "doctor",
            "doctor__membership",
            "vital_signs",
        )
        .prefetch_related(
            "addenda",
            "addenda__author",
            "diagnoses",
            "images",
            Prefetch(
                "prescriptions",
                queryset=Prescription.objects.filter(deleted_at__isnull=True).prefetch_related(
                    "items"
                ),
            ),
            # Anti-N+1: precarga las cédulas validadas de cada médico autor.
            # Sin esto, BookDoctorSerializer.get_cedulas_validadas dispara una
            # query de credenciales por capítulo. Se filtra aquí (mismo criterio
            # que el serializer) y se expone via to_attr="cedulas_validadas_cache".
            Prefetch(
                "doctor__credentials",
                queryset=DoctorCredential.objects.filter(
                    validation_status="validada",
                    is_active=True,
                    deleted_at__isnull=True,
                ),
                to_attr="cedulas_validadas_cache",
            ),
        )
        .order_by("-created_at")
    )

    # --- Contar total de capítulos (siempre el real del paciente) ---
    capitulos_count: int = EvolutionNote.objects.filter(patient=patient).count()

    # --- Seleccionar capítulos según el modo ---
    if modo == "hc":
        # Solo portada + HC + alergias; ningún capítulo.
        capitulos: list[EvolutionNote] = []
    elif modo == "ultimo":
        # Solo el capítulo más reciente (primero en -created_at).
        capitulos = list(_evolutions_base[:1])
    else:
        # completo: todos los capítulos, más reciente primero.
        # IMPORTANTE: evaluar el QuerySet a lista aquí para materializar
        # los prefetch. No se usa Paginator — el PDF no pagina.
        capitulos = list(_evolutions_base)

    page_size_pdf = len(capitulos) if capitulos else 1

    return PatientBook(
        patient=patient,
        clinic_settings=clinic_settings,
        medical_history=medical_history,
        allergies=allergies,
        capitulos_count=capitulos_count,
        capitulos=capitulos,
        page=1,
        total_pages=1,
        page_size=page_size_pdf,
    )


# ---------------------------------------------------------------------------
# ClinicalSummary selectors — Resumen Clínico por consulta
# ---------------------------------------------------------------------------


def clinical_summary_get(*, summary_id: uuid.UUID) -> ClinicalSummary:
    """Retorna un resumen clínico por su UUID.

    Usa el TenantManager (filtra por tenant del contexto activo).
    Lanza ClinicalSummary.DoesNotExist si no existe o no pertenece al tenant
    activo. Las vistas deben capturar DoesNotExist y devolver 404 (anti-IDOR).

    Precarga patient, evolution (con doctor) y doctor (con membership) para
    que el generador de PDF y el serializer de salida no disparen N+1.

    Args:
        summary_id: UUID del resumen clínico.

    Returns:
        Instancia de ClinicalSummary con relaciones precargadas.

    Raises:
        ClinicalSummary.DoesNotExist: si el resumen no existe en el tenant activo.
    """
    return ClinicalSummary.objects.select_related(
        "patient",
        "evolution",
        "evolution__appointment",
        "evolution__vital_signs",
        "doctor",
        "doctor__membership",
        "doctor__membership__user",
    ).get(id=summary_id)


def clinical_summary_list(*, patient: Patient) -> QuerySet[ClinicalSummary]:
    """Retorna el QuerySet de resúmenes clínicos del paciente, orden -created_at.

    Filtra por tenant del contexto activo (TenantManager) y por patient en
    defensa en profundidad. Precarga doctor/membership/user para el nombre
    del médico en el listado, sin N+1.

    Args:
        patient: Paciente cuyos resúmenes se recuperan.

    Returns:
        QuerySet[ClinicalSummary] ordenado por -created_at (Meta.ordering).
    """
    return (
        ClinicalSummary.objects.select_related(
            "doctor", "doctor__membership", "doctor__membership__user"
        )
        .filter(patient=patient)
        .order_by("-created_at")
    )


# ---------------------------------------------------------------------------
# TreatmentPlan selectors — Calendarización de tratamientos (Fase 1)
# ---------------------------------------------------------------------------


def treatment_plan_get(*, plan_id: uuid.UUID) -> TreatmentPlan:
    """Retorna un esquema de calendarización de tratamientos por su UUID.

    Usa el TenantManager (filtra por tenant del contexto activo). Lanza
    TreatmentPlan.DoesNotExist si no existe o no pertenece al tenant activo.
    Las vistas capturan DoesNotExist y devuelven 404 (anti-IDOR).

    Precarga patient, doctor (con membership), consultorio, e
    items→sessions→appointment (con doctor/consultorio de la cita) e
    items→service_concept para que el detalle, el PDF y el cálculo del
    total no disparen N+1 (Fase 4 — Calendarización: cada sesión puede
    traer una cita real ligada).

    Args:
        plan_id: UUID del esquema de tratamientos.

    Returns:
        Instancia de TreatmentPlan con relaciones precargadas.

    Raises:
        TreatmentPlan.DoesNotExist: si el esquema no existe en el tenant activo.
    """
    sessions_qs = TreatmentSession.objects.select_related(
        "appointment",
        "appointment__doctor",
        "appointment__doctor__membership",
        "appointment__doctor__membership__user",
        "appointment__consultorio",
    ).order_by("number", "id")

    return (
        TreatmentPlan.objects.select_related(
            "patient",
            "doctor",
            "doctor__membership",
            "doctor__membership__user",
            "consultorio",
        )
        .prefetch_related(
            Prefetch("items__sessions", queryset=sessions_qs),
            "items__service_concept",
        )
        .get(id=plan_id)
    )


def treatment_session_get(*, session_id: uuid.UUID) -> TreatmentSession:
    """Retorna una TreatmentSession por su UUID (Fase 4 — Calendarización).

    Usa el TenantManager (filtra por tenant del contexto activo — la sesión
    hereda de TenantAwareModel, tiene su propio `tenant_id`). Lanza
    TreatmentSession.DoesNotExist si no existe o no pertenece al tenant
    activo. La vista captura DoesNotExist y devuelve 404 (anti-IDOR).

    Precarga item→plan→patient (para resolver el paciente al agendar) y la
    cita ligada (con doctor/consultorio) para que el endpoint de agendar/
    desagendar no dispare N+1.

    Args:
        session_id: UUID de la sesión de tratamiento.

    Returns:
        Instancia de TreatmentSession con relaciones precargadas.

    Raises:
        TreatmentSession.DoesNotExist: si la sesión no existe en el tenant activo.
    """
    return TreatmentSession.objects.select_related(
        "item",
        "item__plan",
        "item__plan__patient",
        "appointment",
        "appointment__doctor",
        "appointment__doctor__membership",
        "appointment__doctor__membership__user",
        "appointment__consultorio",
    ).get(id=session_id)


def treatment_plan_list(*, patient: Patient) -> QuerySet[TreatmentPlan]:
    """Retorna el QuerySet de esquemas de tratamientos del paciente, orden -created_at.

    Filtra por tenant del contexto activo (TenantManager) y por patient en
    defensa en profundidad. Precarga doctor/membership/user e items→sessions
    para que el listado (total, sessions_count, applied_count) no dispare N+1.

    Args:
        patient: Paciente cuyos esquemas se recuperan.

    Returns:
        QuerySet[TreatmentPlan] ordenado por -created_at (Meta.ordering).
    """
    return (
        TreatmentPlan.objects.select_related(
            "doctor", "doctor__membership", "doctor__membership__user"
        )
        .prefetch_related("items__sessions")
        .filter(patient=patient)
        .order_by("-created_at")
    )
