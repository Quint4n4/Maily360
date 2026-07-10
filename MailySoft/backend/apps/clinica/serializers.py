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

M5 — body de plantilla rechaza etiquetas HTML:
    validate_body comprueba que no haya tags reales (< seguido de letra/slash/!).
    "presión < 120" (con espacio) queda permitido.
"""

import re
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.clinica.models import (
    _HEX_COLOR_RE,
    ClinicSettings,
    ClinicTeamMember,
    ClinicTemplate,
    CredentialKind,
    DoctorCredential,
    DoctorUniversity,
    PatientCategory,
)
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
        raise serializers.ValidationError("El valor no puede contener etiquetas HTML.")
    if _CONTROL_CHAR_RE.search(value):
        raise serializers.ValidationError("El valor no puede contener caracteres de control.")
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


class ClinicSettingsInputSerializer(serializers.Serializer):
    """Entrada para PUT (actualización completa o parcial) de ClinicSettings.

    Las imágenes se envían como multipart (no como base64) igual que el avatar
    de paciente. Se usa SecureImageField para validar formato JPG/PNG/WEBP.

    M2: rechaza campos desconocidos vía validate().
    M3: phone y mobile validan regex de teléfono (_PHONE_RE).
        facebook, instagram, youtube usan validador suave (no URLField estricto):
        permite @handle y URLs, rechaza etiquetas HTML y caracteres de control.
    """

    logo = SecureImageField(required=False, allow_null=True)
    commercial_name = serializers.CharField(
        max_length=200,
        required=False,
        allow_blank=True,
        default="",
        help_text="Nombre comercial de la clínica para el membrete (COFEPRIS F2).",
    )
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
    doctors_see_costs = serializers.BooleanField(
        required=False,
        help_text="Si True, los médicos pueden ver el estado de cuenta del paciente (D-2).",
    )
    brand_color = serializers.CharField(
        max_length=7,
        required=False,
        allow_blank=True,
        help_text=(
            "Color de marca en formato #RRGGBB (p. ej. '#3A7BD5'). "
            "Se usa como acento en PDFs. Default: dorado Maily #9A7B1E."
        ),
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

    def validate_brand_color(self, value: str) -> str:
        """Valida que brand_color sea un color en formato #RRGGBB. Permite vacío."""
        if not value:
            return value
        if not _HEX_COLOR_RE.match(value):
            raise serializers.ValidationError(
                "El color de marca debe estar en formato #RRGGBB "
                "(p. ej. '#3A7BD5'). Valor recibido: '%(value)s'." % {"value": value}
            )
        return value

    def validate_website(self, value: str) -> str:
        """Permite string vacío aunque URLField normalmente lo rechaza."""
        if not value:
            return value
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
            "commercial_name",
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
            "brand_color",
            "doctors_see_costs",
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
        fields = ["id", "name", "kind", "is_active", "created_at"]


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

    def validate_cedulas_adicionales(self, value: str) -> str:
        """Valida que cada cédula adicional (separada por coma) sea solo dígitos."""
        if not value.strip():
            return value
        tokens = [t.strip() for t in value.split(",") if t.strip()]
        for token in tokens:
            if not token.isdigit():
                raise serializers.ValidationError(
                    "Cada cédula adicional solo puede contener dígitos (0-9)."
                )
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """M2: rechaza campos desconocidos (D-EC-7)."""
        _reject_unknown_fields(self, self.initial_data)  # type: ignore[arg-type]
        return attrs


# ---------------------------------------------------------------------------
# DoctorCredential — credenciales COFEPRIS F2
# ---------------------------------------------------------------------------

_CREDENTIAL_KIND_CHOICES: list[str] = [c[0] for c in CredentialKind.choices]


class DoctorCredentialInputSerializer(serializers.Serializer):
    """Entrada para POST/PATCH de DoctorCredential.

    Campos obligatorios: title, institution, kind.
    credential_number, order y logo son opcionales.
    logo se envía como multipart (ImageField); usa SecureImageField para
    validar JPG/PNG/WEBP y máx 5 MB.
    M2: rechaza campos desconocidos vía validate().
    Whitelist de kind contra CredentialKind.choices.
    Rechaza etiquetas HTML en campos de texto libre (M5).
    """

    title = serializers.CharField(
        max_length=200,
        help_text="Nombre del título o grado sin abreviaturas (requerido).",
    )
    institution = serializers.CharField(
        max_length=200,
        help_text="Institución que expide el título (requerido). COFEPRIS obligatorio.",
    )
    kind = serializers.ChoiceField(
        choices=_CREDENTIAL_KIND_CHOICES,
        help_text="Tipo de credencial: profesional, especialidad o posgrado.",
    )
    credential_number = serializers.CharField(
        max_length=60,
        required=False,
        allow_blank=True,
        default="",
        help_text="Número de cédula profesional o de especialidad (opcional).",
    )
    order = serializers.IntegerField(
        min_value=0,
        max_value=999,
        required=False,
        default=0,
        help_text="Orden de aparición en el membrete (0 = primero).",
    )
    logo = SecureImageField(
        required=False,
        allow_null=True,
        help_text="Logo opcional de la institución (JPG/PNG/WEBP, máx 5 MB). Multipart.",
    )

    def validate_title(self, value: str) -> str:
        """Rechaza etiquetas HTML y valida que no esté vacío."""
        stripped = value.strip()
        if not stripped:
            raise serializers.ValidationError("El título no puede estar vacío.")
        if _HTML_TAG_RE.search(stripped):
            raise serializers.ValidationError("El título no puede contener etiquetas HTML.")
        return stripped

    def validate_institution(self, value: str) -> str:
        """Rechaza etiquetas HTML y valida que no esté vacío."""
        stripped = value.strip()
        if not stripped:
            raise serializers.ValidationError("La institución no puede estar vacía.")
        if _HTML_TAG_RE.search(stripped):
            raise serializers.ValidationError("La institución no puede contener etiquetas HTML.")
        return stripped

    def validate_credential_number(self, value: str) -> str:
        """Rechaza etiquetas HTML; si no está vacío, exige solo dígitos (0-9)."""
        if _HTML_TAG_RE.search(value):
            raise serializers.ValidationError(
                "El número de cédula no puede contener etiquetas HTML."
            )
        stripped = value.strip()
        if stripped and not stripped.isdigit():
            raise serializers.ValidationError(
                "El número de cédula solo puede contener dígitos (0-9)."
            )
        return stripped

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """M2: rechaza campos desconocidos (D-EC-7)."""
        _reject_unknown_fields(self, self.initial_data)  # type: ignore[arg-type]
        return attrs


class DoctorCredentialOutputSerializer(serializers.ModelSerializer["DoctorCredential"]):
    """Salida de DoctorCredential.

    logo_url: URL relativa de la imagen o null si no hay logo.
    Sigue el mismo patrón que DoctorUniversityOutputSerializer (campo 'logo'
    del ModelSerializer devuelve la URL relativa al MEDIA_URL cuando está configurado).
    """

    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    logo_url = serializers.ImageField(source="logo", read_only=True, allow_null=True)
    validation_status_display = serializers.CharField(
        source="get_validation_status_display", read_only=True
    )
    doctor_id = serializers.UUIDField(source="doctor.id", read_only=True)
    doctor_name = serializers.CharField(source="doctor.full_name", read_only=True)

    class Meta:
        model = DoctorCredential
        fields = [
            "id",
            "title",
            "institution",
            "credential_number",
            "kind",
            "kind_display",
            "order",
            "logo_url",
            "is_active",
            "validation_status",
            "validation_status_display",
            "validation_note",
            "doctor_id",
            "doctor_name",
            "created_at",
        ]


class DoctorCredentialValidationInputSerializer(serializers.Serializer):
    """Entrada para validar/rechazar una credencial (solo owner/admin).

    status: 'validada' o 'rechazada'. note: motivo (recomendado al rechazar).
    """

    status = serializers.ChoiceField(choices=["validada", "rechazada"])
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")

    def validate_note(self, value: str) -> str:
        if _HTML_TAG_RE.search(value):
            raise serializers.ValidationError("La nota no puede contener etiquetas HTML.")
        return value.strip()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        _reject_unknown_fields(self, self.initial_data)  # type: ignore[arg-type]
        return attrs


# ---------------------------------------------------------------------------
# ClinicTeamMember — equipo/departamentos de la clínica (Fase 4)
# ---------------------------------------------------------------------------


class ClinicTeamMemberInputSerializer(serializers.Serializer):
    """Entrada para POST de ClinicTeamMember.

    M2: rechaza campos desconocidos vía validate().
    """

    departamento = serializers.CharField(max_length=160)
    nombre = serializers.CharField(max_length=160)
    order = serializers.IntegerField(min_value=0, required=False, default=0)
    is_active = serializers.BooleanField(required=False, default=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        _reject_unknown_fields(self, self.initial_data)  # type: ignore[arg-type]
        return attrs


class ClinicTeamMemberPatchSerializer(serializers.Serializer):
    """Entrada para PATCH (actualización parcial) de ClinicTeamMember.

    is_active NO se expone aquí (regla de campos sensibles): se maneja por
    separado en la vista, enrutando a clinic_team_member_activate/deactivate.
    """

    departamento = serializers.CharField(max_length=160, required=False)
    nombre = serializers.CharField(max_length=160, required=False)
    order = serializers.IntegerField(min_value=0, required=False)
    is_active = serializers.BooleanField(required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        _reject_unknown_fields(self, self.initial_data)  # type: ignore[arg-type]
        return attrs


class ClinicTeamMemberOutputSerializer(serializers.ModelSerializer["ClinicTeamMember"]):
    """Salida de ClinicTeamMember."""

    class Meta:
        model = ClinicTeamMember
        fields = ["id", "departamento", "nombre", "order", "is_active", "created_at"]
        read_only_fields = fields
