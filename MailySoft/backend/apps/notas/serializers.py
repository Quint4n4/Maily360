"""
Serializers de la app notas.

Regla: serializers solo validan/formatean. Cero lógica de negocio aquí.

NoteOutputSerializer — forma la respuesta de Note (lectura).

Los InputSerializer se definen inline en cada view como clases anidadas
para mantener el contrato de validación cerca de la vista que los usa.
"""

from rest_framework import serializers

from apps.notas.models import Note


class _AuthorNestedSerializer(serializers.Serializer):
    """Representación mínima del autor de una nota."""

    id = serializers.UUIDField(read_only=True)
    full_name = serializers.SerializerMethodField()

    def get_full_name(self, obj: object) -> str:
        return getattr(obj, "full_name", "") or ""


class NoteOutputSerializer(serializers.ModelSerializer):
    """Serializer de salida para Note.

    Incluye:
        author          Objeto mínimo {id, full_name}.
        scope           Valor interno ('personal', 'role', 'all').
        scope_display   Etiqueta legible del scope.
        target_role     Rol destinatario (vacío si scope != role).
        is_task         Bool.
        done            Bool.
        remind_at       DateTime UTC o null.
        pinned          Bool.
        title           Str.
        body            Str.
        created_at      DateTime UTC.
    """

    author = _AuthorNestedSerializer(read_only=True)
    scope_display = serializers.CharField(source="get_scope_display", read_only=True)

    class Meta:
        model = Note
        fields = [
            "id",
            "author",
            "title",
            "body",
            "scope",
            "scope_display",
            "target_role",
            "is_task",
            "done",
            "remind_at",
            "pinned",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
