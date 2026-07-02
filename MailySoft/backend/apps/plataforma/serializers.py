"""
Serializers de entrada y salida para el panel interno de plataforma.

Regla: Input y Output siempre separados. Sin create()/update() con lógica.
"""

from typing import Any, Optional

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
    clinicas_por_estado = serializers.DictField(
        child=serializers.IntegerField(), read_only=True
    )
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
            raise serializers.ValidationError(
                "El nombre debe tener al menos 3 letras o números."
            )
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

    def get_actor_email(self, obj: Any) -> Optional[str]:
        """Email del actor, o None si el evento es anónimo o el usuario se borró."""
        if obj.actor_id is None:
            return None
        return obj.actor.email

    def get_tenant_name(self, obj: Any) -> Optional[str]:
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
