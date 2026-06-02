"""
Serializers de la app personal.

Regla: serializers solo validan/formatean. Cero lógica de negocio aquí.

DoctorOutputSerializer       — forma la respuesta de Doctor (lectura).
ConsultorioOutputSerializer  — forma la respuesta de Consultorio (lectura).
DoctorScheduleOutputSerializer — forma la respuesta de DoctorSchedule (lectura).

Los InputSerializer se definen inline en cada view como clases anidadas
para mantener el contrato de validación cerca de la vista que lo usa.
"""

from rest_framework import serializers

from apps.personal.models import Consultorio, Doctor, DoctorSchedule


class DoctorOutputSerializer(serializers.ModelSerializer):
    """Serializer de salida para Doctor.

    Expone full_name (propiedad del modelo), y user_email / role derivados
    de la membresía para que la UI los pueda mostrar sin una query extra.
    No expone membership_id directo (implementación interna).
    """

    full_name = serializers.SerializerMethodField()
    user_email = serializers.CharField(source="membership.user.email", read_only=True)
    role = serializers.CharField(source="membership.role", read_only=True)

    def get_full_name(self, obj: Doctor) -> str:
        return obj.full_name

    class Meta:
        model = Doctor
        fields = [
            "id",
            "full_name",
            "user_email",
            "role",
            "cedula_profesional",
            "specialty",
            "default_appointment_duration",
            "bio_short",
            "is_active",
            "created_at",
        ]
        read_only_fields = fields


class ConsultorioOutputSerializer(serializers.ModelSerializer):
    """Serializer de salida para Consultorio."""

    class Meta:
        model = Consultorio
        fields = [
            "id",
            "name",
            "location",
            "color_hex",
            "is_active",
            "created_at",
        ]
        read_only_fields = fields


class ConsultorioNestedSerializer(serializers.ModelSerializer):
    """Representación mínima de Consultorio para incluir en DoctorScheduleOutputSerializer."""

    class Meta:
        model = Consultorio
        fields = ["id", "name"]
        read_only_fields = fields


class DoctorScheduleOutputSerializer(serializers.ModelSerializer):
    """Serializer de salida para DoctorSchedule.

    Incluye:
    - day_of_week_display: etiqueta legible del día (ej. "Lunes").
    - consultorio: objeto con id + name, o null si no tiene consultorio asignado.
    """

    day_of_week_display = serializers.CharField(
        source="get_day_of_week_display",
        read_only=True,
    )
    consultorio = ConsultorioNestedSerializer(read_only=True)

    class Meta:
        model = DoctorSchedule
        fields = [
            "id",
            "day_of_week",
            "day_of_week_display",
            "start_time",
            "end_time",
            "consultorio",
            "valid_from",
            "valid_until",
            "is_active",
        ]
        read_only_fields = fields
