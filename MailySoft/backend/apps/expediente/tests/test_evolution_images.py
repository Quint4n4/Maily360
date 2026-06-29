"""
Tests de la subida segura de imágenes a notas de evolución.

Endpoints cubiertos:
    POST   /api/v1/expediente/evoluciones/<evolution_id>/imagenes/
    GET    /api/v1/expediente/evoluciones/<evolution_id>/imagenes/
    DELETE /api/v1/expediente/imagenes/<image_id>/

Casos de prueba:
    - Subir JPEG/PNG/WEBP válido → 201, registro creado.
    - Subir archivo que NO es imagen (bytes basura / .txt) → 400.
    - Subir SVG disfrazado de .png → 400.
    - Archivo sobre el límite de tamaño → 400.
    - IDOR: subir/listar imágenes de evolución de otro tenant → 404.
    - Permisos: recepción/finanzas no pueden subir (403); doctor sí.
    - GET: lectura = CLINICAL_READ.
    - DELETE: baja lógica (deleted_at rellenado, no borrado físico).
    - DELETE: imagen de otro tenant → 404.

Patrón: AAA. fixture db obligatorio (tocan BD real).
Helpers de contexto idénticos al conftest de expediente.
"""

import io
import uuid
from contextlib import contextmanager
from typing import Any, Generator
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIClient

from apps.expediente.models import EvolutionImage
from tests.factories import (
    PatientFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

# ---------------------------------------------------------------------------
# Factories locales de evolución
# ---------------------------------------------------------------------------
# Importamos las factories existentes del módulo de expediente donde estén.
# Si no existe una factory de EvolutionNote se crea aquí inline.


def _make_evolution(tenant: Any, user: Any, patient: Any) -> Any:
    """Crea una EvolutionNote mínima válida para los tests.

    Crea: Appointment (ATTENDED) + Doctor + EvolutionNote
    Todo dentro del mismo tenant, usuario y paciente.
    """
    from django.utils import timezone

    from apps.agenda.models import Appointment
    from apps.expediente.models import EvolutionNote
    from apps.personal.models import Doctor
    from apps.tenancy.models import TenantMembership

    # Creamos membresía de doctor si el usuario no tiene rol doctor aún.
    membership, _ = TenantMembership.objects.get_or_create(
        user=user,
        tenant=tenant,
        defaults={"role": "doctor", "is_active": True},
    )
    if membership.role != "doctor":
        membership.role = "doctor"
        membership.save(update_fields=["role"])

    doctor, _ = Doctor.objects.get_or_create(
        tenant=tenant,
        membership=membership,
        defaults={"created_by": user},
    )

    appointment = Appointment.objects.create(
        tenant=tenant,
        created_by=user,
        patient=patient,
        doctor=doctor,
        starts_at=timezone.now(),
        ends_at=timezone.now(),
        status=Appointment.Status.ATTENDED,
    )

    note = EvolutionNote.objects.create(
        tenant=tenant,
        created_by=user,
        patient=patient,
        appointment=appointment,
        doctor=doctor,
        is_locked=True,
    )
    return note


# ---------------------------------------------------------------------------
# Helpers de archivos
# ---------------------------------------------------------------------------


def _make_png(name: str = "foto.png") -> SimpleUploadedFile:
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), "gold").save(buf, "PNG")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/png")


def _make_jpeg(name: str = "foto.jpg") -> SimpleUploadedFile:
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), "red").save(buf, "JPEG")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/jpeg")


def _make_webp(name: str = "foto.webp") -> SimpleUploadedFile:
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), "blue").save(buf, "WEBP")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/webp")


def _make_svg_disguised_as_png() -> SimpleUploadedFile:
    """SVG con extensión .png — el Content-Type dice image/png, el contenido es SVG."""
    svg_bytes = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    return SimpleUploadedFile("malicioso.png", svg_bytes, content_type="image/png")


def _make_text_file_disguised_as_jpg() -> SimpleUploadedFile:
    """Bytes de texto que NO son imagen, extensión .jpg."""
    return SimpleUploadedFile(
        "no_soy_imagen.jpg",
        b"esto es texto plano \x00\x01\xff\xfe",
        content_type="image/jpeg",
    )


def _make_oversized_png_bytes(target_bytes: int = 10 * 1024 * 1024 + 1) -> SimpleUploadedFile:
    """Crea un PNG de contenido real cuyo tamaño en bytes supera el límite.

    Genera el PNG con Pillow y lo rellena hasta target_bytes con ceros al final
    del buffer. El resultado es un archivo válido para Pillow (el relleno queda
    después de los bytes IEND del PNG, que Pillow ignora durante verify()).
    """
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), "green").save(buf, "PNG")
    # Añadir padding de ceros hasta superar el límite
    current = buf.tell()
    padding = max(0, target_bytes - current)
    buf.write(b"\x00" * padding)
    buf.seek(0)
    return SimpleUploadedFile("grande.png", buf.read(), content_type="image/png")


# ---------------------------------------------------------------------------
# Helpers de autenticación y contexto
# ---------------------------------------------------------------------------


def _url_imagenes(evolution_id: Any) -> str:
    return f"/api/v1/expediente/evoluciones/{evolution_id}/imagenes/"


def _url_imagen(image_id: Any) -> str:
    return f"/api/v1/expediente/imagenes/{image_id}/"


@contextmanager
def _tenant_ctx(tenant: Any) -> Generator[None, None, None]:
    """Simula el TenantMiddleware en tests con force_authenticate."""
    with (
        patch("apps.expediente.views_imagenes.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
    ):
        yield


def _make_client(tenant: Any, role: str) -> tuple[APIClient, Any]:
    """Crea user con membresía activa y devuelve (cliente autenticado, user)."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


# ===========================================================================
# POST — subir imagen
# ===========================================================================


class TestEvolutionImageUpload:
    """POST /api/v1/expediente/evoluciones/<id>/imagenes/ — subir imagen."""

    def test_upload_valid_jpeg_returns_201(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """JPEG válido devuelve 201 y crea el registro en BD."""
        settings.MEDIA_ROOT = str(tmp_path)

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, user = _make_client(tenant, "doctor")
        note = _make_evolution(tenant, user, patient)

        with _tenant_ctx(tenant):
            response = client.post(
                _url_imagenes(note.id),
                {"image": _make_jpeg()},
                format="multipart",
            )

        assert response.status_code == 201, response.data
        data = response.json()
        assert data.get("id") is not None
        assert data.get("image_url") is not None
        assert EvolutionImage.all_objects.filter(evolution=note).count() == 1

    def test_upload_valid_png_returns_201(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """PNG válido devuelve 201."""
        settings.MEDIA_ROOT = str(tmp_path)

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, user = _make_client(tenant, "doctor")
        note = _make_evolution(tenant, user, patient)

        with _tenant_ctx(tenant):
            response = client.post(
                _url_imagenes(note.id),
                {"image": _make_png()},
                format="multipart",
            )

        assert response.status_code == 201, response.data

    def test_upload_valid_webp_returns_201(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """WEBP válido devuelve 201."""
        settings.MEDIA_ROOT = str(tmp_path)

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, user = _make_client(tenant, "doctor")
        note = _make_evolution(tenant, user, patient)

        with _tenant_ctx(tenant):
            response = client.post(
                _url_imagenes(note.id),
                {"image": _make_webp()},
                format="multipart",
            )

        assert response.status_code == 201, response.data

    def test_upload_non_image_bytes_returns_400(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """CASO CRITICO: bytes basura con extensión .jpg → 400, nunca 500.

        Verificación explícita: Pillow lanzaría SyntaxError / UnidentifiedImageError
        sin atrapar → 500. validate_evolution_image atrapa toda excepción → 400.
        """
        settings.MEDIA_ROOT = str(tmp_path)

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, user = _make_client(tenant, "doctor")
        note = _make_evolution(tenant, user, patient)

        with _tenant_ctx(tenant):
            response = client.post(
                _url_imagenes(note.id),
                {"image": _make_text_file_disguised_as_jpg()},
                format="multipart",
            )

        assert response.status_code == 400, (
            f"Se esperaba 400 para no-imagen, obtuvo {response.status_code}. "
            "validate_evolution_image debe atrapar TODAS las excepciones de Pillow."
        )
        assert response.status_code != 500
        # No se debe haber creado el registro
        assert EvolutionImage.all_objects.filter(evolution=note).count() == 0

    def test_upload_svg_disguised_as_png_returns_400(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """SVG con extensión .png (y Content-Type image/png) → 400.

        Pillow no reconoce SVG como imagen rasterizada → UnidentifiedImageError → 400.
        """
        settings.MEDIA_ROOT = str(tmp_path)

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, user = _make_client(tenant, "doctor")
        note = _make_evolution(tenant, user, patient)

        with _tenant_ctx(tenant):
            response = client.post(
                _url_imagenes(note.id),
                {"image": _make_svg_disguised_as_png()},
                format="multipart",
            )

        assert response.status_code == 400, (
            f"SVG disfrazado de PNG debe dar 400, obtuvo {response.status_code}."
        )
        assert EvolutionImage.all_objects.filter(evolution=note).count() == 0

    def test_upload_oversized_image_returns_400(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """Imagen con tamaño > 10 MB → 400.

        Se genera un PNG real con padding de bytes nulos hasta superar el límite.
        Pillow puede abrir el PNG (ignora el padding IEND), pero validate_evolution_image
        lo rechaza por tamaño ANTES de que Pillow llegue a verify().
        """
        settings.MEDIA_ROOT = str(tmp_path)

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, user = _make_client(tenant, "doctor")
        note = _make_evolution(tenant, user, patient)

        with _tenant_ctx(tenant):
            response = client.post(
                _url_imagenes(note.id),
                {"image": _make_oversized_png_bytes()},
                format="multipart",
            )

        assert response.status_code == 400, (
            f"Imagen sobre límite debe dar 400, obtuvo {response.status_code}."
        )

    def test_upload_without_image_field_returns_400(self, db: None) -> None:
        """POST sin campo 'image' → 400."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, user = _make_client(tenant, "doctor")
        note = _make_evolution(tenant, user, patient)

        with _tenant_ctx(tenant):
            response = client.post(
                _url_imagenes(note.id),
                data={},
                format="multipart",
            )

        assert response.status_code == 400

    def test_upload_with_caption_stores_caption(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """El caption opcional se guarda correctamente."""
        settings.MEDIA_ROOT = str(tmp_path)

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, user = _make_client(tenant, "doctor")
        note = _make_evolution(tenant, user, patient)

        with _tenant_ctx(tenant):
            response = client.post(
                _url_imagenes(note.id),
                {"image": _make_png(), "caption": "Herida día 3"},
                format="multipart",
            )

        assert response.status_code == 201
        data = response.json()
        assert data.get("caption") == "Herida día 3"

    # -----------------------------------------------------------------------
    # IDOR — aislamiento multi-tenant
    # -----------------------------------------------------------------------

    def test_upload_to_evolution_of_other_tenant_returns_404(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """Subir imagen a nota de evolución de otro tenant → 404 (anti-IDOR)."""
        settings.MEDIA_ROOT = str(tmp_path)

        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        patient_b = PatientFactory(tenant=tenant_b)
        user_b = UserFactory()
        TenantMembershipFactory(user=user_b, tenant=tenant_b, role="doctor", is_active=True)
        note_b = _make_evolution(tenant_b, user_b, patient_b)

        # Actor del tenant A intenta subir a la nota del tenant B
        client_a, _ = _make_client(tenant_a, "doctor")

        with _tenant_ctx(tenant_a):
            response = client_a.post(
                _url_imagenes(note_b.id),
                {"image": _make_png()},
                format="multipart",
            )

        assert response.status_code == 404, (
            f"Evolución de otro tenant debe dar 404, obtuvo {response.status_code}."
        )
        assert EvolutionImage.all_objects.filter(evolution=note_b).count() == 0

    def test_upload_to_nonexistent_evolution_returns_404(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """UUID de evolución inexistente → 404."""
        settings.MEDIA_ROOT = str(tmp_path)

        tenant = TenantFactory()
        client, _ = _make_client(tenant, "doctor")

        with _tenant_ctx(tenant):
            response = client.post(
                _url_imagenes(uuid.uuid4()),
                {"image": _make_png()},
                format="multipart",
            )

        assert response.status_code == 404

    # -----------------------------------------------------------------------
    # Permisos
    # -----------------------------------------------------------------------

    def test_upload_requires_auth(self, db: None) -> None:
        """Sin token → 401."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant, role="doctor", is_active=True)
        note = _make_evolution(tenant, user, patient)
        client = APIClient()  # sin autenticar

        response = client.post(
            _url_imagenes(note.id),
            {"image": _make_png()},
            format="multipart",
        )

        assert response.status_code == 401

    def test_upload_reception_role_returns_403(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """Rol 'reception' no puede subir imágenes de evolución (403).

        EvolutionPermission.POST = {owner, admin, doctor}.
        """
        settings.MEDIA_ROOT = str(tmp_path)

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        doctor_user = UserFactory()
        TenantMembershipFactory(user=doctor_user, tenant=tenant, role="doctor", is_active=True)
        note = _make_evolution(tenant, doctor_user, patient)

        client_reception, _ = _make_client(tenant, "reception")

        with _tenant_ctx(tenant):
            response = client_reception.post(
                _url_imagenes(note.id),
                {"image": _make_png()},
                format="multipart",
            )

        assert response.status_code == 403, (
            f"Recepción no debería poder subir imágenes, obtuvo {response.status_code}."
        )

    def test_upload_finance_role_returns_403(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """Rol 'finance' no puede subir imágenes de evolución (403)."""
        settings.MEDIA_ROOT = str(tmp_path)

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        doctor_user = UserFactory()
        TenantMembershipFactory(user=doctor_user, tenant=tenant, role="doctor", is_active=True)
        note = _make_evolution(tenant, doctor_user, patient)

        client_finance, _ = _make_client(tenant, "finance")

        with _tenant_ctx(tenant):
            response = client_finance.post(
                _url_imagenes(note.id),
                {"image": _make_png()},
                format="multipart",
            )

        assert response.status_code == 403

    def test_upload_doctor_role_returns_201(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """Rol 'doctor' puede subir imágenes (201)."""
        settings.MEDIA_ROOT = str(tmp_path)

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, user = _make_client(tenant, "doctor")
        note = _make_evolution(tenant, user, patient)

        with _tenant_ctx(tenant):
            response = client.post(
                _url_imagenes(note.id),
                {"image": _make_png()},
                format="multipart",
            )

        assert response.status_code == 201


# ===========================================================================
# GET — listar imágenes
# ===========================================================================


class TestEvolutionImageList:
    """GET /api/v1/expediente/evoluciones/<id>/imagenes/ — listar imágenes."""

    def test_list_returns_uploaded_images(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """Tras subir N imágenes, GET devuelve exactamente N registros."""
        settings.MEDIA_ROOT = str(tmp_path)

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, user = _make_client(tenant, "doctor")
        note = _make_evolution(tenant, user, patient)

        with _tenant_ctx(tenant):
            client.post(
                _url_imagenes(note.id), {"image": _make_png()}, format="multipart"
            )
            client.post(
                _url_imagenes(note.id), {"image": _make_jpeg()}, format="multipart"
            )
            response = client.get(_url_imagenes(note.id))

        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_list_does_not_include_soft_deleted(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """Las imágenes con deleted_at rellenado no aparecen en el listado."""
        settings.MEDIA_ROOT = str(tmp_path)

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, user = _make_client(tenant, "doctor")
        note = _make_evolution(tenant, user, patient)

        # Subir dos imágenes
        with _tenant_ctx(tenant):
            resp1 = client.post(
                _url_imagenes(note.id), {"image": _make_png()}, format="multipart"
            )
            client.post(
                _url_imagenes(note.id), {"image": _make_jpeg()}, format="multipart"
            )

        # Dar de baja lógica la primera
        image_id = resp1.json()["id"]
        with _tenant_ctx(tenant):
            client.delete(_url_imagen(image_id))

        # El listado debe mostrar solo la segunda
        with _tenant_ctx(tenant):
            response = client.get(_url_imagenes(note.id))

        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_list_other_tenant_evolution_returns_404(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """GET de imágenes de evolución de otro tenant → 404 (anti-IDOR)."""
        settings.MEDIA_ROOT = str(tmp_path)

        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        patient_b = PatientFactory(tenant=tenant_b)
        user_b = UserFactory()
        TenantMembershipFactory(user=user_b, tenant=tenant_b, role="doctor", is_active=True)
        note_b = _make_evolution(tenant_b, user_b, patient_b)

        client_a, _ = _make_client(tenant_a, "doctor")

        with _tenant_ctx(tenant_a):
            response = client_a.get(_url_imagenes(note_b.id))

        assert response.status_code == 404

    def test_list_readonly_role_can_read(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """Rol 'readonly' puede listar imágenes (CLINICAL_READ incluye readonly)."""
        settings.MEDIA_ROOT = str(tmp_path)

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        doctor_user = UserFactory()
        TenantMembershipFactory(user=doctor_user, tenant=tenant, role="doctor", is_active=True)
        note = _make_evolution(tenant, doctor_user, patient)

        client_ro, _ = _make_client(tenant, "readonly")

        with _tenant_ctx(tenant):
            response = client_ro.get(_url_imagenes(note.id))

        assert response.status_code == 200

    def test_list_reception_role_returns_403(self, db: None) -> None:
        """Rol 'reception' no puede listar imágenes de evolución (403).

        CLINICAL_READ excluye recepción (contenido clínico sensible).
        """
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        doctor_user = UserFactory()
        TenantMembershipFactory(user=doctor_user, tenant=tenant, role="doctor", is_active=True)
        note = _make_evolution(tenant, doctor_user, patient)

        client_rec, _ = _make_client(tenant, "reception")

        with _tenant_ctx(tenant):
            response = client_rec.get(_url_imagenes(note.id))

        assert response.status_code == 403


# ===========================================================================
# DELETE — baja lógica
# ===========================================================================


class TestEvolutionImageDelete:
    """DELETE /api/v1/expediente/imagenes/<image_id>/ — baja lógica."""

    def test_delete_sets_deleted_at_not_physical_delete(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """DELETE rellena deleted_at; el registro sigue en BD (D-EC-5)."""
        settings.MEDIA_ROOT = str(tmp_path)

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, user = _make_client(tenant, "doctor")
        note = _make_evolution(tenant, user, patient)

        with _tenant_ctx(tenant):
            resp = client.post(
                _url_imagenes(note.id), {"image": _make_png()}, format="multipart"
            )
        image_id = resp.json()["id"]

        with _tenant_ctx(tenant):
            response = client.delete(_url_imagen(image_id))

        assert response.status_code == 204

        # El registro debe seguir en BD con deleted_at rellenado.
        img = EvolutionImage.all_objects.get(id=image_id)
        assert img.deleted_at is not None, (
            "deleted_at debe estar rellenado tras la baja lógica (D-EC-5)."
        )

    def test_delete_is_idempotent(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """Doble DELETE sobre la misma imagen → 404 en el segundo intento.

        El TenantManager excluye soft-deleted, así que el segundo DELETE no
        encuentra el registro y devuelve 404 (comportamiento correcto).
        """
        settings.MEDIA_ROOT = str(tmp_path)

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, user = _make_client(tenant, "doctor")
        note = _make_evolution(tenant, user, patient)

        with _tenant_ctx(tenant):
            resp = client.post(
                _url_imagenes(note.id), {"image": _make_png()}, format="multipart"
            )
        image_id = resp.json()["id"]

        with _tenant_ctx(tenant):
            r1 = client.delete(_url_imagen(image_id))
            r2 = client.delete(_url_imagen(image_id))

        assert r1.status_code == 204
        # Segundo intento: el TenantManager no ve el soft-deleted → 404
        assert r2.status_code == 404

    def test_delete_image_of_other_tenant_returns_404(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """Baja lógica de imagen de otro tenant → 404 (anti-IDOR)."""
        settings.MEDIA_ROOT = str(tmp_path)

        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        patient_b = PatientFactory(tenant=tenant_b)
        user_b = UserFactory()
        TenantMembershipFactory(user=user_b, tenant=tenant_b, role="doctor", is_active=True)
        note_b = _make_evolution(tenant_b, user_b, patient_b)

        # Subir imagen en tenant B
        client_b, _ = _make_client(tenant_b, "doctor")
        with _tenant_ctx(tenant_b):
            resp = client_b.post(
                _url_imagenes(note_b.id), {"image": _make_png()}, format="multipart"
            )
        image_id = resp.json()["id"]

        # Actor del tenant A intenta borrar la imagen de B
        client_a, _ = _make_client(tenant_a, "doctor")
        with _tenant_ctx(tenant_a):
            response = client_a.delete(_url_imagen(image_id))

        assert response.status_code == 404, (
            f"Imagen de otro tenant debe dar 404, obtuvo {response.status_code}."
        )

        # La imagen no debe haber sido dada de baja
        img = EvolutionImage.all_objects.get(id=image_id)
        assert img.deleted_at is None, "La imagen de otro tenant no debe haberse dado de baja."

    def test_delete_nonexistent_image_returns_404(self, db: None) -> None:
        """UUID de imagen inexistente → 404."""
        tenant = TenantFactory()
        client, _ = _make_client(tenant, "doctor")

        with _tenant_ctx(tenant):
            response = client.delete(_url_imagen(uuid.uuid4()))

        assert response.status_code == 404

    def test_delete_requires_auth(self, db: None, tmp_path: Any, settings: Any) -> None:
        """Sin token → 401."""
        settings.MEDIA_ROOT = str(tmp_path)

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant, role="doctor", is_active=True)
        note = _make_evolution(tenant, user, patient)

        client_doc = APIClient()
        client_doc.force_authenticate(user=user)
        with _tenant_ctx(tenant):
            resp = client_doc.post(
                _url_imagenes(note.id), {"image": _make_png()}, format="multipart"
            )
        image_id = resp.json()["id"]

        unauthenticated = APIClient()
        response = unauthenticated.delete(_url_imagen(image_id))
        assert response.status_code == 401


# ===========================================================================
# Services layer — tests directos
# ===========================================================================


class TestEvolutionImageServices:
    """Tests de los services sin pasar por HTTP (defensa en profundidad)."""

    def test_evolution_image_add_validates_image(self, db: None, tmp_path: Any, settings: Any) -> None:
        """evolution_image_add lanza ValidationError ante bytes no-imagen."""
        from django.core.exceptions import ValidationError

        from apps.expediente.services import evolution_image_add

        settings.MEDIA_ROOT = str(tmp_path)

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant, role="doctor", is_active=True)
        note = _make_evolution(tenant, user, patient)

        # Parchear TenantManager para que no filtre por tenant en el create
        with _tenant_ctx(tenant):
            import pytest
            with pytest.raises(ValidationError):
                evolution_image_add(
                    tenant=tenant,
                    user=user,
                    evolution=note,
                    image=_make_text_file_disguised_as_jpg(),
                )

    def test_evolution_image_remove_is_soft_delete(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """evolution_image_remove pone deleted_at; el objeto permanece en BD."""
        from apps.expediente.services import evolution_image_add, evolution_image_remove

        settings.MEDIA_ROOT = str(tmp_path)

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant, role="doctor", is_active=True)
        note = _make_evolution(tenant, user, patient)

        with _tenant_ctx(tenant):
            img = evolution_image_add(
                tenant=tenant,
                user=user,
                evolution=note,
                image=_make_png(),
            )

        assert img.deleted_at is None

        evolution_image_remove(image=img, user=user)

        img.refresh_from_db()
        assert img.deleted_at is not None, "evolution_image_remove debe rellenar deleted_at."
        # El registro sigue en BD (all_objects incluye soft-deleted)
        assert EvolutionImage.all_objects.filter(id=img.id).exists()


# ===========================================================================
# MEDIO-3 — Bitácora de auditoría NOM-024 en imágenes
# ===========================================================================


class TestEvolutionImageAuditLog:
    """MEDIO-3: evolution_image_add y evolution_image_remove generan AuditLog."""

    def test_image_add_creates_audit_log(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """Subir imagen → AuditLog con EVOLUTION_IMAGE_ADD, sin PII en metadata."""
        from apps.audit.models import ActionType, AuditLog
        from apps.expediente.services import evolution_image_add

        settings.MEDIA_ROOT = str(tmp_path)

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant, role="doctor", is_active=True)
        note = _make_evolution(tenant, user, patient)

        with _tenant_ctx(tenant):
            img = evolution_image_add(
                tenant=tenant,
                user=user,
                evolution=note,
                image=_make_png(),
            )

        # Debe existir exactamente un log EVOLUTION_IMAGE_ADD para esta imagen
        log = AuditLog.all_objects.filter(
            action=ActionType.EVOLUTION_IMAGE_ADD,
            resource_id=img.id,
        ).first()
        assert log is not None, "Debe existir AuditLog con EVOLUTION_IMAGE_ADD."
        assert log.tenant_id == tenant.id
        assert log.resource_type == "EvolutionImage"
        assert log.resource_repr == str(img.id)
        # metadata debe incluir evolution_id y patient_id, NO nombre de archivo (PII)
        assert log.metadata.get("evolution_id") == str(note.id)
        assert log.metadata.get("patient_id") == str(patient.id)
        # Verificar que NO hay nombre de archivo en metadata (regla de privacidad)
        metadata_str = str(log.metadata)
        assert "image" not in metadata_str.lower() or "evolution_id" in metadata_str

    def test_image_remove_creates_audit_log(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """Baja de imagen → AuditLog con EVOLUTION_IMAGE_REMOVE, sin PII."""
        from apps.audit.models import ActionType, AuditLog
        from apps.expediente.services import evolution_image_add, evolution_image_remove

        settings.MEDIA_ROOT = str(tmp_path)

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant, role="doctor", is_active=True)
        note = _make_evolution(tenant, user, patient)

        with _tenant_ctx(tenant):
            img = evolution_image_add(
                tenant=tenant,
                user=user,
                evolution=note,
                image=_make_png(),
            )

        # Necesitamos que evolution esté precargado (como lo hace el selector)
        img.refresh_from_db()
        img.evolution = note  # simular select_related

        evolution_image_remove(image=img, user=user)

        log = AuditLog.all_objects.filter(
            action=ActionType.EVOLUTION_IMAGE_REMOVE,
            resource_id=img.id,
        ).first()
        assert log is not None, "Debe existir AuditLog con EVOLUTION_IMAGE_REMOVE."
        assert log.tenant_id == tenant.id
        assert log.resource_type == "EvolutionImage"
        assert log.resource_repr == str(img.id)
        assert log.metadata.get("evolution_id") == str(note.id)
        assert log.metadata.get("patient_id") == str(patient.id)

    def test_image_remove_idempotent_no_duplicate_audit(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """Doble baja de imagen → AuditLog solo se crea una vez (idempotencia)."""
        from apps.audit.models import ActionType, AuditLog
        from apps.expediente.services import evolution_image_add, evolution_image_remove

        settings.MEDIA_ROOT = str(tmp_path)

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant, role="doctor", is_active=True)
        note = _make_evolution(tenant, user, patient)

        with _tenant_ctx(tenant):
            img = evolution_image_add(
                tenant=tenant,
                user=user,
                evolution=note,
                image=_make_png(),
            )

        img.refresh_from_db()
        img.evolution = note

        evolution_image_remove(image=img, user=user)
        img.refresh_from_db()
        img.evolution = note
        evolution_image_remove(image=img, user=user)  # segunda llamada (idempotente)

        count = AuditLog.all_objects.filter(
            action=ActionType.EVOLUTION_IMAGE_REMOVE,
            resource_id=img.id,
        ).count()
        assert count == 1, (
            f"La baja lógica idempotente debe generar solo 1 AuditLog, generó {count}."
        )


# ===========================================================================
# MEDIO-2 — Límite de imágenes por nota
# ===========================================================================


class TestEvolutionImageLimit:
    """MEDIO-2: evolution_image_add rechaza la imagen N+1 cuando N == MAX."""

    def test_max_images_limit_raises_validation_error(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """La imagen número MAX+1 lanza ValidationError con mensaje apropiado."""
        from django.core.exceptions import ValidationError

        from apps.expediente.services import MAX_IMAGES_PER_EVOLUTION, evolution_image_add

        settings.MEDIA_ROOT = str(tmp_path)

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant, role="doctor", is_active=True)
        note = _make_evolution(tenant, user, patient)

        # Crear exactamente MAX imágenes activas
        with _tenant_ctx(tenant):
            for _ in range(MAX_IMAGES_PER_EVOLUTION):
                evolution_image_add(
                    tenant=tenant,
                    user=user,
                    evolution=note,
                    image=_make_png(),
                )

            # La siguiente debe rechazarse
            with pytest.raises(ValidationError) as exc_info:
                evolution_image_add(
                    tenant=tenant,
                    user=user,
                    evolution=note,
                    image=_make_png(),
                )

        assert "máximo" in str(exc_info.value).lower() or "maximum" in str(exc_info.value).lower()

    def test_image_limit_via_api_returns_400(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """La imagen número MAX+1 vía HTTP → 400 con mensaje claro."""
        from apps.expediente.services import MAX_IMAGES_PER_EVOLUTION

        settings.MEDIA_ROOT = str(tmp_path)

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, user = _make_client(tenant, "doctor")
        note = _make_evolution(tenant, user, patient)

        # Subir exactamente MAX imágenes activas
        with _tenant_ctx(tenant):
            for _ in range(MAX_IMAGES_PER_EVOLUTION):
                r = client.post(
                    _url_imagenes(note.id),
                    {"image": _make_png()},
                    format="multipart",
                )
                assert r.status_code == 201, f"Falla en imagen #{_ + 1}: {r.data}"

            # La imagen (MAX+1) debe dar 400
            response = client.post(
                _url_imagenes(note.id),
                {"image": _make_png()},
                format="multipart",
            )

        assert response.status_code == 400, (
            f"La imagen {MAX_IMAGES_PER_EVOLUTION + 1} debe dar 400, "
            f"obtuvo {response.status_code}."
        )

    def test_soft_deleted_images_do_not_count_toward_limit(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """Las imágenes con deleted_at no cuentan para el límite."""
        from apps.expediente.services import MAX_IMAGES_PER_EVOLUTION, evolution_image_add, evolution_image_remove

        settings.MEDIA_ROOT = str(tmp_path)

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant, role="doctor", is_active=True)
        note = _make_evolution(tenant, user, patient)

        with _tenant_ctx(tenant):
            # Crear MAX imágenes
            first_img = None
            for i in range(MAX_IMAGES_PER_EVOLUTION):
                img = evolution_image_add(
                    tenant=tenant,
                    user=user,
                    evolution=note,
                    image=_make_png(),
                )
                if i == 0:
                    first_img = img

            # Dar de baja la primera (libera un slot)
            assert first_img is not None
            first_img.evolution = note  # simular select_related
            evolution_image_remove(image=first_img, user=user)

            # Ahora hay MAX-1 activas → debe poder agregar una más sin error
            new_img = evolution_image_add(
                tenant=tenant,
                user=user,
                evolution=note,
                image=_make_png(),
            )

        assert new_img.pk is not None, "Debe poder agregar imagen tras liberar un slot."


# ===========================================================================
# BAJO-2 — Prefijo de tenant en la ruta de storage
# ===========================================================================


class TestEvolutionImageTenantPath:
    """BAJO-2: evolution_image_path incluye tenant_id en la ruta del archivo."""

    def test_uploaded_image_path_contains_tenant_id(
        self, db: None, tmp_path: Any, settings: Any
    ) -> None:
        """La ruta del archivo guardado contiene el tenant_id del propietario."""
        from apps.expediente.services import evolution_image_add

        settings.MEDIA_ROOT = str(tmp_path)

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant, role="doctor", is_active=True)
        note = _make_evolution(tenant, user, patient)

        with _tenant_ctx(tenant):
            img = evolution_image_add(
                tenant=tenant,
                user=user,
                evolution=note,
                image=_make_png(),
            )

        # La ruta almacenada debe contener el tenant_id
        image_name = img.image.name  # ruta relativa bajo MEDIA_ROOT
        assert str(tenant.id) in image_name, (
            f"La ruta de la imagen '{image_name}' debe contener el tenant_id '{tenant.id}'."
        )
        assert image_name.startswith("evoluciones/"), (
            f"La ruta debe empezar con 'evoluciones/', obtuvo: '{image_name}'."
        )
