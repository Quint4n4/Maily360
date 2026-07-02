"""
Modelos de la app pacientes.

Patient        — expediente del paciente dentro de un tenant (clínica).
PatientSequence — mecanismo de consecutivo seguro por tenant (SELECT FOR UPDATE).

Ambos heredan de TenantAwareModel: tienen tenant FK, created_by, soft-delete, UUIDs.

Campos NOM-004 agregados en A1 (expediente-clinico-plan §3.1):
  Todos opcionales (blank/null=True) para convivir con expedientes provisionales.
  Usa TextChoices para estado civil, escolaridad y tipo de sangre (D-EC-8).
"""

from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import Q

from apps.core.files import patient_avatar_path
from apps.core.models import TenantAwareModel


class Sex(models.TextChoices):
    """Sexo del paciente según NOM-024."""

    MALE = "M", "Masculino"
    FEMALE = "F", "Femenino"
    OTHER = "X", "Otro"


class MaritalStatus(models.TextChoices):
    """Estado civil del paciente (D-EC-8: respuestas precargadas)."""

    SOLTERO = "soltero", "Soltero/a"
    CASADO = "casado", "Casado/a"
    UNION_LIBRE = "union_libre", "Unión libre"
    DIVORCIADO = "divorciado", "Divorciado/a"
    VIUDO = "viudo", "Viudo/a"
    OTRO = "otro", "Otro"


class Education(models.TextChoices):
    """Escolaridad del paciente (D-EC-8: respuestas precargadas)."""

    NINGUNA = "ninguna", "Ninguna"
    PRIMARIA = "primaria", "Primaria"
    SECUNDARIA = "secundaria", "Secundaria"
    PREPARATORIA = "preparatoria", "Preparatoria / Bachillerato"
    LICENCIATURA = "licenciatura", "Licenciatura"
    POSGRADO = "posgrado", "Posgrado"


class BloodType(models.TextChoices):
    """Tipo de sangre ABO/Rh (D-EC-8: respuestas precargadas)."""

    A_POS = "A+", "A+"
    A_NEG = "A-", "A-"
    B_POS = "B+", "B+"
    B_NEG = "B-", "B-"
    AB_POS = "AB+", "AB+"
    AB_NEG = "AB-", "AB-"
    O_POS = "O+", "O+"
    O_NEG = "O-", "O-"
    DESCONOCIDO = "desconocido", "Desconocido"


class Patient(TenantAwareModel):
    """Expediente del paciente en una clínica específica.

    El `record_number` es generado automáticamente por `patient_create` en
    services.py usando el mecanismo SELECT FOR UPDATE de PatientSequence.
    NO se debe asignar manualmente ni exponer como editable en APIs.

    La CURP es opcional pero única por tenant cuando se provee, usando un
    UniqueConstraint parcial (solo aplica cuando curp != '').
    """

    first_name = models.CharField(
        max_length=120,
        help_text="Nombre(s) del paciente.",
    )
    paternal_surname = models.CharField(
        max_length=120,
        help_text="Apellido paterno.",
    )
    maternal_surname = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="Apellido materno (opcional).",
    )
    date_of_birth = models.DateField(
        null=True,
        blank=True,
        help_text="Fecha de nacimiento. Puede ser null en expedientes provisionales.",
    )
    sex = models.CharField(
        max_length=1,
        choices=Sex.choices,
        blank=True,
        default="",
        help_text="Sexo del paciente según NOM-024 (M/F/X). Vacío en provisionales.",
    )
    curp = models.CharField(
        max_length=18,
        blank=True,
        default="",
        help_text="CURP del paciente. Único por clínica cuando se provee.",
    )
    phone = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Teléfono de contacto (WhatsApp). Vacío en provisionales.",
    )
    email = models.EmailField(
        blank=True,
        default="",
        help_text="Correo electrónico (opcional).",
    )
    record_number = models.CharField(
        max_length=30,
        help_text="Número de expediente generado automáticamente. No editar manualmente.",
    )
    notes = models.TextField(
        blank=True,
        default="",
        help_text="Notas internas del expediente.",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="False = expediente desactivado (soft). No borra el registro.",
    )
    is_provisional = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            "True = expediente creado al vuelo desde la agenda con datos mínimos. "
            "Falta completar la información personal (fecha nac., sexo, etc.)."
        ),
    )
    # Favorito y VIP dejaron de ser banderas: ahora son etiquetas del sistema
    # (PatientCategory kind=favorite/vip) en la relación `categories`.
    avatar = models.ImageField(
        upload_to=patient_avatar_path,
        max_length=255,
        null=True,
        blank=True,
        help_text="Foto del paciente (opcional).",
    )

    # -----------------------------------------------------------------------
    # Campos NOM-004 — Expediente Clínico A1 (plan §3.1)
    # Todos opcionales: conviven con expedientes provisionales (D-06).
    # -----------------------------------------------------------------------

    address_street = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Calle y número del domicilio.",
    )
    address_neighborhood = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="Colonia del domicilio.",
    )
    city = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="Ciudad de residencia.",
    )
    state = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="Estado de residencia.",
    )
    postal_code = models.CharField(
        max_length=10,
        blank=True,
        default="",
        help_text="Código postal (CP).",
    )
    birthplace = models.CharField(
        max_length=160,
        blank=True,
        default="",
        help_text="Lugar de nacimiento.",
    )
    marital_status = models.CharField(
        max_length=20,
        choices=MaritalStatus.choices,
        blank=True,
        default="",
        help_text="Estado civil (D-EC-8: opciones predefinidas).",
    )
    education = models.CharField(
        max_length=20,
        choices=Education.choices,
        blank=True,
        default="",
        help_text="Escolaridad (D-EC-8: opciones predefinidas).",
    )
    occupation = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="Ocupación del paciente.",
    )
    religion = models.CharField(
        max_length=80,
        blank=True,
        default="",
        help_text="Religión (opcional, libre).",
    )
    blood_type = models.CharField(
        max_length=12,
        choices=BloodType.choices,
        blank=True,
        default="",
        help_text="Tipo de sangre ABO/Rh (D-EC-8: opciones predefinidas).",
    )
    phone_secondary = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Segundo teléfono de contacto (opcional).",
    )
    phone_label = models.CharField(
        max_length=40,
        blank=True,
        default="",
        help_text="Etiqueta del segundo teléfono (ej. 'hija', 'esposo').",
    )
    is_deceased = models.BooleanField(
        default=False,
        help_text="True si el paciente ha fallecido (campo 'Finado').",
    )
    deceased_at = models.DateField(
        null=True,
        blank=True,
        help_text="Fecha de defunción. Null si is_deceased=False.",
    )
    custom_consultation_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Costo de consulta personalizado para este paciente. "
            "Null = usa la tarifa estándar de la clínica. Lo usará Finanzas."
        ),
    )
    category = models.CharField(
        max_length=60,
        blank=True,
        default="",
        help_text=(
            "Categoría libre (legacy v1). Se conserva por compatibilidad; "
            "la clasificación nueva usa `categories` (etiquetas del catálogo)."
        ),
    )
    categories = models.ManyToManyField(
        "clinica.PatientCategory",
        blank=True,
        related_name="patients",
        help_text=(
            "Etiquetas asignadas al paciente desde el catálogo de la clínica. "
            "Con ellas el médico organiza y filtra a sus pacientes. "
            "Todas deben pertenecer al mismo tenant que el paciente."
        ),
    )

    class Meta:
        db_table = "pacientes_patients"
        ordering = ["-created_at"]
        constraints = [
            # Unicidad de expediente por clínica.
            models.UniqueConstraint(
                fields=["tenant", "record_number"],
                name="patient_record_number_uniq",
            ),
            # CURP único por clínica, solo cuando se provee (no vacío).
            models.UniqueConstraint(
                fields=["tenant", "curp"],
                condition=~Q(curp=""),
                name="patient_curp_uniq",
            ),
        ]
        indexes = [
            # Búsqueda por apellidos desde recepción.
            models.Index(
                fields=["tenant", "paternal_surname", "maternal_surname"],
                name="patient_apellidos_idx",
            ),
            # Búsqueda libre "search-as-you-type" (icontains) sobre varios campos
            # unidos por OR en patient_list. Para que Postgres pueda indexar el OR
            # completo (y no caer en seq scan O(n) por cada tecleo), CADA campo del
            # OR necesita un índice de trigramas. Requiere la extensión pg_trgm,
            # que crea la migración 0012 (TrigramExtension) antes que estos índices.
            GinIndex(
                fields=["first_name"],
                name="patient_first_name_trgm",
                opclasses=["gin_trgm_ops"],
            ),
            GinIndex(
                fields=["paternal_surname"],
                name="patient_paternal_trgm",
                opclasses=["gin_trgm_ops"],
            ),
            GinIndex(
                fields=["maternal_surname"],
                name="patient_maternal_trgm",
                opclasses=["gin_trgm_ops"],
            ),
            GinIndex(
                fields=["phone"],
                name="patient_phone_trgm",
                opclasses=["gin_trgm_ops"],
            ),
            GinIndex(
                fields=["record_number"],
                name="patient_record_num_trgm",
                opclasses=["gin_trgm_ops"],
            ),
        ]

    def __str__(self) -> str:
        return f"{self.full_name} ({self.record_number})"

    @property
    def full_name(self) -> str:
        """Nombre completo: nombre + apellido paterno + materno (si existe)."""
        return f"{self.first_name} {self.paternal_surname} {self.maternal_surname}".strip()


class PatientSequence(TenantAwareModel):
    """Consecutivo de expedientes por clínica.

    Un único registro por tenant. Se actualiza con SELECT FOR UPDATE dentro de
    transaction.atomic() para evitar colisiones en escrituras concurrentes.
    Ver `_next_record_number()` en services.py.
    """

    last_number = models.PositiveIntegerField(
        default=0,
        help_text="Último número de expediente asignado en esta clínica.",
    )

    class Meta:
        db_table = "pacientes_patient_sequences"
        # FIX-B1: constraint explícito para que la BD rechace duplicados concurrentes
        # y el get_or_create en _next_record_number falle con IntegrityError controlable,
        # en lugar de crear silenciosamente dos filas de secuencia para el mismo tenant.
        constraints = [
            models.UniqueConstraint(
                fields=["tenant"],
                name="patient_sequence_tenant_uniq",
            ),
        ]

    def __str__(self) -> str:
        tenant_name = getattr(self.tenant, "name", str(self.tenant_id))
        return f"Secuencia de {tenant_name}: último={self.last_number}"
