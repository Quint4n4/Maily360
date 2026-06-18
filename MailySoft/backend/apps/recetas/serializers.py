"""
Serializers de la app recetas — sub-fases B1.1 y B1.2.

Regla: serializers solo validan/formatean. Cero lógica de negocio aquí.
Separados en InputSerializer y OutputSerializer (nunca uno solo para todo).
No hay create()/update() con lógica; eso va al servicio.

Validación estricta (M-4):
    PrescriptionItemInputSerializer y PrescriptionCreateInputSerializer rechazan
    explícitamente campos desconocidos en validate(). DRF por defecto los ignora
    silenciosamente; aquí se implementa whitelist real comparando initial_data contra
    los campos declarados.

Límites anti-DoS (M-3):
    indication → max_length=2000.
    items → max_length=20 (máximo 20 medicamentos por receta).

Clases B1.1:
    MedicationSearchOutputSerializer — forma la respuesta del endpoint de búsqueda.
    MedicationCreateInputSerializer  — valida la entrada para crear un Medication custom.
    MedicationCreateOutputSerializer — forma la respuesta tras crear un Medication.

Clases B1.2:
    PrescriptionItemInputSerializer  — valida un renglón de tratamiento al crear.
    PrescriptionItemOutputSerializer — forma un renglón de tratamiento en salida.
    PrescriptionCreateInputSerializer — valida la entrada para crear una receta.
    PrescriptionListOutputSerializer  — forma el historial de recetas (lista, sin detalle completo).
    PrescriptionDetailOutputSerializer — forma el detalle completo (con items, doctor, snapshot).
    PrescriptionCancelInputSerializer — valida la entrada para anular una receta.
"""

from rest_framework import serializers

from apps.recetas.models import MedicationForm


def _reject_unknown_fields(serializer: serializers.Serializer, data: dict) -> None:  # type: ignore[type-arg]
    """Levanta ValidationError si `data` contiene claves no declaradas en el serializer.

    Implementa whitelist de campos (M-4): rechaza mass-assignment de campos no
    declarados explícitamente. Mismo patrón que apps/expediente/serializers.py.

    Args:
        serializer: instancia del serializer que define los campos permitidos.
        data:       datos de entrada (request.data o dict del ítem anidado).

    Raises:
        serializers.ValidationError: si hay campos desconocidos.
    """
    declared = set(serializer.fields.keys())
    received = set(data.keys())
    unknown = received - declared
    if unknown:
        raise serializers.ValidationError(
            {field: ["Campo no permitido."] for field in sorted(unknown)}
        )


class MedicationSearchOutputSerializer(serializers.Serializer):
    """Serializer de salida para un ítem del autocompletado de medicamentos.

    Marca el origen con `source`: "global" (catálogo Maily) o "custom" (de la clínica).
    El frontend usa `source` para diferenciación visual.
    """

    id = serializers.CharField()
    generic_name = serializers.CharField()
    commercial_name = serializers.CharField()
    form = serializers.CharField()
    concentration = serializers.CharField()
    presentation = serializers.CharField()
    source = serializers.ChoiceField(choices=["global", "custom"])


class MedicationCreateInputSerializer(serializers.Serializer):
    """Serializer de entrada para crear un Medication custom.

    Valida:
    - generic_name: requerido, no vacío, max 200 chars.
    - form: requerido, debe ser uno de MedicationForm.choices.
    - commercial_name: opcional, max 200 chars.
    - concentration: opcional, max 100 chars.
    - presentation: opcional, max 200 chars.

    is_active NO se expone: es True siempre al crear.
    tenant/created_by son del contexto, no del input del usuario.
    """

    generic_name = serializers.CharField(
        max_length=200,
        help_text="Nombre genérico del medicamento (requerido).",
    )
    form = serializers.ChoiceField(
        choices=MedicationForm.choices,
        help_text="Forma farmacéutica.",
    )
    commercial_name = serializers.CharField(
        max_length=200,
        required=False,
        allow_blank=True,
        default="",
        help_text="Nombre comercial de referencia (opcional).",
    )
    concentration = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        default="",
        help_text="Concentración del principio activo (opcional). Ej: '500 mg'.",
    )
    presentation = serializers.CharField(
        max_length=200,
        required=False,
        allow_blank=True,
        default="",
        help_text="Presentación comercial (opcional). Ej: 'Caja con 20 tabletas'.",
    )

    def validate_generic_name(self, value: str) -> str:
        """Rechaza generic_name que sea solo espacios."""
        stripped = value.strip()
        if not stripped:
            raise serializers.ValidationError(
                "El nombre genérico no puede estar vacío o contener solo espacios."
            )
        return stripped


class MedicationCreateOutputSerializer(serializers.Serializer):
    """Serializer de salida para un Medication custom recién creado."""

    id = serializers.UUIDField()
    generic_name = serializers.CharField()
    commercial_name = serializers.CharField()
    form = serializers.CharField()
    concentration = serializers.CharField()
    presentation = serializers.CharField()
    is_active = serializers.BooleanField()
    created_at = serializers.DateTimeField()


# ---------------------------------------------------------------------------
# B1.2 — Receta médica
# ---------------------------------------------------------------------------


class PrescriptionItemInputSerializer(serializers.Serializer):
    """Valida un renglón de tratamiento al crear una receta.

    `medication_name` e `indication` son requeridos (DR-7 + regla de negocio).
    Los campos de snapshot (presentation, form, concentration) son opcionales:
    el médico puede no tenerlos si escribe en texto libre.
    Los FK al catálogo (global_medication_id, medication_id) son solo trazabilidad.

    Campos desconocidos son rechazados explícitamente en validate() (M-4).
    DRF NO los rechaza automáticamente; hay que implementarlo en validate().

    Límites anti-DoS (M-3):
        indication: max_length=2000 (campo de texto largo del médico).
    """

    medication_name = serializers.CharField(
        max_length=200,
        help_text="Nombre del medicamento (requerido). Snapshot inmutable.",
    )
    indication = serializers.CharField(
        max_length=2000,  # M-3: límite anti-DoS para campo de texto libre.
        help_text="Indicación completa: dosis, frecuencia y duración (requerido).",
    )
    medication_presentation = serializers.CharField(
        max_length=200,
        required=False,
        allow_blank=True,
        default="",
        help_text="Presentación del medicamento (snapshot, opcional).",
    )
    medication_form = serializers.CharField(
        max_length=20,
        required=False,
        allow_blank=True,
        default="",
        help_text="Forma farmacéutica (snapshot, opcional).",
    )
    medication_concentration = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        default="",
        help_text="Concentración del medicamento (snapshot, opcional).",
    )
    quantity = serializers.CharField(
        max_length=50,
        required=False,
        allow_blank=True,
        default="",
        help_text="Cantidad a dispensar (opcional).",
    )
    global_medication_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="UUID del GlobalMedication asociado (opcional, solo trazabilidad).",
    )
    medication_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="UUID del Medication custom asociado (opcional, solo trazabilidad).",
    )

    def validate_medication_name(self, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise serializers.ValidationError(
                "El nombre del medicamento no puede estar vacío."
            )
        return stripped

    def validate_indication(self, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise serializers.ValidationError(
                "La indicación no puede estar vacía."
            )
        return stripped

class PrescriptionCreateInputSerializer(serializers.Serializer):
    """Valida la entrada para crear una receta médica.

    Reglas:
    - `items` es requerido, mínimo 1 y máximo 20 elementos (M-3: anti-DoS).
    - `recommendations` es opcional (máx 5000 chars).
    - `appointment_id` y `evolution_note_id` son opcionales.
    - No se acepta `doctor_id` en el body: el doctor es el del perfil activo del usuario.
    - No se acepta `patient_id` en el body: viene de la URL.
    - Campos desconocidos son rechazados explícitamente en validate() (M-4).
      DRF NO los rechaza automáticamente; hay que implementarlo en validate().
    """

    items = serializers.ListField(
        child=PrescriptionItemInputSerializer(),
        min_length=1,
        max_length=20,  # M-3: máximo 20 medicamentos por receta (anti-DoS).
        help_text="Lista de renglones de tratamiento. Mínimo 1, máximo 20.",
    )
    recommendations = serializers.CharField(
        max_length=5000,
        required=False,
        allow_blank=True,
        default="",
        help_text="Recomendaciones generales al paciente (opcional).",
    )
    appointment_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="UUID de la cita asociada (opcional).",
    )
    evolution_note_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="UUID de la nota de evolución asociada (opcional).",
    )

    def validate(self, attrs: dict) -> dict:  # type: ignore[override]
        """M-4: Rechaza campos desconocidos en el root y en cada ítem.

        DRF ignora silenciosamente los campos extra; aquí implementamos whitelist real.
        Para el root: comparamos initial_data contra fields declarados.
        Para cada ítem: comparamos cada dict raw contra los fields del child serializer.
        """
        # --- Whitelist root ---
        _reject_unknown_fields(self, self.initial_data)  # type: ignore[arg-type]

        # --- Whitelist de cada ítem (child serializer no tiene initial_data en ListField) ---
        item_child = PrescriptionItemInputSerializer()
        declared_item_fields = set(item_child.fields.keys())
        raw_items = self.initial_data.get("items", []) if isinstance(self.initial_data, dict) else []  # type: ignore[union-attr]
        for idx, raw_item in enumerate(raw_items):
            if not isinstance(raw_item, dict):
                continue
            unknown = set(raw_item.keys()) - declared_item_fields
            if unknown:
                raise serializers.ValidationError(
                    {f"items[{idx}]": {field: ["Campo no permitido."] for field in sorted(unknown)}}
                )

        return attrs


class PrescriptionItemOutputSerializer(serializers.Serializer):
    """Serializer de salida para un renglón de tratamiento."""

    id = serializers.UUIDField()
    order = serializers.IntegerField()
    medication_name = serializers.CharField()
    medication_presentation = serializers.CharField()
    medication_form = serializers.CharField()
    medication_concentration = serializers.CharField()
    indication = serializers.CharField()
    quantity = serializers.CharField()
    global_medication_id = serializers.UUIDField(allow_null=True)
    medication_id = serializers.UUIDField(allow_null=True)


class _DoctorBriefSerializer(serializers.Serializer):
    """Datos mínimos del médico para la receta."""

    id = serializers.UUIDField()
    full_name = serializers.SerializerMethodField()
    cedula_profesional = serializers.CharField()
    specialty = serializers.CharField()

    def get_full_name(self, obj: object) -> str:
        try:
            return obj.membership.user.get_full_name()  # type: ignore[union-attr]
        except AttributeError:
            return ""


class PrescriptionListOutputSerializer(serializers.Serializer):
    """Serializer de salida para el historial de recetas (lista).

    No incluye los ítems completos ni el vitals_snapshot para mantener
    la respuesta liviana en el listado. El detalle completo usa
    PrescriptionDetailOutputSerializer.
    """

    id = serializers.UUIDField()
    folio = serializers.IntegerField()
    issued_at = serializers.DateTimeField()
    status = serializers.CharField()
    recommendations = serializers.CharField()
    doctor = _DoctorBriefSerializer()
    items_count = serializers.SerializerMethodField()
    cancelled_at = serializers.DateTimeField(allow_null=True)
    cancellation_reason = serializers.CharField()

    def get_items_count(self, obj: object) -> int:
        # M-5: usa len() en lugar de .count() para aprovechar el prefetch_related
        # ya cargado por prescription_list. .count() dispararía una query adicional
        # por cada receta en el listado (N+1). len() opera sobre el cache de Python.
        try:
            return len(obj.items.all())  # type: ignore[union-attr]
        except AttributeError:
            return 0


class PrescriptionDetailOutputSerializer(serializers.Serializer):
    """Serializer de salida completo para el detalle de una receta.

    Incluye: folio, fechas, doctor (cédula + especialidad), paciente UUID,
    items ordenados, vitals_snapshot, estado de anulación.
    Diseñado para "copiar de previa": el frontend hace GET de este endpoint
    y prellena el formulario de la nueva receta.
    """

    id = serializers.UUIDField()
    folio = serializers.IntegerField()
    issued_at = serializers.DateTimeField()
    status = serializers.CharField()
    recommendations = serializers.CharField()
    vitals_snapshot = serializers.JSONField(allow_null=True)
    doctor = _DoctorBriefSerializer()
    patient_id = serializers.UUIDField()
    appointment_id = serializers.UUIDField(allow_null=True)
    evolution_note_id = serializers.UUIDField(allow_null=True)
    items = PrescriptionItemOutputSerializer(many=True)
    cancelled_at = serializers.DateTimeField(allow_null=True)
    cancelled_by_id = serializers.UUIDField(allow_null=True)
    cancellation_reason = serializers.CharField()
    created_at = serializers.DateTimeField()


class PrescriptionCancelInputSerializer(serializers.Serializer):
    """Valida la entrada para anular una receta.

    Solo acepta `reason` (motivo de anulación). Requerido y no puede estar vacío.
    """

    reason = serializers.CharField(
        max_length=500,
        help_text="Motivo de la anulación (requerido).",
    )

    def validate_reason(self, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise serializers.ValidationError(
                "El motivo de anulación no puede estar vacío."
            )
        return stripped
