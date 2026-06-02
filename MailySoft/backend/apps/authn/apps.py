"""AppConfig para la app authn (usuario custom)."""

from django.apps import AppConfig


class AuthnConfig(AppConfig):
    """Configuración de la app authn."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.authn"
    verbose_name = "Autenticación"
