"""
Admin de la app audit — bitácora de auditoría NOM-024.

AuditLogAdmin: acceso de solo-lectura para platform staff.
    - Todos los campos son read-only.
    - No se puede agregar, cambiar ni borrar ningún registro.
    - Solo usuarios con is_platform_staff=True pueden acceder.
    - Platform staff ve todos los registros de todas las clínicas via all_objects.
"""

from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from apps.audit.models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Admin de solo lectura para la bitácora de auditoría.

    Restricciones de acceso:
        - Solo usuarios con is_platform_staff=True.
        - Sin capacidad de agregar, cambiar ni borrar.

    Usa all_objects para que el platform staff vea todos los tenants.
    """

    # --- Columnas del listado ---
    list_display = [
        "created_at",
        "action",
        "resource_type",
        "resource_repr",
        "actor",
        "actor_role",
        "ip_address",
        "tenant",
    ]
    list_filter = ["action", "resource_type", "tenant"]
    search_fields = ["actor__email", "resource_repr", "description", "request_id", "ip_address"]
    ordering = ["-created_at"]
    date_hierarchy = "created_at"

    # --- Todos los campos son de solo lectura ---
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "deleted_at",
        "tenant",
        "actor",
        "actor_role",
        "action",
        "resource_type",
        "resource_id",
        "resource_repr",
        "description",
        "ip_address",
        "user_agent",
        "request_id",
        "metadata",
        "created_by",
    ]

    # --- Sin acciones bulk ---
    actions = None

    def get_queryset(self, request: HttpRequest) -> Any:
        """Platform staff ve todos los tenants vía all_objects."""
        return AuditLog.all_objects.select_related("actor", "tenant").order_by("-created_at")

    def has_add_permission(self, request: HttpRequest) -> bool:  # type: ignore[override]
        """Nadie puede agregar registros desde el admin."""
        return False

    def has_change_permission(  # type: ignore[override]
        self, request: HttpRequest, obj: Any = None
    ) -> bool:
        """Nadie puede cambiar registros desde el admin."""
        return False

    def has_delete_permission(  # type: ignore[override]
        self, request: HttpRequest, obj: Any = None
    ) -> bool:
        """Nadie puede borrar registros desde el admin."""
        return False

    def has_view_permission(  # type: ignore[override]
        self, request: HttpRequest, obj: Any = None
    ) -> bool:
        """Solo platform staff puede ver la bitácora."""
        return bool(getattr(request.user, "is_platform_staff", False))

    def has_module_perms(self, request: HttpRequest, app_label: str = "") -> bool:  # type: ignore[override]
        """Solo platform staff tiene acceso al módulo de auditoría en el admin."""
        return bool(getattr(request.user, "is_platform_staff", False))
