"""
Admin de Django para la app personal.

IMPORTANTE — audiencia y alcance:
    Este admin muestra doctores, consultorios y horarios de TODOS los tenants
    (vista cross-tenant). Es una herramienta EXCLUSIVA del equipo interno de
    Maily Soft (is_platform_staff=True o superuser). No debe ser accesible al
    staff de una clínica (is_staff=True de una clínica).

    El staff de una clínica solo debe interactuar con sus propios datos a través
    de la API con filtro de tenant.

    Patrón idéntico al de apps/pacientes/admin.py.
"""

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from apps.personal.models import Consultorio, Doctor, DoctorSchedule


def _is_platform_staff(user: object) -> bool:
    """Retorna True si el usuario es platform_staff o superuser."""
    return bool(
        getattr(user, "is_platform_staff", False)
        or getattr(user, "is_superuser", False)
    )


@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Administración de perfiles de médicos.

    Acceso restringido a is_platform_staff o superuser.
    """

    list_display = [
        "full_name",
        "specialty",
        "cedula_profesional",
        "default_appointment_duration",
        "is_active",
        "created_at",
        "tenant",
    ]
    list_filter = ["is_active", "tenant", "specialty"]
    search_fields = [
        "membership__user__first_name",
        "membership__user__last_name",
        "membership__user__email",
        "cedula_profesional",
        "specialty",
    ]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "deleted_at",
        "created_by",
    ]
    ordering = ["-created_at"]
    list_per_page = 50
    raw_id_fields = ["membership"]

    fieldsets = (
        (
            "Identificación",
            {
                "fields": (
                    "id",
                    "tenant",
                    "membership",
                    "is_active",
                ),
            },
        ),
        (
            "Perfil profesional",
            {
                "fields": (
                    "cedula_profesional",
                    "specialty",
                    "default_appointment_duration",
                    "bio_short",
                ),
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

    def get_queryset(self, request: HttpRequest) -> QuerySet[Doctor]:
        """Usa all_objects para que el admin no quede atrapado en el filtro de tenant."""
        return Doctor.all_objects.select_related("membership__user", "tenant")


@admin.register(Consultorio)
class ConsultorioAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Administración de consultorios.

    Acceso restringido a is_platform_staff o superuser.
    """

    list_display = [
        "name",
        "location",
        "color_hex",
        "is_active",
        "created_at",
        "tenant",
    ]
    list_filter = ["is_active", "tenant"]
    search_fields = ["name", "location"]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "deleted_at",
        "created_by",
    ]
    ordering = ["tenant__name", "name"]
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

    def get_queryset(self, request: HttpRequest) -> QuerySet[Consultorio]:
        return Consultorio.all_objects.select_related("tenant")


@admin.register(DoctorSchedule)
class DoctorScheduleAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Administración de horarios de médicos.

    Acceso restringido a is_platform_staff o superuser.
    """

    list_display = [
        "doctor",
        "get_day_of_week_display",
        "start_time",
        "end_time",
        "consultorio",
        "is_active",
        "tenant",
    ]
    list_filter = ["is_active", "day_of_week", "tenant"]
    search_fields = [
        "doctor__membership__user__first_name",
        "doctor__membership__user__last_name",
        "consultorio__name",
    ]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "deleted_at",
        "created_by",
    ]
    ordering = ["tenant__name", "doctor", "day_of_week", "start_time"]
    list_per_page = 50
    raw_id_fields = ["doctor", "consultorio"]

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

    def get_queryset(self, request: HttpRequest) -> QuerySet[DoctorSchedule]:
        return DoctorSchedule.all_objects.select_related(
            "doctor__membership__user", "consultorio", "tenant"
        )
