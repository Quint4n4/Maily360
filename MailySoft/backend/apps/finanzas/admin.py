"""
Admin de Django para la app finanzas.

Igual que pacientes: herramienta EXCLUSIVA del equipo interno de Maily Soft
(is_platform_staff=True o superuser). Muestra registros de TODOS los tenants
para soporte/auditoría; el staff de clínica opera vía la API con filtro de tenant.
"""

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from apps.finanzas.models import (
    CfdiDocument,
    Charge,
    ClinicFiscalConfig,
    Payment,
    PaymentAllocation,
    Quote,
    QuoteItem,
    ServiceConcept,
)


class _PlatformStaffAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Base: restringe el acceso a is_platform_staff/superuser y usa all_objects."""

    def has_module_perms(self, request: HttpRequest) -> bool:
        return bool(
            getattr(request.user, "is_platform_staff", False) or request.user.is_superuser
        )

    def has_view_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return bool(
            getattr(request.user, "is_platform_staff", False) or request.user.is_superuser
        )

    def has_change_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return bool(request.user.is_superuser)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return bool(request.user.is_superuser)

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return bool(request.user.is_superuser)

    def get_queryset(self, request: HttpRequest) -> QuerySet:  # type: ignore[type-arg]
        return self.model.all_objects.all()


@admin.register(ServiceConcept)
class ServiceConceptAdmin(_PlatformStaffAdmin):
    list_display = ["name", "base_price", "is_active", "tenant", "created_at"]
    list_filter = ["is_active", "tenant"]
    search_fields = ["name", "sat_product_key"]
    ordering = ["name"]


@admin.register(ClinicFiscalConfig)
class ClinicFiscalConfigAdmin(_PlatformStaffAdmin):
    list_display = ["rfc", "legal_name", "series", "next_folio", "tenant"]
    list_filter = ["tenant"]
    search_fields = ["rfc", "legal_name"]


@admin.register(Quote)
class QuoteAdmin(_PlatformStaffAdmin):
    list_display = ["id", "patient", "status", "total", "tenant", "created_at"]
    list_filter = ["status", "tenant"]
    ordering = ["-created_at"]


@admin.register(QuoteItem)
class QuoteItemAdmin(_PlatformStaffAdmin):
    list_display = ["description", "quantity", "unit_price", "line_total", "quote"]


@admin.register(Charge)
class ChargeAdmin(_PlatformStaffAdmin):
    list_display = ["description", "patient", "amount", "amount_paid", "status", "tenant", "issued_at"]
    list_filter = ["status", "tenant"]
    ordering = ["-issued_at"]


@admin.register(Payment)
class PaymentAdmin(_PlatformStaffAdmin):
    list_display = ["id", "patient", "amount", "method", "tenant", "received_at"]
    list_filter = ["method", "tenant"]
    ordering = ["-received_at"]


@admin.register(PaymentAllocation)
class PaymentAllocationAdmin(_PlatformStaffAdmin):
    list_display = ["payment", "charge", "amount", "tenant"]


@admin.register(CfdiDocument)
class CfdiDocumentAdmin(_PlatformStaffAdmin):
    list_display = ["id", "uuid_sat", "status", "receptor_rfc", "total", "tenant", "created_at"]
    list_filter = ["status", "tenant"]
    search_fields = ["uuid_sat", "receptor_rfc"]
    ordering = ["-created_at"]
