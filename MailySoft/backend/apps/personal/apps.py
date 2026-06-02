"""
Configuración de la app personal.
"""

from django.apps import AppConfig


class PersonalConfig(AppConfig):
    name = "apps.personal"
    verbose_name = "Personal"
    default_auto_field = "django.db.models.BigAutoField"
