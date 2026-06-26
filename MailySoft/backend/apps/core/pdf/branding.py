"""
apps.core.pdf.branding — Contexto de marca de la clínica para templates de PDF.

Función principal:
    build_brand_context — construye el dict de contexto de identidad visual
    que se inyecta en cualquier template de PDF de Maily (receta, cotización,
    reporte, expediente).  Centraliza la lectura de ClinicSettings para que
    no haya duplicación de lógica entre los distintos módulos PDF.

Contexto devuelto (llaves garantizadas):
    logo_b64       str   — datos base64 del logo o "".
    logo_mime      str   — subtipo MIME ("png", "jpeg", etc.) o "".
    logo_w         int   — ancho proporcional del logo en pt (0 = sin logo).
    logo_h         int   — alto proporcional del logo en pt (0 = sin logo).
    clinic_name    str   — nombre visible de la clínica (commercial_name ?? tenant.name).
    address        str   — dirección principal.
    address_2      str   — complemento de dirección.
    phone          str   — teléfono fijo.
    mobile         str   — teléfono móvil/WhatsApp.
    email          str   — email de contacto.
    website        str   — URL del sitio web.
    brand_color    str   — color de marca en #RRGGBB (default "#9A7B1E").
    brand_color_svg str  — mismo color con '#' como '%23' para usar en data: URI SVG.
    watermark_b64  str   — logo marca-de-agua (PNG RGBA ~8 % opacidad) o "".
"""

import logging
from typing import Any

from apps.core.pdf.images import image_box, logo_watermark_b64

logger = logging.getLogger("apps.core.pdf.branding")

# Color de marca por defecto (dorado Maily).
_DEFAULT_BRAND_COLOR = "#9A7B1E"


def build_brand_context(
    *,
    clinic_settings: Any,
    logo_max_w_pt: float = 160,
    logo_max_h_pt: float = 58,
) -> dict[str, Any]:
    """Construye el dict de contexto de identidad visual para templates de PDF.

    Lee los campos de ``ClinicSettings`` y devuelve un dict listo para
    pasarlo como contexto a ``render_to_string``. Es la fuente de verdad de
    marca para todos los PDFs de Maily: recetas, cotizaciones, reportes y
    cualquier documento futuro.

    Si ``clinic_settings`` es ``None`` (la clínica no configuró nada aún),
    devuelve un contexto vacío con valores por defecto seguros, para que
    los templates no fallen.

    La clave ``brand_color`` se toma de ``ClinicSettings.brand_color``
    (campo agregado en la migración de esta fase). Si no existe o está
    vacío, usa el dorado por defecto ``#9A7B1E``.

    La clave ``clinic_name`` prioriza ``commercial_name``; si está vacío,
    cae a ``clinic_settings.tenant.name``; si tampoco existe, queda "".

    Args:
        clinic_settings: Instancia de ``ClinicSettings`` o ``None``.
        logo_max_w_pt:   Ancho máximo del logo en puntos tipográficos.
                         Default: 160 pt (mismo que recetas).
        logo_max_h_pt:   Alto máximo del logo en puntos tipográficos.
                         Default: 58 pt (mismo que recetas).

    Returns:
        Dict con las llaves documentadas en el módulo: ``logo_b64``,
        ``logo_mime``, ``logo_w``, ``logo_h``, ``clinic_name``,
        ``address``, ``address_2``, ``phone``, ``mobile``, ``email``,
        ``website``, ``brand_color``, ``brand_color_svg``, ``watermark_b64``.
    """
    if clinic_settings is None:
        return _empty_brand_context()

    # --- Logo ---
    logo_data: dict[str, Any] = {"b64": "", "mime": "", "w": 0, "h": 0}
    watermark: str = ""
    if getattr(clinic_settings, "logo", None):
        try:
            logo_data = image_box(
                clinic_settings.logo,
                max_w_pt=logo_max_w_pt,
                max_h_pt=logo_max_h_pt,
            )
            watermark = logo_watermark_b64(clinic_settings.logo, alpha=0.08)
        except Exception:  # noqa: BLE001
            logger.warning(
                "core.pdf.branding.build_brand_context: error al procesar logo "
                "para ClinicSettings id=%s. Se omite silenciosamente.",
                getattr(clinic_settings, "id", "<desconocido>"),
            )

    # --- Nombre de la clínica ---
    commercial_name: str = getattr(clinic_settings, "commercial_name", "") or ""
    tenant_name: str = ""
    try:
        tenant_name = clinic_settings.tenant.name or ""
    except Exception:  # noqa: BLE001
        pass
    clinic_name: str = commercial_name or tenant_name

    # --- Color de marca ---
    brand_color: str = (
        getattr(clinic_settings, "brand_color", "") or _DEFAULT_BRAND_COLOR
    )
    # Fallback defensivo: si por algún motivo el valor almacenado no es hex válido,
    # lo corregimos silenciosamente aquí (la validación real está en el serializer).
    if not brand_color.startswith("#") or len(brand_color) != 7:
        logger.warning(
            "core.pdf.branding.build_brand_context: brand_color inválido '%s' "
            "para ClinicSettings id=%s. Se usa el color por defecto.",
            brand_color,
            getattr(clinic_settings, "id", "<desconocido>"),
        )
        brand_color = _DEFAULT_BRAND_COLOR

    return {
        "logo_b64": logo_data["b64"],
        "logo_mime": logo_data["mime"],
        "logo_w": logo_data["w"],
        "logo_h": logo_data["h"],
        "clinic_name": clinic_name,
        "address": getattr(clinic_settings, "address", "") or "",
        "address_2": getattr(clinic_settings, "address_2", "") or "",
        "phone": getattr(clinic_settings, "phone", "") or "",
        "mobile": getattr(clinic_settings, "mobile", "") or "",
        "email": getattr(clinic_settings, "email", "") or "",
        "website": getattr(clinic_settings, "website", "") or "",
        "brand_color": brand_color,
        # '#' escapado como '%23' para usar DENTRO de data: URIs SVG.
        # Un '#' crudo rompe el url() y WeasyPrint descarta la regla @page.
        "brand_color_svg": brand_color.replace("#", "%23"),
        "watermark_b64": watermark,
    }


def _empty_brand_context() -> dict[str, Any]:
    """Contexto de marca vacío con todos los valores por defecto.

    Se usa cuando no hay ``ClinicSettings`` configurado. Garantiza que
    los templates nunca reciban un contexto incompleto.

    Returns:
        Dict con las mismas llaves que ``build_brand_context`` pero vacías.
    """
    return {
        "logo_b64": "",
        "logo_mime": "",
        "logo_w": 0,
        "logo_h": 0,
        "clinic_name": "",
        "address": "",
        "address_2": "",
        "phone": "",
        "mobile": "",
        "email": "",
        "website": "",
        "brand_color": _DEFAULT_BRAND_COLOR,
        "brand_color_svg": _DEFAULT_BRAND_COLOR.replace("#", "%23"),
        "watermark_b64": "",
    }
