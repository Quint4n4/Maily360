"""
apps.core.pdf.images — Helpers de imagen para PDFs generados con WeasyPrint.

Todas las imágenes se incrustan como data URIs base64 antes del render,
para que el ``secure_fetcher`` no deba acceder a rutas de archivo.

Funciones públicas:
    image_to_data_uri  — lee un ImageField y devuelve (mime, base64_str).
    image_box          — encaja la imagen en una caja proporcional (pt).
    logo_watermark_b64 — genera versión marca-de-agua del logo (RGBA reducido).
"""

import base64
import logging
import mimetypes
from io import BytesIO
from typing import Any

from PIL import Image, ImageEnhance  # noqa: F401 — ImageEnhance no se usa pero PIL puede requerirlo

logger = logging.getLogger("apps.core.pdf.images")

# MIME por defecto cuando no se puede inferir del nombre del archivo.
_MIME_FALLBACK = "image/png"


def image_to_data_uri(field: Any) -> tuple[str, str]:
    """Lee un ImageField (FileSystemStorage o S3Boto3Storage) y devuelve (mime, base64_str).

    Los bytes se leen directamente desde el storage configurado — funciona
    igual en desarrollo (disco local) y en producción (S3).

    Args:
        field: Un ImageField de Django (puede estar vacío o ser None).

    Returns:
        Tupla ``(mime_subtype, base64_encoded_bytes)`` o ``("", "")`` si no aplica.
        El mime_subtype es solo la parte después de "image/" (p. ej. "png", "jpeg").
    """
    if not field:
        return ("", "")

    try:
        name: str = field.name or ""
        if not name:
            return ("", "")

        mime, _ = mimetypes.guess_type(name)
        if not mime:
            mime = _MIME_FALLBACK

        mime_subtype = mime.split("/")[-1] if "/" in mime else mime

        with field.open("rb") as f:
            raw: bytes = f.read()

        encoded = base64.b64encode(raw).decode("ascii")
        return (mime_subtype, encoded)

    except Exception:  # noqa: BLE001
        logger.warning(
            "core.pdf.images.image_to_data_uri: no se pudo leer la imagen '%s'. "
            "El PDF se generará sin ella.",
            getattr(field, "name", "<desconocido>"),
        )
        return ("", "")


def image_box(field: Any, max_w_pt: float, max_h_pt: float) -> dict[str, Any]:
    """Prepara una imagen para el PDF con dimensiones proporcionales en puntos.

    Lee el tamaño real de la imagen con Pillow y calcula (w, h) en pt que
    encaje dentro de la caja ``max_w_pt × max_h_pt`` conservando la proporción
    (aspect ratio). Los valores w/h se usan para acotar max-width/max-height
    en los templates.

    Args:
        field:     ImageField de Django con la imagen a preparar.
        max_w_pt:  Ancho máximo de la caja en puntos tipográficos.
        max_h_pt:  Alto máximo de la caja en puntos tipográficos.

    Returns:
        Dict con las llaves:
            ``b64``  — cadena base64 o "" si no hay imagen válida.
            ``mime`` — subtipo MIME ("png", "jpeg", etc.) o "".
            ``w``    — ancho calculado en pt (0 si no hay imagen válida).
            ``h``    — alto calculado en pt (0 si no hay imagen válida).
    """
    mime, b64 = image_to_data_uri(field)
    if not b64:
        return {"b64": "", "mime": "", "w": 0, "h": 0}

    try:
        raw = base64.b64decode(b64)
        with Image.open(BytesIO(raw)) as img:
            w_px, h_px = img.size
    except Exception:  # noqa: BLE001
        return {"b64": b64, "mime": mime, "w": 0, "h": 0}

    if w_px <= 0 or h_px <= 0:
        return {"b64": b64, "mime": mime, "w": 0, "h": 0}

    scale = min(max_w_pt / w_px, max_h_pt / h_px)
    return {
        "b64": b64,
        "mime": mime,
        "w": max(1, round(w_px * scale)),
        "h": max(1, round(h_px * scale)),
    }


def logo_watermark_b64(field: Any, *, alpha: float = 0.08) -> str:
    """Genera una versión marca-de-agua del logo de la clínica como data URI PNG.

    Convierte la imagen a RGBA, reduce el canal alpha al valor especificado
    (por defecto 0.08 ≈ 8 % de opacidad), y devuelve el resultado como PNG
    codificado en base64 listo para incrustarse en un data URI.

    Si no hay logo, el campo está vacío o falla cualquier paso, devuelve ""
    (comportamiento seguro: el PDF se genera sin marca de agua).

    Args:
        field: ImageField de Django con el logo de la clínica.
        alpha: Opacidad de la marca de agua (0.0 = invisible, 1.0 = opaco).
               Valor recomendado: 0.06–0.10.

    Returns:
        Data URI completa ("data:image/png;base64,...") o "" si no aplica.
    """
    if not field:
        return ""

    try:
        with field.open("rb") as f:
            raw: bytes = f.read()
    except Exception:  # noqa: BLE001
        logger.warning(
            "core.pdf.images.logo_watermark_b64: no se pudo leer logo para "
            "marca de agua '%s'.",
            getattr(field, "name", "<desconocido>"),
        )
        return ""

    try:
        with Image.open(BytesIO(raw)) as img:
            img_rgba = img.convert("RGBA")
            r, g, b, a = img_rgba.split()
            # Reducir el canal alpha a la fracción indicada (conserva la forma).
            a_dimmed = a.point(lambda px: int(px * alpha))
            watermark = Image.merge("RGBA", (r, g, b, a_dimmed))

            buf = BytesIO()
            watermark.save(buf, format="PNG")
            buf.seek(0)
            encoded = base64.b64encode(buf.read()).decode("ascii")
            return f"data:image/png;base64,{encoded}"
    except Exception:  # noqa: BLE001
        logger.warning(
            "core.pdf.images.logo_watermark_b64: error al procesar imagen "
            "de marca de agua '%s'. El PDF se generará sin marca de agua.",
            getattr(field, "name", "<desconocido>"),
        )
        return ""
