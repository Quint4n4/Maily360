"""
Configuración de la app finanzas.
"""

from django.apps import AppConfig


class FinanzasConfig(AppConfig):
    name = "apps.finanzas"
    verbose_name = "Finanzas"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        """Registra los generadores de PDF y la invalidación de caché de finanzas."""
        from apps.core.permissions import (  # noqa: PLC0415
            FinanceDashboardPermission,
            QuotePermission,
        )
        from apps.finanzas.cache import connect_finance_cache_signals  # noqa: PLC0415
        from apps.finanzas.pdf_jobs import (  # noqa: PLC0415
            build_finance_report_pdf,
            build_quote_pdf,
        )
        from apps.pdfs.registry import register_pdf_kind  # noqa: PLC0415

        connect_finance_cache_signals()

        register_pdf_kind(
            "quote", builder=build_quote_pdf, permission=QuotePermission
        )
        register_pdf_kind(
            "finance_report",
            builder=build_finance_report_pdf,
            permission=FinanceDashboardPermission,
        )
