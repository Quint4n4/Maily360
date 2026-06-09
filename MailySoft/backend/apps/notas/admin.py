"""Admin de la app notas (registro mínimo para el Django admin)."""

from django.contrib import admin

from apps.notas.models import Note


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ["id", "author", "scope", "target_role", "is_task", "done", "pinned", "created_at"]
    list_filter = ["scope", "is_task", "done", "pinned"]
    search_fields = ["title", "body"]
    raw_id_fields = ["author", "tenant", "created_by"]
