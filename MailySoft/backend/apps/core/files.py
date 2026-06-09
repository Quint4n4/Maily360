"""
Utilidades de archivos: validación segura de imágenes de avatar y rutas de subida.

Seguridad (app de salud — LFPDPPP/OWASP):
- Límite de tamaño (evita DoS por archivos enormes).
- Se valida que el archivo SEA realmente una imagen (Pillow), no solo por extensión
  ni por Content-Type (que el cliente puede falsificar).
- Solo formatos rasterizados seguros (JPEG/PNG/WEBP). Se rechaza SVG (vector con
  posible JS embebido → XSS) y cualquier otro formato.
- El nombre del archivo se ALEATORIZA (uuid) para evitar path traversal,
  colisiones y enumeración de archivos de otros usuarios.
"""

import uuid
from pathlib import Path
from typing import Any

from django.core.exceptions import ValidationError
from PIL import Image

#: Tamaño máximo permitido para un avatar (5 MB).
MAX_AVATAR_BYTES: int = 5 * 1024 * 1024

#: Formatos de imagen permitidos (los que reporta Pillow).
ALLOWED_FORMATS: frozenset[str] = frozenset({"JPEG", "PNG", "WEBP"})

#: Extensiones válidas para el archivo guardado.
_ALLOWED_EXTS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".webp"})


def validate_avatar(file: Any) -> None:
    """Valida que `file` sea una imagen segura y dentro del límite de tamaño.

    Args:
        file: archivo subido (UploadedFile) con atributos .size y lectura binaria.

    Raises:
        ValidationError: si excede el tamaño, no es una imagen válida o el
                         formato no está permitido.
    """
    size = getattr(file, "size", None)
    if size is not None and size > MAX_AVATAR_BYTES:
        raise ValidationError("La imagen no debe superar los 5 MB.")

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
        # verify() deja el puntero al final; lo reseteamos para que se pueda guardar.
        try:
            file.seek(0)
        except (AttributeError, OSError):
            pass

    if fmt not in ALLOWED_FORMATS:
        raise ValidationError("Formato no permitido. Usa una imagen JPG, PNG o WEBP.")


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
