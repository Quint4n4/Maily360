"""
apps.core.pdf — Biblioteca compartida de generación de PDFs para Maily Platform.

Módulos:
    fetchers  — URL fetcher seguro para WeasyPrint (solo data URIs; bloquea LFI/SSRF).
    images    — Helpers de imagen: data URI, caja proporcional, marca de agua.
    branding  — build_brand_context: construye el contexto de marca de la clínica.

Los PDFs específicos (recetas, cotizaciones, reportes, expediente) importan de
aquí para reutilizar la misma "piel" visual y política de seguridad.
"""
