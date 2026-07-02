"""
Serializers de entrada y salida para el panel interno de plataforma.

Regla: Input y Output siempre separados. Sin create()/update() con lógica.
"""

from decimal import Decimal
from typing import Any

from rest_framework import serializers

from apps.tenancy.models import Tenant

# ---------------------------------------------------------------------------
# Output — Clínicas (listado)
# ---------------------------------------------------------------------------


class ClinicaOutputSerializer(serializers.Serializer):
    """Serializer de salida para una clínica (Tenant) con conteos anotados."""

    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    slug = serializers.SlugField(read_only=True)
    status = serializers.CharField(read_only=True)
    status_display = serializers.SerializerMethodField()
    trial_ends_at = serializers.DateTimeField(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)
    member_count = serializers.IntegerField(read_only=True, default=0)
    patient_count = serializers.IntegerField(read_only=True, default=0)

    def get_status_display(self, obj: Any) -> str:
        """Devuelve el label legible del estado."""
        if hasattr(obj, "get_status_display"):
            return obj.get_status_display()
        # Si el objeto es un dict (ultimas_clinicas en métricas).
        status_val = obj.get("status", "") if isinstance(obj, dict) else obj.status
        return dict(Tenant.Status.choices).get(status_val, status_val)


# ---------------------------------------------------------------------------
# Output — Métricas del dashboard
# ---------------------------------------------------------------------------


class UltimaClinicaOutputSerializer(serializers.Serializer):
    """Serializer de salida para el resumen de las últimas clínicas."""

    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class DashboardMetricsOutputSerializer(serializers.Serializer):
    """Serializer de salida para las métricas del dashboard de plataforma."""

    total_clinicas = serializers.IntegerField(read_only=True)
    clinicas_por_estado = serializers.DictField(child=serializers.IntegerField(), read_only=True)
    total_usuarios = serializers.IntegerField(read_only=True)
    total_platform_staff = serializers.IntegerField(read_only=True)
    total_pacientes = serializers.IntegerField(read_only=True)
    ultimas_clinicas = UltimaClinicaOutputSerializer(many=True, read_only=True)


# ---------------------------------------------------------------------------
# Input — Cambio de estado de clínica
# ---------------------------------------------------------------------------


class ClinicaEstadoInputSerializer(serializers.Serializer):
    """Input para POST /api/v1/plataforma/clinicas/<id>/estado/."""

    status = serializers.ChoiceField(
        choices=[Tenant.Status.ACTIVE, Tenant.Status.SUSPENDED],
        help_text=(
            "Estado destino: 'active' (reactivar) o 'suspended' (suspender). "
            "No se puede asignar 'trial' desde la plataforma."
        ),
    )


# ---------------------------------------------------------------------------
# Output — Staff de plataforma
# ---------------------------------------------------------------------------


class PlatformStaffOutputSerializer(serializers.Serializer):
    """Serializer de salida para un usuario del equipo de plataforma."""

    id = serializers.UUIDField(read_only=True)
    email = serializers.EmailField(read_only=True)
    full_name = serializers.CharField(read_only=True)
    platform_role = serializers.CharField(read_only=True)
    platform_role_display = serializers.SerializerMethodField()
    is_active = serializers.BooleanField(read_only=True)

    def get_platform_role_display(self, obj: Any) -> str:
        """Devuelve el label legible del platform_role."""
        from apps.authn.models import User

        role_val: str = getattr(obj, "platform_role", "")
        return dict(User.PlatformRole.choices).get(role_val, role_val)


# ---------------------------------------------------------------------------
# Input — Alta de clínica nueva
# ---------------------------------------------------------------------------


class ClinicaCreateInputSerializer(serializers.Serializer):
    """Input para POST /api/v1/plataforma/clinicas/."""

    name = serializers.CharField(
        max_length=200,
        help_text="Nombre comercial de la clínica.",
    )
    owner_email = serializers.EmailField(
        help_text="Correo del dueño. Será su usuario de acceso a la plataforma.",
    )
    owner_first_name = serializers.CharField(
        max_length=150,
        help_text="Nombre(s) del dueño.",
    )
    owner_last_name = serializers.CharField(
        max_length=150,
        help_text="Apellidos del dueño.",
    )
    timezone = serializers.CharField(
        max_length=64,
        default="America/Mexico_City",
        required=False,
        help_text="Zona horaria IANA de la clínica (ej: 'America/Monterrey').",
    )
    trial_days = serializers.IntegerField(
        default=60,
        required=False,
        min_value=1,
        max_value=365,
        help_text="Duración del periodo de prueba en días. Mínimo 1, máximo 365.",
    )

    def validate_name(self, value: str) -> str:
        """Sanitiza el nombre y exige que produzca un identificador legible."""
        from django.utils.text import slugify

        limpio = value.strip()
        if len(slugify(limpio)) < 3:
            raise serializers.ValidationError("El nombre debe tener al menos 3 letras o números.")
        return limpio

    def validate_owner_first_name(self, value: str) -> str:
        return value.strip()

    def validate_owner_last_name(self, value: str) -> str:
        return value.strip()

    def validate_timezone(self, value: str) -> str:
        """Verifica que sea una zona horaria IANA válida (evita clínicas rotas)."""
        import zoneinfo

        try:
            zoneinfo.ZoneInfo(value)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError):
            raise serializers.ValidationError(
                f"Zona horaria inválida: '{value}'. Usa un identificador IANA "
                "(ej: 'America/Mexico_City')."
            )
        return value


# ---------------------------------------------------------------------------
# Output — Alta de clínica (incluye contraseña temporal — uso único)
# ---------------------------------------------------------------------------


class ClinicaCreateOutputSerializer(serializers.Serializer):
    """Salida para POST /api/v1/plataforma/clinicas/.

    SEGURIDAD: temporary_password SOLO se devuelve en esta respuesta.
    El frontend debe mostrarlo exactamente una vez y no persistirlo.
    Esta contraseña no aparece en ningún log ni auditoría.
    """

    tenant = ClinicaOutputSerializer(read_only=True)
    owner_email = serializers.EmailField(read_only=True)
    temporary_password = serializers.CharField(read_only=True)


# ---------------------------------------------------------------------------
# Output — Detalle de clínica (ficha completa)
# ---------------------------------------------------------------------------


class ClinicaMemberOutputSerializer(serializers.Serializer):
    """Miembro de una clínica dentro de la ficha de detalle."""

    id = serializers.UUIDField(read_only=True)
    full_name = serializers.CharField(read_only=True)
    email = serializers.EmailField(read_only=True)
    role = serializers.CharField(read_only=True)
    role_display = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)


class ClinicaDetailOutputSerializer(serializers.Serializer):
    """Ficha de detalle de una clínica para el panel interno de plataforma."""

    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    slug = serializers.SlugField(read_only=True)
    status = serializers.CharField(read_only=True)
    status_display = serializers.CharField(read_only=True)
    trial_ends_at = serializers.DateTimeField(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)
    member_count = serializers.IntegerField(read_only=True)
    patient_count = serializers.IntegerField(read_only=True)
    appointment_count = serializers.IntegerField(read_only=True)
    ultima_actividad = serializers.DateTimeField(read_only=True, allow_null=True)
    members = ClinicaMemberOutputSerializer(many=True, read_only=True)


# ---------------------------------------------------------------------------
# Input — Filtros de la bitácora de auditoría
# ---------------------------------------------------------------------------


class AuditoriaQueryInputSerializer(serializers.Serializer):
    """Valida los query params de GET /api/v1/plataforma/auditoria/.

    Todos los campos son opcionales: filtro no aplicado si se omiten. Se usa
    para coercer/validar tipos (UUID, datetime ISO) antes de pasarlos al
    selector, devolviendo 400 claro en vez de dejar que un valor inválido
    explote como error 500 en el ORM.
    """

    tenant_id = serializers.UUIDField(required=False)
    action = serializers.CharField(required=False, allow_blank=True, max_length=40)
    actor_id = serializers.UUIDField(required=False)
    date_from = serializers.DateTimeField(required=False)
    date_to = serializers.DateTimeField(required=False)
    search = serializers.CharField(required=False, allow_blank=True, max_length=200)


# ---------------------------------------------------------------------------
# Output — Bitácora de auditoría (cross-tenant)
# ---------------------------------------------------------------------------


class AuditLogOutputSerializer(serializers.Serializer):
    """Serializer de salida para un registro de AuditLog en el panel de plataforma."""

    id = serializers.UUIDField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    action = serializers.CharField(read_only=True)
    action_display = serializers.SerializerMethodField()
    actor_email = serializers.SerializerMethodField()
    actor_role = serializers.CharField(read_only=True)
    tenant_id = serializers.UUIDField(read_only=True, allow_null=True)
    tenant_name = serializers.SerializerMethodField()
    resource_type = serializers.CharField(read_only=True)
    resource_id = serializers.UUIDField(read_only=True, allow_null=True)
    description = serializers.CharField(read_only=True)
    ip_address = serializers.IPAddressField(read_only=True, allow_null=True)
    metadata = serializers.JSONField(read_only=True)

    def get_action_display(self, obj: Any) -> str:
        """Devuelve el label legible de la acción."""
        return obj.get_action_display()

    def get_actor_email(self, obj: Any) -> str | None:
        """Email del actor, o None si el evento es anónimo o el usuario se borró."""
        if obj.actor_id is None:
            return None
        return obj.actor.email

    def get_tenant_name(self, obj: Any) -> str | None:
        """Nombre de la clínica, o None si el evento es global (sin tenant)."""
        if obj.tenant_id is None:
            return None
        return obj.tenant.name


# ---------------------------------------------------------------------------
# Output — Salud del sistema (Fase 2, cross-tenant)
# ---------------------------------------------------------------------------


class SystemServiceOutputSerializer(serializers.Serializer):
    """Serializer de salida para el estado de un servicio individual (BD/Redis/Celery)."""

    key = serializers.CharField(read_only=True)
    label = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    latency_ms = serializers.FloatField(read_only=True, allow_null=True)
    detail = serializers.CharField(read_only=True, allow_null=True)


class SystemVersionOutputSerializer(serializers.Serializer):
    """Serializer de salida para el bloque de versión/commit/entorno."""

    commit = serializers.CharField(read_only=True, allow_null=True)
    django = serializers.CharField(read_only=True)
    python = serializers.CharField(read_only=True)
    environment = serializers.CharField(read_only=True)


class SystemPdfQueueOutputSerializer(serializers.Serializer):
    """Serializer de salida para los conteos de la cola de generación de PDFs."""

    pending = serializers.IntegerField(read_only=True)
    processing = serializers.IntegerField(read_only=True)
    failed_24h = serializers.IntegerField(read_only=True)


class SystemHealthOutputSerializer(serializers.Serializer):
    """Serializer de salida para GET /api/v1/plataforma/sistema/.

    Contrato fijado con el frontend (docs/design/plataforma-fases-plan.md,
    Fase 2 — "Sistema" con salud real): NO modificar las llaves sin coordinar
    el cambio con el frontend.
    """

    generated_at = serializers.DateTimeField(read_only=True)
    overall_status = serializers.CharField(read_only=True)
    services = SystemServiceOutputSerializer(many=True, read_only=True)
    version = SystemVersionOutputSerializer(read_only=True)
    pdf_queue = SystemPdfQueueOutputSerializer(read_only=True)


# ---------------------------------------------------------------------------
# Output — Planes (Fase 3, catálogo global sin paginar)
# ---------------------------------------------------------------------------


class PlanOutputSerializer(serializers.Serializer):
    """Serializer de salida para un Plan del catálogo.

    Contrato fijo con el frontend (docs/design/plataforma-fases-plan.md, Fase 3):
    GET /api/v1/plataforma/planes/ → lista SIN paginar, ordenada por `order`.
    """

    id = serializers.UUIDField(read_only=True)
    slug = serializers.SlugField(read_only=True)
    name = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    price_monthly = serializers.DecimalField(read_only=True, max_digits=10, decimal_places=2)
    is_featured = serializers.BooleanField(read_only=True)
    features = serializers.ListField(child=serializers.CharField(), read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    order = serializers.IntegerField(read_only=True)


# ---------------------------------------------------------------------------
# Input — Alta y edición de planes (Fase 3.1)
# ---------------------------------------------------------------------------


class PlanCreateInputSerializer(serializers.Serializer):
    """Input para POST /api/v1/plataforma/planes/.

    NO incluye `slug` (se genera en el servicio a partir de `name`) ni
    `is_active` como excepción distinta a la de PATCH: aquí SÍ se permite
    porque es la creación del recurso (no un update de un flag de estado
    sobre un objeto ya existente); el dueño puede querer dar de alta un plan
    ya desactivado (ej. mientras prepara su lanzamiento).
    """

    name = serializers.CharField(
        max_length=100,
        help_text="Nombre comercial del plan.",
    )
    price_monthly = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0"),
        help_text="Precio mensual en MXN. No puede ser negativo.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=2000,
        help_text="Descripción comercial breve (máx. 2000). Default: cadena vacía.",
    )
    is_featured = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Si el plan aparece destacado en la vitrina.",
    )
    features = serializers.ListField(
        child=serializers.CharField(allow_blank=False, max_length=200),
        required=False,
        allow_null=True,
        default=list,
        max_length=50,
        help_text="Lista de strings no vacíos con las características incluidas (máx. 50).",
    )
    is_active = serializers.BooleanField(
        required=False,
        default=True,
        help_text="Si el plan queda activo/asignable desde su creación.",
    )
    order = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Orden de despliegue. Si se omite, se asigna al final del catálogo.",
    )

    def validate_name(self, value: str) -> str:
        """Rechaza nombres vacíos o solo espacios."""
        limpio = value.strip()
        if not limpio:
            raise serializers.ValidationError("El nombre del plan no puede estar vacío.")
        return limpio


class PlanUpdateInputSerializer(serializers.Serializer):
    """Input para PATCH /api/v1/plataforma/planes/<plan_id>/.

    Todos los campos son opcionales (PATCH parcial): solo se envían los que
    se quieren cambiar. `slug` NO aparece aquí — es inmutable, lo aplica
    `_PLAN_IMMUTABLE_FIELDS` en el servicio `plan_update`.

    EXCEPCIÓN EXPLÍCITA a la regla general de "is_active nunca en el
    InputSerializer de un PATCH genérico": Plan es el caso documentado en el
    encargo (ver docstring de `plan_update` en apps/plataforma/services.py) —
    no tiene borrado físico (PROTECT desde TenantSubscription) y el dueño
    pidió un único flujo de edición sin endpoint separado de
    activar/desactivar.
    """

    name = serializers.CharField(max_length=100, required=False)
    description = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    price_monthly = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0"), required=False
    )
    is_featured = serializers.BooleanField(required=False)
    features = serializers.ListField(
        child=serializers.CharField(allow_blank=False, max_length=200),
        required=False,
        max_length=50,
    )
    is_active = serializers.BooleanField(required=False)
    order = serializers.IntegerField(required=False)

    def validate_name(self, value: str) -> str:
        """Rechaza nombres vacíos o solo espacios cuando se envía el campo."""
        limpio = value.strip()
        if not limpio:
            raise serializers.ValidationError("El nombre del plan no puede estar vacío.")
        return limpio


# ---------------------------------------------------------------------------
# Output — Suscripciones (Fase 3, listado paginado por Tenant)
# ---------------------------------------------------------------------------


class SubscriptionRowOutputSerializer(serializers.Serializer):
    """Serializer de salida para una fila del listado de suscripciones.

    Contrato fijo con el frontend: una fila por Tenant (con o sin
    TenantSubscription). Los campos de plan/suscripción son `allow_null`
    porque el tenant puede no tener suscripción asignada todavía.
    """

    tenant_id = serializers.UUIDField(read_only=True)
    tenant_name = serializers.CharField(read_only=True)
    tenant_slug = serializers.SlugField(read_only=True)
    tenant_status = serializers.CharField(read_only=True)
    trial_ends_at = serializers.DateTimeField(read_only=True, allow_null=True)
    plan_id = serializers.UUIDField(read_only=True, allow_null=True)
    plan_name = serializers.CharField(read_only=True, allow_null=True)
    plan_slug = serializers.CharField(read_only=True, allow_null=True)
    billing_cycle = serializers.CharField(read_only=True, allow_null=True)
    current_period_end = serializers.DateField(read_only=True, allow_null=True)
    plan_price_monthly = serializers.DecimalField(
        read_only=True, allow_null=True, max_digits=10, decimal_places=2
    )
    alerta = serializers.CharField(read_only=True, allow_null=True)


# ---------------------------------------------------------------------------
# Input — Filtros del listado de suscripciones
# ---------------------------------------------------------------------------


class SubscripcionesQueryInputSerializer(serializers.Serializer):
    """Valida los query params de GET /api/v1/plataforma/suscripciones/."""

    search = serializers.CharField(required=False, allow_blank=True, max_length=200)
    plan_id = serializers.UUIDField(required=False)
    alerta = serializers.ChoiceField(
        choices=["vencidas", "por_vencer"],
        required=False,
        allow_blank=True,
        help_text="'vencidas' = solo alertas vencidas. 'por_vencer' = solo por vencer.",
    )


# ---------------------------------------------------------------------------
# Output — Resumen de suscripciones
# ---------------------------------------------------------------------------


class SubscripcionesPorPlanOutputSerializer(serializers.Serializer):
    """Conteo de suscripciones agrupado por plan."""

    plan_id = serializers.UUIDField(read_only=True)
    plan_name = serializers.CharField(read_only=True)
    count = serializers.IntegerField(read_only=True)


class SubscripcionesAlertasOutputSerializer(serializers.Serializer):
    """Conteos de alertas de vencimiento para el resumen del panel."""

    trial_vencido = serializers.IntegerField(read_only=True)
    trial_por_vencer = serializers.IntegerField(read_only=True)
    periodo_vencido = serializers.IntegerField(read_only=True)
    periodo_por_vencer = serializers.IntegerField(read_only=True)


class SubscripcionesResumenOutputSerializer(serializers.Serializer):
    """Serializer de salida para GET /api/v1/plataforma/suscripciones/resumen/."""

    total_clinicas = serializers.IntegerField(read_only=True)
    sin_plan = serializers.IntegerField(read_only=True)
    por_plan = SubscripcionesPorPlanOutputSerializer(many=True, read_only=True)
    alertas = SubscripcionesAlertasOutputSerializer(read_only=True)
    mrr_estimado = serializers.DecimalField(read_only=True, max_digits=12, decimal_places=2)


# ---------------------------------------------------------------------------
# Input — Asignar/cambiar plan de una clínica
# ---------------------------------------------------------------------------


class TenantSubscriptionInputSerializer(serializers.Serializer):
    """Input para POST /api/v1/plataforma/clinicas/<tenant_id>/suscripcion/.

    Los 3 campos son obligatorios (decisión del encargo: sin defaults, la
    plataforma siempre elige explícitamente plan + ciclo + vigencia).
    """

    plan_id = serializers.UUIDField(help_text="UUID del plan a asignar.")
    billing_cycle = serializers.ChoiceField(
        choices=["monthly", "annual"],
        help_text="Ciclo de facturación: 'monthly' o 'annual'.",
    )
    current_period_end = serializers.DateField(
        help_text="Fecha de fin del periodo de facturación. Debe ser futura.",
    )
