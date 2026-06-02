"""Admin de Django para el modelo User custom."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.authn.models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):  # type: ignore[type-arg]
    """Administración del User custom.

    Extiende UserAdmin de Django pero sustituye `username` por `email`
    como campo de identificación principal.
    """

    ordering = ("email",)
    list_display = ("email", "full_name", "is_platform_staff", "is_staff", "is_active")
    list_filter = ("is_platform_staff", "is_staff", "is_active", "platform_role")
    search_fields = ("email", "first_name", "last_name")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "Datos personales",
            {"fields": ("first_name", "last_name")},
        ),
        (
            "Plataforma Maily",
            {"fields": ("is_platform_staff", "platform_role")},
        ),
        (
            "Permisos",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (
            "Fechas",
            {"fields": ("last_login", "date_joined")},
        ),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "password1",
                    "password2",
                    "is_staff",
                    "is_active",
                ),
            },
        ),
    )

    readonly_fields = ("id", "date_joined", "last_login")
