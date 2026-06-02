"""
Modelos de tenancy: Tenant (clínica) y TenantMembership (user ↔ clínica + rol).

Tenant hereda de BaseModel (NO TenantAwareModel) porque ES el tenant, no pertenece a uno.
TenantMembership también hereda de BaseModel por la misma razón.
"""

from django.db import models

from apps.core.models import BaseModel


class Tenant(BaseModel):
    """Una clínica en la plataforma. Representa un tenant completo.

    Ciclo de vida:
        TRIAL → ACTIVE → SUSPENDED

    El campo `slug` es el identificador único legible por humanos (para subdominio
    o header X-Tenant-ID en el Paso 3).
    """

    class Status(models.TextChoices):
        TRIAL = "trial", "En prueba"
        ACTIVE = "active", "Activa"
        SUSPENDED = "suspended", "Suspendida"

    name = models.CharField(max_length=200, help_text="Nombre comercial de la clínica.")
    slug = models.SlugField(
        unique=True,
        max_length=100,
        help_text="Identificador URL-safe único. Ej: clinica-san-jose",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.TRIAL,
        db_index=True,
    )
    trial_ends_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Fecha de fin del periodo de prueba. Null = sin límite.",
    )
    timezone = models.CharField(
        max_length=64,
        default="America/Mexico_City",
        help_text="Zona horaria del tenant para localizar fechas. Usar nombres IANA.",
    )

    class Meta:
        db_table = "tenancy_tenants"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class TenantMembership(BaseModel):
    """Liga un User con un Tenant y le asigna un rol dentro de esa clínica.

    Un mismo usuario puede tener membresías en varias clínicas (útil para
    doctores que trabajan en más de una). El campo `is_active` permite
    suspender el acceso sin borrar el historial.

    Roles posibles:
        owner       — Propietario de la clínica (puede borrar la cuenta).
        admin       — Administrador: gestión de usuarios y configuración.
        doctor      — Médico: acceso a expedientes y agenda completos.
        nurse       — Enfermería: acceso clínico limitado.
        reception   — Recepcionista: agenda y pacientes, sin expediente clínico.
        finance     — Finanzas: facturación y pagos.
        readonly    — Consulta sin modificaciones.
    """

    class Role(models.TextChoices):
        OWNER = "owner", "Dueño"
        ADMIN = "admin", "Administrador"
        DOCTOR = "doctor", "Médico"
        NURSE = "nurse", "Enfermería"
        RECEPTION = "reception", "Recepción"
        FINANCE = "finance", "Finanzas"
        READONLY = "readonly", "Solo lectura"

    user = models.ForeignKey(
        "authn.User",
        on_delete=models.CASCADE,
        related_name="memberships",
        help_text="Usuario miembro de la clínica.",
    )
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="memberships",
        help_text="Clínica a la que pertenece la membresía.",
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        help_text="Rol del usuario dentro de la clínica.",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="False = acceso suspendido (sin borrar la membresía).",
    )

    class Meta:
        db_table = "tenancy_memberships"
        # FIX-9: UniqueConstraint moderno en lugar de unique_together (deprecado en Django 4.2+).
        constraints = [
            models.UniqueConstraint(fields=["user", "tenant"], name="membership_user_tenant_uniq"),
        ]
        indexes = [
            models.Index(fields=["tenant", "role"], name="membership_tenant_role_idx"),
            # FIX-6: índice compuesto (user, is_active) para el filtro del middleware.
            models.Index(fields=["user", "is_active"], name="membership_user_active_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user} @ {self.tenant} ({self.role})"
