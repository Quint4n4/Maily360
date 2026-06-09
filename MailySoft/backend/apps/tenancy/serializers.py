"""
Serializers de la app tenancy — salida de miembros de la clínica.

Regla: solo dan forma a la salida. La validación de entrada vive inline en las
vistas (cerca del contrato), igual que en pacientes/agenda.
"""

from rest_framework import serializers

from apps.tenancy.models import TenantMembership


class _MemberUserSerializer(serializers.Serializer):
    """Datos públicos del usuario detrás de una membresía."""

    id = serializers.UUIDField(read_only=True)
    email = serializers.EmailField(read_only=True)
    first_name = serializers.CharField(read_only=True)
    last_name = serializers.CharField(read_only=True)
    full_name = serializers.CharField(read_only=True)
    avatar = serializers.ImageField(read_only=True)
    # is_active del USUARIO = si la cuenta está bloqueada (False = bloqueada).
    is_active = serializers.BooleanField(read_only=True)


class MemberOutputSerializer(serializers.ModelSerializer):
    """Serializer de salida de una membresía (un miembro de la clínica)."""

    user = _MemberUserSerializer(read_only=True)
    role_display = serializers.SerializerMethodField()
    # is_blocked es la lectura cómoda para el frontend (negación de user.is_active).
    is_blocked = serializers.SerializerMethodField()

    class Meta:
        model = TenantMembership
        fields = [
            "id",
            "user",
            "role",
            "role_display",
            "is_active",
            "is_blocked",
            "created_at",
        ]
        read_only_fields = fields

    def get_role_display(self, obj: TenantMembership) -> str:
        return TenantMembership.Role(obj.role).label

    def get_is_blocked(self, obj: TenantMembership) -> bool:
        return not obj.user.is_active
