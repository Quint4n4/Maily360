"""Configuración de la app expediente."""

from django.apps import AppConfig


class ExpedienteConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.expediente"
    verbose_name = "Expediente Clínico"

    def ready(self) -> None:
        """Registra los generadores de PDF del expediente.

        Kinds: "book", "resumen_clinico", "treatment_plan", "plan_integral".
        """
        from apps.core.permissions import (  # noqa: PLC0415
            ClinicalSummaryPermission,
            EvolutionPermission,
            LongevityPlanPermission,
            TreatmentPlanPermission,
        )
        from apps.expediente.pdf_jobs import (  # noqa: PLC0415
            build_book_pdf,
            build_longevity_plan_pdf,
            build_resumen_clinico_pdf,
            build_treatment_plan_pdf,
        )
        from apps.pdfs.registry import register_pdf_kind  # noqa: PLC0415

        register_pdf_kind("book", builder=build_book_pdf, permission=EvolutionPermission)
        register_pdf_kind(
            "resumen_clinico",
            builder=build_resumen_clinico_pdf,
            permission=ClinicalSummaryPermission,
        )
        register_pdf_kind(
            "treatment_plan",
            builder=build_treatment_plan_pdf,
            permission=TreatmentPlanPermission,
        )
        register_pdf_kind(
            "plan_integral",
            builder=build_longevity_plan_pdf,
            permission=LongevityPlanPermission,
        )
