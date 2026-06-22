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
    VitalsInPrescriptionSerializer   — valida los signos vitales capturados en la receta.
    PrescriptionCreateInputSerializer — valida la entrada para crear una receta.
    PrescriptionListOutputSerializer  — forma el historial de recetas (lista, sin detalle completo).
    PrescriptionDetailOutputSerializer — forma el detalle completo (con items, doctor, snapshot).
    PrescriptionCancelInputSerializer — valida la entrada para anular una receta.
"""

import re as _re

from rest_framework import serializers

from apps.recetas.models import (
    ControlledGroup,
    ItemKind,
    MedicationForm,
    PrescriptionFormat,
    RouteOfAdministration,
    SECTIONS_KEYS,
)

_HEX_RE = _re.compile(r"^#[0-9A-Fa-f]{6}$")
_LAYOUT_CHOICES: list[str] = [c[0] for c in PrescriptionFormat.BaseLayout.choices]
_FONT_CHOICES: list[str] = [c[0] for c in PrescriptionFormat.FontChoice.choices]
_LETTERHEAD_CHOICES: list[str] = [c[0] for c in PrescriptionFormat.LetterheadMode.choices]

_ROUTE_CHOICES: list[str] = [c[0] for c in RouteOfAdministration.choices]
_ITEM_KIND_CHOICES: list[str] = [c[0] for c in ItemKind.choices]
_CONTROLLED_GROUP_CHOICES: list[str] = [c[0] for c in ControlledGroup.choices]


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
    COFEPRIS F2: incluye `kind` y `controlled_group` para que el frontend
    aplique validación condicional del renglón y filtre por tipo.
    """

    id = serializers.CharField()
    generic_name = serializers.CharField()
    commercial_name = serializers.CharField()
    form = serializers.CharField()
    concentration = serializers.CharField()
    presentation = serializers.CharField()
    source = serializers.ChoiceField(choices=["global", "custom"])
    kind = serializers.CharField(default="medicamento")
    controlled_group = serializers.CharField(default="none")


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
    kind = serializers.ChoiceField(
        choices=_ITEM_KIND_CHOICES,
        required=False,
        default="medicamento",
        help_text="Tipo de ítem: medicamento, suero o terapia. COFEPRIS F2.",
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
    kind = serializers.CharField()
    controlled_group = serializers.CharField()
    is_active = serializers.BooleanField()
    created_at = serializers.DateTimeField()


# ---------------------------------------------------------------------------
# B1.2 — Receta médica
# ---------------------------------------------------------------------------


class PrescriptionItemInputSerializer(serializers.Serializer):
    """Valida un renglón de tratamiento al crear una receta.

    COFEPRIS F2 — validación condicional por kind:
        Cuando kind == "medicamento", los campos dose, frequency, route y duration
        son obligatorios (COFEPRIS exige renglón estructurado sin abreviaturas).
        Para kind == "suero" o "terapia" esos campos son opcionales.

    `medication_name` es siempre requerido (DR-7 — snapshot inmutable).
    `indication` pasa de obligatorio a opcional: ahora es nota/observación adicional.
        Se conserva para compatibilidad con recetas pre-F2 donde contiene la indicación
        completa en texto libre. El médico puede enviarlo vacío si usa el renglón COFEPRIS.

    Campos desconocidos son rechazados explícitamente en validate() (M-4).
    Límites anti-DoS (M-3): indication max_length=2000.
    """

    kind = serializers.ChoiceField(
        choices=_ITEM_KIND_CHOICES,
        required=False,
        default="medicamento",
        help_text="Tipo de ítem: medicamento, suero o terapia. COFEPRIS F2.",
    )
    medication_name = serializers.CharField(
        max_length=200,
        help_text="Nombre del medicamento/suero/terapia (requerido). Snapshot inmutable.",
    )
    # --- COFEPRIS F2: renglón estructurado ---
    dose = serializers.CharField(
        max_length=120,
        required=False,
        allow_blank=True,
        default="",
        help_text="Dosis sin abreviaturas. Obligatorio si kind=medicamento. COFEPRIS F2.",
    )
    frequency = serializers.CharField(
        max_length=120,
        required=False,
        allow_blank=True,
        default="",
        help_text="Frecuencia sin abreviaturas. Obligatorio si kind=medicamento. COFEPRIS F2.",
    )
    route = serializers.ChoiceField(
        choices=[""] + _ROUTE_CHOICES,
        required=False,
        allow_blank=True,
        default="",
        help_text="Vía de administración. Obligatorio si kind=medicamento. COFEPRIS F2.",
    )
    duration = serializers.CharField(
        max_length=120,
        required=False,
        allow_blank=True,
        default="",
        help_text="Duración del tratamiento sin abreviaturas. Obligatorio si kind=medicamento. COFEPRIS F2.",
    )
    # --- Nota adicional (antes campo obligatorio) ---
    indication = serializers.CharField(
        max_length=2000,  # M-3: límite anti-DoS
        required=False,
        allow_blank=True,
        default="",
        help_text=(
            "Nota u observación adicional (opcional). "
            "En recetas pre-F2 contiene la indicación completa por compatibilidad."
        ),
    )
    # --- Snapshot de catálogo ---
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

    def validate_route(self, value: str) -> str:
        """Permite vacío o un valor válido de RouteOfAdministration."""
        if value and value not in _ROUTE_CHOICES:
            raise serializers.ValidationError(
                f"Vía de administración inválida '{value}'. "
                f"Las válidas son: {', '.join(_ROUTE_CHOICES)}."
            )
        return value

    def validate(self, attrs: dict) -> dict:  # type: ignore[override]
        """Validación condicional COFEPRIS: si kind=medicamento, dose/frequency/route/duration son obligatorios."""
        kind = attrs.get("kind", "medicamento")
        if kind == "medicamento":
            errors: dict[str, list[str]] = {}
            if not attrs.get("dose", "").strip():
                errors["dose"] = ["Obligatorio para medicamentos (COFEPRIS). Indique la dosis sin abreviaturas."]
            if not attrs.get("frequency", "").strip():
                errors["frequency"] = ["Obligatorio para medicamentos (COFEPRIS). Indique la frecuencia sin abreviaturas."]
            if not attrs.get("route", "").strip():
                errors["route"] = ["Obligatorio para medicamentos (COFEPRIS). Indique la vía de administración."]
            if not attrs.get("duration", "").strip():
                errors["duration"] = ["Obligatorio para medicamentos (COFEPRIS). Indique la duración del tratamiento."]
            if errors:
                raise serializers.ValidationError(errors)
        return attrs

# ---------------------------------------------------------------------------
# Rangos fisiológicos — mismos que apps/expediente/serializers.py (D-EC-7).
# Se duplican aquí para evitar import circular entre apps y mantener
# la app recetas desacoplada de los internos de expediente.
# ---------------------------------------------------------------------------

_VITAL_RANGES: dict[str, tuple[float, float]] = {
    "weight_kg": (0.2, 500.0),
    "height_m": (0.2, 2.6),
    "heart_rate": (20, 300),
    "resp_rate": (5, 80),
    "systolic": (40, 300),
    "diastolic": (20, 200),
    "temperature_c": (30.0, 45.0),
    "oxygen_saturation": (50, 100),
    "glucose": (10, 1000),
}

#: Claves permitidas dentro del objeto `vitals` en el body de la receta.
_VITALS_ALLOWED_KEYS: frozenset[str] = frozenset(_VITAL_RANGES.keys())


class VitalsInPrescriptionSerializer(serializers.Serializer):
    """Valida los signos vitales capturados por el médico al crear la receta.

    Todos los campos son opcionales: el médico puede enviar solo los que mide
    en el momento (p.ej. solo peso + talla para calcular IMC). Si se envía al
    menos un campo válido, el servicio construirá el vitals_snapshot con esos
    valores y descartará el snapshot de la última toma de enfermería.

    Rangos fisiológicos: idénticos a VitalSignsInputSerializer en expediente (D-EC-7).
    Claves desconocidas son rechazadas en validate() (M-4 whitelist).

    Nota: `measured_at` NO se acepta aquí (se genera automáticamente en el
    servicio con timezone.now() del momento de emisión de la receta).
    """

    weight_kg = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        required=False,
        allow_null=True,
        help_text="Peso en kg (rango: 0.2 – 500.0).",
    )
    height_m = serializers.DecimalField(
        max_digits=4,
        decimal_places=3,
        required=False,
        allow_null=True,
        help_text="Talla en metros (rango: 0.2 – 2.6).",
    )
    heart_rate = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Frecuencia cardíaca en lpm (rango: 20 – 300).",
    )
    resp_rate = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Frecuencia respiratoria en rpm (rango: 5 – 80).",
    )
    systolic = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Presión sistólica en mmHg (rango: 40 – 300).",
    )
    diastolic = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Presión diastólica en mmHg (rango: 20 – 200).",
    )
    temperature_c = serializers.DecimalField(
        max_digits=4,
        decimal_places=1,
        required=False,
        allow_null=True,
        help_text="Temperatura en °C (rango: 30.0 – 45.0).",
    )
    oxygen_saturation = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Saturación de oxígeno en % (rango: 50 – 100).",
    )
    glucose = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Glucosa en mg/dL (rango: 10 – 1000).",
    )

    def _validate_range(self, field: str, value: object) -> None:
        """Valida que `value` esté dentro del rango fisiológico plausible para `field`."""
        if value is None:
            return
        lo, hi = _VITAL_RANGES[field]
        if not (lo <= float(value) <= hi):  # type: ignore[arg-type]
            raise serializers.ValidationError(
                {field: f"Valor fuera del rango fisiológico plausible ({lo} – {hi})."}
            )

    def validate_weight_kg(self, value: object) -> object:
        self._validate_range("weight_kg", value)
        return value

    def validate_height_m(self, value: object) -> object:
        self._validate_range("height_m", value)
        return value

    def validate_heart_rate(self, value: object) -> object:
        self._validate_range("heart_rate", value)
        return value

    def validate_resp_rate(self, value: object) -> object:
        self._validate_range("resp_rate", value)
        return value

    def validate_systolic(self, value: object) -> object:
        self._validate_range("systolic", value)
        return value

    def validate_diastolic(self, value: object) -> object:
        self._validate_range("diastolic", value)
        return value

    def validate_temperature_c(self, value: object) -> object:
        self._validate_range("temperature_c", value)
        return value

    def validate_oxygen_saturation(self, value: object) -> object:
        self._validate_range("oxygen_saturation", value)
        return value

    def validate_glucose(self, value: object) -> object:
        self._validate_range("glucose", value)
        return value

    def validate(self, attrs: dict) -> dict:  # type: ignore[override]
        """M-4: Rechaza claves desconocidas dentro del objeto vitals.

        Cuando VitalsInPrescriptionSerializer actúa como serializer raíz (tests
        de unidad), `self.initial_data` está disponible y se usa para la whitelist.
        Cuando actúa como campo anidado dentro de PrescriptionCreateInputSerializer,
        `initial_data` no está disponible en el nivel del child; la whitelist se
        aplica en el validate() del padre usando `_VITALS_ALLOWED_KEYS`.
        """
        initial = getattr(self, "initial_data", None)
        if initial is not None and isinstance(initial, dict):
            _reject_unknown_fields(self, initial)  # type: ignore[arg-type]
        return attrs


class PrescriptionCreateInputSerializer(serializers.Serializer):
    """Valida la entrada para crear una receta médica.

    Reglas:
    - `items` es requerido, mínimo 1 y máximo 20 elementos (M-3: anti-DoS).
    - `recommendations` es opcional (máx 5000 chars).
    - `diagnosis` es opcional por compatibilidad, pero recomendado (COFEPRIS F2).
    - `appointment_id` y `evolution_note_id` son opcionales.
    - No se acepta `doctor_id` en el body: el doctor es el del perfil activo del usuario.
    - No se acepta `patient_id` en el body: viene de la URL.
    - Campos desconocidos son rechazados explícitamente en validate() (M-4).
    """

    items = serializers.ListField(
        child=PrescriptionItemInputSerializer(),
        min_length=1,
        max_length=20,  # M-3: máximo 20 medicamentos por receta (anti-DoS).
        help_text="Lista de renglones de tratamiento. Mínimo 1, máximo 20.",
    )
    diagnosis = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        default="",
        help_text=(
            "Diagnóstico del paciente (recomendado, COFEPRIS F2). "
            "COFEPRIS considera 'receta sin diagnóstico' como error invalidante."
        ),
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
    # F6 — folio del recetario especial COFEPRIS (requerido si hay controlados)
    controlled_folio = serializers.CharField(
        max_length=60,
        required=False,
        allow_blank=True,
        default="",
        help_text=(
            "Folio del recetario especial emitido por COFEPRIS (F6). "
            "El médico lo ingresa manualmente. "
            "Requerido cuando la receta contiene medicamentos controlados (grupo I–V). "
            "COFEPRIS emite el recetario especial fuera del sistema."
        ),
    )
    # Signos vitales capturados por el médico en la receta.
    # Todos los campos son opcionales. Si se envía al menos uno, el servicio
    # construye vitals_snapshot con esos valores (+ IMC si hay peso y talla)
    # y descarta el snapshot de la última toma de enfermería.
    # Si no se envía `vitals`, el comportamiento anterior se mantiene:
    #   snapshot = última toma de enfermería (o None si no hay).
    # Precedencia: vitals capturados en la receta > última toma de enfermería.
    vitals = VitalsInPrescriptionSerializer(
        required=False,
        allow_null=True,
        default=None,
        help_text=(
            "Signos vitales capturados por el médico al emitir la receta (opcional). "
            "Si se provee con al menos un campo, sobreescribe el snapshot de la "
            "última toma de enfermería. Claves: weight_kg, height_m, heart_rate, "
            "resp_rate, systolic, diastolic, temperature_c, oxygen_saturation, glucose. "
            "Todas las claves son opcionales. Claves desconocidas son rechazadas."
        ),
    )

    def validate(self, attrs: dict) -> dict:  # type: ignore[override]
        """M-4: Rechaza campos desconocidos en el root, en cada ítem y en vitals.

        DRF ignora silenciosamente los campos extra; aquí implementamos whitelist real.
        Para el root: comparamos initial_data contra fields declarados.
        Para cada ítem: comparamos cada dict raw contra los fields del child serializer.
        Para vitals: VitalsInPrescriptionSerializer ya rechaza claves desconocidas
          en su propio validate(), pero también verificamos aquí a nivel de root.
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

        # --- Whitelist de vitals (defensa adicional en profundidad) ---
        raw_vitals = self.initial_data.get("vitals") if isinstance(self.initial_data, dict) else None  # type: ignore[union-attr]
        if raw_vitals is not None and isinstance(raw_vitals, dict):
            unknown_vitals = set(raw_vitals.keys()) - _VITALS_ALLOWED_KEYS
            if unknown_vitals:
                raise serializers.ValidationError(
                    {
                        "vitals": {
                            field: ["Campo no permitido en vitals."]
                            for field in sorted(unknown_vitals)
                        }
                    }
                )

        return attrs


class PrescriptionItemOutputSerializer(serializers.Serializer):
    """Serializer de salida para un renglón de tratamiento."""

    id = serializers.UUIDField()
    order = serializers.IntegerField()
    kind = serializers.CharField()
    medication_name = serializers.CharField()
    medication_presentation = serializers.CharField()
    medication_form = serializers.CharField()
    medication_concentration = serializers.CharField()
    # COFEPRIS F2: renglón estructurado
    dose = serializers.CharField()
    frequency = serializers.CharField()
    route = serializers.CharField()
    duration = serializers.CharField()
    # Nota/observación (opcional; antes era obligatorio)
    indication = serializers.CharField()
    quantity = serializers.CharField()
    global_medication_id = serializers.UUIDField(allow_null=True)
    medication_id = serializers.UUIDField(allow_null=True)
    # F6: snapshot del grupo COFEPRIS
    controlled_group = serializers.CharField()


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
    diagnosis = serializers.CharField()
    recommendations = serializers.CharField()
    doctor = _DoctorBriefSerializer()
    items_count = serializers.SerializerMethodField()
    cancelled_at = serializers.DateTimeField(allow_null=True)
    cancellation_reason = serializers.CharField()
    # F6: medicamentos controlados (resumen en lista)
    controlled_folio = serializers.CharField()
    valid_until = serializers.DateTimeField(allow_null=True)

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
    diagnosis = serializers.CharField()
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
    # F6: medicamentos controlados
    controlled_folio = serializers.CharField()
    valid_until = serializers.DateTimeField(allow_null=True)
    is_controlled = serializers.BooleanField()


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


# ---------------------------------------------------------------------------
# F3 — PrescriptionFormat serializers
# ---------------------------------------------------------------------------


class SectionsField(serializers.DictField):
    """Campo JSON de secciones con validación de whitelist y tipos booleanos.

    Acepta un diccionario con claves en SECTIONS_KEYS y valores bool.
    Rechaza claves desconocidas y valores no booleanos.
    """

    child = serializers.BooleanField()

    def to_internal_value(self, data: object) -> dict[str, bool]:
        if not isinstance(data, dict):
            raise serializers.ValidationError("sections debe ser un objeto JSON.")
        unknown = set(data.keys()) - SECTIONS_KEYS  # type: ignore[arg-type]
        if unknown:
            raise serializers.ValidationError(
                f"Claves no permitidas en sections: {', '.join(sorted(unknown))}. "
                f"Permitidas: {', '.join(sorted(SECTIONS_KEYS))}."
            )
        result: dict[str, bool] = {}
        for key, val in data.items():  # type: ignore[union-attr]
            if not isinstance(val, bool):
                raise serializers.ValidationError(
                    f"El valor de sections.{key} debe ser booleano (true/false)."
                )
            result[key] = val
        return result


class PrescriptionFormatCreateInputSerializer(serializers.Serializer):
    """Valida la entrada para crear un PrescriptionFormat.

    Campos aceptados: name, base_layout, accent_color, font, sections,
    letterhead_mode, is_default, doctor_id.

    Campos NO aceptados aquí: is_authorized (solo admin, endpoint propio),
    is_active (inmutable en create, siempre True).
    """

    name = serializers.CharField(max_length=120, allow_blank=False)
    base_layout = serializers.ChoiceField(choices=_LAYOUT_CHOICES, default="digital")
    accent_color = serializers.CharField(max_length=7, default="#9A7B1E")
    font = serializers.ChoiceField(choices=_FONT_CHOICES, default="helvetica")
    sections = SectionsField(required=False, default=dict)
    letterhead_mode = serializers.ChoiceField(choices=_LETTERHEAD_CHOICES, default="digital")
    is_default = serializers.BooleanField(default=False)
    doctor_id = serializers.UUIDField(required=False, allow_null=True, default=None)

    def validate_accent_color(self, value: str) -> str:
        if not _HEX_RE.match(value):
            raise serializers.ValidationError(
                "El color de acento debe tener el formato #RRGGBB (ej: #9A7B1E)."
            )
        return value

    def validate(self, attrs: dict) -> dict:
        _reject_unknown_fields(self, self.initial_data)  # type: ignore[arg-type]
        return attrs


class PrescriptionFormatUpdateInputSerializer(serializers.Serializer):
    """Valida la entrada PATCH para actualizar un PrescriptionFormat.

    Todos los campos son opcionales. is_authorized solo lo puede cambiar
    un admin (la view lo controla pasando is_admin al servicio).
    """

    name = serializers.CharField(max_length=120, allow_blank=False, required=False)
    base_layout = serializers.ChoiceField(choices=_LAYOUT_CHOICES, required=False)
    accent_color = serializers.CharField(max_length=7, required=False)
    font = serializers.ChoiceField(choices=_FONT_CHOICES, required=False)
    sections = SectionsField(required=False)
    letterhead_mode = serializers.ChoiceField(choices=_LETTERHEAD_CHOICES, required=False)
    is_default = serializers.BooleanField(required=False)
    doctor_id = serializers.UUIDField(required=False, allow_null=True)
    is_authorized = serializers.BooleanField(required=False)

    def validate_accent_color(self, value: str) -> str:
        if not _HEX_RE.match(value):
            raise serializers.ValidationError(
                "El color de acento debe tener el formato #RRGGBB (ej: #9A7B1E)."
            )
        return value

    def validate(self, attrs: dict) -> dict:
        _reject_unknown_fields(self, self.initial_data)  # type: ignore[arg-type]
        return attrs


class PrescriptionFormatOutputSerializer(serializers.Serializer):
    """Forma la respuesta de un PrescriptionFormat (lista y detalle)."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    base_layout = serializers.CharField()
    accent_color = serializers.CharField()
    font = serializers.CharField()
    sections = serializers.DictField(child=serializers.BooleanField())
    letterhead_mode = serializers.CharField()
    is_default = serializers.BooleanField()
    is_authorized = serializers.BooleanField()
    is_active = serializers.BooleanField()
    doctor_id = serializers.UUIDField(allow_null=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


# ---------------------------------------------------------------------------
# F5 — Verificación pública de autenticidad de receta
# ---------------------------------------------------------------------------


class PrescriptionVerifyOutputSerializer(serializers.Serializer):
    """Respuesta del endpoint público de verificación de autenticidad (F5+F6).

    Política de privacidad estricta (información de salud):
      EXPONE: folio, estado (vigente/anulada), fecha de emisión,
              nombre del médico + cédula profesional, nombre comercial de la clínica,
              controlado (bool), vigencia (datetime | null — sin PII del paciente).
      NUNCA expone: nombre del paciente, medicamentos, diagnóstico, signos vitales,
                    ni cualquier otro dato clínico o PII del paciente.

    F6 — medicamentos controlados:
      controlado: True si la receta contiene al menos un medicamento controlado.
      vigencia:   valid_until de la receta (datetime ISO-8601) o null.
                  Permite a la farmacia verificar si la receta sigue vigente.
                  No expone qué medicamentos son controlados ni el grupo exacto.
    """

    folio = serializers.IntegerField()
    estado = serializers.CharField()
    fecha_emision = serializers.DateField()
    medico = serializers.DictField()
    clinica = serializers.CharField()
    # F6: datos de controlado sin PII
    controlado = serializers.BooleanField()
    vigencia = serializers.DateTimeField(allow_null=True)
