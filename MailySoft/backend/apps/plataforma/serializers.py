"""
Serializers de entrada y salida para el panel interno de plataforma.

Regla: Input y Output siempre separados. Sin create()/update() con lógica.
"""

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
