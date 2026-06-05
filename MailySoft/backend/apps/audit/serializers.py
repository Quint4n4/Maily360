"""
Serializers de salida para la app audit.

Solo salida (lectura). La bitácora es append-only; no hay serializer de entrada.
metadata se incluye en la respuesta: el endpoint ya está restringido a owner/admin.
"""

from typing import Any, Optional

from rest_framework import serializers

from apps.audit.models import AuditLog, ActionType


class _ActorSerializer(serializers.Serializer):
    """Serializer embebido para el actor del evento."""

    id = serializers.UUIDField(read_only=True)
    email = serializers.EmailField(read_only=True)
    full_name = serializers.SerializerMethodField()

    def get_full_name(self, obj: Any) -> str:
        """Devuelve el nombre completo o email si no hay nombre."""
        if hasattr(obj, "get_full_name"):
            name: str = obj.get_full_name()
            return name if name else str(obj.email)
        return str(getattr(obj, "email", ""))


class AuditLogOutputSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    """Serializer de salida para un registro de auditoría.

    Incluye el actor serializado (id + email + full_name), el action con
    su label legible, y el metadata completo (solo visible a owner/admin
    según AuditLogPermission que protege el endpoint).
    """

    actor = _ActorSerializer(read_only=True, allow_null=True)
    action_display = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "created_at",
            "actor",
            "actor_role",
            "action",
            "action_display",
            "resource_type",
            "resource_id",
            "resource_repr",
            "description",
            "ip_address",
            "user_agent",
            "request_id",
            "metadata",
        ]
        read_only_fields = fields

    def get_action_display(self, obj: AuditLog) -> str:
        """Devuelve el label legible del ActionType."""
        # get_FOO_display() es generado por Django para fields con choices.
        return obj.get_action_display()  # type: ignore[no-any-return]
