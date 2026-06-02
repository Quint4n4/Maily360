"""
Serializers de la app agenda.

Regla: serializers solo validan/formatean. Cero lógica de negocio aquí.

AppointmentOutputSerializer   — forma la respuesta de Appointment (lectura).
TenantAgendaConfigOutputSerializer — forma la respuesta de TenantAgendaConfig (lectura).

Los InputSerializer se definen inline en cada view como clases anidadas
para mantener el contrato de validación cerca de la vista que lo usa.

IMPORTANTE: `status` NUNCA aparece en un InputSerializer de PATCH genérico.
Solo se acepta en AppointmentChangeStatusApi.
"""

from rest_framework import serializers

from apps.agenda.models import Appointment, TenantAgendaConfig


# ---------------------------------------------------------------------------
# Serializers de representación anidada (mínimos)
# ---------------------------------------------------------------------------


class _PatientNestedSerializer(serializers.Serializer):
    """Representación mínima del paciente dentro de una cita."""

    id = serializers.UUIDField(read_only=True)
    full_name = serializers.SerializerMethodField()

    def get_full_name(self, obj: object) -> str:
        return getattr(obj, "full_name", "")


class _DoctorNestedSerializer(serializers.Serializer):
    """Representación mínima del médico dentro de una cita."""

    id = serializers.UUIDField(read_only=True)
    full_name = serializers.SerializerMethodField()

    def get_full_name(self, obj: object) -> str:
        return getattr(obj, "full_name", "")


class _ConsultorioNestedSerializer(serializers.Serializer):
    """Representación mínima del consultorio dentro de una cita (puede ser null)."""

    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)


# ---------------------------------------------------------------------------
# AppointmentOutputSerializer
# ---------------------------------------------------------------------------


class AppointmentOutputSerializer(serializers.ModelSerializer):
    """Serializer de salida para Appointment.

    Incluye:
    - patient: id + full_name (requiere select_related("patient")).
    - doctor:  id + full_name (requiere select_related("doctor__membership__user")).
    - consultorio: id + name o null (requiere select_related("consultorio")).
    - status_display: etiqueta legible del estado.
    """

    patient = _PatientNestedSerializer(read_only=True)
    doctor = _DoctorNestedSerializer(read_only=True)
    consultorio = _ConsultorioNestedSerializer(read_only=True, allow_null=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Appointment
        fields = [
            "id",
            "patient",
            "doctor",
            "consultorio",
            "starts_at",
            "ends_at",
            "status",
            "status_display",
            "reason",
            "specialty",
            "notes",
            "created_at",
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# TenantAgendaConfigOutputSerializer
# ---------------------------------------------------------------------------


class TenantAgendaConfigOutputSerializer(serializers.ModelSerializer):
    """Serializer de salida para TenantAgendaConfig."""

    class Meta:
        model = TenantAgendaConfig
        fields = [
            "id",
            "record_number_format",
            "record_number_reset_yearly",
            "default_appointment_duration",
            "reminder_offsets_minutes",
            "reminders_enabled",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
