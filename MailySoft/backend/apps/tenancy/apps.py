"""AppConfig para la app tenancy (clínicas y membresías)."""

from django.apps import AppConfig


class TenancyConfig(AppConfig):
    """Configuración de la app tenancy."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tenancy"
    verbose_name = "Tenancy"
