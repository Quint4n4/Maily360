"""
Modelos de la app clinica — módulo «Mi Consultorio».

ClinicSettings   — configuración única por tenant (identidad, membrete, recetas).
ClinicTemplate   — plantillas reutilizables para recetas, documentos y consentimientos.
PatientCategory  — catálogo de sugerencias de categoría de paciente.

Todos heredan de TenantAwareModel: UUID pk, timestamps, soft-delete, tenant FK,
created_by FK y TenantManager (filtra por tenant activo + excluye soft-deleted).

Imágenes:
    - Nombre aleatorizado (uuid hex) con prefijo de tenant para aislamiento físico en S3.
    - Validación real de contenido con Pillow (validate_image de core/files).
    - Formatos permitidos: JPEG, PNG, WEBP.
"""

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db import models
from django.db.models import Q

from apps.core.files import validate_image, _random_name
from apps.core.models import TenantAwareModel


# ---------------------------------------------------------------------------
# Rutas de subida (upload_to) — prefijo de tenant + nombre aleatorizado
# ---------------------------------------------------------------------------


def clinic_logo_path(instance: "ClinicSettings", filename: str) -> str:
    """Ruta para el logo de la clínica.

    Incluye tenant_id para aislamiento físico en S3/MEDIA_ROOT.
    El nombre se aleatoriza para evitar enumeración y colisiones.
    """
    tenant_id = getattr(instance, "tenant_id", None) or "unknown"
    return f"clinica/{tenant_id}/logo/{_random_name(filename)}"


def clinic_letterhead_full_path(instance: "ClinicSettings", filename: str) -> str:
    """Ruta para el membrete de hoja completa."""
    tenant_id = getattr(instance, "tenant_id", None) or "unknown"
    return f"clinica/{tenant_id}/membretes/full/{_random_name(filename)}"


def clinic_letterhead_half_path(instance: "ClinicSettings", filename: str) -> str:
    """Ruta para el membrete de media hoja."""
    tenant_id = getattr(instance, "tenant_id", None) or "unknown"
    return f"clinica/{tenant_id}/membretes/half/{_random_name(filename)}"


def doctor_sello_path(instance: "object", filename: str) -> str:
    """Ruta para el sello/firma del médico.

    Usa el tenant_id del doctor para aislamiento físico.
    """
    tenant_id = getattr(instance, "tenant_id", None) or "unknown"
    return f"clinica/{tenant_id}/doctores/sellos/{_random_name(filename)}"


def doctor_foto_path(instance: "object", filename: str) -> str:
    """Ruta para la fotografía del médico."""
    tenant_id = getattr(instance, "tenant_id", None) or "unknown"
    return f"clinica/{tenant_id}/doctores/fotos/{_random_name(filename)}"


def doctor_university_logo_path(instance: "DoctorUniversity", filename: str) -> str:
    """Ruta para el logo de universidad de un médico."""
    tenant_id = getattr(instance, "tenant_id", None) or "unknown"
    return f"clinica/{tenant_id}/universidades/{_random_name(filename)}"


# ---------------------------------------------------------------------------
# Validadores de imagen reutilizables para campos ImageField
# ---------------------------------------------------------------------------


def validate_clinic_image(file: object) -> None:
    """Valida que el archivo sea una imagen JPG/PNG/WEBP de máx 5 MB."""
    validate_image(file)


# ---------------------------------------------------------------------------
# ClinicSettings
# ---------------------------------------------------------------------------


class ClinicSettings(TenantAwareModel):
    """Configuración global de la clínica — uno por tenant activo.

    Almacena la identidad visual (logo, membrete), datos de contacto y
    preferencias de generación de recetas.

    Unicidad: solo puede existir un registro activo (deleted_at IS NULL) por tenant.
    La constraint UniqueConstraint parcial previene duplicados sin bloquear
    la re-creación tras un soft-delete.

    recipe_whatsapp_contacts almacena lista de {nombre: str, numero: str}.
    La validación de estructura se hace en el serializer (campo ListField).
    """

    # --- Identidad visual ---
    logo = models.ImageField(
        upload_to=clinic_logo_path,
        null=True,
        blank=True,
        validators=[validate_clinic_image],
        help_text="Logo de la clínica (JPG/PNG/WEBP, máx 5 MB).",
    )

    # --- Datos de contacto ---
    address = models.CharField(
        max_length=300,
        blank=True,
        default="",
        help_text="Dirección principal de la clínica.",
    )
    address_2 = models.CharField(
        max_length=300,
        blank=True,
        default="",
        help_text="Complemento de dirección (colonia, referencias, etc.).",
    )
    phone = models.CharField(
        max_length=30,
        blank=True,
        default="",
        help_text="Teléfono fijo.",
    )
    mobile = models.CharField(
        max_length=30,
        blank=True,
        default="",
        help_text="Teléfono móvil / WhatsApp.",
    )
    email = models.CharField(
        max_length=254,
        blank=True,
        default="",
        help_text="Email de contacto de la clínica.",
    )
    website = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="URL del sitio web.",
    )
    facebook = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="URL o handle de Facebook.",
    )
    instagram = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="URL o handle de Instagram.",
    )
    youtube = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="URL o handle de YouTube.",
    )

    # --- Membretes ---
    letterhead_full = models.ImageField(
        upload_to=clinic_letterhead_full_path,
        null=True,
        blank=True,
        validators=[validate_clinic_image],
        help_text="Membrete de hoja completa (carta). JPG/PNG/WEBP, máx 5 MB.",
    )
    letterhead_half = models.ImageField(
        upload_to=clinic_letterhead_half_path,
        null=True,
        blank=True,
        validators=[validate_clinic_image],
        help_text="Membrete de media hoja. JPG/PNG/WEBP, máx 5 MB.",
    )
    letterhead_full_spaces = models.PositiveIntegerField(
        default=0,
        validators=[MaxValueValidator(200)],
        help_text=(
            "Líneas en blanco a respetar después del membrete de hoja completa. "
            "Máximo 200 (anti-DoS: evita generar PDFs con alturas descomunales)."
        ),
    )
    letterhead_half_spaces = models.PositiveIntegerField(
        default=0,
        validators=[MaxValueValidator(200)],
        help_text=(
            "Líneas en blanco a respetar después del membrete de media hoja. "
            "Máximo 200 (anti-DoS: evita generar PDFs con alturas descomunales)."
        ),
    )

    # --- Preferencias de recetas ---
    recipe_use_responsible_doctor = models.BooleanField(
        default=False,
        help_text=(
            "Si True, todas las recetas se imprimen con el nombre del médico "
            "responsable (no el tratante). Útil cuando hay un responsable sanitario."
        ),
    )
    recipe_whatsapp_contacts = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Lista de contactos de WhatsApp para envío de recetas. "
            "Estructura: [{\"nombre\": \"...\", \"numero\": \"...\"}, ...]."
        ),
    )

    class Meta:
        db_table = "clinica_settings"
        ordering = ["-created_at"]
        constraints = [
            # Solo un ClinicSettings activo por tenant.
            models.UniqueConstraint(
                fields=["tenant"],
                condition=Q(deleted_at__isnull=True),
                name="clinic_settings_tenant_active_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"Config de {self.tenant_id}"


# ---------------------------------------------------------------------------
# ClinicTemplate
# ---------------------------------------------------------------------------


class TemplateKind(models.TextChoices):
    """Tipos de plantilla clínica."""

    RECIPE = "recipe", "Receta"
    DOCUMENT = "document", "Documento"
    CONSENT = "consent", "Consentimiento informado"


class ClinicTemplate(TenantAwareModel):
    """Plantilla reutilizable para recetas, documentos o consentimientos.

    El campo `group` permite agrupar plantillas por categoría clínica
    (p. ej. "PECAJEN", "ONCOLOGÍA", "PEDIATRÍA").

    Baja lógica: DELETE establece is_active=False. No se borra físicamente.
    Índice por (tenant, kind) para acelerar el filtrado por tipo.
    """

    kind = models.CharField(
        max_length=20,
        choices=TemplateKind.choices,
        db_index=True,
        help_text="Tipo de plantilla: receta, documento o consentimiento.",
    )
    name = models.CharField(
        max_length=200,
        help_text="Nombre identificador de la plantilla.",
    )
    body = models.TextField(
        help_text="Cuerpo de la plantilla. Texto libre; puede incluir variables {placeholder}.",
    )
    group = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Grupo o categoría temática (p. ej. 'PECAJEN', 'GINECOLOGÍA').",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="False = plantilla desactivada (soft). No se borra físicamente.",
    )

    class Meta:
        db_table = "clinica_templates"
        ordering = ["kind", "name"]
        indexes = [
            models.Index(
                fields=["tenant", "kind"],
                name="clinic_tmpl_tenant_kind_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"[{self.get_kind_display()}] {self.name}"


# ---------------------------------------------------------------------------
# PatientCategory
# ---------------------------------------------------------------------------


class PatientCategory(TenantAwareModel):
    """Catálogo de sugerencias de categoría de paciente por tenant.

    No modifica Patient.category (que sigue siendo CharField libre).
    Proporciona las opciones de autocompletado en la UI.

    Unicidad: nombre único por tenant en registros activos
    (deleted_at IS NULL). Un registro soft-deleted no bloquea la re-creación.
    """

    name = models.CharField(
        max_length=100,
        help_text="Nombre de la categoría (p. ej. 'VIP', 'Asegurado IMSS').",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="False = categoría desactivada (soft-delete).",
    )

    class Meta:
        db_table = "clinica_patient_categories"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "name"],
                condition=Q(deleted_at__isnull=True),
                name="clinic_category_tenant_name_active_uniq",
            ),
        ]

    def __str__(self) -> str:
        return self.name


# ---------------------------------------------------------------------------
# DoctorUniversity
# ---------------------------------------------------------------------------


class DoctorUniversity(TenantAwareModel):
    """Logo e institución educativa asociada a un médico.

    Permite mostrar los logos de las universidades/instituciones donde el médico
    se formó (pregrado, posgrado, certificación). Cada fila = una institución.

    El campo name es opcional; logo es obligatorio (razón de ser del modelo).
    """

    doctor = models.ForeignKey(
        "personal.Doctor",
        on_delete=models.CASCADE,
        related_name="universities",
        help_text="Médico al que pertenece esta institución educativa.",
    )
    logo = models.ImageField(
        upload_to=doctor_university_logo_path,
        validators=[validate_clinic_image],
        help_text="Logo de la universidad/institución. JPG/PNG/WEBP, máx 5 MB.",
    )
    name = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Nombre de la institución (opcional si el logo es suficiente).",
    )

    class Meta:
        db_table = "clinica_doctor_universities"
        ordering = ["name"]

    def __str__(self) -> str:
        from apps.personal.models import Doctor  # evitar circular al nivel de módulo
        doctor_str = str(self.doctor_id)
        return f"{self.name or 'Logo'} — Doctor {doctor_str}"

    def clean(self) -> None:
        """Valida que el doctor pertenezca al mismo tenant."""
        if self.doctor_id and self.tenant_id:
            # La FK del doctor puede no estar en memoria si viene de migración.
            # Usamos _doctor_cache si existe, de lo contrario skip (la validación
            # de tenant la hace el service en todos los paths de escritura).
            doctor_tenant = getattr(self, "_doctor_cache_tenant_id", None)
            if doctor_tenant is not None and str(doctor_tenant) != str(self.tenant_id):
                raise ValidationError(
                    "El médico no pertenece al tenant de esta institución."
                )
