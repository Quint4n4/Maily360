"""AppConfig para el módulo core de Maily Soft."""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Configuración de la app core."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    verbose_name = "Core"
