"""
Admin de Django para la app pacientes.

IMPORTANTE — audiencia y alcance (FIX-B9):
    Este admin muestra pacientes de TODOS los tenants (multi-tenant cross-tenant view).
    Es una herramienta EXCLUSIVA del equipo interno de Maily Soft (is_platform_staff=True
    o superuser). No debe ser accesible a staff de clínica (is_staff=True de una clínica).

    El motivo es operativo: soporte, auditoría y resolución de incidencias requieren
    que el equipo de plataforma pueda ver registros de cualquier tenant. El staff de una
    clínica solo debe ver sus propios pacientes, a través de la API con filtro de tenant.

    CURP se eliminó de list_display para reducir la exposición de PII en listados.
"""

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from apps.pacientes.models import Patient, PatientSequence


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Administración de expedientes de pacientes.

    Acceso restringido a is_platform_staff o superuser. Ver docstring del módulo.
    """

    # FIX-B9: curp eliminado de list_display para reducir exposición de PII.
    list_display = [
        "record_number",
        "full_name",
        "phone",
        "sex",
        "is_active",
        "created_at",
        "tenant",
    ]
    list_filter = ["sex", "is_active", "tenant"]
    search_fields = [
        "first_name",
        "paternal_surname",
        "maternal_surname",
        "phone",
        "record_number",
        # CURP se puede buscar pero no se muestra en la lista.
        "curp",
    ]
    readonly_fields = [
        "id",
        "record_number",
        "created_at",
        "updated_at",
        "deleted_at",
        "created_by",
    ]
    ordering = ["-created_at"]
    list_per_page = 50

    fieldsets = (
        (
            "Identificación",
            {
                "fields": (
                    "id",
                    "record_number",
                    "tenant",
                    "is_active",
                ),
            },
        ),
        (
            "Datos personales",
            {
                "fields": (
                    "first_name",
                    "paternal_surname",
                    "maternal_surname",
                    "date_of_birth",
                    "sex",
                    "curp",
                ),
            },
        ),
        (
            "Contacto",
            {
                "fields": (
                    "phone",
                    "email",
                ),
            },
        ),
        (
            "Notas",
            {
                "fields": ("notes",),
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

    # FIX-B9: solo equipo de plataforma puede acceder a este admin.
    def has_module_perms(self, request: HttpRequest) -> bool:
        """Solo is_platform_staff o superuser puede ver el módulo en el admin."""
        return bool(
            getattr(request.user, "is_platform_staff", False) or request.user.is_superuser
        )

    def has_view_permission(self, request: HttpRequest, obj: object = None) -> bool:
        """Solo is_platform_staff o superuser puede ver expedientes."""
        return bool(
            getattr(request.user, "is_platform_staff", False) or request.user.is_superuser
        )

    def has_change_permission(self, request: HttpRequest, obj: object = None) -> bool:
        """Solo is_platform_staff o superuser puede editar expedientes."""
        return bool(
            getattr(request.user, "is_platform_staff", False) or request.user.is_superuser
        )

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Solo is_platform_staff o superuser puede agregar expedientes."""
        return bool(
            getattr(request.user, "is_platform_staff", False) or request.user.is_superuser
        )

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        """Solo superuser puede borrar (acción destructiva). is_platform_staff no puede."""
        return bool(request.user.is_superuser)

    def get_queryset(self, request: HttpRequest) -> QuerySet[Patient]:
        """Usa all_objects para que el admin no quede atrapado en el filtro de tenant."""
        return Patient.all_objects.all()


@admin.register(PatientSequence)
class PatientSequenceAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Administración de secuencias de expediente (solo lectura práctica).

    FIX-B9: restringido a is_platform_staff o superuser (misma política que PatientAdmin).
    """

    list_display = ["tenant", "last_number", "created_at", "updated_at"]
    readonly_fields = ["id", "created_at", "updated_at", "created_by"]
    ordering = ["tenant__name"]

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

    def get_queryset(self, request: HttpRequest) -> QuerySet[PatientSequence]:
        return PatientSequence.all_objects.all()
