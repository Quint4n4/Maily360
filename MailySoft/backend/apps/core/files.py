"""
Utilidades de archivos: validación segura de imágenes y rutas de subida.

Seguridad (app de salud — LFPDPPP/OWASP):
- Límite de tamaño configurable por contexto (evita DoS por archivos enormes).
- Se valida que el archivo SEA realmente una imagen (Pillow), no solo por extensión
  ni por Content-Type (que el cliente puede falsificar).
- Solo formatos rasterizados seguros (JPEG/PNG/WEBP). Se rechaza SVG (vector con
  posible JS embebido → XSS) y cualquier otro formato.
- El nombre del archivo se ALEATORIZA (uuid) para evitar path traversal,
  colisiones y enumeración de archivos de otros usuarios.

Funciones públicas:
    validate_image   — validación genérica reutilizable para cualquier imagen.
    validate_avatar  — alias de validate_image con límite 5 MB (compatibilidad).
    validate_evolution_image — variante para fotos clínicas (límite 10 MB).
    patient_avatar_path      — ruta de subida para avatar de paciente.
    user_avatar_path         — ruta de subida para avatar de usuario/miembro.
    evolution_image_path     — ruta de subida para imágenes de notas de evolución.
"""

import uuid
from pathlib import Path
from typing import Any

from django.core.exceptions import ValidationError
from PIL import Image

#: Tamaño máximo para avatares (5 MB).
MAX_AVATAR_BYTES: int = 5 * 1024 * 1024

#: Tamaño máximo para fotos clínicas de evolución (10 MB).
#: Las fotos de heridas, estudios o hallazgos clínicos pueden ser más pesadas
#: que un avatar de perfil. Definido como constante para facilitar revisión.
MAX_EVOLUTION_IMAGE_BYTES: int = 10 * 1024 * 1024

#: Formatos de imagen permitidos (los que reporta Pillow).
ALLOWED_FORMATS: frozenset[str] = frozenset({"JPEG", "PNG", "WEBP"})

#: Extensiones válidas para el archivo guardado.
_ALLOWED_EXTS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".webp"})

# MEDIO-1 / Bomba de descompresión — límite global de píxeles.
# Pillow lanza DecompressionBombWarning por defecto a 89 MP y
# DecompressionBombError a 178 MP. Bajamos el umbral a 40 MP (resolución
# máxima razonable para fotos clínicas) para reducir el vector de DoS.
# Se asigna a nivel módulo para que surta efecto en todos los Image.open().
Image.MAX_IMAGE_PIXELS = 40_000_000


def validate_image(file: Any, *, max_bytes: int = MAX_AVATAR_BYTES) -> None:
    """Valida que `file` sea una imagen segura y dentro del límite de tamaño.

    Barrera principal de seguridad: usa Pillow para verificar que el contenido
    binario SEA una imagen real. Rechaza SVG (y todo formato no rasterizado),
    archivos corruptos, bytes arbitrarios con extensión .jpg, etc.

    Seguridad adicional (MEDIO-1):
    - Tras image.verify(), reabre el archivo y llama a .load() para forzar la
      decodificación completa de los píxeles. Esto hace que Pillow lance
      DecompressionBombError ante imágenes que pasan verify() pero cuya
      descompresión excede MAX_IMAGE_PIXELS (bomba de descompresión / zip-bomb
      de imagen). Cualquier falla en .load() se convierte en ValidationError.

    Seguridad adicional (BAJO-1):
    - Si getattr(file, "size", None) devuelve None, la validación de tamaño falla
      de forma cerrada (fail-closed): se lanza ValidationError en lugar de
      omitir silenciosamente el chequeo.

    Args:
        file:      Archivo subido (UploadedFile) con atributos .size y lectura binaria.
        max_bytes: Límite de tamaño en bytes (default: MAX_AVATAR_BYTES = 5 MB).

    Raises:
        ValidationError: si excede el tamaño, no es una imagen válida, el
                         formato no está en ALLOWED_FORMATS (JPEG/PNG/WEBP), o
                         si la imagen es una bomba de descompresión.
    """
    # BAJO-1 — Fail-closed: si no podemos verificar el tamaño, rechazamos.
    size = getattr(file, "size", None)
    if size is None:
        raise ValidationError("No se pudo verificar el tamaño del archivo.")
    limit_mb = max_bytes // (1024 * 1024)
    if size > max_bytes:
        raise ValidationError(f"La imagen no debe superar los {limit_mb} MB.")

    fmt: str = ""
    try:
        image = Image.open(file)
        fmt = (image.format or "").upper()
        image.verify()  # detecta archivos corruptos / que no son imágenes
    except Exception:  # noqa: BLE001
        # Pillow lanza tipos variados ante entrada maliciosa/corrupta
        # (UnidentifiedImageError, OSError, ValueError, SyntaxError,
        # DecompressionBombError…). Ante CUALQUIER fallo, es inválida.
        raise ValidationError("El archivo no es una imagen válida.")
    finally:
        # verify() deja el puntero al final; lo reseteamos antes del .load()
        # y al salir del bloque para que el archivo se pueda guardar.
        try:
            file.seek(0)
        except (AttributeError, OSError):
            pass

    # MEDIO-1 — Detección de bomba de descompresión.
    # verify() valida la estructura pero NO decodifica los píxeles; es posible
    # construir imágenes que pasen verify() pero que al decodificarse generen
    # cientos de megabytes (zip-bomb de imagen). .load() fuerza la decodificación
    # completa y hará que Pillow lance DecompressionBombError si supera
    # MAX_IMAGE_PIXELS (fijado a 40 MP a nivel módulo).
    try:
        file.seek(0)
        Image.open(file).load()
    except Exception:  # noqa: BLE001
        raise ValidationError("El archivo no es una imagen válida.")
    finally:
        try:
            file.seek(0)
        except (AttributeError, OSError):
            pass

    if fmt not in ALLOWED_FORMATS:
        raise ValidationError("Formato no permitido. Usa una imagen JPG, PNG o WEBP.")


def validate_avatar(file: Any) -> None:
    """Alias de validate_image con límite de 5 MB (avatares de perfil).

    Mantiene compatibilidad retroactiva con el código existente que llama
    a validate_avatar directamente.

    Args:
        file: archivo subido (UploadedFile).

    Raises:
        ValidationError: si no pasa la validación de imagen segura.
    """
    validate_image(file, max_bytes=MAX_AVATAR_BYTES)


def validate_evolution_image(file: Any) -> None:
    """Valida una imagen de nota de evolución (límite 10 MB).

    Las fotos clínicas (heridas, hallazgos, estudios fotográficos) suelen ser
    más pesadas que un avatar. El límite mayor está justificado clínicamente.
    La validación de formato y contenido es idéntica a validate_avatar.

    Args:
        file: archivo subido (UploadedFile).

    Raises:
        ValidationError: si no pasa la validación de imagen segura o supera 10 MB.
    """
    validate_image(file, max_bytes=MAX_EVOLUTION_IMAGE_BYTES)


def _random_name(filename: str) -> str:
    """Nombre de archivo aleatorizado conservando una extensión segura."""
    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_EXTS:
        ext = ".jpg"
    return f"{uuid.uuid4().hex}{ext}"


def patient_avatar_path(instance: Any, filename: str) -> str:
    """Ruta de subida para el avatar de un paciente (nombre aleatorizado)."""
    return f"avatars/pacientes/{_random_name(filename)}"


def user_avatar_path(instance: Any, filename: str) -> str:
    """Ruta de subida para el avatar de un usuario/miembro (nombre aleatorizado)."""
    return f"avatars/usuarios/{_random_name(filename)}"


def evolution_image_path(instance: Any, filename: str) -> str:
    """Ruta de subida para imágenes adjuntas a notas de evolución.

    BAJO-2: incluye el tenant_id en la ruta para aislar físicamente los
    archivos de cada clínica en el storage (S3 o sistema de archivos local).
    Esto complementa el aislamiento lógico de la BD y facilita políticas
    de IAM/bucket por prefijo de tenant.

    Almacena bajo evoluciones/<tenant_id>/ con nombre UUID aleatorizado para
    evitar path traversal, colisiones y enumeración de archivos entre tenants.

    En producción, MEDIA_ROOT apunta a S3 (solo cambia la configuración de
    DEFAULT_FILE_STORAGE / STORAGES en settings; el código no cambia).

    Args:
        instance: instancia de EvolutionImage. Django llama esta función antes
                  del primer save(), pero DESPUÉS de asignar los campos del
                  modelo. tenant_id ya está disponible en este punto.
        filename: nombre original del archivo subido por el cliente.

    Returns:
        Ruta relativa bajo MEDIA_ROOT:
        "evoluciones/<tenant_id>/<uuid><ext>".
    """
    tenant_id = getattr(instance, "tenant_id", None) or "unknown"
    return f"evoluciones/{tenant_id}/{_random_name(filename)}"
