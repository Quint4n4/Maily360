"""Configuración de la app plataforma (panel interno del equipo Maily)."""

from django.apps import AppConfig


class PlataformaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.plataforma"
    verbose_name = "Plataforma (Panel Interno)"
