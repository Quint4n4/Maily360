"""
Admin de Django para la app agenda.

IMPORTANTE — audiencia y alcance:
    Este admin muestra citas y config de agenda de TODOS los tenants
    (vista cross-tenant). Es una herramienta EXCLUSIVA del equipo interno de
    Maily Soft (is_platform_staff=True o superuser). No debe ser accesible al
    staff de una clínica (is_staff=True de una clínica).

    El staff de una clínica solo debe interactuar con sus propios datos a través
    de la API con filtro de tenant.

    Patrón idéntico al de apps/pacientes/admin.py y apps/personal/admin.py.
"""

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from apps.agenda.models import Appointment, TenantAgendaConfig


def _is_platform_staff(user: object) -> bool:
    """Retorna True si el usuario es platform_staff o superuser."""
    return bool(
        getattr(user, "is_platform_staff", False)
        or getattr(user, "is_superuser", False)
    )


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Administración de citas médicas.

    Acceso restringido a is_platform_staff o superuser.
    NO permite cambiar el status manualmente — solo lectura del estado.
    El cambio de estado debe ocurrir a través de la API (appointment_change_status).
    """

    list_display = [
        "id",
        "patient",
        "doctor",
        "consultorio",
        "starts_at",
        "ends_at",
        "status",
        "reason",
        "tenant",
        "created_at",
    ]
    list_filter = ["status", "tenant", "starts_at"]
    search_fields = [
        "patient__first_name",
        "patient__paternal_surname",
        "doctor__membership__user__first_name",
        "doctor__membership__user__last_name",
        "reason",
    ]
    readonly_fields = [
        "id",
        "status",  # inmutable via admin; solo via API
        "created_at",
        "updated_at",
        "deleted_at",
        "created_by",
        "cancelled_by",
        "no_show_registered_by",
        "series_id",
    ]
    ordering = ["-starts_at"]
    list_per_page = 50
    raw_id_fields = ["patient", "doctor", "consultorio"]
    date_hierarchy = "starts_at"

    fieldsets = (
        (
            "Identificación",
            {
                "fields": (
                    "id",
                    "tenant",
                    "status",
                ),
            },
        ),
        (
            "Cita",
            {
                "fields": (
                    "patient",
                    "doctor",
                    "consultorio",
                    "starts_at",
                    "ends_at",
                    "reason",
                    "specialty",
                    "notes",
                ),
            },
        ),
        (
            "Cancelación / No show",
            {
                "fields": (
                    "cancelled_by",
                    "cancellation_reason",
                    "no_show_registered_by",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Auditoría",
            {
                "fields": (
                    "created_by",
                    "created_at",
                    "updated_at",
                    "deleted_at",
                    "series_id",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def has_module_perms(self, request: HttpRequest) -> bool:
        return _is_platform_staff(request.user)

    def has_view_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return _is_platform_staff(request.user)

    def has_change_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return _is_platform_staff(request.user)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return _is_platform_staff(request.user)

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return bool(getattr(request.user, "is_superuser", False))

    def get_queryset(self, request: HttpRequest) -> QuerySet[Appointment]:
        """Usa all_objects para que el admin no quede atrapado en el filtro de tenant."""
        return Appointment.all_objects.select_related(
            "patient",
            "doctor__membership__user",
            "consultorio",
            "tenant",
            "cancelled_by",
            "no_show_registered_by",
        )


@admin.register(TenantAgendaConfig)
class TenantAgendaConfigAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Administración de configuración de agenda por clínica.

    Acceso restringido a is_platform_staff o superuser.
    """

    list_display = [
        "tenant",
        "default_appointment_duration",
        "reminders_enabled",
        "record_number_format",
        "created_at",
    ]
    list_filter = ["reminders_enabled", "tenant"]
    search_fields = ["tenant__name", "tenant__slug"]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "deleted_at",
        "created_by",
    ]
    ordering = ["tenant__name"]
    list_per_page = 50

    def has_module_perms(self, request: HttpRequest) -> bool:
        return _is_platform_staff(request.user)

    def has_view_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return _is_platform_staff(request.user)

    def has_change_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return _is_platform_staff(request.user)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return _is_platform_staff(request.user)

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return bool(getattr(request.user, "is_superuser", False))

    def get_queryset(self, request: HttpRequest) -> QuerySet[TenantAgendaConfig]:
        return TenantAgendaConfig.all_objects.select_related("tenant")
