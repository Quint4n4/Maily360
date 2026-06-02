"""
Modelos de la app pacientes.

Patient        — expediente del paciente dentro de un tenant (clínica).
PatientSequence — mecanismo de consecutivo seguro por tenant (SELECT FOR UPDATE).

Ambos heredan de TenantAwareModel: tienen tenant FK, created_by, soft-delete, UUIDs.
"""

from django.db import models
from django.db.models import Q

from apps.core.models import TenantAwareModel


class Sex(models.TextChoices):
    """Sexo del paciente según NOM-024."""

    MALE = "M", "Masculino"
    FEMALE = "F", "Femenino"
    OTHER = "X", "Otro"


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
        help_text="Fecha de nacimiento.",
    )
    sex = models.CharField(
        max_length=1,
        choices=Sex.choices,
        help_text="Sexo del paciente según NOM-024 (M/F/X).",
    )
    curp = models.CharField(
        max_length=18,
        blank=True,
        default="",
        help_text="CURP del paciente. Único por clínica cuando se provee.",
    )
    phone = models.CharField(
        max_length=20,
        help_text="Teléfono de contacto (WhatsApp).",
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
