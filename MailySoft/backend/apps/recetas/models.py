"""
Modelos de la app recetas — sub-fases B1.1 y B1.2.

B1.1:
  GlobalMedication(BaseModel)  — catálogo global compartido por todas las clínicas.
                                 Sin tenant. Solo lectura para clientes; lo escribe
                                 el equipo Maily vía seed/plataforma.
  Medication(TenantAwareModel) — medicamentos custom de una clínica (autocompletado
                                 propio del médico). Con tenant, RLS normal.

B1.2:
  Prescription(TenantAwareModel)     — receta médica INMUTABLE (DR-1, NOM-004).
                                       Solo se puede pasar a `cancelled`. Sin edición
                                       de contenido. Sin borrado físico (DR-5).
  PrescriptionItem(TenantAwareModel) — renglón de tratamiento de una receta.
                                       Snapshot de nombre/presentación/forma/concentración
                                       al momento de crear (DR-7 — receta autocontenida).

Decisiones del plan respetadas:
  DR-1 — receta inmutable + anulación con motivo.
  DR-2 — catálogo global + custom por tenant + texto libre.
  DR-5 — sin borrado físico: baja lógica en Prescription (status=cancelled).
  DR-6 — permisos: el médico crea y anula; lectura = roles clínicos.
  DR-7 — seguridad clínica: PrescriptionItem congela nombre/presentación al crear.
          La receta congela los signos vitales en vitals_snapshot (JSON).

Folio consecutivo por tenant (B1.2 — decisión de diseño):
  Se genera dentro de transaction.atomic con SELECT FOR UPDATE sobre las
  recetas del tenant para garantizar consecutivo sin race conditions.
  El modelo NO expone un contador separado (patrón selector max+1 bloqueado).
  Ver prescription_create en services.py.

Notas sobre RLS:
  Prescription y PrescriptionItem: RLS USING + WITH CHECK igual que expediente.
  Migración 0003_prescription.py aplica RLS en ambas tablas.
"""

import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel, TenantAwareModel


class ItemKind(models.TextChoices):
    """Tipo de ítem de prescripción (COFEPRIS F2).

    Distingue entre medicamentos, sueros (soluciones parenterales) y terapias
    (procedimientos o tratamientos no farmacológicos). El catálogo usa el mismo
    campo para unificar el autocompletado y el filtrado.
    """

    MEDICAMENTO = "medicamento", "Medicamento"
    SUERO = "suero", "Suero / solución parenteral"
    TERAPIA = "terapia", "Terapia / procedimiento"


class ControlledGroup(models.TextChoices):
    """Grupo COFEPRIS de medicamento controlado (psicotrópicos y estupefacientes).

    none = no controlado (la mayoría del catálogo).
    I–V  = grupos según Ley General de Salud y Reglamento de Insumos:
        Grupo I   — estupefacientes experimentales (uso muy restringido, 24 h).
        Grupo II  — opioides y psicotrópicos de alto potencial (30 días, un surtido).
        Grupo III — psicotrópicos de potencial moderado.
        Grupo IV  — psicotrópicos de bajo potencial (benzodiazepinas, etc.).
        Grupo V   — psicotrópicos de menor potencial (algunos antiepilépticos).

    El módulo de controlados (F6) usará este campo para aplicar reglas
    de vigencia, folio autorizado y recetario especial.
    """

    NONE = "none", "No controlado"
    I = "I", "Grupo I"
    II = "II", "Grupo II"
    III = "III", "Grupo III"
    IV = "IV", "Grupo IV"
    V = "V", "Grupo V"


class RouteOfAdministration(models.TextChoices):
    """Vía de administración del medicamento (COFEPRIS F2).

    COFEPRIS exige especificar la vía sin abreviaturas. Se incluyen las vías
    más comunes en práctica clínica ambulatoria.
    """

    ORAL = "oral", "Oral"
    SUBLINGUAL = "sublingual", "Sublingual"
    INTRAVENOSA = "intravenosa", "Intravenosa"
    INTRAMUSCULAR = "intramuscular", "Intramuscular"
    SUBCUTANEA = "subcutanea", "Subcutánea"
    TOPICA = "topica", "Tópica"
    OFTALMICA = "oftalmica", "Oftálmica"
    OTICA = "otica", "Ótica"
    NASAL = "nasal", "Nasal"
    RECTAL = "rectal", "Rectal"
    VAGINAL = "vaginal", "Vaginal"
    INHALADA = "inhalada", "Inhalada"
    TRANSDERMICA = "transdermica", "Transdérmica"
    OTRA = "otra", "Otra"


class MedicationForm(models.TextChoices):
    """Formas farmacéuticas del medicamento (DR-2: catálogo con choices)."""

    TABLETA = "tableta", "Tableta"
    CAPSULA = "capsula", "Cápsula"
    JARABE = "jarabe", "Jarabe"
    SUSPENSION = "suspension", "Suspensión"
    SOLUCION = "solucion", "Solución"
    SOLUCION_INYECTABLE = "solucion_inyectable", "Solución inyectable"
    CREMA = "crema", "Crema"
    UNGUENTO = "unguento", "Ungüento"
    GEL = "gel", "Gel"
    GOTAS = "gotas", "Gotas"
    OVULO = "ovulo", "Óvulo"
    SUPOSITORIO = "supositorio", "Supositorio"
    PARCHE = "parche", "Parche"
    AEROSOL = "aerosol", "Aerosol"
    POLVO = "polvo", "Polvo"
    OTRO = "otro", "Otro"


class GlobalMedication(BaseModel):
    """Medicamento del catálogo global compartido (sin tenant).

    Lo crea y mantiene el equipo Maily vía el management command
    `seed_medicamentos`. Ningún endpoint de cliente puede escribir en esta tabla.

    Nota de seguridad clínica (DR-7):
        Este catálogo ÚNICAMENTE almacena identificación farmacéutica básica:
        nombre genérico, forma farmacéutica, concentración y presentación comercial
        estándar. NO contiene dosis recomendadas, indicaciones terapéuticas ni
        contraindicaciones. Esos datos son responsabilidad del médico y se
        registran en PrescriptionItem (receta individual), no aquí.

    RLS (PostgreSQL):
        Tabla global sin tenant_id; no aplica política RLS por tenant.
        La migración 0002_rls_medication.py documenta y omite RLS para esta tabla.
        La restricción de escritura se garantiza en la capa de aplicación:
        no existe endpoint ni service que permita escritura al cliente.

    Índices:
        - generic_name + form: búsqueda de autocompletado (icontains).
        - commercial_name:     búsqueda secundaria por nombre comercial.

    Unicidad funcional:
        get_or_create usa (generic_name, concentration, form) para idempotencia
        del seed. No se declara UniqueConstraint para permitir variantes del
        mismo principio activo con distintas presentaciones (ej. amoxicilina 250mg
        y amoxicilina 500mg son registros separados pero mismo generic_name).
    """

    generic_name = models.CharField(
        max_length=200,
        db_index=True,
        help_text=(
            "Denominación Común Internacional (DCI) o nombre genérico del principio activo. "
            "Ej: 'Paracetamol', 'Amoxicilina', 'Metformina'. "
            "NUNCA incluir indicaciones ni dosis recomendadas (DR-7)."
        ),
    )
    commercial_name = models.CharField(
        max_length=200,
        blank=True,
        default="",
        db_index=True,
        help_text=(
            "Nombre comercial de referencia (opcional). "
            "Ej: 'Panadol', 'Tempra'. "
            "No es el único nombre posible; es solo referencia."
        ),
    )
    form = models.CharField(
        max_length=20,
        choices=MedicationForm.choices,
        db_index=True,
        help_text="Forma farmacéutica. Ej: tableta, jarabe, solución inyectable.",
    )
    concentration = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text=(
            "Concentración estándar del principio activo. "
            "Ej: '500 mg', '250 mg/5 mL', '10 mg/mL'. "
            "Solo concentraciones de uso común bien conocidas; "
            "dejar en blanco si hay duda (DR-7)."
        ),
    )
    presentation = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text=(
            "Presentación comercial estándar. "
            "Ej: 'Caja con 20 tabletas', 'Frasco 120 mL'. "
            "Solo presentaciones estándar bien conocidas; "
            "dejar en blanco si hay duda (DR-7)."
        ),
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text=(
            "True = medicamento vigente en el catálogo. "
            "False = retirado o descontinuado (no aparece en autocompletado)."
        ),
    )

    # --- COFEPRIS F2: clasificación ---
    kind = models.CharField(
        max_length=15,
        choices=ItemKind.choices,
        default=ItemKind.MEDICAMENTO,
        db_index=True,
        help_text=(
            "Tipo de ítem del catálogo: medicamento, suero o terapia. "
            "El seed inicial (313 entradas) mantiene 'medicamento'. COFEPRIS F2."
        ),
    )
    controlled_group = models.CharField(
        max_length=5,
        choices=ControlledGroup.choices,
        default=ControlledGroup.NONE,
        db_index=True,
        help_text=(
            "Grupo COFEPRIS de medicamento controlado (none = no controlado). "
            "Grupos I–V según LGS. Módulo de controlados F6 lo usa para "
            "aplicar reglas de vigencia y folio autorizado."
        ),
    )

    class Meta:
        db_table = "recetas_global_medications"
        ordering = ["generic_name", "form", "concentration"]
        indexes = [
            models.Index(
                fields=["generic_name", "form"],
                name="global_med_name_form_idx",
            ),
            models.Index(
                fields=["commercial_name"],
                name="global_med_commercial_idx",
            ),
        ]

    def __str__(self) -> str:
        parts = [self.generic_name]
        if self.concentration:
            parts.append(self.concentration)
        parts.append(f"({self.form})")
        return " ".join(parts)


class Medication(TenantAwareModel):
    """Medicamento custom de una clínica.

    Permite al médico agregar medicamentos no presentes en el catálogo global.
    El autocompletado del frontend une GlobalMedication + Medication del tenant
    (selector `medication_search`).

    Baja lógica (DR-5): `is_active=False` oculta del autocompletado.
    NUNCA se usa DELETE físico. El campo `deleted_at` heredado de BaseModel
    se reserva para el soft-delete del sistema; `is_active` es la baja clínica.

    RLS (PostgreSQL):
        RLS USING + WITH CHECK igual que tablas de expediente.
        Migración 0002_rls_medication.py.

    Nota de seguridad clínica (DR-7):
        Misma restricción que GlobalMedication: solo identificación farmacéutica.
        La dosis/indicación va en PrescriptionItem.
    """

    generic_name = models.CharField(
        max_length=200,
        db_index=True,
        help_text=(
            "Denominación genérica o nombre propio del médico para este medicamento. "
            "NUNCA incluir indicaciones ni dosis recomendadas (DR-7)."
        ),
    )
    commercial_name = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Nombre comercial de referencia (opcional).",
    )
    form = models.CharField(
        max_length=20,
        choices=MedicationForm.choices,
        db_index=True,
        help_text="Forma farmacéutica.",
    )
    concentration = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Concentración del principio activo (opcional). Ej: '500 mg'.",
    )
    presentation = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Presentación (opcional). Ej: 'Caja con 20 tabletas'.",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text=(
            "True = medicamento vigente (aparece en autocompletado). "
            "False = dado de baja (baja clínica, sin borrado físico — DR-5)."
        ),
    )

    # --- COFEPRIS F2: clasificación ---
    kind = models.CharField(
        max_length=15,
        choices=ItemKind.choices,
        default=ItemKind.MEDICAMENTO,
        db_index=True,
        help_text=(
            "Tipo de ítem: medicamento, suero o terapia. "
            "Permite catálogos custom de sueros y terapias. COFEPRIS F2."
        ),
    )
    controlled_group = models.CharField(
        max_length=5,
        choices=ControlledGroup.choices,
        default=ControlledGroup.NONE,
        db_index=True,
        help_text=(
            "Grupo COFEPRIS de medicamento controlado (none = no controlado). "
            "Módulo de controlados F6."
        ),
    )

    class Meta:
        db_table = "recetas_medications"
        ordering = ["generic_name", "form", "concentration"]
        indexes = [
            models.Index(
                fields=["tenant", "generic_name"],
                name="medication_tenant_name_idx",
            ),
            models.Index(
                fields=["tenant", "is_active"],
                name="medication_tenant_active_idx",
            ),
        ]

    def __str__(self) -> str:
        parts = [self.generic_name]
        if self.concentration:
            parts.append(self.concentration)
        parts.append(f"({self.form})")
        return f"{' '.join(parts)} [custom tenant={self.tenant_id}]"


# ---------------------------------------------------------------------------
# Prescription — Receta Médica Inmutable (B1.2 — DR-1, DR-7)
# ---------------------------------------------------------------------------


class PrescriptionStatus(models.TextChoices):
    """Estado de la receta médica.

    Conforme a DR-1: solo dos estados. La receta nace en `active` y solo puede
    pasar a `cancelled` (anulación con motivo). No existe PATCH ni UPDATE de
    contenido clínico.
    """

    ACTIVE = "active", "Activa"
    CANCELLED = "cancelled", "Anulada"


class Prescription(TenantAwareModel):
    """Receta médica INMUTABLE (DR-1).

    Documento médico-legal conforme a NOM-004. Una vez creada, el contenido
    clínico (medicamentos, recomendaciones, signos) NO se modifica. Si el médico
    cometió un error, se anula (baja lógica con motivo) y se emite una nueva.

    Inmutabilidad:
        Solo los campos `status`, `cancelled_at`, `cancelled_by` y
        `cancellation_reason` cambian después de la creación, y solo a través
        del servicio `prescription_cancel`. No existen endpoints PATCH/PUT.
        La BD no tiene CheckConstraint de inmutabilidad (es de aplicación).

    Folio consecutivo por tenant:
        Generado con SELECT FOR UPDATE dentro de transaction.atomic para
        prevenir race conditions. Único por tenant (UniqueConstraint).
        El número arranca en 1 por tenant.

    Snapshot de signos vitales (DR-7):
        `vitals_snapshot` guarda los valores de la última toma de signos del
        paciente al crear la receta. Es un JSON con los campos relevantes.
        Si el paciente no tiene tomas, queda null. El snapshot congela los
        datos: cambios futuros en los signos no afectan la receta.

    Auditado: PRESCRIPTION_CREATE / PRESCRIPTION_READ / PRESCRIPTION_CANCEL
    en AuditLog (NOM-024). resource_repr = folio sin PII del paciente.

    Sin borrado físico (DR-5): nunca se llama .delete(). Se usa status=cancelled.
    """

    patient = models.ForeignKey(
        "pacientes.Patient",
        on_delete=models.PROTECT,
        related_name="prescriptions",
        db_index=True,
        help_text="Paciente al que se emite la receta.",
    )
    doctor = models.ForeignKey(
        "personal.Doctor",
        on_delete=models.PROTECT,
        related_name="prescriptions",
        db_index=True,
        help_text="Médico que emite la receta (inferido del perfil activo del usuario).",
    )
    appointment = models.ForeignKey(
        "agenda.Appointment",
        on_delete=models.SET_NULL,
        related_name="prescriptions",
        null=True,
        blank=True,
        db_index=True,
        help_text="Cita médica asociada (opcional).",
    )
    evolution_note = models.ForeignKey(
        "expediente.EvolutionNote",
        on_delete=models.SET_NULL,
        related_name="prescriptions",
        null=True,
        blank=True,
        db_index=True,
        help_text="Nota de evolución asociada (opcional).",
    )

    # --- Folio consecutivo por tenant ---
    folio = models.PositiveIntegerField(
        db_index=True,
        help_text=(
            "Número de folio consecutivo por tenant. "
            "Generado automáticamente con SELECT FOR UPDATE. "
            "Único por tenant (UniqueConstraint)."
        ),
    )

    issued_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        help_text="Fecha y hora de emisión de la receta. Por defecto = ahora.",
    )

    # --- COFEPRIS F2: diagnóstico ---
    diagnosis = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text=(
            "Diagnóstico del paciente al momento de la receta (COFEPRIS F2). "
            "COFEPRIS marca 'receta sin diagnóstico' como error que invalida el documento. "
            "Texto libre; FK opcional a expediente.Diagnosis = fase futura. "
            "No incluir en la receta datos de otro paciente (NOM-024)."
        ),
    )

    recommendations = models.TextField(
        blank=True,
        default="",
        max_length=5000,
        help_text="Recomendaciones generales del médico al paciente (opcional).",
    )

    # --- Snapshot de signos vitales (DR-7) ---
    vitals_snapshot = models.JSONField(
        null=True,
        blank=True,
        help_text=(
            "Snapshot de la última toma de signos vitales del paciente al crear la receta. "
            "Estructura: {weight_kg, height_m, imc, heart_rate, resp_rate, "
            "systolic, diastolic, temperature_c, oxygen_saturation, glucose, measured_at}. "
            "Null si el paciente no tiene tomas registradas al momento de crear. "
            "DR-7: congela los signos — cambios futuros no alteran la receta."
        ),
    )

    # --- F6: Medicamentos controlados (COFEPRIS) ---
    controlled_folio = models.CharField(
        max_length=60,
        blank=True,
        default="",
        help_text=(
            "Folio del recetario especial que el médico ingresa manualmente (F6). "
            "Emitido por COFEPRIS fuera del sistema. "
            "Requerido cuando la receta contiene al menos un medicamento controlado "
            "(is_controlled=True). Máximo 60 caracteres."
        ),
    )
    valid_until = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Vigencia de la receta, calculada automáticamente al crear (F6). "
            "Null para recetas sin medicamentos controlados. "
            "Grupo I → 24 horas desde issued_at. "
            "Grupo II–V → 30 días desde issued_at (configurable en settings)."
        ),
    )

    # --- Estado (activa / anulada) ---
    status = models.CharField(
        max_length=10,
        choices=PrescriptionStatus.choices,
        default=PrescriptionStatus.ACTIVE,
        db_index=True,
        help_text="Estado de la receta. Solo puede ir de active → cancelled.",
    )
    cancelled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Fecha y hora de anulación. Null si la receta está activa.",
    )
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Usuario que anuló la receta. Null si la receta está activa.",
    )
    cancellation_reason = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Motivo de la anulación. Requerido al cancelar; en blanco si activa.",
    )

    class Meta:
        db_table = "recetas_prescriptions"
        ordering = ["-issued_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "folio"],
                name="prescription_tenant_folio_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "patient", "issued_at"],
                name="rx_tenant_patient_issued_idx",
            ),
            models.Index(
                fields=["tenant", "doctor", "issued_at"],
                name="rx_tenant_doctor_issued_idx",
            ),
            models.Index(
                fields=["tenant", "status"],
                name="rx_tenant_status_idx",
            ),
        ]

    @property
    def is_controlled(self) -> bool:
        """True si al menos un ítem de la receta tiene controlled_group != 'none'.

        Basado en los ítems ya cargados (prefetch_related) o consultados al vuelo.
        Nota: Si los ítems no están precargados se disparará una query adicional.
        Para evitar N+1, usar prefetch_related("items") en los selectors.
        """
        return any(
            item.controlled_group != ControlledGroup.NONE
            for item in self.items.all()
        )

    def __str__(self) -> str:
        return (
            f"Receta#{self.folio} [{self.status}] "
            f"— paciente {self.patient_id} (tenant={self.tenant_id})"
        )


# ---------------------------------------------------------------------------
# PrescriptionItem — Renglón de tratamiento (B1.2 — DR-7)
# ---------------------------------------------------------------------------


class PrescriptionItem(TenantAwareModel):
    """Renglón de tratamiento de una receta médica.

    Snapshot autocontenido (DR-7):
        Los campos `medication_name`, `medication_presentation`, `medication_form`
        y `medication_concentration` capturan el nombre y presentación al momento
        de crear la receta. Son la fuente de verdad del documento médico-legal.
        Los campos `global_medication` y `medication` son solo trazabilidad opcional
        (FK nullable) — si el catálogo cambia en el futuro, la receta no se altera.

    Inmutable: no existe endpoint PATCH/PUT sobre ítems. La receta como un todo
        es inmutable (DR-1). Si hay un error en un ítem, se anula la receta y se
        emite una nueva.

    Sin borrado físico (DR-5): los ítems se eliminan en cascada SOLO si la receta
        es eliminada (lo cual no ocurre en v1 — DR-5). En la práctica los ítems
        son permanentes mientras exista su receta.
    """

    prescription = models.ForeignKey(
        Prescription,
        on_delete=models.CASCADE,
        related_name="items",
        db_index=True,
        help_text="Receta a la que pertenece este renglón.",
    )
    order = models.PositiveSmallIntegerField(
        default=1,
        help_text="Orden del renglón en la receta (1-based). Permite presentación ordenada.",
    )

    # --- COFEPRIS F2: tipo de ítem ---
    kind = models.CharField(
        max_length=15,
        choices=ItemKind.choices,
        default=ItemKind.MEDICAMENTO,
        db_index=True,
        help_text=(
            "Tipo de ítem: medicamento, suero o terapia. "
            "Determina qué campos son obligatorios (validación condicional COFEPRIS). "
            "COFEPRIS F2."
        ),
    )

    # --- Snapshot del medicamento (DR-7: fuente de verdad) ---
    medication_name = models.CharField(
        max_length=200,
        help_text=(
            "Nombre del medicamento (snapshot al crear). Requerido. "
            "Es la fuente de verdad inmutable del documento. "
            "DR-7: el catálogo puede cambiar; la receta no."
        ),
    )
    medication_presentation = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Presentación del medicamento (snapshot). Ej: 'Caja con 20 tabletas'.",
    )
    medication_form = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Forma farmacéutica del medicamento (snapshot). Ej: 'tableta'.",
    )
    medication_concentration = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Concentración del medicamento (snapshot). Ej: '500 mg'.",
    )

    # --- Trazabilidad opcional al catálogo (solo referencial — DR-7) ---
    global_medication = models.ForeignKey(
        GlobalMedication,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prescription_items",
        help_text=(
            "FK al catálogo global (opcional, solo trazabilidad). "
            "El snapshot de texto es la fuente de verdad."
        ),
    )
    medication = models.ForeignKey(
        Medication,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prescription_items",
        help_text=(
            "FK al medicamento custom del tenant (opcional, solo trazabilidad). "
            "El snapshot de texto es la fuente de verdad."
        ),
    )

    # --- COFEPRIS F2: campos estructurados del renglón ---
    dose = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text=(
            "Dosis sin abreviaturas (COFEPRIS F2). "
            "Ej: '1 tableta', '500 miligramos', '10 mililitros'. "
            "Obligatorio para kind=medicamento."
        ),
    )
    frequency = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text=(
            "Frecuencia de administración sin abreviaturas (COFEPRIS F2). "
            "Ej: 'cada 8 horas', 'dos veces al día', 'una vez en ayunas'. "
            "Obligatorio para kind=medicamento."
        ),
    )
    route = models.CharField(
        max_length=15,
        choices=RouteOfAdministration.choices,
        blank=True,
        default="",
        help_text=(
            "Vía de administración (COFEPRIS F2). "
            "Obligatorio para kind=medicamento. Siempre validado contra choices."
        ),
    )
    duration = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text=(
            "Duración del tratamiento sin abreviaturas (COFEPRIS F2). "
            "Ej: '7 días', 'hasta terminar el frasco', 'uso crónico'. "
            "Obligatorio para kind=medicamento."
        ),
    )

    # --- Indicación (nota/observación — ahora complemento al renglón estructurado) ---
    indication = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Nota u observación adicional del médico (opcional). "
            "El renglón estructurado (dose/frequency/route/duration) es la fuente "
            "COFEPRIS; este campo permite texto libre adicional. "
            "En recetas pre-F2 puede contener la indicación completa por compatibilidad."
        ),
    )

    # --- Cantidad (opcional) ---
    quantity = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Cantidad a dispensar (opcional). Ej: '20 tabletas', '1 frasco'.",
    )

    # --- F6: snapshot del grupo COFEPRIS de medicamento controlado (DR-7) ---
    controlled_group = models.CharField(
        max_length=5,
        choices=ControlledGroup.choices,
        default=ControlledGroup.NONE,
        db_index=True,
        help_text=(
            "Snapshot del grupo COFEPRIS del medicamento al momento de emitir la receta (F6). "
            "DR-7: capturado del catálogo al crear — no depende del catálogo futuro. "
            "none = no controlado. I–V = grupos según LGS."
        ),
    )

    class Meta:
        db_table = "recetas_prescription_items"
        ordering = ["prescription", "order"]
        indexes = [
            models.Index(
                fields=["prescription", "order"],
                name="rx_item_prescription_order_idx",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"Item#{self.order} [{self.medication_name}] "
            f"— receta {self.prescription_id} (tenant={self.tenant_id})"
        )


# ---------------------------------------------------------------------------
# PrescriptionFormat — Formato de receta configurable por clínica (F3)
# ---------------------------------------------------------------------------

_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# Whitelist de secciones opcionales configurables (medicamentos siempre presente).
# Las 10 claves canónicas (todas activadas por defecto).
SECTIONS_KEYS: frozenset[str] = frozenset(
    {
        "signos",
        "edad_sexo",
        "diagnostico",
        "alergias",
        "sueros",
        "terapias",
        "indicaciones",
        "vigencia",
        "contacto_clinica",
        "qr",
    }
)

_DEFAULT_SECTIONS: dict[str, bool] = {
    "signos": True,
    "edad_sexo": True,
    "diagnostico": True,
    "alergias": True,
    "sueros": True,
    "terapias": True,
    "indicaciones": True,
    "vigencia": True,
    "contacto_clinica": True,
    "qr": True,
}


class PrescriptionFormat(TenantAwareModel):
    """Formato de receta configurable por clínica (F3).

    Permite que cada clínica personalice el PDF de sus recetas:
    - base_layout: plantilla base (compact/digital).
    - accent_color: color de acento en hex (#RRGGBB).
    - font: tipografía (helvetica / times).
    - sections: flags booleanos por sección opcional (JSON).
    - letterhead_mode: digital (el sistema imprime el encabezado) o
      preprinted (deja espacio superior — el médico usa papel pre-impreso).
    - is_default: el formato que se aplica automáticamente a las recetas
      del tenant. Solo uno puede ser default por tenant (enforced en servicio).
    - doctor (FK opcional a Doctor) + is_authorized: formato propio de un
      médico. Si is_authorized=True, se aplica a las recetas del médico
      con prioridad sobre el default del tenant. Solo owner/admin puede
      autorizar (cambiar is_authorized).

    Resolución de formato en prescription_pdf_build:
        1. format_override explícito (vista previa / ?formato=).
        2. PrescriptionFormat del médico con is_authorized=True.
        3. PrescriptionFormat con is_default=True del tenant.
        4. Objeto en memoria con defaults de fábrica (sin persistencia).

    Paper:
        Deriva del base_layout — compact = media carta horizontal;
        digital = carta. No es un campo separado (fase actual).

    RLS (PostgreSQL):
        USING + WITH CHECK igual que otras tablas tenant-aware.
        Migración 0007_prescription_format.py.

    Baja lógica (DR-5): is_active=False + deleted_at, sin borrado físico.
    Bitácora: FORMAT_CREATE / FORMAT_UPDATE / FORMAT_DELETE.
    """

    class BaseLayout(models.TextChoices):
        COMPACT = "compact", "Farmacia (media carta)"
        DIGITAL = "digital", "Paciente (hoja completa)"

    class FontChoice(models.TextChoices):
        HELVETICA = "helvetica", "Helvetica / Arial (sans-serif)"
        TIMES = "times", "Times New Roman (serif)"

    class LetterheadMode(models.TextChoices):
        DIGITAL = "digital", "Digital (el sistema imprime el encabezado)"
        PREPRINTED = "preprinted", "Pre-impreso (deja espacio superior)"

    class Theme(models.TextChoices):
        """Estilo decorativo del fondo/marco del PDF (no altera la estructura)."""

        ONDAS = "ondas", "Ondas suaves"
        MINIMAL = "minimal", "Minimalista"
        BARRA = "barra", "Barra lateral"
        GEOMETRICO = "geometrico", "Geométrico"

    name = models.CharField(
        max_length=120,
        help_text="Nombre descriptivo del formato. Ej: 'Estándar clínica', 'Compacta Camsa'.",
    )
    base_layout = models.CharField(
        max_length=10,
        choices=BaseLayout.choices,
        default=BaseLayout.DIGITAL,
        db_index=True,
        help_text="Plantilla base del PDF: 'digital' = hoja completa (paciente); 'compact' = media carta (farmacia).",
    )
    accent_color = models.CharField(
        max_length=7,
        default="#9A7B1E",
        help_text=(
            "Color de acento en hex (#RRGGBB). "
            "Se inyecta como variable Django en el template — NO como CSS var() "
            "(xhtml2pdf no soporta custom properties)."
        ),
    )
    font = models.CharField(
        max_length=10,
        choices=FontChoice.choices,
        default=FontChoice.HELVETICA,
        help_text="Tipografía del PDF. Solo fuentes base (Helvetica/Times); fase futura: embeber TTF.",
    )
    theme = models.CharField(
        max_length=12,
        choices=Theme.choices,
        default=Theme.ONDAS,
        help_text="Estilo decorativo del fondo/marco del PDF (no cambia la estructura).",
    )
    sections = models.JSONField(
        default=dict,
        blank=True,  # {} es un valor válido; full_clean no debe tratarlo como "vacío"
        help_text=(
            "Flags booleanos de secciones opcionales. "
            "Whitelist (10 claves): signos, edad_sexo, diagnostico, alergias, sueros, "
            "terapias, indicaciones, vigencia, contacto_clinica, qr. "
            "medicamentos siempre está presente. "
            "Claves omitidas reciben True por defecto vía get_sections_full()."
        ),
    )
    letterhead_mode = models.CharField(
        max_length=12,
        choices=LetterheadMode.choices,
        default=LetterheadMode.DIGITAL,
        help_text=(
            "Modo de membrete: 'digital' = el sistema imprime el encabezado; "
            "'preprinted' = el médico usa papel pre-impreso (se deja espacio superior)."
        ),
    )
    is_default = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            "True = se aplica automáticamente a todas las recetas del tenant "
            "cuando no hay formato por médico. Solo uno puede ser default por tenant. "
            "El servicio prescription_format_set_default desmarca el anterior."
        ),
    )

    # --- Formato por médico (decisión 3 del plan) ---
    doctor = models.ForeignKey(
        "personal.Doctor",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prescription_formats",
        db_index=True,
        help_text=(
            "Médico propietario del formato (opcional). "
            "Si se establece, es el formato personal de ese médico. "
            "Se aplica a sus recetas solo si is_authorized=True."
        ),
    )
    is_authorized = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            "True = el formato personal del médico está autorizado y se aplica "
            "a sus recetas. Solo owner/admin puede cambiar este flag. "
            "Irrelevante si doctor es null."
        ),
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="False = formato dado de baja (baja lógica). No aparece en selects normales.",
    )

    class Meta:
        db_table = "recetas_prescription_formats"
        ordering = ["-is_default", "name"]
        indexes = [
            models.Index(
                fields=["tenant", "is_default", "is_active"],
                name="pf_tenant_default_active_idx",
            ),
            models.Index(
                fields=["tenant", "doctor", "is_authorized"],
                name="pf_tenant_doctor_auth_idx",
            ),
        ]

    def clean(self) -> None:
        """Valida accent_color con regex y sections contra la whitelist."""
        if self.accent_color and not _HEX_RE.match(self.accent_color):
            raise ValidationError(
                {"accent_color": "El color de acento debe tener el formato #RRGGBB."}
            )
        if self.sections:
            unknown = set(self.sections.keys()) - SECTIONS_KEYS
            if unknown:
                raise ValidationError(
                    {
                        "sections": (
                            f"Claves desconocidas en sections: {', '.join(sorted(unknown))}. "
                            f"Permitidas: {', '.join(sorted(SECTIONS_KEYS))}."
                        )
                    }
                )
            for key, val in self.sections.items():
                if not isinstance(val, bool):
                    raise ValidationError(
                        {"sections": f"El valor de '{key}' debe ser booleano (true/false)."}
                    )

    def get_sections_full(self) -> dict[str, bool]:
        """Devuelve las secciones completas, rellenando con defaults los flags ausentes."""
        merged = dict(_DEFAULT_SECTIONS)
        merged.update(self.sections or {})
        return merged

    @property
    def font_family(self) -> str:
        """CSS font-family para el template (xhtml2pdf entiende estos valores)."""
        if self.font == self.FontChoice.TIMES:
            return "Times, serif"
        return "Helvetica, Arial, sans-serif"

    def __str__(self) -> str:
        default_flag = " [default]" if self.is_default else ""
        doctor_flag = f" [doctor={self.doctor_id}]" if self.doctor_id else ""
        return f"{self.name}{default_flag}{doctor_flag} (tenant={self.tenant_id})"
