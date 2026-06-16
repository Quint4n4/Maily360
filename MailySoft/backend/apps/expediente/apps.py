"""Configuración de la app expediente."""

from django.apps import AppConfig


class ExpedienteConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.expediente"
    verbose_name = "Expediente Clínico"
