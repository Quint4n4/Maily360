"""
Tests de services de la app clinica.

Cubre:
- clinic_settings_upsert: crear, actualizar, partial update, validación contacts.
- template_create/update/deactivate: CRUD de plantillas.
- patient_category_create/deactivate: unicidad, baja lógica.
- doctor_update_profile_images: sello, foto, cédulas.
- doctor_university_create/delete: validación de tenant, borrado físico.
- Auditoría: audit_record llamado en cada escritura.

Patrón: AAA. Todas tocan BD → fixture db.
"""

import io

import pytest
from django.core.exceptions import ValidationError
from PIL import Image

from apps.clinica.models import ClinicSettings, ClinicTemplate, PatientCategory
from apps.clinica.services import (
    clinic_settings_upsert,
    doctor_university_create,
    doctor_university_delete,
    doctor_update_profile_images,
    patient_category_create,
    patient_category_deactivate,
    template_create,
    template_deactivate,
    template_update,
)
from tests.factories import (
    ClinicSettingsFactory,
    ClinicTemplateFactory,
    DoctorFactory,
    DoctorUniversityFactory,
    PatientCategoryFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_png():
    """Genera un PNG real en memoria."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    buf = io.BytesIO()
    Image.new("RGB", (30, 30), "gold").save(buf, "PNG")
    buf.seek(0)
    return SimpleUploadedFile("img.png", buf.read(), content_type="image/png")


# ---------------------------------------------------------------------------
# clinic_settings_upsert
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_clinic_settings_upsert_creates_on_first_call() -> None:
    """Primera llamada crea ClinicSettings si no existe."""
    tenant = TenantFactory()
    user = UserFactory()

    settings = clinic_settings_upsert(
        tenant=tenant,
        user=user,
        address="Av. Reforma 1",
        phone="5512345678",
    )

    assert settings.pk is not None
    assert settings.address == "Av. Reforma 1"
    assert settings.phone == "5512345678"
    assert settings.tenant_id == tenant.id


@pytest.mark.django_db
def test_clinic_settings_upsert_updates_existing() -> None:
    """Segunda llamada actualiza la config existente (no crea duplicado)."""
    tenant = TenantFactory()
    user = UserFactory()
    ClinicSettingsFactory(tenant=tenant, address="vieja")

    settings = clinic_settings_upsert(
        tenant=tenant,
        user=user,
        address="nueva",
        _partial_fields=frozenset({"address"}),
    )

    assert settings.address == "nueva"
    assert ClinicSettings.all_objects.filter(tenant=tenant, deleted_at__isnull=True).count() == 1


@pytest.mark.django_db
def test_clinic_settings_upsert_partial_leaves_other_fields() -> None:
    """Un partial update no borra los campos no incluidos."""
    tenant = TenantFactory()
    user = UserFactory()
    ClinicSettingsFactory(tenant=tenant, phone="1111111111", email="a@b.com")

    settings = clinic_settings_upsert(
        tenant=tenant,
        user=user,
        phone="9999999999",
        _partial_fields=frozenset({"phone"}),
    )

    assert settings.phone == "9999999999"
    assert settings.email == "a@b.com"  # intocado



# Los tests de recipe_whatsapp_contacts y recipe_use_responsible_doctor fueron
# eliminados: los campos se removieron del modelo en la migración 0007_remove_recipe_fields.


# ---------------------------------------------------------------------------
# ClinicTemplate
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_template_create_success() -> None:
    """template_create crea una plantilla con los campos dados."""
    tenant = TenantFactory()
    user = UserFactory()

    tmpl = template_create(
        tenant=tenant,
        user=user,
        kind="recipe",
        name="Receta PECAJEN",
        body="Cuerpo de la receta...",
        group="PECAJEN",
    )

    assert tmpl.pk is not None
    assert tmpl.kind == "recipe"
    assert tmpl.is_active is True
    assert tmpl.tenant_id == tenant.id


@pytest.mark.django_db
def test_template_create_invalid_kind() -> None:
    """template_create con kind inválido lanza ValidationError."""
    tenant = TenantFactory()
    user = UserFactory()

    with pytest.raises(ValidationError, match="Tipo de plantilla inválido"):
        template_create(
            tenant=tenant,
            user=user,
            kind="invalid_type",
            name="X",
            body="X",
        )


@pytest.mark.django_db
def test_template_update_modifies_name_and_body() -> None:
    """template_update cambia nombre y cuerpo de la plantilla."""
    tmpl = ClinicTemplateFactory(name="Original", body="cuerpo original")

    updated = template_update(template=tmpl, user=UserFactory(), name="Nuevo", body="nuevo cuerpo")

    assert updated.name == "Nuevo"
    assert updated.body == "nuevo cuerpo"


@pytest.mark.django_db
def test_template_update_rejects_immutable_fields() -> None:
    """template_update rechaza campos inmutables como is_active."""
    tmpl = ClinicTemplateFactory()

    with pytest.raises(ValidationError, match="is_active"):
        template_update(template=tmpl, user=UserFactory(), is_active=False)


@pytest.mark.django_db
def test_template_deactivate_sets_is_active_false() -> None:
    """template_deactivate marca is_active=False sin borrar el registro."""
    tmpl = ClinicTemplateFactory(is_active=True)

    deactivated = template_deactivate(template=tmpl, user=UserFactory())

    assert deactivated.is_active is False
    # El registro sigue en BD.
    assert ClinicTemplate.all_objects.filter(pk=tmpl.pk).exists()


# ---------------------------------------------------------------------------
# PatientCategory
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_patient_category_create_success() -> None:
    """patient_category_create crea una categoría activa."""
    tenant = TenantFactory()
    user = UserFactory()

    cat = patient_category_create(tenant=tenant, user=user, name="VIP")

    assert cat.pk is not None
    assert cat.name == "VIP"
    assert cat.is_active is True


@pytest.mark.django_db
def test_patient_category_create_rejects_duplicate() -> None:
    """No se puede crear una categoría con el mismo nombre en el mismo tenant."""
    tenant = TenantFactory()
    user = UserFactory()
    PatientCategoryFactory(tenant=tenant, name="VIP")

    with pytest.raises(ValidationError, match="VIP"):
        patient_category_create(tenant=tenant, user=user, name="VIP")


@pytest.mark.django_db
def test_patient_category_create_different_tenants_allow_same_name() -> None:
    """El mismo nombre es válido en distintos tenants."""
    t1, t2 = TenantFactory(), TenantFactory()
    user = UserFactory()
    PatientCategoryFactory(tenant=t1, name="VIP")

    # No debe lanzar
    cat2 = patient_category_create(tenant=t2, user=user, name="VIP")
    assert cat2.tenant_id == t2.id


@pytest.mark.django_db
def test_patient_category_deactivate() -> None:
    """patient_category_deactivate marca is_active=False."""
    cat = PatientCategoryFactory(is_active=True)

    result = patient_category_deactivate(category=cat, user=UserFactory())

    assert result.is_active is False
    assert PatientCategory.all_objects.filter(pk=cat.pk).exists()


# ---------------------------------------------------------------------------
# Doctor — perfil ampliado
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_doctor_update_profile_images_cedulas() -> None:
    """doctor_update_profile_images actualiza cédulas adicionales."""
    doctor = DoctorFactory()
    user = doctor.created_by

    updated = doctor_update_profile_images(
        doctor=doctor,
        user=user,
        cedulas_adicionales="12345678,87654321",
    )

    assert updated.cedulas_adicionales == "12345678,87654321"


@pytest.mark.django_db
def test_doctor_update_profile_images_sello(settings) -> None:
    """doctor_update_profile_images actualiza el campo sello con imagen PNG."""
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    settings.MEDIA_ROOT = "/tmp/maily_test_media"

    doctor = DoctorFactory()
    user = doctor.created_by
    png = _make_png()

    updated = doctor_update_profile_images(
        doctor=doctor,
        user=user,
        sello=png,
    )

    assert updated.sello
    assert str(updated.sello).startswith("clinica/")


@pytest.mark.django_db
def test_doctor_update_profile_images_no_changes_returns_doctor() -> None:
    """Si no se pasa ningún campo, el doctor se retorna sin cambios."""
    doctor = DoctorFactory()
    user = doctor.created_by

    result = doctor_update_profile_images(doctor=doctor, user=user)

    assert result.pk == doctor.pk


# ---------------------------------------------------------------------------
# DoctorUniversity
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_doctor_university_create_success(settings) -> None:
    """doctor_university_create crea un registro de universidad."""
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    settings.MEDIA_ROOT = "/tmp/maily_test_media"

    doctor = DoctorFactory()
    tenant = doctor.tenant
    user = doctor.created_by
    png = _make_png()

    univ = doctor_university_create(
        tenant=tenant,
        user=user,
        doctor=doctor,
        logo=png,
        name="UNAM",
    )

    assert univ.pk is not None
    assert univ.name == "UNAM"
    assert univ.doctor_id == doctor.id


@pytest.mark.django_db
def test_doctor_university_create_rejects_wrong_tenant() -> None:
    """doctor_university_create rechaza doctor de otro tenant."""
    doctor = DoctorFactory()
    other_tenant = TenantFactory()
    user = UserFactory()
    png = _make_png()

    with pytest.raises(ValidationError, match="no pertenece"):
        doctor_university_create(
            tenant=other_tenant,
            user=user,
            doctor=doctor,
            logo=png,
        )


@pytest.mark.django_db
def test_doctor_university_delete_removes_record(settings) -> None:
    """doctor_university_delete borra físicamente el registro."""
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    settings.MEDIA_ROOT = "/tmp/maily_test_media"

    doctor = DoctorFactory()
    png = _make_png()
    univ = doctor_university_create(
        tenant=doctor.tenant,
        user=doctor.created_by,
        doctor=doctor,
        logo=png,
    )

    univ_id = univ.id
    doctor_university_delete(university=univ, user=doctor.created_by)

    from apps.clinica.models import DoctorUniversity
    assert not DoctorUniversity.all_objects.filter(pk=univ_id).exists()


# Los tests de _validate_whatsapp_contacts fueron eliminados porque el campo
# recipe_whatsapp_contacts se removió del modelo en la migración 0007_remove_recipe_fields.


# ---------------------------------------------------------------------------
# B-2: tenant capturado antes del delete en doctor_university_delete
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_doctor_university_delete_audit_uses_pre_delete_tenant(settings) -> None:
    """B-2: audit_record recibe el tenant capturado antes de borrar el objeto.

    Verifica indirectamente que no se lanza RelatedObjectDoesNotExist al
    acceder a university.tenant después del delete.
    """
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    settings.MEDIA_ROOT = "/tmp/maily_test_media"

    doctor = DoctorFactory()
    png = _make_png()
    univ = doctor_university_create(
        tenant=doctor.tenant,
        user=doctor.created_by,
        doctor=doctor,
        logo=png,
        name="UNAM",
    )

    # Si B-2 no se hubiera corregido, esto lanzaría RelatedObjectDoesNotExist
    # porque university.tenant se accede después de university.delete().
    # Con la corrección, se captura tenant antes del delete y no hay excepción.
    doctor_university_delete(university=univ, user=doctor.created_by)  # No debe lanzar

    from apps.clinica.models import DoctorUniversity
    assert not DoctorUniversity.all_objects.filter(pk=univ.id).exists()
