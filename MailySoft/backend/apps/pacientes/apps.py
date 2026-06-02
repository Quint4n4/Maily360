"""
Configuración de la app pacientes.
"""

from django.apps import AppConfig


class PacientesConfig(AppConfig):
    name = "apps.pacientes"
    verbose_name = "Pacientes"
    default_auto_field = "django.db.models.BigAutoField"
