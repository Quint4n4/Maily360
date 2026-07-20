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

from apps.clinica.models import Sucursal
from apps.personal.models import Consultorio, Doctor, DoctorSchedule


class _ConsultorioMinimalSerializer(serializers.ModelSerializer):
    """Representación mínima de Consultorio para el M2M del Doctor.

    Se usa en DoctorOutputSerializer.consultorios para evitar N+1.
    El queryset debe ser prefetched en el selector antes de serializar.
    """

    class Meta:
        model = Consultorio
        fields = ["id", "name"]
        read_only_fields = fields


class _SucursalMinimalSerializer(serializers.ModelSerializer):
    """Representación mínima de Sucursal (multi-sede — Fase 1).

    Se usa en DoctorOutputSerializer.sucursales y ConsultorioOutputSerializer.sucursal
    para evitar exponer el modelo completo de clinica en el módulo de personal.
    """

    class Meta:
        model = Sucursal
        fields = ["id", "name"]
        read_only_fields = fields


class DoctorOutputSerializer(serializers.ModelSerializer):
    """Serializer de salida para Doctor.

    Expone full_name (propiedad del modelo), user_email / role derivados
    de la membresía, y la lista mínima de consultorios asignados ({id, name}).
    No expone membership_id directo (implementación interna).

    Incluye sello, foto (URLs absolutas via ImageField serialization) y
    cedulas_adicionales para que el frontend del Expediente/Mi Consultorio
    pueda renderizar el perfil completo del médico sin un endpoint adicional.

    sucursales (multi-sede — Fase 1): lista mínima {id, name} de las sedes
    donde el médico puede atender. Vacía = sin restricción (compat. retro).

    Requiere que el queryset haya llamado prefetch_related("consultorios",
    "sucursales") para evitar N+1 al listar múltiples doctores.
    """

    full_name = serializers.SerializerMethodField()
    user_email = serializers.CharField(source="membership.user.email", read_only=True)
    role = serializers.CharField(source="membership.role", read_only=True)
    consultorios = _ConsultorioMinimalSerializer(many=True, read_only=True)
    sucursales = _SucursalMinimalSerializer(many=True, read_only=True)
    sello = serializers.ImageField(read_only=True, use_url=True)
    foto = serializers.ImageField(read_only=True, use_url=True)

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
            "sello",
            "foto",
            "cedulas_adicionales",
            "is_active",
            "consultorios",
            "sucursales",
            "created_at",
        ]
        read_only_fields = fields


class ConsultorioOutputSerializer(serializers.ModelSerializer):
    """Serializer de salida para Consultorio.

    sucursal (multi-sede — Fase 1): objeto mínimo {id, name} o null si el
    consultorio no está asignado a ninguna sede (compatibilidad retro).
    """

    sucursal = _SucursalMinimalSerializer(read_only=True)

    class Meta:
        model = Consultorio
        fields = [
            "id",
            "name",
            "location",
            "color_hex",
            "is_active",
            "sucursal",
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
    - sucursal (multi-sede — Fase 2): objeto mínimo {id, name} o null.
    """

    day_of_week_display = serializers.CharField(
        source="get_day_of_week_display",
        read_only=True,
    )
    consultorio = ConsultorioNestedSerializer(read_only=True)
    sucursal = _SucursalMinimalSerializer(read_only=True, allow_null=True)

    class Meta:
        model = DoctorSchedule
        fields = [
            "id",
            "day_of_week",
            "day_of_week_display",
            "start_time",
            "end_time",
            "consultorio",
            "sucursal",
            "valid_from",
            "valid_until",
            "is_active",
        ]
        read_only_fields = fields
