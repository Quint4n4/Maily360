"""
Tests unitarios para apps/core/files.py — validate_avatar.

Cubre:
- Imagen válida (PNG, JPEG, WEBP) no lanza excepción.
- Bytes de texto (no imagen) → ValidationError (NO SyntaxError/500).
  CASO CRÍTICO: este es el bug histórico donde Pillow lanzaba SyntaxError
  sin atrapar y el servidor devolvía 500.
- Imagen corrompida parcialmente → ValidationError.
- Formato no permitido (GIF, BMP) → ValidationError.
- Archivo > 5 MB → ValidationError.
- Sin atributo .size → no lanza por tamaño.
- verify() resetea el puntero del archivo (seek(0)) para que se pueda guardar.

Patrón: AAA. Tests unitarios puros — NO tocan BD.
"""

import io
import struct
from typing import Any

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.core.files import validate_avatar, validate_image


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_image_bytes(fmt: str, size: tuple[int, int] = (50, 50)) -> bytes:
    """Genera bytes de una imagen real en el formato indicado usando Pillow."""
    buf = io.BytesIO()
    Image.new("RGB", size, color="blue").save(buf, fmt)
    return buf.getvalue()


def _make_uploaded_file(
    name: str, content: bytes, content_type: str = "image/png"
) -> SimpleUploadedFile:
    """Envuelve bytes en un SimpleUploadedFile (simula un archivo subido por el usuario)."""
    return SimpleUploadedFile(name, content, content_type=content_type)


# ===========================================================================
# Formatos permitidos (JPEG, PNG, WEBP)
# ===========================================================================


class TestValidateAvatarAllowedFormats:
    """validate_avatar no debe lanzar para imágenes válidas en formatos permitidos."""

    def test_valid_png_does_not_raise(self) -> None:
        """Un PNG válido no lanza ValidationError."""
        # Arrange
        file = _make_uploaded_file("avatar.png", _make_image_bytes("PNG"))

        # Act / Assert — no debe lanzar
        validate_avatar(file)

    def test_valid_jpeg_does_not_raise(self) -> None:
        """Un JPEG válido no lanza ValidationError."""
        # Arrange
        file = _make_uploaded_file("foto.jpg", _make_image_bytes("JPEG"), "image/jpeg")

        # Act / Assert
        validate_avatar(file)

    def test_valid_webp_does_not_raise(self) -> None:
        """Un WEBP válido no lanza ValidationError."""
        # Arrange
        buf = io.BytesIO()
        Image.new("RGB", (50, 50), "green").save(buf, "WEBP")
        file = _make_uploaded_file("avatar.webp", buf.getvalue(), "image/webp")

        # Act / Assert
        validate_avatar(file)

    def test_valid_image_seek_is_reset_after_validation(self) -> None:
        """validate_avatar resetea el puntero del archivo a 0 tras verify().

        Si el puntero no se resetea, el archivo quedará vacío al intentar
        guardarlo en el storage. Este test verifica el seek(0) del finally.
        """
        # Arrange — SimpleUploadedFile tiene .size (BAJO-1 requiere que esté presente)
        content = _make_image_bytes("PNG")
        file = _make_uploaded_file("avatar.png", content, "image/png")

        # Act
        validate_avatar(file)

        # Assert — el puntero está al inicio
        assert file.tell() == 0

    @pytest.mark.parametrize(
        "fmt,content_type,ext",
        [
            ("PNG", "image/png", "avatar.png"),
            ("JPEG", "image/jpeg", "avatar.jpg"),
        ],
    )
    def test_valid_formats_do_not_raise_parametrized(
        self, fmt: str, content_type: str, ext: str
    ) -> None:
        """PNG y JPEG en sus variantes principales no lanzan excepción."""
        file = _make_uploaded_file(ext, _make_image_bytes(fmt), content_type)
        validate_avatar(file)  # no debe lanzar


# ===========================================================================
# Formatos NO permitidos
# ===========================================================================


class TestValidateAvatarForbiddenFormats:
    """validate_avatar debe lanzar ValidationError para formatos no permitidos."""

    def test_gif_raises_validation_error(self) -> None:
        """GIF (animable, vector-like) no está permitido; debe lanzar ValidationError."""
        # Arrange
        buf = io.BytesIO()
        Image.new("RGB", (20, 20), "red").save(buf, "GIF")
        file = _make_uploaded_file("avatar.gif", buf.getvalue(), "image/gif")

        # Act / Assert
        with pytest.raises(ValidationError, match="[Ff]ormato"):
            validate_avatar(file)

    def test_bmp_raises_validation_error(self) -> None:
        """BMP no está en la lista de permitidos (JPEG/PNG/WEBP); debe lanzar."""
        # Arrange
        buf = io.BytesIO()
        Image.new("RGB", (20, 20), "white").save(buf, "BMP")
        file = _make_uploaded_file("avatar.bmp", buf.getvalue(), "image/bmp")

        # Act / Assert
        with pytest.raises(ValidationError, match="[Ff]ormato"):
            validate_avatar(file)


# ===========================================================================
# Archivos inválidos / no imágenes (CASO CRÍTICO)
# ===========================================================================


class TestValidateAvatarInvalidFiles:
    """validate_avatar debe lanzar ValidationError, no propagar excepciones de Pillow.

    CONTEXTO HISTÓRICO (bug): Pillow lanzaba tipos variados de excepciones
    (SyntaxError, OSError, UnidentifiedImageError, ValueError) cuando recibía
    archivos corruptos o que no eran imágenes. Si el código de producción no
    atrapaba TODAS esas excepciones, el servidor devolvía 500 Internal Server Error
    en lugar de 400 Bad Request.

    ESTOS TESTS VERIFICAN EL FIX: validate_avatar usa `except Exception` para
    atrapar cualquier excepción de Pillow y relevarla como ValidationError.
    """

    def test_plain_text_bytes_raises_validation_error_not_500(self) -> None:
        """Bytes de texto plano (no imagen) → ValidationError, no excepción interna.

        CASO CRÍTICO: este es exactamente el escenario del bug histórico.
        Un atacante (o usuario confundido) sube un archivo .jpg con contenido de texto.
        Pillow lanzaba SyntaxError; sin atrapar, el servidor devolvía 500.
        """
        # Arrange
        file = _make_uploaded_file(
            "no_es_imagen.jpg",
            b"esto no es una imagen, es texto plano \x00\x01\x02",
            content_type="image/jpeg",
        )

        # Act / Assert — ValidationError, no SyntaxError/OSError/UnidentifiedImageError
        with pytest.raises(ValidationError):
            validate_avatar(file)

    def test_empty_bytes_raises_validation_error(self) -> None:
        """Archivo vacío → ValidationError."""
        # Arrange
        file = _make_uploaded_file("empty.png", b"", "image/png")

        # Act / Assert
        with pytest.raises(ValidationError):
            validate_avatar(file)

    def test_html_content_raises_validation_error(self) -> None:
        """HTML disfrazado de imagen → ValidationError (potencial XSS vector)."""
        # Arrange
        file = _make_uploaded_file(
            "xss.jpg",
            b"<html><script>alert('xss')</script></html>",
            content_type="image/jpeg",
        )

        # Act / Assert
        with pytest.raises(ValidationError):
            validate_avatar(file)

    def test_truncated_png_header_raises_validation_error(self) -> None:
        """PNG corrompido (solo los primeros bytes de la firma) → ValidationError."""
        # Arrange — solo los 8 bytes de la firma PNG, sin datos reales
        png_signature = b"\x89PNG\r\n\x1a\n"
        file = _make_uploaded_file("truncado.png", png_signature + b"\x00" * 20)

        # Act / Assert
        with pytest.raises(ValidationError):
            validate_avatar(file)

    def test_random_binary_raises_validation_error(self) -> None:
        """Bytes aleatorios → ValidationError."""
        # Arrange
        random_bytes = bytes(range(256)) * 4  # 1024 bytes de basura
        file = _make_uploaded_file("rubbish.png", random_bytes)

        # Act / Assert
        with pytest.raises(ValidationError):
            validate_avatar(file)


# ===========================================================================
# Límite de tamaño
# ===========================================================================


class TestValidateAvatarSizeLimit:
    """validate_avatar rechaza archivos que excedan 5 MB."""

    def test_file_over_5mb_raises_validation_error(self) -> None:
        """Archivo de 5 MB + 1 byte → ValidationError con mención de 5 MB."""
        # Arrange — no necesitamos una imagen real; solo simular el .size
        over_5mb = 5 * 1024 * 1024 + 1
        file = _make_uploaded_file("grande.png", b"x" * 100)
        file.size = over_5mb  # type: ignore[attr-defined]

        # Act / Assert
        with pytest.raises(ValidationError, match="5 MB"):
            validate_avatar(file)

    def test_file_exactly_5mb_is_accepted(self) -> None:
        """Archivo de exactamente 5 MB no se rechaza por tamaño."""
        # Arrange — crear una imagen PNG real que llegue a 5 MB
        # (se fake el .size porque crear 5 MB reales sería lento)
        exactly_5mb = 5 * 1024 * 1024
        file = _make_uploaded_file("exacto.png", _make_image_bytes("PNG"))
        file.size = exactly_5mb  # type: ignore[attr-defined]

        # Act / Assert — no debe lanzar por tamaño
        # (puede lanzar por formato si el PNG es válido, que es lo esperado:
        #  pasamos a la validación de Pillow, no nos quedamos en el check de size)
        try:
            validate_avatar(file)
        except ValidationError as exc:
            # Solo lanzar si el mensaje es de tamaño (otros errores son aceptables
            # porque estamos forzando el .size y el contenido es un PNG real)
            assert "5 MB" not in str(exc), (
                "No debe rechazarse por tamaño cuando el archivo mide exactamente 5 MB."
            )

    def test_file_without_size_attribute_raises_validation_error(self) -> None:
        """BAJO-1: si el archivo no tiene atributo .size, se lanza ValidationError.

        Fail-closed: no podemos verificar el tamaño → rechazamos el archivo.
        Esto evita que un atacante construya un UploadedFile sin .size para
        saltarse el chequeo de límite de bytes.
        """
        # Arrange — usar un BytesIO sin .size
        buf = io.BytesIO(_make_image_bytes("PNG"))
        buf.name = "avatar.png"
        # BytesIO no tiene .size por defecto → getattr devuelve None →
        # BAJO-1: fail-closed → ValidationError

        # Act / Assert — DEBE lanzar porque no podemos verificar el tamaño
        with pytest.raises(ValidationError):
            validate_avatar(buf)


# ===========================================================================
# MEDIO-1 — Bomba de descompresión y detección con .load()
# ===========================================================================


class TestValidateImageDecompressionBomb:
    """MEDIO-1: validate_image debe rechazar bombas de descompresión.

    verify() no decodifica los píxeles; una imagen manipulada puede pasar
    verify() pero explotar en tamaño al decodificarse. La nueva llamada a
    .load() tras verify() fuerza la decodificación completa.
    """

    def test_image_that_passes_verify_but_fails_load_raises_validation_error(
        self,
    ) -> None:
        """Imagen cuyo .load() falla → ValidationError (nunca propaga la excepción).

        Simulamos el caso con un mock: Image.open().load() lanza
        DecompressionBombError aunque verify() haya pasado.
        """
        from unittest.mock import MagicMock, patch

        from PIL import Image as PILImage

        # Imagen PNG real pequeña que pasa verify()
        content = _make_image_bytes("PNG")
        file = _make_uploaded_file("bomb.png", content, "image/png")

        # Parchear Image.open para que el segundo open() (el del .load()) lance
        # DecompressionBombError, simulando una bomba de descompresión.
        original_open = PILImage.open
        call_count: list[int] = [0]

        def patched_open(f: Any, **kwargs: Any) -> Any:
            call_count[0] += 1
            if call_count[0] == 2:
                # Segunda llamada: simula la bomba de descompresión
                raise PILImage.DecompressionBombError(  # type: ignore[attr-defined]
                    "Image size (999999999 pixels) exceeds limit"
                )
            return original_open(f, **kwargs)

        with patch("apps.core.files.Image.open", side_effect=patched_open):
            with pytest.raises(ValidationError):
                validate_image(file, max_bytes=5 * 1024 * 1024)

    def test_normal_image_passes_load_check(self) -> None:
        """Una imagen legítima pasa verify() Y .load() sin lanzar excepción."""
        content = _make_image_bytes("PNG")
        file = _make_uploaded_file("ok.png", content, "image/png")
        # no debe lanzar
        validate_image(file, max_bytes=5 * 1024 * 1024)

    def test_pointer_reset_after_load_check(self) -> None:
        """El puntero del archivo queda en 0 tras el ciclo verify + load."""
        content = _make_image_bytes("PNG")
        file = _make_uploaded_file("ok.png", content, "image/png")
        validate_image(file, max_bytes=5 * 1024 * 1024)
        assert file.tell() == 0, "El puntero debe estar en 0 para que el storage pueda guardar."
