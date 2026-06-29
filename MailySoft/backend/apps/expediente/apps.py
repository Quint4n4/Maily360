"""Configuración de la app expediente."""

from django.apps import AppConfig


class ExpedienteConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.expediente"
    verbose_name = "Expediente Clínico"

    def ready(self) -> None:
        """Registra el generador del PDF del libro clínico (kind "book")."""
        from apps.core.permissions import EvolutionPermission  # noqa: PLC0415
        from apps.expediente.pdf_jobs import build_book_pdf  # noqa: PLC0415
        from apps.pdfs.registry import register_pdf_kind  # noqa: PLC0415

        register_pdf_kind(
            "book", builder=build_book_pdf, permission=EvolutionPermission
        )
