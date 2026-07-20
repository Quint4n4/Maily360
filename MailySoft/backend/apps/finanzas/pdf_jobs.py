"""Generadores de PDF de finanzas para la infra de PDFs asíncronos (apps.pdfs).

Registrados como kinds "quote" (cotización) y "finance_report" (reporte de periodo)
en FinanzasConfig.ready(). Corren en el worker de Celery con el contexto de tenant
ya activado por la tarea generate_pdf.

Ambas salidas son MUTABLES (la cotización se edita; el reporte se calcula sobre
datos vivos), así que se generan SIEMPRE frescas (sin caché; cache_key="").
"""

import datetime
from typing import Any


def build_quote_pdf(*, params: dict[str, Any], tenant: Any) -> tuple[bytes, str]:
    """Construye el PDF de una cotización. params: {quote_id: str}."""
    from apps.clinica.selectors import clinic_settings_get  # noqa: PLC0415
    from apps.finanzas.pdf import quote_pdf_build  # noqa: PLC0415
    from apps.finanzas.selectors import quote_get  # noqa: PLC0415

    quote = quote_get(quote_id=params["quote_id"])
    clinic_settings = clinic_settings_get(tenant_id=tenant.id) if tenant is not None else None
    pdf_bytes = quote_pdf_build(quote=quote, clinic_settings=clinic_settings)
    folio_short = str(quote.id).replace("-", "")[:8].upper()
    return pdf_bytes, f"cotizacion-{folio_short}.pdf"


def build_finance_report_pdf(*, params: dict[str, Any], tenant: Any) -> tuple[bytes, str]:
    """Construye el PDF del reporte de periodo.

    params: {date_from, date_to, group, sucursal_ids?}. `sucursal_ids` (multi-
    sede — Fase 3, privado por sede) es una lista de UUIDs en string, o
    ausente/None para vista consolidada — la view que encola el job ya
    resolvió el alcance del usuario con `sucursal_scope_ids` antes de encolar,
    así el PDF respeta el mismo alcance que el reporte en pantalla.
    """
    import uuid  # noqa: PLC0415

    from apps.clinica.selectors import clinic_settings_get  # noqa: PLC0415
    from apps.finanzas.pdf import finance_report_pdf_build  # noqa: PLC0415
    from apps.finanzas.selectors import finance_period_report  # noqa: PLC0415

    date_from = datetime.date.fromisoformat(params["date_from"])
    date_to = datetime.date.fromisoformat(params["date_to"])
    group: str = params.get("group", "day")
    raw_sucursal_ids: list[str] | None = params.get("sucursal_ids")
    sucursal_ids: list[uuid.UUID] | None = (
        [uuid.UUID(sid) for sid in raw_sucursal_ids] if raw_sucursal_ids is not None else None
    )
    clinic_settings = clinic_settings_get(tenant_id=tenant.id) if tenant is not None else None
    report = finance_period_report(
        date_from=date_from, date_to=date_to, group=group, sucursal_ids=sucursal_ids
    )
    pdf_bytes = finance_report_pdf_build(report=report, clinic_settings=clinic_settings)
    return pdf_bytes, f"reporte-{date_from}-{date_to}.pdf"
