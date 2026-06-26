"""
apps.core.pdf.fetchers — URL fetcher seguro para WeasyPrint.

Política de seguridad: SOLO se permiten data URIs (esquema ``data:``).
Cualquier otro esquema (``file://``, ``http://``, ``https://``, rutas
relativas) lanza ``ValueError``, bloqueando LFI y SSRF.

Todos los PDFs de Maily deben pasar este fetcher a WeasyPrint:

    from weasyprint import HTML
    from apps.core.pdf.fetchers import secure_fetcher

    pdf_bytes = HTML(string=html_str, url_fetcher=secure_fetcher).write_pdf()
"""

import logging
from typing import Any

logger = logging.getLogger("apps.core.pdf.fetchers")


def secure_fetcher(url: str) -> dict[str, Any]:
    """URL fetcher de seguridad para WeasyPrint — bloquea todo excepto data URIs.

    WeasyPrint llama a esta función para resolver recursos referenciados en
    el HTML o CSS del template (imágenes, fuentes, etc.). La política es:

        - URIs ``data:`` → se procesan normalmente. Son los únicos recursos
          usados; las imágenes se incrustan en base64 antes del render.
        - Cualquier otro esquema (``file://``, ``http://``, ``https://``,
          rutas relativas) → se lanza ``ValueError``.
          Esto bloquea LFI y SSRF al evitar que WeasyPrint lea archivos
          del sistema o haga peticiones salientes.

    Args:
        url: URL del recurso tal como aparece en el HTML/CSS.

    Returns:
        Dict con los datos del recurso para WeasyPrint (solo para data URIs).

    Raises:
        ValueError: si la URL no empieza con ``data:`` (política de seguridad).
    """
    if url.startswith("data:"):
        from weasyprint.urls import default_url_fetcher

        return default_url_fetcher(url)  # type: ignore[return-value]

    logger.warning(
        "core.pdf.fetchers.secure_fetcher: URL bloqueada por política de "
        "seguridad — '%s'. Solo se permiten data URIs en los templates de PDF.",
        url[:200],
    )
    raise ValueError(
        f"URL bloqueada por política de seguridad del generador de PDF: "
        f"'{url[:200]}'. Solo se permiten data URIs (imágenes base64 incrustadas)."
    )
