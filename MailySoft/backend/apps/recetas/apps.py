"""AppConfig de la app recetas (B1 — Módulo de Recetas Médicas)."""

from django.apps import AppConfig


class RecetasConfig(AppConfig):
    """Configuración de la app recetas."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.recetas"
    verbose_name = "Recetas"
