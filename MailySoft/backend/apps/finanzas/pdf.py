"""
Generador de PDF para reportes financieros — Fase 2.

Librería: WeasyPrint (misma que apps/recetas y apps/expediente).

Seguridad:
  - _secure_fetcher: SOLO permite data URIs (bloquea file://, http://, SSRF/LFI).
  - El PDF se genera con datos del tenant activo; el endpoint valida Bearer auth.

SVG inline para la barra de A/R aging:
  - Se construye en Python y se inyecta en el template como string SVG.
  - Sin JavaScript: WeasyPrint no lo ejecuta de todas formas.
  - Sin imágenes externas: solo formas y texto SVG puros.
"""

import logging
from decimal import Decimal
from typing import Any

from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger("apps.finanzas.pdf")

ZERO = Decimal("0.00")

# Colores para las cubetas de aging (escala de riesgo: verde→rojo).
_AGING_COLORS: dict[str, str] = {
    "0-30":  "#27ae60",   # Verde: riesgo bajo
    "31-60": "#f39c12",   # Naranja: atención
    "61-90": "#e67e22",   # Naranja oscuro: alto
    "90+":   "#c0392b",   # Rojo: crítico
}
_AGING_LABELS: dict[str, str] = {
    "0-30":  "0-30 días",
    "31-60": "31-60 días",
    "61-90": "61-90 días",
    "90+":   "Más de 90 días",
}


def _secure_fetcher(url: str) -> dict[str, Any]:
    """URL fetcher de seguridad para WeasyPrint — bloquea todo excepto data URIs.

    Replica la política de apps/recetas/pdf.py: solo data URIs permitidas.
    Bloquea LFI y SSRF al rechazar file://, http:// y cualquier otro esquema.

    Args:
        url: URL del recurso referenciado en el HTML/CSS generado.

    Raises:
        ValueError: si la URL no empieza con 'data:'.
    """
    if url.startswith("data:"):
        from weasyprint.urls import default_url_fetcher  # noqa: PLC0415
        return default_url_fetcher(url)  # type: ignore[return-value]

    logger.warning(
        "finanzas.pdf._secure_fetcher: URL bloqueada — '%s'. Solo data URIs permitidas.",
        url[:200],
    )
    raise ValueError(
        f"URL bloqueada por política de seguridad del PDF de finanzas: '{url[:200]}'."
    )


def _fmt_money(value: Decimal) -> str:
    """Formatea un Decimal como cadena monetaria con 2 decimales y separador de miles."""
    return f"${value:,.2f}"


def _build_aging_svg(aging: list[dict[str, Any]], *, width: int = 480, bar_height: int = 22) -> str:
    """Construye el SVG inline de barras horizontales para el A/R aging.

    Genera barras proporcionales al monto máximo de las cubetas. Las cubetas
    se muestran de arriba a abajo en orden de antigüedad: 0-30, 31-60, 61-90, 90+.
    El SVG NO usa JavaScript ni referencias externas: es puro SVG/texto.

    Args:
        aging:      Lista de dicts {bucket, amount, count} del selector.
        width:      Ancho del SVG en px.
        bar_height: Alto de cada barra en px.

    Returns:
        String con el SVG completo (se inyecta directamente en el HTML con |safe).
    """
    if not aging:
        return "<svg width='480' height='40'><text x='10' y='25' font-size='10' fill='#aaa'>Sin cuentas por cobrar pendientes.</text></svg>"

    max_amount: Decimal = max((row["amount"] for row in aging), default=ZERO)
    if max_amount <= ZERO:
        return "<svg width='480' height='40'><text x='10' y='25' font-size='10' fill='#27ae60'>Sin saldo pendiente en ninguna cubeta.</text></svg>"

    label_w = 80   # ancho reservado para la etiqueta izquierda
    bar_area = width - label_w - 120  # 120 px para la etiqueta derecha (monto + count)
    gap = 5        # espacio entre barras
    total_h = len(aging) * (bar_height + gap) + 10

    lines: list[str] = [
        f"<svg width='{width}' height='{total_h}' xmlns='http://www.w3.org/2000/svg'>"
        "<style>text { font-family: Helvetica, Arial, sans-serif; }</style>"
    ]

    for i, row in enumerate(aging):
        bucket: str = row["bucket"]
        amount: Decimal = row["amount"]
        count: int = row["count"]
        color = _AGING_COLORS.get(bucket, "#999")
        label = _AGING_LABELS.get(bucket, bucket)

        bar_w = int(float(amount / max_amount) * bar_area) if max_amount > ZERO else 0
        bar_w = max(bar_w, 2)  # al menos 2px para que se vea

        y = i * (bar_height + gap) + 5
        text_y = y + bar_height // 2 + 4  # centrado vertical en la barra

        # Etiqueta izquierda (nombre de cubeta)
        lines.append(
            f"<text x='{label_w - 4}' y='{text_y}' text-anchor='end' "
            f"font-size='7.5' fill='#444'>{label}</text>"
        )
        # Barra de fondo gris (siempre el ancho completo)
        lines.append(
            f"<rect x='{label_w}' y='{y}' width='{bar_area}' height='{bar_height}' "
            f"fill='#f0f0f0' rx='2'/>"
        )
        # Barra coloreada (proporcional)
        lines.append(
            f"<rect x='{label_w}' y='{y}' width='{bar_w}' height='{bar_height}' "
            f"fill='{color}' rx='2' opacity='0.85'/>"
        )
        # Monto + count a la derecha
        lines.append(
            f"<text x='{label_w + bar_area + 6}' y='{text_y}' font-size='7.5' fill='#222' font-weight='bold'>"
            f"{_fmt_money(amount)}</text>"
        )
        lines.append(
            f"<text x='{label_w + bar_area + 6}' y='{text_y + 9}' font-size='6' fill='#888'>"
            f"{count} cargo{'s' if count != 1 else ''}</text>"
        )

    lines.append("</svg>")
    return "\n".join(lines)


def finance_report_pdf_build(*, report: dict[str, Any], clinic_name: str) -> bytes:
    """Genera el PDF del reporte financiero de periodo con WeasyPrint.

    Recibe el dict devuelto por `finance_period_report` (ya calculado por el selector)
    y el nombre de la clínica para el encabezado. Construye el contexto para el template
    HTML, renderiza el HTML y lo convierte a PDF.

    Seguridad:
        - Usa _secure_fetcher para bloquear LFI/SSRF.
        - No escribe archivos a disco: devuelve bytes.
        - El PDF no se cachea en memoria ni en BD: se genera en tiempo real.

    Args:
        report:      Dict devuelto por finance_period_report().
        clinic_name: Nombre de la clínica para el encabezado.

    Returns:
        bytes: contenido del PDF.

    Raises:
        RuntimeError: si WeasyPrint falla al renderizar el PDF.
    """
    import weasyprint  # noqa: PLC0415 — importación tardía para no penalizar startup

    aging: list[dict[str, Any]] = report.get("aging", [])
    aging_svg = _build_aging_svg(aging)

    production: Decimal = report["production"]
    collection: Decimal = report["collection"]
    collection_pct: Decimal = report["collection_pct"]
    prev_production: Decimal = report["prev_production"]
    prev_collection: Decimal = report["prev_collection"]
    prev_collection_pct: Decimal = report["prev_collection_pct"]

    delta_production_pct = report.get("delta_production_pct")
    delta_collection_pct = report.get("delta_collection_pct")
    delta_collection_rate_ppt = report.get("delta_collection_rate_ppt")

    def _sign(val: Any) -> str:
        if val is None:
            return "neutral"
        if val > 0:
            return "up"
        if val < 0:
            return "down"
        return "neutral"

    by_method = report.get("by_method", [])
    total_payments_count = sum(row["count"] for row in by_method)

    # Calcular % de producción por doctor.
    by_doctor = report.get("by_doctor", [])
    for row in by_doctor:
        row["pct"] = round(
            float(row["amount"] / production * 100) if production > ZERO else 0.0, 1
        )

    context: dict[str, Any] = {
        "clinic_name": clinic_name,
        "date_from": report["range"]["date_from"],
        "date_to": report["range"]["date_to"],
        "prev_date_from": report["prev_range"]["date_from"],
        "prev_date_to": report["prev_range"]["date_to"],
        "generated_at": timezone.now().strftime("%Y-%m-%d %H:%M UTC"),
        # KPIs
        "production": _fmt_money(production),
        "collection": _fmt_money(collection),
        "collection_pct_display": f"{float(collection_pct) * 100:.1f}",
        "ar_total": _fmt_money(report["ar_total"]),
        "average_ticket": _fmt_money(report["average_ticket"]),
        "charges_count": report["charges_count"],
        # Comparativa
        "prev_production": _fmt_money(prev_production),
        "prev_collection": _fmt_money(prev_collection),
        "prev_collection_pct_display": f"{float(prev_collection_pct) * 100:.1f}",
        "delta_production_pct": delta_production_pct,
        "delta_collection_pct": delta_collection_pct,
        "delta_collection_rate_ppt": delta_collection_rate_ppt,
        "delta_prod_sign": _sign(delta_production_pct),
        "delta_col_sign": _sign(delta_collection_pct),
        # Desglose
        "by_method": by_method,
        "by_service": report.get("by_service", []),
        "by_doctor": by_doctor,
        "total_payments_count": total_payments_count,
        # SVG aging
        "aging_svg": aging_svg,
        # Nota ajustes
        "adjustments_note": report.get("adjustments_note", "Sin datos de ajustes."),
    }

    html_string = render_to_string("finanzas/reporte_periodo.html", context)

    try:
        pdf_bytes: bytes = weasyprint.HTML(
            string=html_string,
            url_fetcher=_secure_fetcher,
            base_url=None,
        ).write_pdf()
    except Exception as exc:
        logger.error(
            "finance_report_pdf_build: WeasyPrint falló — %s",
            exc,
        )
        raise RuntimeError(f"Error al generar PDF del reporte financiero: {exc}") from exc

    return pdf_bytes
