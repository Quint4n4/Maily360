"""
Helpers de verificación de autenticidad de receta médica (F5).

Implementa un token HMAC-SHA256 por receta que:
  - No es adivinable (requiere conocer PRESCRIPTION_VERIFY_SECRET).
  - No es falsificable sin la clave.
  - Se valida en tiempo constante con hmac.compare_digest (anti-timing-attack).

Flujo:
  1. Al generar el PDF, `verification_url(prescription)` construye la URL del QR.
  2. `prescription_qr_b64(prescription)` genera el QR como PNG en memoria y
     devuelve (base64, mime) listo para incrustarse en el template HTML.
  3. El frontend en {BASE_URL}/verificar-receta/{id}?sig={token} llama al
     endpoint público GET /api/v1/verificar-receta/{id}/?sig={token}.
  4. La vista pública llama a `verify_token(prescription_id, sig)` para validar.

Decisiones de seguridad:
  - Token = primeros 32 caracteres del HMAC-SHA256 hex (128 bits de entropía).
    Es suficientemente corto para una URL de QR pero lo bastante largo para
    resistir fuerza bruta (2^128 posibilidades).
  - La clave es `settings.PRESCRIPTION_VERIFY_SECRET` (independiente de SECRET_KEY
    aunque en dev puede coincidir).
  - `hmac.compare_digest` evita ataques de temporización.
  - El QR se genera con la librería `qrcode` (puro Python + Pillow).
    error_correction=L (7%) es suficiente para una URL corta sin impresión dañada.

Privacidad:
  - El QR y la URL NO contienen nombre del paciente, medicamentos ni diagnóstico.
  - Solo exponen: UUID de la receta (no PII) y el token HMAC.
  - El endpoint público (view) responde con datos mínimos no sensibles.
"""

import base64
import hashlib
import hmac
import logging
from io import BytesIO
from typing import Any

from django.conf import settings

logger = logging.getLogger("apps.recetas.verification")

# Longitud del token truncado (en chars hex). 32 chars = 128 bits de entropía.
_TOKEN_HEX_LEN: int = 32


def _get_secret() -> bytes:
    """Retorna la clave HMAC como bytes desde settings.PRESCRIPTION_VERIFY_SECRET."""
    secret: str = getattr(settings, "PRESCRIPTION_VERIFY_SECRET", "") or settings.SECRET_KEY
    return secret.encode("utf-8")


def verification_token(*, prescription: Any) -> str:
    """Genera el token HMAC-SHA256 para una receta.

    Token = hex(HMAC-SHA256(str(prescription.id), PRESCRIPTION_VERIFY_SECRET))
    truncado a _TOKEN_HEX_LEN caracteres (128 bits de entropía).

    Args:
        prescription: Instancia de Prescription con `.id` accesible.

    Returns:
        Token hex de 32 caracteres (minúsculas).
    """
    msg = str(prescription.id).encode("utf-8")
    sig = hmac.new(_get_secret(), msg, hashlib.sha256).hexdigest()
    return sig[:_TOKEN_HEX_LEN]


def verify_token(*, prescription_id: Any, sig: str) -> bool:
    """Valida que `sig` sea el token correcto para `prescription_id`.

    Usa `hmac.compare_digest` para comparación en tiempo constante.
    Devuelve False (no lanza excepciones) en caso de cualquier error.

    Args:
        prescription_id: UUID de la receta (str o UUID).
        sig:             Token recibido del query string.

    Returns:
        True si la firma es correcta; False en cualquier otro caso.
    """
    if not sig or not prescription_id:
        return False

    try:
        msg = str(prescription_id).encode("utf-8")
        expected = hmac.new(_get_secret(), msg, hashlib.sha256).hexdigest()[:_TOKEN_HEX_LEN]
        return hmac.compare_digest(expected, sig)
    except Exception:  # noqa: BLE001
        logger.warning(
            "verification.verify_token: excepción al validar token "
            "(prescription_id=%s). Devolviendo False.",
            str(prescription_id)[:36],
        )
        return False


def verification_url(*, prescription: Any) -> str:
    """Construye la URL completa del QR de verificación de la receta.

    Formato: {PRESCRIPTION_VERIFY_BASE_URL}/verificar-receta/{id}?sig={token}

    Args:
        prescription: Instancia de Prescription.

    Returns:
        URL pública de verificación (no contiene PII).
    """
    base_url: str = (
        getattr(settings, "PRESCRIPTION_VERIFY_BASE_URL", "http://localhost:5173")
        .rstrip("/")
    )
    token = verification_token(prescription=prescription)
    return f"{base_url}/verificar-receta/{prescription.id}?sig={token}"


def prescription_qr_b64(*, prescription: Any) -> tuple[str, str]:
    """Genera el QR de verificación de la receta como imagen PNG en base64.

    Usa `qrcode` (puro Python) + Pillow para producir el PNG en memoria.
    El QR se incrusta como data URI en los templates HTML del PDF.

    Correctness/error_correction=L: 7% de corrección es suficiente para una
    URL corta en un PDF digital (no hay impresión dañada ni rasguños).
    box_size=4, border=1: imagen compacta (~70–80 px) apropiada para el pie.

    Args:
        prescription: Instancia de Prescription.

    Returns:
        Tupla (base64_str, "png"). Si falla, devuelve ("", "") silenciosamente.
    """
    try:
        import qrcode  # import tardío: modulo opcional; no bloquea si falta
        from qrcode.image.pil import PilImage  # noqa: F401 — confirmar que está Pillow

        url = verification_url(prescription=prescription)
        qr = qrcode.QRCode(
            version=None,  # autodetectar el tamaño mínimo
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=4,
            border=1,
        )
        qr.add_data(url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        encoded = base64.b64encode(buffer.read()).decode("ascii")
        return encoded, "png"

    except Exception:  # noqa: BLE001
        logger.warning(
            "verification.prescription_qr_b64: no se pudo generar el QR "
            "para prescription_id=%s. El PDF se generará sin él.",
            str(getattr(prescription, "id", "?"))[:36],
        )
        return "", ""
