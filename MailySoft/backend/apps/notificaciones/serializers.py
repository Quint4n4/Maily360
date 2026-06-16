"""
Serializers de la app notificaciones.

Regla: serializers solo validan/formatean. Cero lógica de negocio aquí.

NotificationOutputSerializer — forma la respuesta de Notification (lectura).
"""

from rest_framework import serializers

from apps.notificaciones.models import Notification


class _ActorNestedSerializer(serializers.Serializer):
    """Representación mínima de quien disparó la notificación."""

    id = serializers.UUIDField(read_only=True)
    full_name = serializers.SerializerMethodField()

    def get_full_name(self, obj: object) -> str:
        return getattr(obj, "full_name", "") or ""


class NotificationOutputSerializer(serializers.ModelSerializer):
    """Serializer de salida para Notification.

    Incluye:
        actor         Objeto mínimo {id, full_name} o null.
        kind          Valor interno (meeting / team_note / role_note / broadcast).
        kind_display  Etiqueta legible del tipo.
        title / body  Textos ya armados.
        target_type   Tipo de objeto destino ("" si no hay).
        target_id     UUID del objeto destino o null.
        read_at       DateTime UTC o null.
        is_read       Bool derivado (read_at != null).
        created_at    DateTime UTC.
    """

    actor = _ActorNestedSerializer(read_only=True)
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    is_read = serializers.BooleanField(read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "actor",
            "kind",
            "kind_display",
            "title",
            "body",
            "target_type",
            "target_id",
            "read_at",
            "is_read",
            "created_at",
        ]
        read_only_fields = fields
