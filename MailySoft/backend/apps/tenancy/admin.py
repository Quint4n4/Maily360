"""Admin de Django para tenancy: Tenant y TenantMembership."""

from django.contrib import admin

from apps.tenancy.models import Tenant, TenantMembership


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Administración de clínicas (tenants)."""

    list_display = ("name", "slug", "status", "timezone", "created_at")
    search_fields = ("name", "slug")
    list_filter = ("status",)
    readonly_fields = ("id", "created_at", "updated_at")
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("name",)


@admin.register(TenantMembership)
class TenantMembershipAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Administración de membresías usuario ↔ clínica."""

    list_display = ("user", "tenant", "role", "is_active", "created_at")
    list_filter = ("role", "is_active", "tenant")
    search_fields = ("user__email", "tenant__name")
    readonly_fields = ("id", "created_at", "updated_at")
    raw_id_fields = ("user", "tenant")
