"""
Modelos de tenancy: Tenant (clínica), TenantMembership (user ↔ clínica + rol),
Plan (catálogo de planes de suscripción) y TenantSubscription (suscripción activa
de un tenant a un plan).

Tenant hereda de BaseModel (NO TenantAwareModel) porque ES el tenant, no pertenece a uno.
TenantMembership también hereda de BaseModel por la misma razón.

Plan y TenantSubscription TAMPOCO heredan de TenantAwareModel (ver docstrings de
cada clase): son catálogo/gestión exclusiva de la plataforma (equipo Maily), no
datos de negocio de una clínica. Por eso el test guardián de RLS
(apps/core/tests/test_rls_coverage.py, que solo recorre subclases de
TenantAwareModel) no los exige con política RLS — es la decisión correcta, no un
descuido: ningún endpoint de clínica llega a leer/escribir estas tablas.
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
    trial_expired_notified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Marca de idempotencia: cuándo se registró el aviso (evento de "
            "auditoría TRIAL_EXPIRED) de que el trial ya venció. Null = no "
            "avisado todavía. Se resetea si el trial se extiende (nuevo "
            "trial_ends_at posterior a esta marca) para poder volver a avisar."
        ),
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

    @classmethod
    def operational_roles(cls) -> frozenset[str]:
        """Roles "operacionales": TODOS los roles EXCEPTO `owner` y `admin`.

        Jerarquía de roles (decisión del dueño 2026-07-16): un actor con rol
        `owner` administra a cualquiera (incluidos otros owners y admins,
        sin cambios). Un actor con cualquier OTRO rol — el "administrador de
        sucursal" (típicamente `admin`, pero la regla aplica al rol en sí, no
        al nombre) — solo puede VER/CREAR/GESTIONAR personal con un rol
        operacional: nunca a un owner ni a otro admin. Ver
        `apps.tenancy.selectors.membership_list` (visibilidad) y
        `apps.tenancy.services._authorize_write_on_member` (autorización de
        escritura), consumidores de este helper.

        Se DERIVA de `Role.choices` en cada llamada (no se hardcodea la
        lista) para que agregar un rol nuevo a `Role` nunca requiera tocar
        este cálculo ni arriesgue que la lista quede desactualizada.

        Returns:
            frozenset con los values de `Role` distintos de OWNER y ADMIN.
        """
        return frozenset(choice[0] for choice in cls.Role.choices) - {
            cls.Role.OWNER,
            cls.Role.ADMIN,
        }

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


class Plan(BaseModel):
    """Catálogo global de planes de suscripción de la plataforma.

    NO hereda de TenantAwareModel: un Plan no pertenece a ninguna clínica, es
    catálogo administrado por el equipo de Maily (super_admin/sales) y visible
    (de solo lectura) a todos los tenants por igual — como el catálogo de
    productos de un SaaS. Por eso no aplica el test guardián de RLS (que solo
    exige política a subclases de TenantAwareModel): no hay "tenant" que aislar.

    El slug es el identificador estable que usan las migraciones de datos y el
    frontend (no cambia aunque se edite el nombre comercial del plan).
    """

    slug = models.SlugField(
        unique=True,
        max_length=50,
        help_text="Identificador estable del plan. Ej: 'basico', 'pro', 'premium'.",
    )
    name = models.CharField(max_length=100, help_text="Nombre comercial del plan.")
    description = models.TextField(
        blank=True,
        default="",
        help_text="Descripción comercial breve del plan.",
    )
    price_monthly = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Precio mensual en MXN.",
    )
    is_featured = models.BooleanField(
        default=False,
        help_text="Plan destacado/recomendado en la vitrina de planes.",
    )
    features = models.JSONField(
        default=list,
        help_text="Lista de strings con las características incluidas en el plan.",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="False = plan retirado del catálogo (no asignable a nuevas suscripciones).",
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text="Orden de despliegue en la vitrina de planes (ascendente).",
    )

    class Meta:
        db_table = "tenancy_plans"
        ordering = ["order", "name"]

    def __str__(self) -> str:
        return self.name


class TenantSubscription(BaseModel):
    """Suscripción vigente de un Tenant a un Plan.

    NO hereda de TenantAwareModel: aunque tiene un FK a Tenant, esta tabla es
    de gestión EXCLUSIVA de la plataforma (solo super_admin/sales la leen o
    escriben, vía el panel interno cross-tenant) — ninguna clínica tiene un
    endpoint propio que toque su propia suscripción. Al no ser TenantAwareModel
    no aplica (ni tiene sentido aplicar) el aislamiento RLS por tenant: quien
    consulta esta tabla siempre es plataforma, nunca una clínica operando sobre
    sí misma.

    Relación 1:1 con Tenant: una clínica tiene a lo más una suscripción activa
    en un momento dado (cambiar de plan actualiza la misma fila, no crea otra).
    """

    class BillingCycle(models.TextChoices):
        MONTHLY = "monthly", "Mensual"
        ANNUAL = "annual", "Anual"

    tenant = models.OneToOneField(
        Tenant,
        on_delete=models.CASCADE,
        related_name="subscription",
        help_text="Clínica suscrita.",
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name="subscriptions",
        help_text="Plan asignado. PROTECT: no se puede borrar un plan con suscripciones activas.",
    )
    billing_cycle = models.CharField(
        max_length=10,
        choices=BillingCycle.choices,
        help_text="Ciclo de facturación contratado.",
    )
    current_period_end = models.DateField(
        help_text="Fecha en que vence el periodo de facturación vigente.",
    )
    period_expired_notified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Marca de idempotencia: cuándo se registró el aviso (evento de "
            "auditoría SUBSCRIPTION_EXPIRED) de que el periodo ya venció. "
            "Null = no avisado todavía. Se resetea al renovar/cambiar el plan "
            "con una current_period_end futura."
        ),
    )

    class Meta:
        db_table = "tenancy_subscriptions"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.tenant} → {self.plan} ({self.billing_cycle})"
