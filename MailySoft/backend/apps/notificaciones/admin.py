"""Admin de la app notificaciones (registro mínimo para el Django admin)."""

from django.contrib import admin

from apps.notificaciones.models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ["id", "kind", "title", "recipient", "actor", "read_at", "created_at"]
    list_filter = ["kind", "target_type"]
    search_fields = ["title", "body"]
    raw_id_fields = ["recipient", "actor", "tenant", "created_by"]
