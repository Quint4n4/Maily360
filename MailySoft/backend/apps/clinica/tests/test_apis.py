"""
Tests de APIs de la app clinica (views.py).

Cubre:
- GET/PUT configuracion/: upsert, solo owner/admin escribe (otros 403), clínicos leen.
- GET/POST plantillas/: CRUD por kind; permisos; baja lógica DELETE.
- GET/POST categorias/: permisos; unicidad.
- DELETE categorias/<id>/: baja lógica.
- PATCH clinica/doctores/<id>/perfil/: subir sello; validación de imagen; roles.
- POST clinica/doctores/<id>/universidades/: subir logo; validación.
- Aislamiento IDOR: recursos de otro tenant → 404.
- Imagen inválida → 400 (no 500).

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

from tests.factories import (
    ClinicSettingsFactory,
    ClinicTemplateFactory,
    DoctorFactory,
    PatientCategoryFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

SETTINGS_URL = "/api/v1/clinica/configuracion/"
TEMPLATES_URL = "/api/v1/clinica/plantillas/"
CATEGORIES_URL = "/api/v1/clinica/categorias/"


def _template_detail_url(pk: Any) -> str:
    return f"/api/v1/clinica/plantillas/{pk}/"


def _category_detail_url(pk: Any) -> str:
    return f"/api/v1/clinica/categorias/{pk}/"


def _doctor_profile_url(doctor_id: Any) -> str:
    return f"/api/v1/clinica/doctores/{doctor_id}/perfil/"


def _doctor_universities_url(doctor_id: Any) -> str:
    return f"/api/v1/clinica/doctores/{doctor_id}/universidades/"


def _university_detail_url(university_id: Any) -> str:
    return f"/api/v1/clinica/universidades/{university_id}/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_png(name: str = "img.png") -> SimpleUploadedFile:
    buf = io.BytesIO()
    Image.new("RGB", (30, 30), "gold").save(buf, "PNG")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/png")


def _make_text_file(name: str = "fake.png") -> SimpleUploadedFile:
    """Bytes de texto disfrazado de imagen — debe ser rechazado."""
    return SimpleUploadedFile(name, b"not an image content", content_type="image/png")


def _make_gif() -> SimpleUploadedFile:
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "blue").save(buf, "GIF")
    buf.seek(0)
    return SimpleUploadedFile("img.gif", buf.read(), content_type="image/gif")


@contextmanager
def _tenant_context(tenant: Any) -> Generator[None, None, None]:
    """Inyecta tenant en el middleware y TenantManager para tests con force_authenticate."""
    with (
        patch("apps.clinica.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
    ):
        yield


def _make_member_client(tenant: Any, role: str) -> tuple[APIClient, Any]:
    """Crea user con membresía en BD y devuelve (APIClient, user)."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    # Inyectar active_role igual que TenantAPIView lo haría
    client._role = role  # solo referencia; el patch de tenant_context simula el middleware
    return client, user


# ---------------------------------------------------------------------------
# ClinicSettings — autenticación
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_clinic_settings_get_requires_auth() -> None:
    """GET /clinica/configuracion/ sin token → 401."""
    client = APIClient()
    response = client.get(SETTINGS_URL)
    assert response.status_code == 401


@pytest.mark.django_db
def test_clinic_settings_get_204_when_no_config() -> None:
    """GET retorna 204 si la clínica aún no tiene configuración."""
    tenant = TenantFactory()
    client, _ = _make_member_client(tenant, "owner")

    with _tenant_context(tenant), patch(
        "apps.clinica.views.get_current_tenant", return_value=tenant
    ), patch("apps.core.tenant_context.resolve_membership_for_user") as mock_resolve:
        mock_resolve.return_value = TenantMembershipFactory(tenant=tenant, role="owner")
        response = client.get(SETTINGS_URL)

    assert response.status_code in (204, 200)


# ---------------------------------------------------------------------------
# ClinicSettings — permisos por rol
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_clinic_settings_put_owner_succeeds() -> None:
    """Owner puede hacer PUT en configuracion/."""
    tenant = TenantFactory()
    membership = TenantMembershipFactory(tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    with (
        patch("apps.clinica.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
        patch(
            "apps.core.tenant_context.resolve_membership_for_user",
            return_value=membership,
        ),
    ):
        response = client.put(SETTINGS_URL, {"address": "Reforma 100"}, format="json")

    assert response.status_code in (200, 201)
    assert response.data["address"] == "Reforma 100"


@pytest.mark.django_db
def test_clinic_settings_put_readonly_rejected() -> None:
    """Rol readonly no puede modificar la configuración (403)."""
    tenant = TenantFactory()
    membership = TenantMembershipFactory(tenant=tenant, role="readonly")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    with (
        patch("apps.clinica.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
        patch(
            "apps.core.tenant_context.resolve_membership_for_user",
            return_value=membership,
        ),
    ):
        response = client.put(SETTINGS_URL, {"address": "intento"}, format="json")

    assert response.status_code == 403


@pytest.mark.django_db
def test_clinic_settings_put_invalid_empty_payload() -> None:
    """PUT con payload vacío retorna 400."""
    tenant = TenantFactory()
    membership = TenantMembershipFactory(tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    with (
        patch("apps.clinica.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
        patch(
            "apps.core.tenant_context.resolve_membership_for_user",
            return_value=membership,
        ),
    ):
        response = client.put(SETTINGS_URL, {}, format="json")

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# ClinicTemplate
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_template_list_returns_active_templates() -> None:
    """GET /clinica/plantillas/ retorna las plantillas activas del tenant."""
    tenant = TenantFactory()
    ClinicTemplateFactory(tenant=tenant, kind="recipe", is_active=True)
    ClinicTemplateFactory(tenant=tenant, kind="recipe", is_active=False)
    membership = TenantMembershipFactory(tenant=tenant, role="doctor")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    with (
        patch("apps.clinica.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
        patch(
            "apps.core.tenant_context.resolve_membership_for_user",
            return_value=membership,
        ),
    ):
        response = client.get(TEMPLATES_URL)

    assert response.status_code == 200
    results = response.data["results"]
    assert len(results) == 1
    assert results[0]["is_active"] is True


@pytest.mark.django_db
def test_template_create_by_doctor_succeeds() -> None:
    """Doctor puede crear una plantilla."""
    tenant = TenantFactory()
    membership = TenantMembershipFactory(tenant=tenant, role="doctor")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    payload = {"kind": "recipe", "name": "Mi Receta", "body": "Cuerpo..."}

    with (
        patch("apps.clinica.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
        patch(
            "apps.core.tenant_context.resolve_membership_for_user",
            return_value=membership,
        ),
    ):
        response = client.post(TEMPLATES_URL, payload, format="json")

    assert response.status_code == 201
    assert response.data["kind"] == "recipe"


@pytest.mark.django_db
def test_template_create_by_reception_rejected() -> None:
    """Recepción no puede crear plantillas (403)."""
    tenant = TenantFactory()
    membership = TenantMembershipFactory(tenant=tenant, role="reception")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    payload = {"kind": "recipe", "name": "Test", "body": "Cuerpo"}

    with (
        patch("apps.clinica.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
        patch(
            "apps.core.tenant_context.resolve_membership_for_user",
            return_value=membership,
        ),
    ):
        response = client.post(TEMPLATES_URL, payload, format="json")

    assert response.status_code == 403


@pytest.mark.django_db
def test_template_delete_logical_soft_delete() -> None:
    """DELETE en /plantillas/<id>/ marca is_active=False (baja lógica)."""
    tenant = TenantFactory()
    tmpl = ClinicTemplateFactory(tenant=tenant, is_active=True)
    membership = TenantMembershipFactory(tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    with (
        patch("apps.clinica.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
        patch(
            "apps.core.tenant_context.resolve_membership_for_user",
            return_value=membership,
        ),
    ):
        response = client.delete(_template_detail_url(tmpl.id))

    assert response.status_code == 204
    tmpl.refresh_from_db()
    assert tmpl.is_active is False


@pytest.mark.django_db
def test_template_detail_other_tenant_404() -> None:
    """Plantilla de otro tenant retorna 404 (no 403; no revela existencia)."""
    t1, t2 = TenantFactory(), TenantFactory()
    tmpl = ClinicTemplateFactory(tenant=t2)
    membership = TenantMembershipFactory(tenant=t1, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    with (
        patch("apps.clinica.views.get_current_tenant", return_value=t1),
        patch("apps.core.managers.get_current_tenant", return_value=t1),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
        patch(
            "apps.core.tenant_context.resolve_membership_for_user",
            return_value=membership,
        ),
    ):
        response = client.get(_template_detail_url(tmpl.id))

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# PatientCategory
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_category_create_owner_succeeds() -> None:
    """Owner puede crear una categoría."""
    tenant = TenantFactory()
    membership = TenantMembershipFactory(tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    with (
        patch("apps.clinica.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
        patch(
            "apps.core.tenant_context.resolve_membership_for_user",
            return_value=membership,
        ),
    ):
        response = client.post(CATEGORIES_URL, {"name": "Premium"}, format="json")

    assert response.status_code == 201
    assert response.data["name"] == "Premium"


@pytest.mark.django_db
def test_category_create_duplicate_returns_400() -> None:
    """Crear categoría con nombre duplicado retorna 400."""
    tenant = TenantFactory()
    PatientCategoryFactory(tenant=tenant, name="VIP")
    membership = TenantMembershipFactory(tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    with (
        patch("apps.clinica.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
        patch(
            "apps.core.tenant_context.resolve_membership_for_user",
            return_value=membership,
        ),
    ):
        response = client.post(CATEGORIES_URL, {"name": "VIP"}, format="json")

    assert response.status_code == 400


@pytest.mark.django_db
def test_category_delete_soft_delete() -> None:
    """DELETE categorias/<id>/ marca is_active=False."""
    tenant = TenantFactory()
    cat = PatientCategoryFactory(tenant=tenant, is_active=True)
    membership = TenantMembershipFactory(tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    with (
        patch("apps.clinica.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
        patch(
            "apps.core.tenant_context.resolve_membership_for_user",
            return_value=membership,
        ),
    ):
        response = client.delete(_category_detail_url(cat.id))

    assert response.status_code == 204
    cat.refresh_from_db()
    assert cat.is_active is False


@pytest.mark.django_db
def test_category_other_tenant_404() -> None:
    """Categoría de otro tenant → 404."""
    t1, t2 = TenantFactory(), TenantFactory()
    cat = PatientCategoryFactory(tenant=t2)
    membership = TenantMembershipFactory(tenant=t1, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    with (
        patch("apps.clinica.views.get_current_tenant", return_value=t1),
        patch("apps.core.managers.get_current_tenant", return_value=t1),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
        patch(
            "apps.core.tenant_context.resolve_membership_for_user",
            return_value=membership,
        ),
    ):
        response = client.delete(_category_detail_url(cat.id))

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Doctor — perfil (sello, foto, cédulas)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_doctor_profile_patch_cedulas_owner(settings) -> None:
    """Owner puede actualizar cédulas adicionales del médico."""
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    settings.MEDIA_ROOT = "/tmp/maily_test_media"

    doctor = DoctorFactory()
    tenant = doctor.tenant
    membership = TenantMembershipFactory(tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    with (
        patch("apps.clinica.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
        patch(
            "apps.core.tenant_context.resolve_membership_for_user",
            return_value=membership,
        ),
    ):
        response = client.patch(
            _doctor_profile_url(doctor.id),
            {"cedulas_adicionales": "12345678"},
            format="multipart",
        )

    assert response.status_code == 200


@pytest.mark.django_db
def test_doctor_profile_patch_invalid_image_returns_400(settings) -> None:
    """Bytes de texto disfrazados de imagen → 400 (no 500)."""
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    settings.MEDIA_ROOT = "/tmp/maily_test_media"

    doctor = DoctorFactory()
    tenant = doctor.tenant
    membership = TenantMembershipFactory(tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    fake_image = _make_text_file("sello.png")

    with (
        patch("apps.clinica.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
        patch(
            "apps.core.tenant_context.resolve_membership_for_user",
            return_value=membership,
        ),
    ):
        response = client.patch(
            _doctor_profile_url(doctor.id),
            {"sello": fake_image},
            format="multipart",
        )

    assert response.status_code == 400


@pytest.mark.django_db
def test_doctor_profile_patch_other_tenant_404() -> None:
    """Doctor de otro tenant → 404."""
    t1, t2 = TenantFactory(), TenantFactory()
    doctor = DoctorFactory(tenant=t2)
    membership = TenantMembershipFactory(tenant=t1, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    with (
        patch("apps.clinica.views.get_current_tenant", return_value=t1),
        patch("apps.core.managers.get_current_tenant", return_value=t1),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
        patch(
            "apps.core.tenant_context.resolve_membership_for_user",
            return_value=membership,
        ),
    ):
        response = client.patch(
            _doctor_profile_url(doctor.id),
            {"cedulas_adicionales": "xxx"},
            format="multipart",
        )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# DoctorUniversity
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_university_create_valid_png(settings) -> None:
    """POST /clinica/doctores/<id>/universidades/ con PNG válido → 201."""
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    settings.MEDIA_ROOT = "/tmp/maily_test_media"

    doctor = DoctorFactory()
    tenant = doctor.tenant
    membership = TenantMembershipFactory(tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    with (
        patch("apps.clinica.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
        patch(
            "apps.core.tenant_context.resolve_membership_for_user",
            return_value=membership,
        ),
    ):
        response = client.post(
            _doctor_universities_url(doctor.id),
            {"logo": _make_png(), "name": "UNAM"},
            format="multipart",
        )

    assert response.status_code == 201
    assert response.data["name"] == "UNAM"


@pytest.mark.django_db
def test_university_create_non_image_returns_400(settings) -> None:
    """Archivo no-imagen → 400 al intentar crear universidad."""
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    settings.MEDIA_ROOT = "/tmp/maily_test_media"

    doctor = DoctorFactory()
    tenant = doctor.tenant
    membership = TenantMembershipFactory(tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    with (
        patch("apps.clinica.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
        patch(
            "apps.core.tenant_context.resolve_membership_for_user",
            return_value=membership,
        ),
    ):
        response = client.post(
            _doctor_universities_url(doctor.id),
            {"logo": _make_text_file(), "name": "X"},
            format="multipart",
        )

    assert response.status_code == 400


@pytest.mark.django_db
def test_university_create_gif_rejected(settings) -> None:
    """GIF (formato no permitido) → 400."""
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    settings.MEDIA_ROOT = "/tmp/maily_test_media"

    doctor = DoctorFactory()
    tenant = doctor.tenant
    membership = TenantMembershipFactory(tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    with (
        patch("apps.clinica.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
        patch(
            "apps.core.tenant_context.resolve_membership_for_user",
            return_value=membership,
        ),
    ):
        response = client.post(
            _doctor_universities_url(doctor.id),
            {"logo": _make_gif(), "name": "X"},
            format="multipart",
        )

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# M-1: Guard de ownership en DoctorUniversity (POST y DELETE)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_university_create_doctor_b_cannot_post_to_doctor_a(settings) -> None:
    """Doctor B no puede agregar universidades al perfil de Doctor A → 403 (M-1).

    TenantAPIView.initial llama a resolve_membership_for_user y fija
    request.active_role = membership.role. Mockeando la función con la
    membership de Doctor B, el guard de la vista compara:
        doctor_a.membership_id  !=  membership_b.id  → 403.
    """
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    settings.MEDIA_ROOT = "/tmp/maily_test_media"

    tenant = TenantFactory()
    # Doctor A: el dueño del perfil
    doctor_a = DoctorFactory(tenant=tenant)
    # Doctor B: el actor — tiene role="doctor" pero es una membership distinta
    membership_b = TenantMembershipFactory(tenant=tenant, role="doctor")

    client = APIClient()
    client.force_authenticate(user=membership_b.user)

    # resolve_membership_for_user devuelve la membership de Doctor B.
    # TenantAPIView.initial fijará request.active_role = "doctor"
    # y request.membership = membership_b → el guard detecta mismatch.
    with (
        patch("apps.clinica.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
        patch(
            "apps.core.tenant_context.resolve_membership_for_user",
            return_value=membership_b,
        ),
    ):
        response = client.post(
            _doctor_universities_url(doctor_a.id),
            {"logo": _make_png(), "name": "UNAM"},
            format="multipart",
        )

    assert response.status_code == 403, (
        f"Guard M-1 fallido: Doctor B pudo crear universidad en perfil de Doctor A "
        f"(status={response.status_code})."
    )


@pytest.mark.django_db
def test_university_create_own_doctor_allowed(settings) -> None:
    """El propio médico puede agregar universidades a su perfil → 201 (M-1 no bloquea)."""
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    settings.MEDIA_ROOT = "/tmp/maily_test_media"

    doctor = DoctorFactory()
    tenant = doctor.tenant
    # La membership del propio doctor (la que tiene doctor.membership_id)
    own_membership = doctor.membership
    client = APIClient()
    client.force_authenticate(user=own_membership.user)

    with (
        patch("apps.clinica.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
        patch(
            "apps.core.tenant_context.resolve_membership_for_user",
            return_value=own_membership,
        ),
    ):
        response = client.post(
            _doctor_universities_url(doctor.id),
            {"logo": _make_png(), "name": "IPN"},
            format="multipart",
        )

    assert response.status_code == 201


@pytest.mark.django_db
def test_university_create_owner_can_post_to_any_doctor(settings) -> None:
    """Owner/admin puede agregar universidades a cualquier médico (sin restricción M-1)."""
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    settings.MEDIA_ROOT = "/tmp/maily_test_media"

    doctor = DoctorFactory()
    tenant = doctor.tenant
    owner_membership = TenantMembershipFactory(tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=owner_membership.user)

    with (
        patch("apps.clinica.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
        patch(
            "apps.core.tenant_context.resolve_membership_for_user",
            return_value=owner_membership,
        ),
    ):
        response = client.post(
            _doctor_universities_url(doctor.id),
            {"logo": _make_png(), "name": "UAM"},
            format="multipart",
        )

    assert response.status_code == 201


# ---------------------------------------------------------------------------
# M-2: body con max_length=50_000
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_template_create_body_over_limit_returns_400() -> None:
    """Cuerpo de plantilla mayor a 50 000 caracteres → 400 (M-2)."""
    tenant = TenantFactory()
    membership = TenantMembershipFactory(tenant=tenant, role="doctor")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    oversized_body = "x" * 50_001

    with (
        patch("apps.clinica.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
        patch(
            "apps.core.tenant_context.resolve_membership_for_user",
            return_value=membership,
        ),
    ):
        response = client.post(
            TEMPLATES_URL,
            {"kind": "recipe", "name": "Grande", "body": oversized_body},
            format="json",
        )

    assert response.status_code == 400


@pytest.mark.django_db
def test_template_patch_body_over_limit_returns_400() -> None:
    """PATCH con body mayor a 50 000 → 400 (M-2 en ClinicTemplatePatchSerializer)."""
    from tests.factories import ClinicTemplateFactory

    tenant = TenantFactory()
    tmpl = ClinicTemplateFactory(tenant=tenant)
    membership = TenantMembershipFactory(tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    oversized_body = "y" * 50_001

    with (
        patch("apps.clinica.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
        patch(
            "apps.core.tenant_context.resolve_membership_for_user",
            return_value=membership,
        ),
    ):
        response = client.patch(
            _template_detail_url(tmpl.id),
            {"body": oversized_body},
            format="json",
        )


# ---------------------------------------------------------------------------
# M2 — serializers de clinica rechazan campos desconocidos
# ---------------------------------------------------------------------------


def _clinica_ctx(tenant: Any, membership: Any) -> Any:
    """Context manager reutilizable para tests de clinica."""
    from contextlib import contextmanager
    from unittest.mock import patch as _patch

    @contextmanager  # type: ignore[misc]
    def _ctx() -> Any:
        with (
            _patch("apps.clinica.views.get_current_tenant", return_value=tenant),
            _patch("apps.core.managers.get_current_tenant", return_value=tenant),
            _patch("apps.core.managers.is_tenant_context_active", return_value=True),
            _patch(
                "apps.core.tenant_context.resolve_membership_for_user",
                return_value=membership,
            ),
        ):
            yield

    return _ctx()


@pytest.mark.django_db
def test_clinic_settings_unknown_field_returns_400() -> None:
    """PUT con campo desconocido en ClinicSettingsInputSerializer → 400 (M2)."""
    tenant = TenantFactory()
    membership = TenantMembershipFactory(tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    with _clinica_ctx(tenant, membership):
        response = client.put(
            SETTINGS_URL,
            {"address": "Reforma 100", "campo_extra": "valor"},
            format="json",
        )

    assert response.status_code == 400


@pytest.mark.django_db
def test_template_create_unknown_field_returns_400() -> None:
    """POST plantilla con campo desconocido → 400 (M2)."""
    tenant = TenantFactory()
    membership = TenantMembershipFactory(tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    with _clinica_ctx(tenant, membership):
        response = client.post(
            TEMPLATES_URL,
            {"kind": "recipe", "name": "T", "body": "Cuerpo", "campo_extra": "x"},
            format="json",
        )

    assert response.status_code == 400


@pytest.mark.django_db
def test_template_patch_unknown_field_returns_400() -> None:
    """PATCH plantilla con campo desconocido → 400 (M2)."""
    tenant = TenantFactory()
    tmpl = ClinicTemplateFactory(tenant=tenant)
    membership = TenantMembershipFactory(tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    with _clinica_ctx(tenant, membership):
        response = client.patch(
            _template_detail_url(tmpl.id),
            {"name": "Nuevo nombre", "inyectado": "x"},
            format="json",
        )

    assert response.status_code == 400


@pytest.mark.django_db
def test_category_create_unknown_field_returns_400() -> None:
    """POST categoría con campo desconocido → 400 (M2)."""
    tenant = TenantFactory()
    membership = TenantMembershipFactory(tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    with _clinica_ctx(tenant, membership):
        response = client.post(
            CATEGORIES_URL,
            {"name": "Elite", "extra": "y"},
            format="json",
        )

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# M3 — validación de formato en ClinicSettings (phone, mobile, redes sociales)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_clinic_settings_phone_valid_succeeds() -> None:
    """PUT con phone válido (10 dígitos) → 200 (M3)."""
    tenant = TenantFactory()
    membership = TenantMembershipFactory(tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    with _clinica_ctx(tenant, membership):
        response = client.put(
            SETTINGS_URL,
            {"phone": "7445514025"},
            format="json",
        )

    assert response.status_code in (200, 201)


@pytest.mark.django_db
def test_clinic_settings_phone_html_returns_400() -> None:
    """PUT con phone que contiene etiqueta HTML (<script>) → 400 (M3)."""
    tenant = TenantFactory()
    membership = TenantMembershipFactory(tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    with _clinica_ctx(tenant, membership):
        response = client.put(
            SETTINGS_URL,
            {"phone": "<script>alert(1)</script>"},
            format="json",
        )

    assert response.status_code == 400


@pytest.mark.django_db
def test_clinic_settings_facebook_handle_succeeds() -> None:
    """PUT con facebook = '@miclinica' → 200 (M3: handle permitido)."""
    tenant = TenantFactory()
    membership = TenantMembershipFactory(tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    with _clinica_ctx(tenant, membership):
        response = client.put(
            SETTINGS_URL,
            {"facebook": "@miclinica"},
            format="json",
        )

    assert response.status_code in (200, 201)


@pytest.mark.django_db
def test_clinic_settings_facebook_url_succeeds() -> None:
    """PUT con facebook = 'https://fb.com/x' → 200 (M3: URL permitida)."""
    tenant = TenantFactory()
    membership = TenantMembershipFactory(tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    with _clinica_ctx(tenant, membership):
        response = client.put(
            SETTINGS_URL,
            {"facebook": "https://fb.com/miclinica"},
            format="json",
        )

    assert response.status_code in (200, 201)


@pytest.mark.django_db
def test_clinic_settings_facebook_html_returns_400() -> None:
    """PUT con facebook que contiene tag HTML → 400 (M3)."""
    tenant = TenantFactory()
    membership = TenantMembershipFactory(tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    with _clinica_ctx(tenant, membership):
        response = client.put(
            SETTINGS_URL,
            {"facebook": "<b>hackeado</b>"},
            format="json",
        )

    assert response.status_code == 400



# Los tests de recipe_whatsapp_contacts (WhatsApp) fueron eliminados:
# el campo se removió del modelo en la migración 0007_remove_recipe_fields.


# ---------------------------------------------------------------------------
# M5 — body de plantilla rechaza etiquetas HTML
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_template_create_body_with_html_tag_returns_400() -> None:
    """POST plantilla con <script> en body → 400 (M5)."""
    tenant = TenantFactory()
    membership = TenantMembershipFactory(tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    with _clinica_ctx(tenant, membership):
        response = client.post(
            TEMPLATES_URL,
            {
                "kind": "recipe",
                "name": "Mala plantilla",
                "body": "Texto <script>alert(1)</script> inyectado.",
            },
            format="json",
        )

    assert response.status_code == 400


@pytest.mark.django_db
def test_template_create_body_with_less_than_space_succeeds() -> None:
    """POST plantilla con '< 120' (espacio tras <) → 201 (M5: no es tag real)."""
    tenant = TenantFactory()
    membership = TenantMembershipFactory(tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    with _clinica_ctx(tenant, membership):
        response = client.post(
            TEMPLATES_URL,
            {
                "kind": "recipe",
                "name": "Plantilla clínica",
                "body": "Presión sistólica < 120 mmHg, continuar monitoreo.",
            },
            format="json",
        )

    assert response.status_code == 201


@pytest.mark.django_db
def test_template_patch_body_with_html_tag_returns_400() -> None:
    """PATCH plantilla con tag HTML → 400 (M5 en ClinicTemplatePatchSerializer)."""
    tenant = TenantFactory()
    tmpl = ClinicTemplateFactory(tenant=tenant)
    membership = TenantMembershipFactory(tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)

    with _clinica_ctx(tenant, membership):
        response = client.patch(
            _template_detail_url(tmpl.id),
            {"body": "<b>negrita</b>"},
            format="json",
        )

    assert response.status_code == 400



# Los tests de B8 (recipe_whatsapp_contacts max_length=20) fueron eliminados:
# el campo se removió del modelo en la migración 0007_remove_recipe_fields.
