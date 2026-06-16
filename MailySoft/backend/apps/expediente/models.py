"""
Modelos de la app expediente (sub-fases A1, A2, A3 y A4).

Allergy(TenantAwareModel)        — alergia / bandera de seguridad del paciente (A1).
MedicalHistory(TenantAwareModel) — historia clínica formal, un documento vivo por
                                   paciente (A2).
VitalSignsRecord(TenantAwareModel) — toma de signos vitales append-only (A3).
EvolutionNote(TenantAwareModel)  — nota de evolución inmutable, nace de cita ATTENDED (A4).
Addendum(TenantAwareModel)       — addendum append-only sobre una EvolutionNote (A4).
Diagnosis(TenantAwareModel)      — diagnóstico clínico, se puede resolver (A4).

Todas las entidades heredan de TenantAwareModel: UUID pk, timestamps, soft-delete,
tenant FK, created_by FK y TenantManager.

Decisiones del plan respetadas:
  D-EC-1 — evolución inmutable + addendum: EvolutionNote no se modifica; el addendum
             es append-only.
  D-EC-2 — evolución nace de cita ATTENDED: validado en service.
  D-EC-4 — HC con almacenamiento flexible: un JSONField por bloque.
  D-EC-5 — sin borrado físico: is_active=False (Allergy); Diagnosis.status=resuelto.
  D-EC-7 — validación estricta: choices y claves JSON se validan en el serializer.
  D-EC-8 — respuestas precargadas: severity/choices de bloques usan TextChoices.

Nota sobre is_active vs deleted_at en Allergy:
  - deleted_at (heredado) = borrado lógico del SISTEMA. Nunca se usa (D-EC-5).
  - is_active = bandera CLÍNICA. True = alergia vigente. False = resuelta.
"""

from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.core.models import TenantAwareModel


class Severity(models.TextChoices):
    """Severidad de la reacción alérgica (D-EC-8: respuestas precargadas)."""

    LEVE = "leve", "Leve"
    MODERADA = "moderada", "Moderada"
    SEVERA = "severa", "Severa"


class Allergy(TenantAwareModel):
    """Alergia o hipersensibilidad de un paciente.

    Funciona como **bandera de seguridad** visible en la ficha del paciente
    para todos los roles clínicos (no exponer a finanzas solo).

    Campos:
        patient     Paciente al que pertenece la alergia (indexado, mismo tenant).
        substance   Sustancia, medicamento o alergeno (ej. "Penicilina", "Látex").
        reaction    Reacción observada (ej. "Urticaria generalizada"). Opcional.
        severity    Intensidad de la reacción (leve/moderada/severa). Opcional.
        is_active   True = alergia vigente. False = resuelta (baja lógica clínica).
                    Nunca se usa DELETE físico (D-EC-5).

    Auditoría y soft-delete del sistema heredados de TenantAwareModel:
        id, created_at, updated_at, deleted_at, tenant, created_by.
    """

    patient = models.ForeignKey(
        "pacientes.Patient",
        on_delete=models.PROTECT,
        related_name="allergies",
        db_index=True,
        help_text="Paciente al que pertenece la alergia.",
    )
    substance = models.CharField(
        max_length=160,
        help_text="Sustancia o medicamento al que el paciente es alérgico.",
    )
    reaction = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Reacción observada (opcional).",
    )
    severity = models.CharField(
        max_length=10,
        choices=Severity.choices,
        blank=True,
        default="",
        help_text="Severidad de la reacción: leve, moderada o severa.",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text=(
            "True = alergia vigente (clínica). "
            "False = resuelta (baja lógica). "
            "Nunca se borra físicamente (D-EC-5)."
        ),
    )

    class Meta:
        db_table = "expediente_allergies"
        ordering = ["-created_at"]
        indexes = [
            # Listado de alergias vigentes del paciente (caso más común).
            models.Index(
                fields=["patient", "is_active"],
                name="allergy_patient_active_idx",
            ),
        ]

    def __str__(self) -> str:
        estado = "vigente" if self.is_active else "resuelta"
        return f"{self.substance} ({estado}) — paciente {self.patient_id}"


# ---------------------------------------------------------------------------
# MedicalHistory — Historia Clínica Formal (A2)
# ---------------------------------------------------------------------------


class MedicalHistory(TenantAwareModel):
    """Historia clínica formal NOM-004 de un paciente.

    Documento **vivo**: se actualiza con cada consulta. La trazabilidad de los
    cambios se obtiene de la bitácora de auditoría (AuditLog), no de versiones.
    No se borra físicamente (D-EC-5).

    Unicidad por paciente activo: UniqueConstraint parcial sobre `patient` con
    `condition=Q(deleted_at__isnull=True)`. Garantiza que solo exista una HC
    activa por paciente en la BD; si alguna vez se requiere archivar una HC y
    crear otra, se usa el deleted_at heredado (aunque no está planeado en v1).

    Bloques JSON (D-EC-4):
        Cada bloque es un JSONField validado por un schema de whitelist en el
        serializer (D-EC-7). Las claves son fijas y conocidas; el serializer
        rechaza claves no declaradas. Permite añadir campos sin migración.

    Los campos de texto del padecimiento actual se guardan como TextField para
    permitir búsqueda full-text futura y mayor legibilidad en el admin.

    REGLA DE PRIVACIDAD (igual que Allergy):
        resource_repr en AuditLog SIEMPRE es el UUID del registro, NUNCA
        contenido de los campos clínicos (NOM-024 / LFPDPPP).
    """

    patient = models.ForeignKey(
        "pacientes.Patient",
        on_delete=models.PROTECT,
        related_name="medical_histories",
        db_index=True,
        help_text="Paciente al que pertenece la historia clínica.",
    )

    # ------------------------------------------------------------------
    # Bloques JSON (D-EC-4): validados por schema en el serializer (D-EC-7)
    # ------------------------------------------------------------------

    heredo_familiares = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Antecedentes heredo-familiares (AHF). "
            "Claves del schema: numero_hermanos (int), diabetes, hipertension_arterial, "
            "cardiopatias, hepatopatias, urologicos, neurologicos, respiratorias, "
            "cancer, alergicas, metabolicas, sanguineas, articulares, inmunologicas, "
            "malformaciones, dermatologicas, otros (strings, default 'Negado')."
        ),
    )
    personales_patologicos = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Antecedentes personales patológicos (APP). "
            "NO incluye alergias (fuente de verdad: modelo Allergy). "
            "Strings con default 'Negado': enfermedades_infancia, diabetes, "
            "hipertension, respiratorias, oftalmico, cardiovasculares, neurologicos, "
            "gastrointestinales, hepatopatias, metabolicas, urologicos, circulatorio, "
            "traumaticas, articulares, dermatologicas, quirurgicos, transfusionales, "
            "vectores, autoinmunes, emocionales, adicciones, hospitalizaciones_previas, "
            "pesticidas, dx_cancer, otros."
        ),
    )
    no_patologicos = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Antecedentes personales no patológicos (APNP) — núcleo universal. "
            "Lo dental se mueve a la extensión Odontología (plan §3.2). "
            "Claves: casa_habitacion (choices), servicios_basicos, actividad_fisica, "
            "tabaquismo, alcoholismo, otras_toxicomanias, inmunizaciones, "
            "ultima_desparasitacion, otros."
        ),
    )
    habitos_alimenticios = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Hábitos alimenticios — versión corta del núcleo. "
            "La encuesta de 32 alimentos va a la extensión Nutrición. "
            "Claves: numero_comidas_dia (int), dieta_especial, intolerancias_alimentarias, "
            "consumo_agua_litros, suplementos."
        ),
    )
    gineco_obstetricos = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Antecedentes gineco-obstétricos (AGO). "
            "Solo aplica a pacientes de sexo F; el serializer rechaza contenido "
            "no vacío para sexos M/X (validación condicional por sexo). "
            "Claves: menarca, ritmo_menstrual, alteraciones, fum, ivsa, "
            "numero_parejas, gestas, abortos, partos, cesareas, fup, "
            "metodo_planificacion, citologia_vaginal, colposcopia, usg_pelvico, "
            "mastografia, usg_mamas, menopausia_climaterio, tratamientos_hormonales."
        ),
    )
    exploracion_fisica_basal = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Exploración física basal por sistema/aparato. "
            "Estructura: { 'sistema': { 'estado': <sin_alteraciones|con_alteraciones>, "
            "'detalle': <str> } }. Sistemas permitidos: cerebro, sistema_nervioso, "
            "ocular, endocrino, corazon, circulatorio, respiratorio, hepatico, "
            "pancreas, renal, gastrointestinal, osteoarticular, tendomuscular, "
            "reproductor, inmunologico, extremidades, piel_tegumentos, otros."
        ),
    )

    # ------------------------------------------------------------------
    # Campos de texto del padecimiento actual (TextField para búsqueda futura)
    # ------------------------------------------------------------------

    antecedentes_importancia = models.TextField(
        blank=True,
        default="",
        help_text="Antecedentes de importancia (texto libre).",
    )
    padecimiento_actual = models.TextField(
        blank=True,
        default="",
        help_text="Padecimiento actual del paciente (texto libre).",
    )
    tratamientos_actuales = models.TextField(
        blank=True,
        default="",
        help_text="Tratamientos actuales del paciente (texto libre).",
    )
    prioridad_analisis = models.TextField(
        blank=True,
        default="",
        help_text="Prioridades de análisis clínico (texto libre).",
    )

    class Meta:
        db_table = "expediente_medical_histories"
        ordering = ["-created_at"]
        constraints = [
            # Una sola HC activa por paciente (D-EC-5: se puede "archivar" con
            # deleted_at, pero en v1 nunca se usa; la constraint previene duplicados).
            models.UniqueConstraint(
                fields=["patient"],
                condition=models.Q(deleted_at__isnull=True),
                name="medical_history_patient_active_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["patient"],
                name="medical_history_patient_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"HistoriaClínica — paciente {self.patient_id} (tenant={self.tenant_id})"


# ---------------------------------------------------------------------------
# VitalSignsRecord — Signos Vitales (A3)
# ---------------------------------------------------------------------------

# Claves permitidas en extra_params (D-EC-8: parámetros extensibles del legacy).
EXTRA_PARAMS_WHITELIST: frozenset[str] = frozenset(
    {"colesterol", "trigliceridos", "urea", "creatinina", "hemoglobina"}
)


class VitalSignsRecord(TenantAwareModel):
    """Toma de signos vitales de un paciente (A3 — sección Enfermería).

    Modelo de **serie temporal append-only**: cada toma es un registro inmutable.
    No se edita ni se borra físicamente (D-EC-5). Si hubo un error en el registro,
    se crea una nueva toma con los valores correctos.

    La inmutabilidad es de negocio (no de BD); el modelo solo provee CREATE + LIST.
    Los endpoints PATCH/PUT/DELETE no están ruteados (→ 404/405).

    Campos principales:
        patient      FK al paciente (mismo tenant). Indexado.
        appointment  FK opcional a Appointment (toma asociada a una cita). Si se
                     provee, el service valida que pertenezca al mismo paciente y tenant.
        measured_at  Momento de la toma. Por defecto = ahora. No se permite futuro.
                     Sí se permite pasado (tomas retroactivas).
        weight_kg    Peso en kg (null si no se midió).
        height_m     Talla en metros (null si no se midió).
        heart_rate   Frecuencia cardíaca en lpm (null si no se midió).
        resp_rate    Frecuencia respiratoria en rpm (null si no se midió).
        systolic     Presión sistólica mmHg (null si no se midió).
        diastolic    Presión diastólica mmHg (null si no se midió).
        temperature_c Temperatura en °C (null si no se midió).
        oxygen_saturation SatO₂ en % (null si no se midió).
        glucose      Glucosa en mg/dL (null si no se midió).
        extra_params Parámetros extensibles del legacy (whitelist estricta):
                     colesterol, trigliceridos, urea, creatinina, hemoglobina.
        notes        Observaciones breves del responsable (max 255 chars).

    Responsable de la toma:
        Se infiere de `created_by` (campo heredado de TenantAwareModel). No hay campo
        aparte (D-EC-6).

    IMC derivado (D-EC-6):
        Se calcula en la property `imc` (weight_kg / height_m²). No se almacena.
        El OutputSerializer lo expone como campo virtual.

    Auditoría: VITALSIGNS_CREATE se registra en AuditLog (NOM-024).
    """

    patient = models.ForeignKey(
        "pacientes.Patient",
        on_delete=models.PROTECT,
        related_name="vital_signs",
        db_index=True,
        help_text="Paciente al que pertenece la toma.",
    )
    appointment = models.ForeignKey(
        "agenda.Appointment",
        on_delete=models.SET_NULL,
        related_name="vital_signs",
        null=True,
        blank=True,
        db_index=True,
        help_text=(
            "Cita médica asociada a esta toma (opcional). "
            "Si se provee, debe pertenecer al mismo paciente y tenant."
        ),
    )
    measured_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        help_text=(
            "Momento de la toma. Por defecto = ahora. "
            "No se permite fecha futura; sí se permiten tomas retroactivas."
        ),
    )

    # --- Parámetros principales (todos opcionales — la toma puede ser parcial) ---
    weight_kg = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Peso corporal en kilogramos. Rango válido: 0.2 – 500.",
    )
    height_m = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="Talla en metros. Rango válido: 0.2 – 2.6.",
    )
    heart_rate = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Frecuencia cardíaca en lpm. Rango válido: 20 – 300.",
    )
    resp_rate = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Frecuencia respiratoria en rpm. Rango válido: 5 – 80.",
    )
    systolic = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Presión sistólica en mmHg. Rango válido: 40 – 300.",
    )
    diastolic = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Presión diastólica en mmHg. Rango válido: 20 – 200. Debe ser < sistólica.",
    )
    temperature_c = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        null=True,
        blank=True,
        help_text="Temperatura corporal en °C. Rango válido: 30 – 45.",
    )
    oxygen_saturation = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Saturación de oxígeno en %. Rango válido: 50 – 100.",
    )
    glucose = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Glucosa en mg/dL. Rango válido: 10 – 1000.",
    )

    # --- Parámetros extensibles del legacy (D-EC-8) ---
    extra_params = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Parámetros del legacy. Claves permitidas (EXTRA_PARAMS_WHITELIST): "
            "colesterol, trigliceridos, urea, creatinina, hemoglobina. "
            "Todos deben ser numéricos positivos. "
            "El serializer rechaza claves no declaradas (D-EC-7)."
        ),
    )

    # --- Notas breves ---
    notes = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Observaciones breves del responsable de la toma (máx 255 caracteres).",
    )

    class Meta:
        db_table = "expediente_vital_signs"
        ordering = ["-measured_at"]
        indexes = [
            # Historial del paciente y series temporales (caso principal).
            models.Index(
                fields=["tenant", "patient", "measured_at"],
                name="vitals_tenant_patient_time_idx",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"Signos({self.id}) — paciente {self.patient_id} "
            f"@ {self.measured_at} (tenant={self.tenant_id})"
        )

    @property
    def imc(self) -> Decimal | None:
        """IMC derivado: weight_kg / height_m². No se almacena (D-EC-6).

        Returns:
            Decimal redondeado a 2 decimales, o None si falta peso o talla.
        """
        if self.weight_kg is None or self.height_m is None:
            return None
        if self.height_m == 0:
            return None
        result = Decimal(str(self.weight_kg)) / (Decimal(str(self.height_m)) ** 2)
        return result.quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# EvolutionNote — Nota de Evolución (A4)  INMUTABLE — D-EC-1
# ---------------------------------------------------------------------------


class EvolutionNote(TenantAwareModel):
    """Nota de evolución clínica de una cita ATTENDED.

    Modelo INMUTABLE (D-EC-1): solo se crea; no se modifica ni borra físicamente.
    Los endpoints PATCH/PUT/DELETE no están ruteados (devolverán 405 por defecto
    de DRF, o 403 si alguna vista intenta responder con mensaje explícito).

    Restricciones de negocio (D-EC-2):
      - La cita (appointment) debe estar en estado ATTENDED.
      - La cita debe pertenecer al mismo paciente y tenant.
      - El doctor registrado debe ser el doctor de la cita.

    Campos clínicos (todos opcionales, max_length en serializer para evitar DoS):
      antecedentes         — antecedentes de importancia de la consulta.
      interrogatorio       — interrogatorio por aparatos y sistemas.
      estudios             — estudios solicitados o reportados.
      diagnosticos_texto   — diagnósticos en texto libre (complementa Diagnosis).
      tratamiento          — tratamiento prescrito.
      plan_recomendaciones — plan y recomendaciones al paciente.
      indicaciones_enfermeria — indicaciones para enfermería.
      exploracion_fisica   — exploración física por aparatos (JSONField).

    Auditoría: EVOLUTION_CREATE + EVOLUTION_READ en AuditLog (NOM-024).
    resource_repr = str(obj.id) — NUNCA PII clínica.
    """

    patient = models.ForeignKey(
        "pacientes.Patient",
        on_delete=models.PROTECT,
        related_name="evolution_notes",
        db_index=True,
        help_text="Paciente al que pertenece la nota de evolución.",
    )
    appointment = models.ForeignKey(
        "agenda.Appointment",
        on_delete=models.PROTECT,
        related_name="evolution_notes",
        db_index=True,
        help_text=(
            "Cita médica de la que nace esta evolución. "
            "Debe estar en estado ATTENDED y pertenecer al mismo paciente y tenant (D-EC-2)."
        ),
    )
    doctor = models.ForeignKey(
        "personal.Doctor",
        on_delete=models.PROTECT,
        related_name="evolution_notes",
        db_index=True,
        help_text="Médico autor clínico de la nota (debe ser el doctor de la cita).",
    )
    vital_signs = models.ForeignKey(
        VitalSignsRecord,
        on_delete=models.SET_NULL,
        related_name="evolution_notes",
        null=True,
        blank=True,
        db_index=True,
        help_text=(
            "Toma de signos vitales asociada (opcional). "
            "Si se provee, debe pertenecer al mismo paciente y tenant."
        ),
    )

    # --- Campos de texto clínico (all optional — blank, default "") ---
    antecedentes = models.TextField(
        blank=True,
        default="",
        help_text="Antecedentes de importancia del episodio.",
    )
    interrogatorio = models.TextField(
        blank=True,
        default="",
        help_text="Interrogatorio por aparatos y sistemas.",
    )
    estudios = models.TextField(
        blank=True,
        default="",
        help_text="Estudios solicitados o reportados en la consulta.",
    )
    diagnosticos_texto = models.TextField(
        blank=True,
        default="",
        help_text="Diagnósticos en texto libre (complementa el modelo Diagnosis).",
    )
    tratamiento = models.TextField(
        blank=True,
        default="",
        help_text="Tratamiento prescrito en la consulta.",
    )
    plan_recomendaciones = models.TextField(
        blank=True,
        default="",
        help_text="Plan de seguimiento y recomendaciones al paciente.",
    )
    indicaciones_enfermeria = models.TextField(
        blank=True,
        default="",
        help_text="Indicaciones específicas para el personal de enfermería.",
    )

    # --- Exploración física por aparatos (D-EC-7: whitelist de sistemas y estados) ---
    exploracion_fisica = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Exploración física por aparatos/sistema. "
            "Estructura: { '<sistema>': { 'estado': <estado_semaforo>, 'detalle': <str> } }. "
            "Estados: no_evaluado (default), normal, observacion, alterado. "
            "Sistemas = misma lista que exploracion_fisica_basal de MedicalHistory."
        ),
    )

    # --- Flag de firma (bloqueada al crear) ---
    is_locked = models.BooleanField(
        default=True,
        help_text=(
            "True = nota firmada (inmutable). "
            "Se establece True al crear y nunca cambia. "
            "No existe endpoint para desbloquear (D-EC-1)."
        ),
    )

    class Meta:
        db_table = "expediente_evolution_notes"
        ordering = ["-created_at"]
        constraints = [
            # MEDIO-2: una sola nota de evolución activa por cita.
            # Usa constraint parcial (deleted_at IS NULL) para permitir
            # en el futuro archivar notas sin violar la restricción.
            models.UniqueConstraint(
                fields=["appointment"],
                condition=models.Q(deleted_at__isnull=True),
                name="evolution_note_appointment_uniq",
            ),
            # BAJO-2: is_locked siempre True — inmutabilidad a nivel BD.
            # Refuerza la regla D-EC-1 en la base de datos directamente.
            # Usa `condition` (no `check`) — API de Django 5+ (evita deprecation warning).
            models.CheckConstraint(
                condition=models.Q(is_locked=True),
                name="evolution_is_locked_always",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "patient", "created_at"],
                name="evol_tenant_patient_time_idx",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"EvolutionNote({self.id}) — paciente {self.patient_id} "
            f"cita {self.appointment_id} (tenant={self.tenant_id})"
        )


# ---------------------------------------------------------------------------
# Addendum — Addendum sobre EvolutionNote (A4) — Append-only
# ---------------------------------------------------------------------------


class Addendum(TenantAwareModel):
    """Addendum médico sobre una nota de evolución (D-EC-1).

    Append-only: solo crear y listar. No hay UPDATE ni DELETE (D-EC-5).
    Registra observaciones, correcciones o ampliaciones sin modificar la nota
    original, preservando la trazabilidad clínica.

    author FK a User (no a Doctor) para permitir addenda del propio médico u
    otro usuario autorizado (owner/admin). Se registra en AuditLog con ADDENDUM_CREATE.
    resource_repr = str(obj.id) — NUNCA PII.
    """

    evolution = models.ForeignKey(
        EvolutionNote,
        on_delete=models.CASCADE,
        related_name="addenda",
        db_index=True,
        help_text="Nota de evolución a la que se agrega este addendum.",
    )
    author = models.ForeignKey(
        "authn.User",
        on_delete=models.PROTECT,
        related_name="addenda",
        db_index=True,
        help_text="Usuario que agrega el addendum.",
    )
    body = models.TextField(
        help_text="Texto del addendum (requerido, no puede estar vacío).",
    )

    class Meta:
        db_table = "expediente_addenda"
        ordering = ["created_at"]
        indexes = [
            models.Index(
                fields=["tenant", "evolution", "created_at"],
                name="addendum_evol_time_idx",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"Addendum({self.id}) — evolución {self.evolution_id} "
            f"autor {self.author_id} (tenant={self.tenant_id})"
        )


# ---------------------------------------------------------------------------
# Diagnosis — Diagnóstico Clínico (A4)
# ---------------------------------------------------------------------------


class DiagnosisKind(models.TextChoices):
    """Tipo de diagnóstico (D-EC-8: respuestas precargadas)."""

    PRESUNTIVO = "presuntivo", "Presuntivo"
    DEFINITIVO = "definitivo", "Definitivo"


class DiagnosisStatus(models.TextChoices):
    """Estado del diagnóstico (activo o resuelto)."""

    ACTIVO = "activo", "Activo"
    RESUELTO = "resuelto", "Resuelto"


class Diagnosis(TenantAwareModel):
    """Diagnóstico clínico de un paciente.

    Pueden existir múltiples diagnósticos por paciente. Un diagnóstico puede
    nacer de una nota de evolución (evolution FK opcional).

    Inmutabilidad parcial: description, cie_code y kind NO se pueden modificar
    tras crear (validado en el service con _IMMUTABLE_FIELDS).
    El status se puede cambiar de activo a resuelto mediante el endpoint
    POST /diagnosticos/<id>/resolver/ (baja lógica — D-EC-5: sin borrado físico).

    Auditoría: DIAGNOSIS_CREATE / DIAGNOSIS_RESOLVE en AuditLog (NOM-024).
    resource_repr = str(obj.id) — NUNCA PII.
    """

    patient = models.ForeignKey(
        "pacientes.Patient",
        on_delete=models.PROTECT,
        related_name="diagnoses",
        db_index=True,
        help_text="Paciente al que pertenece el diagnóstico.",
    )
    evolution = models.ForeignKey(
        EvolutionNote,
        on_delete=models.SET_NULL,
        related_name="diagnoses",
        null=True,
        blank=True,
        db_index=True,
        help_text=(
            "Nota de evolución donde se asentó el diagnóstico (opcional). "
            "Si se provee, debe pertenecer al mismo paciente y tenant."
        ),
    )
    cie_code = models.CharField(
        max_length=10,
        blank=True,
        default="",
        help_text="Código CIE-10 (texto libre en v1; catálogo formal en versiones futuras).",
    )
    description = models.CharField(
        max_length=255,
        help_text="Descripción del diagnóstico (requerida, no puede estar vacía).",
    )
    kind = models.CharField(
        max_length=12,
        choices=DiagnosisKind.choices,
        default=DiagnosisKind.PRESUNTIVO,
        help_text="Tipo de diagnóstico: presuntivo (default) o definitivo.",
    )
    status = models.CharField(
        max_length=10,
        choices=DiagnosisStatus.choices,
        default=DiagnosisStatus.ACTIVO,
        db_index=True,
        help_text="Estado del diagnóstico: activo (default) o resuelto (baja lógica).",
    )

    class Meta:
        db_table = "expediente_diagnoses"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["tenant", "patient", "status"],
                name="diag_tenant_patient_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"Diagnosis({self.id}) [{self.kind}/{self.status}] "
            f"— paciente {self.patient_id} (tenant={self.tenant_id})"
        )
