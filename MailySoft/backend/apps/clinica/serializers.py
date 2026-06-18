"""
Serializers de la app clinica.

Reglas:
    - Serializers de entrada (Input) y salida (Output) SIEMPRE separados.
    - Sin create()/update() con lógica; eso va al service.
    - Validaciones de formato en el serializer; reglas de negocio en el service.

M2 — rechazo de campos desconocidos:
    Todos los serializers de entrada invocan _reject_unknown_fields() en validate().

M3 — validación de formato de contacto:
    phone/mobile: regex razonable de teléfono (_PHONE_RE).
    facebook/instagram/youtube: validador suave que rechaza etiquetas HTML y
        caracteres de control, pero permite @handle y URLs.
    WhatsAppContactSerializer.numero: mismo regex de teléfono.

M5 — body de plantilla rechaza etiquetas HTML:
    validate_body comprueba que no haya tags reales (< seguido de letra/slash/!).
    "presión < 120" (con espacio) queda permitido.

B8 — recipe_whatsapp_contacts con max_length=20.
"""

import re
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.clinica.models import ClinicSettings, ClinicTemplate, DoctorUniversity, PatientCategory
from apps.core.files import validate_image

# ---------------------------------------------------------------------------
# Constantes de validación de formato
# ---------------------------------------------------------------------------

# Reutiliza el mismo patrón de apps/pacientes/views.py._PHONE_RE
_PHONE_RE = re.compile(r"^\+?[\d\s\-\(\)]{7,20}$")

# Etiqueta HTML real: < seguido de letra, /  o ! (sin espacio inmediato).
# "presión < 120" tiene espacio → no coincide → permitido.
_HTML_TAG_RE = re.compile(r"<[a-zA-Z/!][^>]*>")

# Carácter de control (excepto el propio vacío): U+0000–U+001F
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f]")


# ---------------------------------------------------------------------------
# Helpers compartidos (M2 / D-EC-7)
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
        data:       datos de entrada (request.data o equivalente).

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
# Validadores de formato reutilizables (M3)
# ---------------------------------------------------------------------------


def _validate_phone_field(value: str, field_name: str = "teléfono") -> str:
    """Valida que `value` tenga un formato de teléfono razonable. Permite vacío.

    Args:
        value:      cadena a validar.
        field_name: nombre del campo para mensajes de error (solo informativos).

    Returns:
        El valor sin modificar si pasa la validación o si está vacío.

    Raises:
        serializers.ValidationError: si el formato no coincide con _PHONE_RE.
    """
    if not value:
        return value
    if not _PHONE_RE.match(value):
        raise serializers.ValidationError(
            f"{field_name} inválido. Use formato nacional (5512345678) "
            "o internacional (+52 55 1234 5678), 7-20 caracteres."
        )
    return value


def _validate_social_field(value: str) -> str:
    """Validador suave para campos de redes sociales (M3).

    Permite: URLs (https://...), handles (@usuario), texto plano.
    Rechaza: etiquetas HTML reales (<b>, <script>, etc.)
             y caracteres de control (U+0000-U+001F).

    Args:
        value: cadena a validar.

    Returns:
        El valor sin modificar si pasa la validación o si está vacío.

    Raises:
        serializers.ValidationError: si contiene etiquetas HTML o chars de control.
    """
    if not value:
        return value
    if _HTML_TAG_RE.search(value):
        raise serializers.ValidationError(
            "El valor no puede contener etiquetas HTML."
        )
    if _CONTROL_CHAR_RE.search(value):
        raise serializers.ValidationError(
            "El valor no puede contener caracteres de control."
        )
    return value


class SecureImageField(serializers.ImageField):
    """ImageField que aplica validate_image (JPG/PNG/WEBP, máx 5MB, sin GIF/SVG).

    DRF's ImageField estándar solo verifica que Pillow pueda leer el archivo
    (acepta GIF, BMP, etc.). SecureImageField añade la validación de formato
    estricta de Maily antes de que el valor llegue al service/model.
    """

    def to_internal_value(self, data: Any) -> Any:
        file = super().to_internal_value(data)
        try:
            validate_image(file)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages)
        return file


# ---------------------------------------------------------------------------
# ClinicSettings
# ---------------------------------------------------------------------------


class WhatsAppContactSerializer(serializers.Serializer):
    """Validador de un ítem de recipe_whatsapp_contacts.

    M3: numero valida el mismo regex de teléfono que phone/mobile.
    """

    nombre = serializers.CharField(max_length=100)
    numero = serializers.CharField(max_length=30)

    def validate_numero(self, value: str) -> str:
        """M3: valida formato de teléfono en número de WhatsApp."""
        return _validate_phone_field(value, field_name="Número de WhatsApp")


class ClinicSettingsInputSerializer(serializers.Serializer):
    """Entrada para PUT (actualización completa o parcial) de ClinicSettings.

    Las imágenes se envían como multipart (no como base64) igual que el avatar
    de paciente. Se usa SecureImageField para validar formato JPG/PNG/WEBP.

    M2: rechaza campos desconocidos vía validate().
    M3: phone y mobile validan regex de teléfono (_PHONE_RE).
        facebook, instagram, youtube usan validador suave (no URLField estricto):
        permite @handle y URLs, rechaza etiquetas HTML y caracteres de control.
    B8: recipe_whatsapp_contacts limitado a max_length=20 elementos.
    """

    logo = SecureImageField(required=False, allow_null=True)
    address = serializers.CharField(max_length=300, required=False, allow_blank=True)
    address_2 = serializers.CharField(max_length=300, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True)
    mobile = serializers.CharField(max_length=30, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    website = serializers.URLField(required=False, allow_blank=True, max_length=200)
    facebook = serializers.CharField(max_length=200, required=False, allow_blank=True)
    instagram = serializers.CharField(max_length=200, required=False, allow_blank=True)
    youtube = serializers.CharField(max_length=200, required=False, allow_blank=True)
    letterhead_full = SecureImageField(required=False, allow_null=True)
    letterhead_half = SecureImageField(required=False, allow_null=True)
    letterhead_full_spaces = serializers.IntegerField(min_value=0, max_value=100, required=False)
    letterhead_half_spaces = serializers.IntegerField(min_value=0, max_value=100, required=False)
    recipe_use_responsible_doctor = serializers.BooleanField(required=False)
    # B8: máximo 20 contactos de WhatsApp por clínica.
    recipe_whatsapp_contacts = serializers.ListField(
        child=WhatsAppContactSerializer(),
        required=False,
        allow_empty=True,
        max_length=20,
    )

    # --- M3: phone / mobile ---

    def validate_phone(self, value: str) -> str:
        """M3: valida formato de teléfono principal. Permite vacío."""
        return _validate_phone_field(value, field_name="Teléfono")

    def validate_mobile(self, value: str) -> str:
        """M3: valida formato de teléfono móvil. Permite vacío."""
        return _validate_phone_field(value, field_name="Móvil")

    # --- M3: redes sociales (validador suave) ---

    def validate_facebook(self, value: str) -> str:
        """M3: rechaza etiquetas HTML y chars de control. Permite @handle y URLs."""
        return _validate_social_field(value)

    def validate_instagram(self, value: str) -> str:
        """M3: rechaza etiquetas HTML y chars de control. Permite @handle y URLs."""
        return _validate_social_field(value)

    def validate_youtube(self, value: str) -> str:
        """M3: rechaza etiquetas HTML y chars de control. Permite @handle y URLs."""
        return _validate_social_field(value)

    # --- Validaciones existentes ---

    def validate_website(self, value: str) -> str:
        """Permite string vacío aunque URLField normalmente lo rechaza."""
        if not value:
            return value
        return value

    def validate_recipe_whatsapp_contacts(
        self, value: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Valida la estructura de cada contacto WhatsApp.

        La validación de formato de `numero` se hace en WhatsAppContactSerializer.
        Aquí solo chequeamos que nombre y numero no estén vacíos.
        """
        for i, contact in enumerate(value):
            if not isinstance(contact, dict):
                raise serializers.ValidationError(
                    f"El elemento {i} debe ser un objeto {{nombre, numero}}."
                )
            for key in ("nombre", "numero"):
                if not contact.get(key, "").strip():
                    raise serializers.ValidationError(
                        f"El campo '{key}' del elemento {i} no puede estar vacío."
                    )
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """M2: rechaza campos desconocidos (D-EC-7)."""
        _reject_unknown_fields(self, self.initial_data)  # type: ignore[arg-type]
        return attrs


class ClinicSettingsOutputSerializer(serializers.ModelSerializer["ClinicSettings"]):
    """Salida de ClinicSettings con URLs absolutas de imágenes."""

    class Meta:
        model = ClinicSettings
        fields = [
            "id",
            "logo",
            "address",
            "address_2",
            "phone",
            "mobile",
            "email",
            "website",
            "facebook",
            "instagram",
            "youtube",
            "letterhead_full",
            "letterhead_half",
            "letterhead_full_spaces",
            "letterhead_half_spaces",
            "recipe_use_responsible_doctor",
            "recipe_whatsapp_contacts",
            "created_at",
            "updated_at",
        ]


# ---------------------------------------------------------------------------
# ClinicTemplate
# ---------------------------------------------------------------------------


class ClinicTemplateInputSerializer(serializers.Serializer):
    """Entrada para POST de ClinicTemplate.

    M2: rechaza campos desconocidos vía validate().
    M5: validate_body rechaza etiquetas HTML reales (<tag>).
        Texto plano con "< 120" (espacio después de <) queda permitido.
    """

    kind = serializers.ChoiceField(choices=["recipe", "document", "consent"])
    name = serializers.CharField(max_length=200)
    body = serializers.CharField(max_length=50_000)
    group = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")

    def validate_body(self, value: str) -> str:
        """M5: rechaza etiquetas HTML reales en el cuerpo de la plantilla.

        "presión < 120" → permitido (espacio después de <).
        "<script>alert(1)</script>" → 400.
        """
        if _HTML_TAG_RE.search(value):
            raise serializers.ValidationError(
                "El cuerpo de la plantilla no puede contener etiquetas HTML. "
                "Use texto plano con variables {placeholder}."
            )
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """M2: rechaza campos desconocidos (D-EC-7)."""
        _reject_unknown_fields(self, self.initial_data)  # type: ignore[arg-type]
        return attrs


class ClinicTemplatePatchSerializer(serializers.Serializer):
    """Entrada para PATCH (actualización parcial) de ClinicTemplate.

    Todos los campos son opcionales en PATCH.
    M2: rechaza campos desconocidos vía validate().
    M5: validate_body rechaza etiquetas HTML reales (<tag>).
    """

    kind = serializers.ChoiceField(choices=["recipe", "document", "consent"], required=False)
    name = serializers.CharField(max_length=200, required=False)
    body = serializers.CharField(max_length=50_000, required=False)
    group = serializers.CharField(max_length=100, required=False, allow_blank=True)

    def validate_body(self, value: str) -> str:
        """M5: rechaza etiquetas HTML reales en el cuerpo de la plantilla."""
        if _HTML_TAG_RE.search(value):
            raise serializers.ValidationError(
                "El cuerpo de la plantilla no puede contener etiquetas HTML. "
                "Use texto plano con variables {placeholder}."
            )
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """M2: rechaza campos desconocidos (D-EC-7)."""
        _reject_unknown_fields(self, self.initial_data)  # type: ignore[arg-type]
        return attrs


class ClinicTemplateOutputSerializer(serializers.ModelSerializer["ClinicTemplate"]):
    """Salida de ClinicTemplate."""

    class Meta:
        model = ClinicTemplate
        fields = [
            "id",
            "kind",
            "name",
            "body",
            "group",
            "is_active",
            "created_at",
            "updated_at",
        ]


# ---------------------------------------------------------------------------
# PatientCategory
# ---------------------------------------------------------------------------


class PatientCategoryInputSerializer(serializers.Serializer):
    """Entrada para POST de PatientCategory.

    M2: rechaza campos desconocidos vía validate().
    """

    name = serializers.CharField(max_length=100)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """M2: rechaza campos desconocidos (D-EC-7)."""
        _reject_unknown_fields(self, self.initial_data)  # type: ignore[arg-type]
        return attrs


class PatientCategoryOutputSerializer(serializers.ModelSerializer["PatientCategory"]):
    """Salida de PatientCategory."""

    class Meta:
        model = PatientCategory
        fields = ["id", "name", "is_active", "created_at"]


# ---------------------------------------------------------------------------
# DoctorUniversity
# ---------------------------------------------------------------------------


class DoctorUniversityInputSerializer(serializers.Serializer):
    """Entrada para POST de DoctorUniversity.

    M2: rechaza campos desconocidos vía validate().
    """

    logo = SecureImageField()
    name = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """M2: rechaza campos desconocidos (D-EC-7)."""
        _reject_unknown_fields(self, self.initial_data)  # type: ignore[arg-type]
        return attrs


class DoctorUniversityOutputSerializer(serializers.ModelSerializer["DoctorUniversity"]):
    """Salida de DoctorUniversity."""

    class Meta:
        model = DoctorUniversity
        fields = ["id", "logo", "name", "created_at"]


# ---------------------------------------------------------------------------
# Doctor — perfil ampliado (sello, foto, cédulas adicionales)
# ---------------------------------------------------------------------------


class DoctorProfileImageInputSerializer(serializers.Serializer):
    """Entrada para PATCH /personal/doctores/<id>/perfil/ con imágenes.

    M2: rechaza campos desconocidos vía validate().
    """

    sello = SecureImageField(required=False, allow_null=True)
    foto = SecureImageField(required=False, allow_null=True)
    cedulas_adicionales = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        help_text="Cédulas adicionales separadas por coma.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """M2: rechaza campos desconocidos (D-EC-7)."""
        _reject_unknown_fields(self, self.initial_data)  # type: ignore[arg-type]
        return attrs
