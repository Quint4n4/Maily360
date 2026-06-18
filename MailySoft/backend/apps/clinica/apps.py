"""AppConfig para el módulo Mi Consultorio (configuración de la clínica)."""

from django.apps import AppConfig


class ClinicaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.clinica"
    verbose_name = "Mi Consultorio"
