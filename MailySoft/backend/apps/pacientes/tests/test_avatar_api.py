"""
Tests de los endpoints de avatar de pacientes.

Endpoints:
    POST   /api/v1/pacientes/<id>/avatar/  — subir/reemplazar foto.
    DELETE /api/v1/pacientes/<id>/avatar/  — eliminar foto.

Cubre:
- PNG válido → 200 y campo 'avatar' no nulo en la respuesta.
- JPEG válido → 200.
- Bytes de texto (no imagen) → 400 CRÍTICO (no 500). Bug histórico.
- GIF (formato no permitido) → 400.
- Sin campo 'avatar' → 400.
- DELETE → 200 y avatar queda nulo.
- Permisos: roles sin acceso a POST/DELETE reciben 403.
- Aislamiento: paciente de otro tenant → 404.

Patrón: AAA. Todas tocan BD → fixture db.
"""

import io
from contextlib import contextmanager
from typing import Any, Generator
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIClient

from apps.pacientes.models import Patient
from tests.factories import PatientFactory, TenantFactory, TenantMembershipFactory, UserFactory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _avatar_url(patient_id: Any) -> str:
    return f"/api/v1/pacientes/{patient_id}/avatar/"


def _make_png_file(name: str = "avatar.png") -> SimpleUploadedFile:
    """Genera un PNG real en memoria con Pillow."""
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), "gold").save(buf, "PNG")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/png")


def _make_jpeg_file(name: str = "avatar.jpg") -> SimpleUploadedFile:
    """Genera un JPEG real en memoria con Pillow."""
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), "red").save(buf, "JPEG")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/jpeg")


def _make_gif_file(name: str = "avatar.gif") -> SimpleUploadedFile:
    """Genera un GIF real en memoria con Pillow (formato NO permitido)."""
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "blue").save(buf, "GIF")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/gif")


@contextmanager
def _tenant_context(tenant: Any) -> Generator[None, None, None]:
    """Simula el TenantMiddleware para un tenant dado en tests con force_authenticate."""
    with (
        patch("apps.pacientes.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
    ):
        yield


def _make_member_client(tenant: Any, role: str) -> tuple[APIClient, Any]:
    """Crea user con membresía real en BD y devuelve (APIClient autenticado, user)."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


# ===========================================================================
# POST /api/v1/pacientes/<id>/avatar/ — subir avatar
# ===========================================================================


class TestPatientAvatarUploadApi:
    """POST /api/v1/pacientes/<id>/avatar/ — subir avatar de paciente."""

    def test_upload_valid_png_returns_200_and_avatar_not_null(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """Un PNG válido devuelve 200 y la respuesta incluye 'avatar' no nulo."""
        settings.MEDIA_ROOT = str(tmp_path)

        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, _ = _make_member_client(tenant, "reception")

        # Act
        with _tenant_context(tenant):
            response = client.post(
                _avatar_url(patient.id),
                {"avatar": _make_png_file()},
                format="multipart",
            )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data.get("avatar") is not None, (
            "La respuesta debe incluir el campo 'avatar' con una URL no nula."
        )

    def test_upload_valid_jpeg_returns_200(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """Un JPEG válido devuelve 200."""
        settings.MEDIA_ROOT = str(tmp_path)

        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, _ = _make_member_client(tenant, "doctor")

        # Act
        with _tenant_context(tenant):
            response = client.post(
                _avatar_url(patient.id),
                {"avatar": _make_jpeg_file()},
                format="multipart",
            )

        # Assert
        assert response.status_code == 200

    def test_upload_non_image_bytes_returns_400_not_500(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """CASO CRÍTICO: bytes de texto (no imagen) → 400, nunca 500.

        Verificación explícita del bug histórico: Pillow lanzaba SyntaxError
        sin atrapar → 500. validate_avatar atrapa toda excepción → ValidationError → 400.
        """
        settings.MEDIA_ROOT = str(tmp_path)

        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, _ = _make_member_client(tenant, "reception")

        fake_file = SimpleUploadedFile(
            "not_an_image.jpg",
            b"no soy una imagen, solo texto \x00\x01\xff\xfe",
            content_type="image/jpeg",
        )

        # Act
        with _tenant_context(tenant):
            response = client.post(
                _avatar_url(patient.id),
                {"avatar": fake_file},
                format="multipart",
            )

        # Assert — NUNCA 500
        assert response.status_code == 400, (
            f"Se esperaba 400 para archivo inválido, obtuvo {response.status_code}. "
            "BUG CRÍTICO: validate_avatar debe atrapar TODAS las excepciones de Pillow "
            "para evitar 500 Internal Server Error."
        )
        assert response.status_code != 500

    def test_upload_gif_returns_400(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """GIF (formato no permitido) devuelve 400."""
        settings.MEDIA_ROOT = str(tmp_path)

        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, _ = _make_member_client(tenant, "reception")

        # Act
        with _tenant_context(tenant):
            response = client.post(
                _avatar_url(patient.id),
                {"avatar": _make_gif_file()},
                format="multipart",
            )

        # Assert
        assert response.status_code == 400

    def test_upload_without_avatar_field_returns_400(self, db: None) -> None:
        """POST sin el campo 'avatar' devuelve 400."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, _ = _make_member_client(tenant, "reception")

        # Act
        with _tenant_context(tenant):
            response = client.post(
                _avatar_url(patient.id), data={}, format="multipart"
            )

        # Assert
        assert response.status_code == 400

    def test_upload_avatar_for_unknown_patient_returns_404(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """UUID de paciente inexistente devuelve 404."""
        settings.MEDIA_ROOT = str(tmp_path)

        # Arrange
        import uuid
        tenant = TenantFactory()
        client, _ = _make_member_client(tenant, "reception")

        # Act
        with _tenant_context(tenant):
            response = client.post(
                _avatar_url(uuid.uuid4()),
                {"avatar": _make_png_file()},
                format="multipart",
            )

        # Assert
        assert response.status_code == 404

    def test_upload_avatar_other_tenant_patient_returns_404(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """Paciente de otro tenant → 404 (aislamiento multi-tenant)."""
        settings.MEDIA_ROOT = str(tmp_path)

        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        patient_b = PatientFactory(tenant=tenant_b)
        client, _ = _make_member_client(tenant_a, "reception")

        # Act — contexto de A, pero el paciente es de B
        with _tenant_context(tenant_a):
            response = client.post(
                _avatar_url(patient_b.id),
                {"avatar": _make_png_file()},
                format="multipart",
            )

        # Assert
        assert response.status_code == 404, (
            f"Se esperaba 404 para paciente de otro tenant, obtuvo {response.status_code}."
        )

    def test_upload_avatar_requires_auth(self, db: None) -> None:
        """Sin token devuelve 401."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = APIClient()

        # Act
        response = client.post(
            _avatar_url(patient.id),
            {"avatar": _make_png_file()},
            format="multipart",
        )

        # Assert
        assert response.status_code == 401

    def test_upload_avatar_finance_role_returns_403(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """Rol 'finance' no puede subir avatar de paciente (403)."""
        settings.MEDIA_ROOT = str(tmp_path)

        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, _ = _make_member_client(tenant, "finance")

        # Act
        with _tenant_context(tenant):
            response = client.post(
                _avatar_url(patient.id),
                {"avatar": _make_png_file()},
                format="multipart",
            )

        # Assert — finance no tiene POST en PatientPermission
        assert response.status_code == 403

    def test_avatar_field_appears_in_patient_serializer_output(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """El campo 'avatar' aparece en la respuesta del serializer de paciente."""
        settings.MEDIA_ROOT = str(tmp_path)

        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, _ = _make_member_client(tenant, "reception")

        # Act
        with _tenant_context(tenant):
            response = client.post(
                _avatar_url(patient.id),
                {"avatar": _make_png_file()},
                format="multipart",
            )

        # Assert — el campo 'avatar' existe en la respuesta
        assert response.status_code == 200
        assert "avatar" in response.json()

    def test_upload_png_persists_avatar_to_db(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """Tras subir el avatar, Patient.avatar tiene un valor en BD."""
        settings.MEDIA_ROOT = str(tmp_path)

        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, _ = _make_member_client(tenant, "reception")

        # Act
        with _tenant_context(tenant):
            response = client.post(
                _avatar_url(patient.id),
                {"avatar": _make_png_file()},
                format="multipart",
            )

        # Assert
        assert response.status_code == 200
        patient.refresh_from_db()
        assert bool(patient.avatar), (
            "Patient.avatar debe tener un valor en BD tras subir la imagen."
        )


# ===========================================================================
# DELETE /api/v1/pacientes/<id>/avatar/ — eliminar avatar
# ===========================================================================


class TestPatientAvatarDeleteApi:
    """DELETE /api/v1/pacientes/<id>/avatar/ — eliminar avatar de paciente."""

    def test_delete_avatar_returns_200_and_avatar_is_null(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """DELETE elimina el avatar; la respuesta tiene avatar=null."""
        settings.MEDIA_ROOT = str(tmp_path)

        # Arrange — primero subir
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, _ = _make_member_client(tenant, "owner")

        with _tenant_context(tenant):
            post_resp = client.post(
                _avatar_url(patient.id),
                {"avatar": _make_png_file()},
                format="multipart",
            )
        assert post_resp.status_code == 200

        # Act — eliminar
        with _tenant_context(tenant):
            response = client.delete(_avatar_url(patient.id))

        # Assert
        assert response.status_code == 200
        assert response.json().get("avatar") is None

    def test_delete_avatar_clears_field_in_db(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """Tras DELETE, Patient.avatar es nulo en BD."""
        settings.MEDIA_ROOT = str(tmp_path)

        # Arrange — subir primero
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, _ = _make_member_client(tenant, "owner")

        with _tenant_context(tenant):
            client.post(
                _avatar_url(patient.id),
                {"avatar": _make_png_file()},
                format="multipart",
            )

        # Act
        with _tenant_context(tenant):
            client.delete(_avatar_url(patient.id))

        # Assert
        patient.refresh_from_db()
        assert not bool(patient.avatar), "Patient.avatar debe quedar vacío tras DELETE."

    def test_delete_avatar_when_no_avatar_returns_200(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """DELETE sobre un paciente sin avatar devuelve 200 (idempotente)."""
        settings.MEDIA_ROOT = str(tmp_path)

        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)  # sin avatar
        client, _ = _make_member_client(tenant, "owner")

        # Act
        with _tenant_context(tenant):
            response = client.delete(_avatar_url(patient.id))

        # Assert
        assert response.status_code == 200

    def test_delete_avatar_requires_auth(self, db: None) -> None:
        """Sin token devuelve 401."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = APIClient()

        # Act
        response = client.delete(_avatar_url(patient.id))

        # Assert
        assert response.status_code == 401
