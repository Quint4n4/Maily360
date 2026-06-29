"""
Serializers de la app expediente (sub-fases A1, A2, A3 y A4).

Regla: serializers solo validan/formatean. Cero lógica de negocio aquí.
Separados en InputSerializer y OutputSerializer (nunca uno solo para todo).

D-EC-7 — Validación estricta:
  Los serializers rechazan campos no declarados y valores fuera de choices.
  Se implementa sobreescribiendo validate() para detectar claves extra.

Clases A1:
    AllergyInputSerializer         — valida la entrada para crear una alergia.
    AllergyOutputSerializer        — forma la respuesta de Allergy (lectura).

Clases A2:
    MedicalHistoryInputSerializer  — valida y delega la entrada de HC al upsert.
    MedicalHistoryOutputSerializer — forma la respuesta de MedicalHistory (lectura).

Clases A3:
    VitalSignsInputSerializer      — valida la entrada para crear una toma de signos.
    VitalSignsOutputSerializer     — forma la respuesta de VitalSignsRecord (lectura).
                                     Incluye el campo derivado `imc`.

Clases A4:
    EvolutionNoteInputSerializer   — valida la entrada para crear una nota de evolución.
    AddendumOutputSerializer       — forma la respuesta de Addendum.
    EvolutionNoteOutputSerializer  — forma la respuesta de EvolutionNote (con addenda).
    AddendumInputSerializer        — valida la entrada para crear un addendum.
    DiagnosisInputSerializer       — valida la entrada para crear un diagnóstico.
    DiagnosisOutputSerializer      — forma la respuesta de Diagnosis.

Nota MEDIO-4: PatientNom004InputSerializer y PatientNom004OutputSerializer
  fueron eliminados (código muerto). La validación NOM-004 del PATCH de Patient
  vive en PatientDetailApi.InputSerializer (apps/pacientes/views.py), que es la
  única fuente de verdad.
"""

import re
from decimal import Decimal
from typing import Any, Optional

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from rest_framework import serializers

from apps.expediente.models import (
    Addendum,
    Allergy,
    Diagnosis,
    DiagnosisKind,
    EvolutionImage,
    EvolutionNote,
    MedicalHistory,
    MedicalHistoryQuestion,
    QuestionFieldType,
    Severity,
    VitalSignsRecord,
    EXTRA_PARAMS_WHITELIST,
)
from apps.expediente.validators import (
    validate_exploracion_evolucion,
    validate_exploracion_fisica_basal,
    validate_gineco_obstetricos,
    validate_habitos_alimenticios,
    validate_heredo_familiares,
    validate_no_patologicos,
    validate_personales_patologicos,
)


# ---------------------------------------------------------------------------
# Constantes de validación
# ---------------------------------------------------------------------------

# B6: patrón CIE-10 estándar: letra mayúscula + 2 dígitos + subcategoría opcional.
# Ejemplos válidos: "J06", "J06.9", "A01.0", "Z00.00".
_CIE10_RE = re.compile(r"^[A-Z]\d{2}(\.\d{1,2})?$")


# ---------------------------------------------------------------------------
# Helpers de validación estricta (D-EC-7)
# ---------------------------------------------------------------------------


def _reject_unknown_fields(
    serializer: serializers.Serializer,
    data: dict,  # type: ignore[type-arg]
) -> None:
    """Levanta ValidationError si `data` contiene claves no declaradas en el serializer.

    Implementa la whitelist de campos (D-EC-7): rechaza mass-assignment de campos
    no declarados explícitamente.

    Args:
        serializer: instancia del serializer que define los campos permitidos.
        data:       datos de entrada (request.data).

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


# ---------------------------------------------------------------------------
# Allergy
# ---------------------------------------------------------------------------


class AllergyInputSerializer(serializers.Serializer):
    """Valida los datos de entrada para registrar una alergia nueva.

    D-EC-7: rechaza campos no declarados y choices inválidos.
    substance es obligatorio; reaction y severity son opcionales.
    """

    substance = serializers.CharField(max_length=160)
    reaction = serializers.CharField(max_length=255, required=False, default="", allow_blank=True)
    severity = serializers.ChoiceField(
        choices=Severity.choices,
        required=False,
        default="",
        allow_blank=True,
    )

    def validate(self, attrs: dict) -> dict:  # type: ignore[override]
        """Validación de nivel serializer: rechaza campos desconocidos (D-EC-7)."""
        _reject_unknown_fields(self, self.initial_data)  # type: ignore[arg-type]
        return attrs

    def validate_substance(self, value: str) -> str:
        """Normaliza y valida que la sustancia no esté vacía."""
        value = value.strip()
        if not value:
            raise serializers.ValidationError("La sustancia no puede estar vacía.")
        return value


class AllergyOutputSerializer(serializers.ModelSerializer):
    """Serializer de salida para Allergy.

    Incluye severity_display para la etiqueta legible.
    No expone deleted_at, created_by_id ni tenant_id (campos internos).
    """

    severity_display = serializers.CharField(source="get_severity_display", read_only=True)

    class Meta:
        model = Allergy
        fields = [
            "id",
            "patient_id",
            "substance",
            "reaction",
            "severity",
            "severity_display",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# MedicalHistory (A2)
# ---------------------------------------------------------------------------

# Campos de nivel raíz permitidos en el InputSerializer de HC (D-EC-7 whitelist).
_MEDICAL_HISTORY_INPUT_FIELDS: frozenset[str] = frozenset(
    {
        "heredo_familiares",
        "personales_patologicos",
        "no_patologicos",
        "habitos_alimenticios",
        "gineco_obstetricos",
        "exploracion_fisica_basal",
        "antecedentes_importancia",
        "padecimiento_actual",
        "tratamientos_actuales",
        "prioridad_analisis",
        "custom_answers",
    }
)


class MedicalHistoryInputSerializer(serializers.Serializer):
    """Valida la entrada para el upsert de la Historia Clínica formal (PUT).

    D-EC-7: rechaza campos de nivel raíz no declarados y delega la validación
    de cada bloque JSON a los validadores de schema en validators.py.

    D-EC-8: todos los bloques son opcionales (la HC se puede guardar incompleta).
    Los bloques no provistos se pasan como None al service, que los omite.

    Validación condicional por sexo (bloque gineco_obstetricos):
    Si el paciente tiene sexo M o X y llega contenido no vacío en gineco_obstetricos,
    se rechaza con 400. Requiere acceso al paciente: se pasa vía context['patient'].
    """

    heredo_familiares = serializers.JSONField(required=False, default=None, allow_null=True)
    personales_patologicos = serializers.JSONField(required=False, default=None, allow_null=True)
    no_patologicos = serializers.JSONField(required=False, default=None, allow_null=True)
    habitos_alimenticios = serializers.JSONField(required=False, default=None, allow_null=True)
    gineco_obstetricos = serializers.JSONField(required=False, default=None, allow_null=True)
    exploracion_fisica_basal = serializers.JSONField(required=False, default=None, allow_null=True)
    # MEDIO-2: max_length explícito para prevenir payloads gigantes (DoS).
    # Los tres primeros campos son narrativos y pueden ser extensos pero razonables:
    # 10 000 caracteres (~5 páginas de texto clínico denso) es suficiente en práctica.
    # prioridad_analisis es más corta (resumen analítico): 5 000 caracteres.
    antecedentes_importancia = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=10_000
    )
    padecimiento_actual = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=10_000
    )
    tratamientos_actuales = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=10_000
    )
    prioridad_analisis = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=5_000
    )
    # Fase 2: respuestas a preguntas extra configurables por la clínica.
    # El service filtra las claves para quedarse solo con preguntas activas del tenant.
    custom_answers = serializers.JSONField(required=False, default=dict)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Validación de nivel raíz: rechaza campos desconocidos (D-EC-7) y
        valida el schema de cada bloque JSON provisto.

        La validación condicional por sexo del bloque gineco_obstetricos también
        se ejecuta aquí porque requiere acceso al paciente (vía context).
        """
        # D-EC-7: rechazar campos de nivel raíz no declarados.
        _reject_unknown_fields(self, self.initial_data)  # type: ignore[arg-type]

        # Validar schema de cada bloque que llegue (bloques None se saltan).
        if attrs.get("heredo_familiares") is not None:
            validate_heredo_familiares(attrs["heredo_familiares"])

        if attrs.get("personales_patologicos") is not None:
            validate_personales_patologicos(attrs["personales_patologicos"])

        if attrs.get("no_patologicos") is not None:
            validate_no_patologicos(attrs["no_patologicos"])

        if attrs.get("habitos_alimenticios") is not None:
            validate_habitos_alimenticios(attrs["habitos_alimenticios"])

        if attrs.get("gineco_obstetricos") is not None:
            gineco = attrs["gineco_obstetricos"]
            # Validación condicional por sexo (D-EC instrucciones).
            patient = self.context.get("patient")

            # BAJO-1: fail-closed. Si hay datos en gineco_obstetricos y no hay
            # paciente en el contexto, no se puede verificar el sexo → 400.
            # Esto previene que un bug de configuración (view que olvida pasar el
            # paciente al context) deje pasar datos gineco sin validar.
            if gineco and patient is None:
                raise serializers.ValidationError(
                    {
                        "gineco_obstetricos": (
                            "No se pudo verificar el sexo del paciente."
                        )
                    }
                )

            if patient is not None and gineco:
                from apps.pacientes.models import Sex  # noqa: PLC0415
                if patient.sex != Sex.FEMALE:
                    raise serializers.ValidationError(
                        {
                            "gineco_obstetricos": (
                                "Bloque gineco-obstétrico solo aplica a "
                                "pacientes de sexo femenino."
                            )
                        }
                    )
            validate_gineco_obstetricos(gineco)

        if attrs.get("exploracion_fisica_basal") is not None:
            validate_exploracion_fisica_basal(attrs["exploracion_fisica_basal"])

        return attrs


class MedicalHistoryOutputSerializer(serializers.ModelSerializer):
    """Serializer de salida para MedicalHistory.

    Expone todos los bloques JSON y los campos de texto del padecimiento.
    Incluye custom_answers (respuestas a preguntas extra) y active_questions
    (catálogo de preguntas activas del tenant para renderizar el formulario).
    No expone deleted_at, created_by_id ni tenant_id (campos internos).

    Anti-N+1: active_questions usa el TenantManager que ya está configurado;
    el QuerySet se evalúa una sola vez por serialización.
    """

    active_questions = serializers.SerializerMethodField(
        help_text="Lista de preguntas extra activas del tenant (para renderizar el formulario)."
    )

    class Meta:
        model = MedicalHistory
        fields = [
            "id",
            "patient_id",
            "heredo_familiares",
            "personales_patologicos",
            "no_patologicos",
            "habitos_alimenticios",
            "gineco_obstetricos",
            "exploracion_fisica_basal",
            "antecedentes_importancia",
            "padecimiento_actual",
            "tratamientos_actuales",
            "prioridad_analisis",
            "custom_answers",
            "active_questions",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_active_questions(self, obj: MedicalHistory) -> list[dict[str, Any]]:
        """Retorna las preguntas activas del tenant para renderizar el formulario.

        Usa el selector del módulo (filtra por TenantManager). Sin N+1:
        una sola query por serialización de una HC.
        """
        from apps.expediente.selectors import medical_history_questions_list  # noqa: PLC0415

        qs = medical_history_questions_list(only_active=True)
        return MedicalHistoryQuestionOutputSerializer(qs, many=True).data


# ---------------------------------------------------------------------------
# VitalSignsRecord (A3)
# ---------------------------------------------------------------------------

# Rangos fisiológicos plausibles (D-EC-7). Los valores fuera de estos rangos
# son imposibles o de altísima improbabilidad clínica y se rechazan con 400.
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

# Límite superior para parámetros extensibles del legacy (mg/dL o mmol/L).
# Se usa un tope amplio pero razonable para descartar entradas de teclado erradas.
_EXTRA_MAX: float = 10_000.0


class VitalSignsInputSerializer(serializers.Serializer):
    """Valida los datos de entrada para crear una toma de signos vitales.

    D-EC-7: rechaza campos no declarados en la raíz y claves no autorizadas en
    extra_params. Valida rangos fisiológicos plausibles en cada parámetro numérico.

    Append-only: este serializer solo se usa en POST (creación). No existe PATCH.

    Validaciones especiales:
        - measured_at no puede ser futuro.
        - systolic > diastolic si ambos están presentes.
        - extra_params: solo las claves en EXTRA_PARAMS_WHITELIST; cada valor debe
          ser numérico positivo con un tope amplio (_EXTRA_MAX).
    """

    measured_at = serializers.DateTimeField(
        required=False,
        help_text="Momento de la toma (ISO 8601). Default: ahora. No puede ser futuro.",
    )
    weight_kg = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, allow_null=True
    )
    height_m = serializers.DecimalField(
        max_digits=4, decimal_places=3, required=False, allow_null=True
    )
    heart_rate = serializers.IntegerField(required=False, allow_null=True)
    resp_rate = serializers.IntegerField(required=False, allow_null=True)
    systolic = serializers.IntegerField(required=False, allow_null=True)
    diastolic = serializers.IntegerField(required=False, allow_null=True)
    temperature_c = serializers.DecimalField(
        max_digits=4, decimal_places=1, required=False, allow_null=True
    )
    oxygen_saturation = serializers.IntegerField(required=False, allow_null=True)
    glucose = serializers.IntegerField(required=False, allow_null=True)
    extra_params = serializers.JSONField(required=False, default=dict)
    notes = serializers.CharField(
        max_length=255, required=False, default="", allow_blank=True
    )
    appointment_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="UUID de la cita asociada (opcional).",
    )

    def validate_measured_at(self, value: Any) -> Any:
        """Rechaza fechas futuras (D-EC-7)."""
        if value > timezone.now():
            raise serializers.ValidationError(
                "La fecha de la toma no puede ser futura."
            )
        return value

    def _validate_range(self, field: str, value: Any) -> None:
        """Valida que `value` esté dentro del rango fisiológico plausible para `field`."""
        if value is None:
            return
        lo, hi = _VITAL_RANGES[field]
        if not (lo <= float(value) <= hi):
            raise serializers.ValidationError(
                {field: f"Valor fuera del rango fisiológico plausible ({lo} – {hi})."}
            )

    def validate_weight_kg(self, value: Any) -> Any:
        self._validate_range("weight_kg", value)
        return value

    def validate_height_m(self, value: Any) -> Any:
        self._validate_range("height_m", value)
        return value

    def validate_heart_rate(self, value: Any) -> Any:
        self._validate_range("heart_rate", value)
        return value

    def validate_resp_rate(self, value: Any) -> Any:
        self._validate_range("resp_rate", value)
        return value

    def validate_systolic(self, value: Any) -> Any:
        self._validate_range("systolic", value)
        return value

    def validate_diastolic(self, value: Any) -> Any:
        self._validate_range("diastolic", value)
        return value

    def validate_temperature_c(self, value: Any) -> Any:
        self._validate_range("temperature_c", value)
        return value

    def validate_oxygen_saturation(self, value: Any) -> Any:
        self._validate_range("oxygen_saturation", value)
        return value

    def validate_glucose(self, value: Any) -> Any:
        self._validate_range("glucose", value)
        return value

    def validate_extra_params(self, value: dict[str, Any]) -> dict[str, Any]:
        """Valida whitelist de claves y que los valores sean numéricos positivos."""
        if not isinstance(value, dict):
            raise serializers.ValidationError("Debe ser un objeto JSON.")
        unknown = set(value.keys()) - EXTRA_PARAMS_WHITELIST
        if unknown:
            raise serializers.ValidationError(
                f"Claves no permitidas en extra_params: {', '.join(sorted(unknown))}. "
                f"Claves válidas: {', '.join(sorted(EXTRA_PARAMS_WHITELIST))}."
            )
        for key, val in value.items():
            # MEDIO-1: isinstance(True, (int, float)) es True en Python; excluir bool
            # explícitamente para evitar que valores booleanos pasen como numéricos.
            # BAJO-1: exigir positivo estricto (val > 0) — 0 es fisiológicamente
            # imposible para cualquier parámetro de laboratorio o signo vital.
            if isinstance(val, bool) or not isinstance(val, (int, float)) or val <= 0:
                raise serializers.ValidationError(
                    f"El valor de '{key}' debe ser un número positivo (mayor que cero)."
                )
            if val > _EXTRA_MAX:
                raise serializers.ValidationError(
                    f"El valor de '{key}' excede el límite permitido ({_EXTRA_MAX})."
                )
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Validación de nivel serializer: campos desconocidos y relaciones cruzadas."""
        # D-EC-7: rechazar campos de nivel raíz no declarados.
        _reject_unknown_fields(self, self.initial_data)  # type: ignore[arg-type]

        # Si ambos vienen, systolic debe ser mayor que diastolic.
        sys_val = attrs.get("systolic")
        dia_val = attrs.get("diastolic")
        if sys_val is not None and dia_val is not None:
            if sys_val <= dia_val:
                raise serializers.ValidationError(
                    {
                        "systolic": (
                            "La presión sistólica debe ser mayor que la diastólica."
                        )
                    }
                )

        # Si measured_at no llegó, poner el valor actual (se validó en el service también).
        if "measured_at" not in attrs:
            attrs["measured_at"] = timezone.now()

        return attrs


class VitalSignsOutputSerializer(serializers.ModelSerializer):
    """Serializer de salida para VitalSignsRecord.

    Expone todos los parámetros medidos, el campo derivado `imc` (D-EC-6)
    y el UUID del responsable (created_by_id, nunca el objeto completo).
    No expone deleted_at ni tenant_id (campos internos).
    """

    imc = serializers.SerializerMethodField(
        help_text="IMC derivado (weight_kg / height_m²). None si falta peso o talla. No se almacena."
    )

    class Meta:
        model = VitalSignsRecord
        fields = [
            "id",
            "patient_id",
            "appointment_id",
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
            "notes",
            "imc",
            "created_by_id",
            "created_at",
        ]
        read_only_fields = fields

    def get_imc(self, obj: VitalSignsRecord) -> Optional[float]:
        """Retorna el IMC derivado como float, o None si falta peso o talla."""
        val = obj.imc
        if val is None:
            return None
        return float(val)


# ---------------------------------------------------------------------------
# EvolutionNote — Nota de Evolución (A4)
# ---------------------------------------------------------------------------

# Campos de texto de la nota de evolución permitidos en el InputSerializer (whitelist D-EC-7).
# Max_length en el serializer (no en el modelo) para evitar DoS y mantener flexibilidad.
_EVOLUTION_TEXT_MAX: int = 10_000  # 10K chars ≈ 5 páginas de texto clínico


class EvolutionNoteInputSerializer(serializers.Serializer):
    """Valida los datos de entrada para crear una nota de evolución.

    D-EC-7: rechaza campos no declarados.
    D-EC-1: inmutable — este serializer solo se usa en POST.
    D-EC-2: appointment_id es requerido; el service valida que esté ATTENDED.

    max_length en campos de texto para evitar payloads gigantes (MEDIO-2 DoS).
    appointment_id y doctor_id son requeridos; vital_signs_id es opcional.
    """

    appointment_id = serializers.UUIDField(
        help_text="UUID de la cita médica (debe estar ATTENDED y ser del mismo paciente).",
    )
    doctor_id = serializers.UUIDField(
        help_text="UUID del médico autor (debe ser el doctor de la cita).",
    )
    vital_signs_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="UUID de la toma de signos vitales asociada (opcional).",
    )

    antecedentes = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=_EVOLUTION_TEXT_MAX
    )
    interrogatorio = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=_EVOLUTION_TEXT_MAX
    )
    estudios = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=_EVOLUTION_TEXT_MAX
    )
    diagnosticos_texto = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=_EVOLUTION_TEXT_MAX
    )
    tratamiento = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=_EVOLUTION_TEXT_MAX
    )
    plan_recomendaciones = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=_EVOLUTION_TEXT_MAX
    )
    indicaciones_enfermeria = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=_EVOLUTION_TEXT_MAX
    )
    exploracion_fisica = serializers.JSONField(
        required=False, default=dict, allow_null=False
    )

    def validate_exploracion_fisica(
        self, value: dict[str, Any]
    ) -> dict[str, Any]:
        """Valida el bloque de exploración por aparatos (D-EC-7 whitelist)."""
        if not isinstance(value, dict):
            raise serializers.ValidationError("Debe ser un objeto JSON.")
        validate_exploracion_evolucion(value)
        return value

    # Campos de texto clínico que determinan si una nota tiene contenido.
    # appointment_id, doctor_id y vital_signs_id son selección de cita, no contenido.
    _CLINICAL_TEXT_FIELDS: tuple[str, ...] = (
        "antecedentes",
        "interrogatorio",
        "estudios",
        "diagnosticos_texto",
        "tratamiento",
        "plan_recomendaciones",
        "indicaciones_enfermeria",
    )

    # Valor de estado que indica aparato "sin evaluar" en exploracion_fisica.
    _ESTADO_NO_EVALUADO: str = "no_evaluado"

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Validación de nivel serializer: rechaza campos desconocidos (D-EC-7)
        y rechaza notas completamente vacías (D-EC contenido mínimo).

        Una nota está vacía cuando:
        - Todos los campos de texto clínico están ausentes o contienen solo espacios.
        - Y exploracion_fisica no tiene ningún aparato con estado != 'no_evaluado'.

        En ese caso lanza ValidationError con 400.
        La selección de cita (appointment_id, doctor_id, vital_signs_id) no cuenta
        como contenido clínico.
        """
        # D-EC-7: rechazar campos de nivel raíz no declarados.
        _reject_unknown_fields(self, self.initial_data)  # type: ignore[arg-type]

        # Verificar si hay al menos un campo de texto con contenido real.
        has_text_content = any(
            attrs.get(field, "").strip()
            for field in self._CLINICAL_TEXT_FIELDS
        )

        # Verificar si exploracion_fisica tiene al menos un aparato evaluado
        # (estado distinto de 'no_evaluado').
        exploracion: dict[str, Any] = attrs.get("exploracion_fisica") or {}
        has_exploracion_content = any(
            isinstance(aparato, dict)
            and aparato.get("estado") != self._ESTADO_NO_EVALUADO
            for aparato in exploracion.values()
        )

        if not has_text_content and not has_exploracion_content:
            raise serializers.ValidationError(
                "La nota de evolución no puede estar vacía: "
                "escribe al menos un campo clínico o evalúa un aparato."
            )

        return attrs


class AddendumOutputSerializer(serializers.ModelSerializer):
    """Serializer de salida para Addendum.

    No expone tenant_id, deleted_at ni campos internos.
    """

    class Meta:
        model = Addendum
        fields = [
            "id",
            "evolution_id",
            "author_id",
            "body",
            "created_at",
        ]
        read_only_fields = fields


class EvolutionNoteOutputSerializer(serializers.ModelSerializer):
    """Serializer de salida para EvolutionNote.

    Incluye los addenda anidados (append-only). Los diagnósticos se listan
    por su propio endpoint (/diagnosticos/).
    No expone tenant_id, deleted_at ni campos internos.
    """

    addenda = AddendumOutputSerializer(many=True, read_only=True)

    class Meta:
        model = EvolutionNote
        fields = [
            "id",
            "patient_id",
            "appointment_id",
            "doctor_id",
            "vital_signs_id",
            "antecedentes",
            "interrogatorio",
            "estudios",
            "diagnosticos_texto",
            "tratamiento",
            "plan_recomendaciones",
            "indicaciones_enfermeria",
            "exploracion_fisica",
            "is_locked",
            "addenda",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Addendum — Input (A4)
# ---------------------------------------------------------------------------


class AddendumInputSerializer(serializers.Serializer):
    """Valida los datos de entrada para crear un addendum.

    D-EC-7: rechaza campos no declarados.
    body es el único campo; requerido y no vacío.
    max_length = 5000 para evitar DoS.
    """

    body = serializers.CharField(
        max_length=5_000,
        help_text="Texto del addendum (requerido, no puede estar vacío).",
    )

    def validate_body(self, value: str) -> str:
        """Normaliza y valida que el cuerpo no esté vacío."""
        value = value.strip()
        if not value:
            raise serializers.ValidationError("El texto del addendum no puede estar vacío.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Rechaza campos no declarados (D-EC-7)."""
        _reject_unknown_fields(self, self.initial_data)  # type: ignore[arg-type]
        return attrs


# ---------------------------------------------------------------------------
# Diagnosis — Input/Output (A4)
# ---------------------------------------------------------------------------


class DiagnosisInputSerializer(serializers.Serializer):
    """Valida los datos de entrada para crear un diagnóstico.

    D-EC-7: rechaza campos no declarados.
    description es requerido. cie_code, kind y evolution_id son opcionales.
    """

    description = serializers.CharField(
        max_length=255,
        help_text="Descripción del diagnóstico (requerida).",
    )
    cie_code = serializers.CharField(
        max_length=10,
        required=False,
        default="",
        allow_blank=True,
        help_text="Código CIE-10 (ej. J06.9). Normalizado a mayúsculas.",
    )
    kind = serializers.ChoiceField(
        choices=DiagnosisKind.choices,
        required=False,
        default=DiagnosisKind.PRESUNTIVO,
        help_text="Tipo: 'presuntivo' (default) o 'definitivo'.",
    )
    evolution_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="UUID de la nota de evolución vinculada (opcional).",
    )

    def validate_description(self, value: str) -> str:
        """Normaliza y valida que la descripción no esté vacía."""
        value = value.strip()
        if not value:
            raise serializers.ValidationError(
                "La descripción del diagnóstico no puede estar vacía."
            )
        return value

    def validate_cie_code(self, value: str) -> str:
        """B6: valida y normaliza el código CIE-10.

        Permite vacío. Si se provee, normaliza a mayúsculas y valida el formato
        estándar: letra + 2 dígitos + subcategoría opcional (ej. J06.9).

        Args:
            value: código CIE-10 recibido del cliente.

        Returns:
            Código en mayúsculas si es válido, o cadena vacía.

        Raises:
            serializers.ValidationError: si el formato no coincide con CIE-10.
        """
        if not value:
            return ""
        normalized = value.strip().upper()
        if not _CIE10_RE.match(normalized):
            raise serializers.ValidationError(
                "Código CIE-10 inválido. Formato esperado: "
                "letra mayúscula + 2 dígitos + subcategoría opcional (ej. J06.9, A01)."
            )
        return normalized

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Rechaza campos no declarados (D-EC-7)."""
        _reject_unknown_fields(self, self.initial_data)  # type: ignore[arg-type]
        return attrs


class DiagnosisOutputSerializer(serializers.ModelSerializer):
    """Serializer de salida para Diagnosis.

    Incluye kind_display y status_display para etiquetas legibles.
    No expone tenant_id, deleted_at ni campos internos.
    """

    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Diagnosis
        fields = [
            "id",
            "patient_id",
            "evolution_id",
            "cie_code",
            "description",
            "kind",
            "kind_display",
            "status",
            "status_display",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Indicaciones de enfermería — Output (A4 — sub-vista especializada)
# ---------------------------------------------------------------------------


class NursingInstructionOutputSerializer(serializers.ModelSerializer):
    """Serializer de salida para el listado de indicaciones de enfermería.

    Expone únicamente los campos necesarios para que enfermería ejecute
    las órdenes del médico:
        id           — UUID de la nota de evolución de origen.
        fecha        — Alias de created_at (cuando se creó la nota).
        doctor       — Nombre completo del médico autor (full_name del User).
        indicaciones — Texto de las indicaciones para enfermería.

    No expone contenido clínico del resto de la nota (diagnósticos, tratamiento,
    antecedentes) ya que este endpoint está optimizado para el flujo de enfermería.
    """

    fecha = serializers.DateTimeField(source="created_at", read_only=True)
    doctor = serializers.SerializerMethodField()
    indicaciones = serializers.CharField(source="indicaciones_enfermeria", read_only=True)

    class Meta:
        model = EvolutionNote
        fields = ["id", "fecha", "doctor", "indicaciones"]
        read_only_fields = fields

    def get_doctor(self, obj: EvolutionNote) -> str:
        """Retorna el nombre completo del médico autor de la nota.

        Accede a doctor.membership.user usando las relaciones precargadas por
        el selector (select_related). Si por alguna razón el usuario no está
        disponible, retorna una cadena vacía en lugar de fallar.
        """
        try:
            return str(obj.doctor.membership.user.get_full_name() or obj.doctor.membership.user.email)
        except (AttributeError, ObjectDoesNotExist):
            return ""


# ---------------------------------------------------------------------------
# EvolutionImage — Input/Output
# ---------------------------------------------------------------------------


class EvolutionImageInputSerializer(serializers.Serializer):
    """Valida los datos de entrada para subir una imagen a una nota de evolución.

    Campos:
        image   — archivo de imagen (requerido). La validación Pillow real se hace
                  en el service; aquí solo verificamos que el campo esté presente.
        caption — descripción breve opcional (máx 255 chars).

    Seguridad: no confiar en este serializer para la validación de contenido binario.
    La barrera real es validate_evolution_image() en el service (Pillow + whitelist).
    Este serializer solo garantiza que el campo llegue al service.
    """

    image = serializers.ImageField(
        help_text="Imagen clínica (JPEG/PNG/WEBP, máx 10 MB).",
    )
    caption = serializers.CharField(
        max_length=255,
        required=False,
        default="",
        allow_blank=True,
        help_text="Descripción breve de la imagen (opcional).",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Rechaza campos no declarados (D-EC-7)."""
        _reject_unknown_fields(self, self.initial_data)  # type: ignore[arg-type]
        return attrs


class EvolutionImageOutputSerializer(serializers.ModelSerializer):
    """Serializer de salida para EvolutionImage.

    Expone image_url (URL absoluta o relativa servible) en lugar del path interno
    para que el frontend pueda renderizar la imagen directamente.
    No expone tenant_id, deleted_at ni campos internos de auditoría.
    """

    image_url = serializers.SerializerMethodField()

    class Meta:
        model = EvolutionImage
        fields = [
            "id",
            "evolution_id",
            "image_url",
            "caption",
            "created_at",
        ]
        read_only_fields = fields

    def get_image_url(self, obj: EvolutionImage) -> str | None:
        """Retorna la URL servible de la imagen.

        Usa request del context para construir URL absoluta cuando esté disponible.
        Si no hay request en el context (ej. tests sin contexto HTTP), devuelve
        la URL relativa del ImageField (que puede ser un path o una URL si se usa S3).
        """
        request = self.context.get("request")
        if not obj.image:
            return None
        if request is not None:
            return request.build_absolute_uri(obj.image.url)
        return obj.image.url


# ---------------------------------------------------------------------------
# MedicalHistoryQuestion — Input/Output (Fase 2)
# ---------------------------------------------------------------------------


class MedicalHistoryQuestionInputSerializer(serializers.Serializer):
    """Valida la entrada para crear o actualizar una pregunta extra de HC.

    D-EC-7: rechaza campos no declarados (incluyendo is_active — se gestiona
    con el endpoint DELETE, no con PATCH).

    Regla de coherencia options/field_type:
        Si field_type == 'select': options debe ser lista no vacía de strings.
        Si field_type != 'select': options debe ser [] (o ausente).
    """

    label = serializers.CharField(max_length=255)
    field_type = serializers.ChoiceField(choices=QuestionFieldType.choices)
    options = serializers.ListField(
        child=serializers.CharField(),
        default=list,
        required=False,
        help_text="Lista de opciones para field_type='select'. Vacío para otros tipos.",
    )
    section = serializers.CharField(
        max_length=100,
        allow_blank=True,
        default="",
        required=False,
    )
    order = serializers.IntegerField(min_value=0, default=0, required=False)
    is_required = serializers.BooleanField(default=False, required=False)

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validación: rechaza campos desconocidos y valida coherencia options/field_type."""
        _reject_unknown_fields(self, self.initial_data)  # type: ignore[arg-type]

        field_type = data.get("field_type", "")
        options = data.get("options", [])

        # Si field_type == 'select', options no puede ser vacía.
        if field_type == QuestionFieldType.SELECT and not options:
            raise serializers.ValidationError(
                {"options": "Las opciones son requeridas para tipo 'select'."}
            )

        # Si field_type != 'select', options debe ser [].
        if field_type != QuestionFieldType.SELECT and options:
            raise serializers.ValidationError(
                {"options": "Las opciones solo aplican para tipo 'select'."}
            )

        return data


class MedicalHistoryQuestionOutputSerializer(serializers.ModelSerializer):
    """Serializer de salida para MedicalHistoryQuestion.

    No expone tenant_id, deleted_at, created_by_id (campos internos).
    """

    class Meta:
        model = MedicalHistoryQuestion
        fields = [
            "id",
            "label",
            "field_type",
            "options",
            "section",
            "order",
            "is_required",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Libro Clínico — Serializers de salida (Fase 1)
# ---------------------------------------------------------------------------


class BookDoctorSerializer(serializers.Serializer):
    """Snapshot ligero del médico autor de un capítulo del libro.

    Solo expone el nombre para el libro (sin datos sensibles del doctor).
    Las cédulas validadas se incluyen para cumplir con NOM-004.
    """

    full_name = serializers.SerializerMethodField()
    cedulas_validadas = serializers.SerializerMethodField()

    def get_full_name(self, obj: Any) -> str:
        """Retorna el nombre completo del médico desde su membership.user."""
        try:
            user = obj.membership.user
            return str(user.get_full_name() or user.email)
        except (AttributeError, ObjectDoesNotExist):
            return ""

    def get_cedulas_validadas(self, obj: Any) -> list[str]:
        """Retorna lista de cédulas validadas del médico (desde DoctorCredential).

        Si book_build precargó las credenciales validadas (via Prefetch con
        to_attr="cedulas_validadas_cache"), las usa SIN pegar a la BD —evitando
        un N+1 de una query de credenciales por capítulo del libro. Si no están
        precargadas (serializer usado fuera de book_build), cae a una query directa.
        """
        # Camino rápido: credenciales ya precargadas y filtradas por book_build.
        cached = getattr(obj, "cedulas_validadas_cache", None)
        if cached is not None:
            return [c.credential_number for c in cached if c.credential_number]

        # Fallback defensivo: sin prefetch. Mantiene el comportamiento previo.
        try:
            return [
                num
                for num in obj.credentials.filter(
                    validation_status="validada",
                    is_active=True,
                    deleted_at__isnull=True,
                ).values_list("credential_number", flat=True)
                if num
            ]
        except AttributeError:
            return []


class BookPrescriptionSummarySerializer(serializers.Serializer):
    """Resumen ligero de una receta vinculada a un capítulo del libro.

    Devuelve solo metadatos de la receta (id, folio, estado, resumen de ítems).
    NO devuelve el PDF ni el contenido completo — eso es Fase 3.

    El campo items_resumen es una lista de textos con el nombre y dosis de cada
    ítem, suficiente para la navegación del libro clínico en pantalla.
    """

    id = serializers.UUIDField(read_only=True)
    folio = serializers.IntegerField(read_only=True)
    status = serializers.CharField(read_only=True)
    issued_at = serializers.DateTimeField(read_only=True)
    items_resumen = serializers.SerializerMethodField()

    def get_items_resumen(self, obj: Any) -> list[str]:
        """Construye lista de strings 'Nombre (dosis)' a partir de los ítems.

        Usa los ítems ya precargados por book_build (Prefetch "prescriptions__items").
        """
        try:
            parts: list[str] = []
            for item in obj.items.all():
                label = item.medication_name
                if item.dose:
                    label = f"{label} ({item.dose})"
                parts.append(label)
            return parts
        except AttributeError:
            return []


class BookCapituloSerializer(serializers.Serializer):
    """Serializer de un capítulo del libro clínico (una nota de evolución completa).

    Ensambla todos los sub-serializers existentes en la estructura del contrato
    de API definido en el plan (docs/design/libro-clinico-plan.md §3).

    Estructura producida:
        id          UUID de la nota de evolución.
        fecha       Fecha/hora de creación de la nota (ISO 8601).
        doctor      { full_name, cedulas_validadas }.
        signos      VitalSignsOutputSerializer | null.
        subjetivo   Texto libre (interrogatorio + antecedentes).
        objetivo    Texto de estudios solicitados/reportados.
        exploracion Lista de { sistema, estado, detalle } del JSONField.
        analisis    { texto: diagnosticos_texto, diagnosticos: [DiagnosisOutputSerializer] }.
        plan        { tratamiento, recomendaciones, indicaciones_enfermeria }.
        imagenes    [EvolutionImageOutputSerializer].
        recetas     [BookPrescriptionSummarySerializer].
        addenda     [AddendumOutputSerializer].
    """

    id = serializers.UUIDField(read_only=True)
    fecha = serializers.DateTimeField(source="created_at", read_only=True)
    doctor = BookDoctorSerializer(read_only=True)
    signos = serializers.SerializerMethodField()
    subjetivo = serializers.SerializerMethodField()
    objetivo = serializers.SerializerMethodField()
    exploracion = serializers.SerializerMethodField()
    analisis = serializers.SerializerMethodField()
    plan = serializers.SerializerMethodField()
    imagenes = serializers.SerializerMethodField()
    recetas = serializers.SerializerMethodField()
    addenda = serializers.SerializerMethodField()

    def get_signos(self, obj: EvolutionNote) -> Optional[dict[str, Any]]:
        """Serializa los signos vitales de la nota (o null si no los tiene)."""
        if obj.vital_signs is None:
            return None
        return VitalSignsOutputSerializer(obj.vital_signs).data

    def get_subjetivo(self, obj: EvolutionNote) -> str:
        """Concatena interrogatorio + antecedentes como campo subjetivo (S del SOAP)."""
        parts = [obj.interrogatorio, obj.antecedentes]
        return "\n\n".join(p for p in parts if p.strip())

    def get_objetivo(self, obj: EvolutionNote) -> str:
        """Devuelve el campo estudios como objetivo (O del SOAP)."""
        return obj.estudios

    def get_exploracion(self, obj: EvolutionNote) -> list[dict[str, Any]]:
        """Convierte el JSONField exploracion_fisica en lista navegable.

        Estructura de salida: [{ "sistema": str, "estado": str, "detalle": str }].
        Se mantiene el orden de inserción del dict (Python 3.7+).
        """
        if not obj.exploracion_fisica:
            return []
        result: list[dict[str, Any]] = []
        for sistema, data in obj.exploracion_fisica.items():
            if not isinstance(data, dict):
                continue
            result.append(
                {
                    "sistema": sistema,
                    "estado": data.get("estado", "no_evaluado"),
                    "detalle": data.get("detalle", ""),
                }
            )
        return result

    def get_analisis(self, obj: EvolutionNote) -> dict[str, Any]:
        """Arma la sección de análisis (A del SOAP).

        Diagnósticos: solo los vinculados a esta evolución (evolution FK).
        Ver docstring de book_build para la decisión sobre diagnósticos sin FK.
        """
        return {
            "texto": obj.diagnosticos_texto,
            "diagnosticos": DiagnosisOutputSerializer(
                obj.diagnoses.all(), many=True
            ).data,
        }

    def get_plan(self, obj: EvolutionNote) -> dict[str, Any]:
        """Arma la sección de plan y tratamiento (P del SOAP)."""
        return {
            "tratamiento": obj.tratamiento,
            "recomendaciones": obj.plan_recomendaciones,
            "indicaciones_enfermeria": obj.indicaciones_enfermeria,
        }

    def get_imagenes(self, obj: EvolutionNote) -> list[dict[str, Any]]:
        """Serializa las imágenes activas de la nota.

        Usa el prefetch "images" cargado por book_build. No pasa request
        en el context porque el serializer de imágenes no lo necesita para
        la URL relativa. El frontend puede construir la URL absoluta.
        """
        return EvolutionImageOutputSerializer(
            obj.images.all(), many=True
        ).data

    def get_recetas(self, obj: EvolutionNote) -> list[dict[str, Any]]:
        """Serializa el resumen de recetas vinculadas a esta evolución.

        Usa el prefetch "prescriptions" + "prescriptions__items" de book_build.
        """
        return BookPrescriptionSummarySerializer(
            obj.prescriptions.all(), many=True
        ).data

    def get_addenda(self, obj: EvolutionNote) -> list[dict[str, Any]]:
        """Serializa los addenda de la nota en orden cronológico."""
        return AddendumOutputSerializer(
            obj.addenda.all(), many=True
        ).data


class PatientBookSerializer(serializers.Serializer):
    """Serializer de salida del libro clínico completo del paciente.

    Ensambla los serializers existentes en la estructura del contrato de API:

        {
          "paciente":         PatientOutputSerializer (portada),
          "clinica":          ClinicSettingsOutputSerializer | null (portada),
          "historia_clinica": MedicalHistoryOutputSerializer | null (HC viva),
          "alergias":         [AllergyOutputSerializer],
          "capitulos_count":  int (total de evoluciones),
          "total_pages":      int,
          "page":             int (actual),
          "page_size":        int,
          "capitulos":        [BookCapituloSerializer] (página actual, MÁS RECIENTE PRIMERO)
        }

    Los campos de paginación (page, total_pages, page_size, capitulos_count)
    dan contexto al frontend para implementar la navegación.

    No tiene campos de entrada (solo de salida): es un serializer de respuesta puro.
    """

    paciente = serializers.SerializerMethodField()
    clinica = serializers.SerializerMethodField()
    historia_clinica = serializers.SerializerMethodField()
    alergias = serializers.SerializerMethodField()
    capitulos_count = serializers.IntegerField(read_only=True)
    total_pages = serializers.IntegerField(read_only=True)
    page = serializers.IntegerField(read_only=True)
    page_size = serializers.IntegerField(read_only=True)
    capitulos = serializers.SerializerMethodField()

    def get_paciente(self, obj: Any) -> dict[str, Any]:
        """Serializa el paciente (portada del libro)."""
        from apps.pacientes.serializers import PatientOutputSerializer  # noqa: PLC0415
        return PatientOutputSerializer(obj.patient).data

    def get_clinica(self, obj: Any) -> Optional[dict[str, Any]]:
        """Serializa la configuración de la clínica (portada)."""
        if obj.clinic_settings is None:
            return None
        from apps.clinica.serializers import ClinicSettingsOutputSerializer  # noqa: PLC0415
        return ClinicSettingsOutputSerializer(
            obj.clinic_settings, context=self.context
        ).data

    def get_historia_clinica(self, obj: Any) -> Optional[dict[str, Any]]:
        """Serializa la HC viva del paciente (null si no existe aún)."""
        if obj.medical_history is None:
            return None
        return MedicalHistoryOutputSerializer(obj.medical_history).data

    def get_alergias(self, obj: Any) -> list[dict[str, Any]]:
        """Serializa las alergias vigentes del paciente."""
        return AllergyOutputSerializer(obj.allergies, many=True).data

    def get_capitulos(self, obj: Any) -> list[dict[str, Any]]:
        """Serializa los capítulos (evoluciones) de la página actual."""
        return BookCapituloSerializer(obj.capitulos, many=True).data
