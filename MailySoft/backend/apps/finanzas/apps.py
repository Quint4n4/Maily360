"""
Configuración de la app finanzas.
"""

from django.apps import AppConfig


class FinanzasConfig(AppConfig):
    name = "apps.finanzas"
    verbose_name = "Finanzas"
    default_auto_field = "django.db.models.BigAutoField"
