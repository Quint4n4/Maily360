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

from apps.agenda.models import (
    AgendaBlock,
    AgendaItemNote,
    Appointment,
    AppointmentReminder,
    AppointmentType,
    TenantAgendaConfig,
)


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


class _AppointmentTypeNestedSerializer(serializers.Serializer):
    """Representación mínima del tipo de cita (id + nombre + color)."""

    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    color_hex = serializers.CharField(read_only=True)


class AppointmentTypeOutputSerializer(serializers.ModelSerializer):
    """Serializer de salida para AppointmentType (catálogo de tipos de cita)."""

    class Meta:
        model = AppointmentType
        fields = ["id", "name", "color_hex", "is_active", "created_at"]
        read_only_fields = fields


class AgendaBlockOutputSerializer(serializers.ModelSerializer):
    """Serializer de salida para AgendaBlock (reuniones y bloqueos)."""

    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    doctor = _DoctorNestedSerializer(read_only=True, allow_null=True)
    consultorio = _ConsultorioNestedSerializer(read_only=True, allow_null=True)

    class Meta:
        model = AgendaBlock
        fields = [
            "id",
            "kind",
            "kind_display",
            "title",
            "doctor",
            "consultorio",
            "starts_at",
            "ends_at",
            "all_day",
            "notes",
            "created_at",
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# AppointmentReminderOutputSerializer
# ---------------------------------------------------------------------------


class AppointmentReminderOutputSerializer(serializers.ModelSerializer):
    """Serializer de salida (solo lectura) para AppointmentReminder.

    Se anida dentro de AppointmentOutputSerializer y se usa en el endpoint de
    recordatorios de una cita. No expone campos internos como error_detail o
    external_message_id (no son útiles para el usuario clínico).
    """

    channel_display = serializers.CharField(source="get_channel_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = AppointmentReminder
        fields = [
            "id",
            "channel",
            "channel_display",
            "scheduled_at",
            "sent_at",
            "status",
            "status_display",
        ]
        read_only_fields = fields


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
    - reminders: lista de recordatorios (read-only; requiere prefetch_related("reminders")).
    """

    patient = _PatientNestedSerializer(read_only=True)
    doctor = _DoctorNestedSerializer(read_only=True)
    consultorio = _ConsultorioNestedSerializer(read_only=True, allow_null=True)
    appointment_type = _AppointmentTypeNestedSerializer(read_only=True, allow_null=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    reminders = AppointmentReminderOutputSerializer(many=True, read_only=True)

    class Meta:
        model = Appointment
        fields = [
            "id",
            "patient",
            "doctor",
            "consultorio",
            "appointment_type",
            "starts_at",
            "ends_at",
            "status",
            "status_display",
            "reason",
            "specialty",
            "notes",
            "reminders",
            "created_at",
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# AgendaItemNoteOutputSerializer
# ---------------------------------------------------------------------------


class _AuthorNestedSerializer(serializers.Serializer):
    """Representación mínima del autor de una nota de agenda."""

    id = serializers.UUIDField(read_only=True)
    full_name = serializers.SerializerMethodField()

    def get_full_name(self, obj: object) -> str:
        return getattr(obj, "full_name", "") or getattr(obj, "email", "")


class AgendaItemNoteOutputSerializer(serializers.ModelSerializer):
    """Serializer de salida para AgendaItemNote (hilo de notas de la agenda).

    Requiere select_related("author") en el queryset para evitar N+1.
    """

    author = _AuthorNestedSerializer(read_only=True)

    class Meta:
        model = AgendaItemNote
        fields = ["id", "author", "body", "created_at"]
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
