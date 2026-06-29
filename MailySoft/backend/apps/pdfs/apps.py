"""AppConfig de la infraestructura genérica de PDFs."""

from django.apps import AppConfig


class PdfsConfig(AppConfig):
    """Configuración de la app pdfs (PdfJob genérico + tarea + endpoints)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.pdfs"
    verbose_name = "PDFs asíncronos"
