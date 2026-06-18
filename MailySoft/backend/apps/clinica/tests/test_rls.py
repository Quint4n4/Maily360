"""
Tests de aislamiento multi-tenant y RLS para la app clinica.

Verifica que el TenantManager + RLS garantiza que los datos de un tenant
no son visibles desde el contexto de otro tenant.

Patrón: AAA. Todas tocan BD → fixture db.
"""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.clinica.models import ClinicSettings, ClinicTemplate, DoctorUniversity, PatientCategory
from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from tests.factories import (
    ClinicSettingsFactory,
    ClinicTemplateFactory,
    DoctorFactory,
    DoctorUniversityFactory,
    PatientCategoryFactory,
    TenantFactory,
)


@pytest.mark.django_db
def test_clinic_settings_tenant_isolation() -> None:
    """TenantManager filtra ClinicSettings del contexto activo, no de otro tenant."""
    t1 = TenantFactory()
    t2 = TenantFactory()
    s1 = ClinicSettingsFactory(tenant=t1)
    s2 = ClinicSettingsFactory(tenant=t2)

    # Activar contexto de t1
    set_current_tenant(t1)
    set_tenant_context_active(True)

    visible = list(ClinicSettings.objects.all())
    visible_ids = {s.id for s in visible}

    assert s1.id in visible_ids
    assert s2.id not in visible_ids


@pytest.mark.django_db
def test_clinic_template_tenant_isolation() -> None:
    """TenantManager filtra ClinicTemplate del contexto activo."""
    t1 = TenantFactory()
    t2 = TenantFactory()
    tmpl1 = ClinicTemplateFactory(tenant=t1)
    tmpl2 = ClinicTemplateFactory(tenant=t2)

    set_current_tenant(t1)
    set_tenant_context_active(True)

    visible_ids = set(ClinicTemplate.objects.values_list("id", flat=True))

    assert tmpl1.id in visible_ids
    assert tmpl2.id not in visible_ids


@pytest.mark.django_db
def test_patient_category_tenant_isolation() -> None:
    """TenantManager filtra PatientCategory del contexto activo."""
    t1 = TenantFactory()
    t2 = TenantFactory()
    c1 = PatientCategoryFactory(tenant=t1)
    c2 = PatientCategoryFactory(tenant=t2)

    set_current_tenant(t1)
    set_tenant_context_active(True)

    visible_ids = set(PatientCategory.objects.values_list("id", flat=True))

    assert c1.id in visible_ids
    assert c2.id not in visible_ids


@pytest.mark.django_db
def test_clinic_settings_all_objects_sees_all() -> None:
    """all_objects (sin filtro de tenant) ve todos los registros — para seeds/migrations."""
    t1 = TenantFactory()
    t2 = TenantFactory()
    ClinicSettingsFactory(tenant=t1)
    ClinicSettingsFactory(tenant=t2)

    total = ClinicSettings.all_objects.count()
    assert total >= 2  # al menos los dos que acabamos de crear


# ---------------------------------------------------------------------------
# B-1: DoctorUniversity — aislamiento multi-tenant
# ---------------------------------------------------------------------------


def _make_png_file(name: str = "logo.png") -> SimpleUploadedFile:
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(buf, "PNG")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/png")


@pytest.mark.django_db
def test_doctor_university_tenant_isolation(settings) -> None:
    """TenantManager filtra DoctorUniversity del contexto activo, no de otro tenant.

    Un logo de universidad registrado en t2 no es visible desde el contexto de t1.
    """
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    settings.MEDIA_ROOT = "/tmp/maily_test_media"

    t1 = TenantFactory()
    t2 = TenantFactory()

    doctor_t1 = DoctorFactory(tenant=t1)
    doctor_t2 = DoctorFactory(tenant=t2)

    univ1 = DoctorUniversityFactory(
        tenant=t1,
        doctor=doctor_t1,
        logo=_make_png_file("logo_t1.png"),
    )
    univ2 = DoctorUniversityFactory(
        tenant=t2,
        doctor=doctor_t2,
        logo=_make_png_file("logo_t2.png"),
    )

    # Activar contexto de t1.
    set_current_tenant(t1)
    set_tenant_context_active(True)

    visible_ids = set(DoctorUniversity.objects.values_list("id", flat=True))

    assert univ1.id in visible_ids
    assert univ2.id not in visible_ids


@pytest.mark.django_db
def test_doctor_university_all_objects_sees_all(settings) -> None:
    """all_objects ve DoctorUniversity de todos los tenants (sin filtro)."""
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    settings.MEDIA_ROOT = "/tmp/maily_test_media"

    t1 = TenantFactory()
    t2 = TenantFactory()
    doctor_t1 = DoctorFactory(tenant=t1)
    doctor_t2 = DoctorFactory(tenant=t2)

    DoctorUniversityFactory(
        tenant=t1, doctor=doctor_t1, logo=_make_png_file("logo_a.png")
    )
    DoctorUniversityFactory(
        tenant=t2, doctor=doctor_t2, logo=_make_png_file("logo_b.png")
    )

    total = DoctorUniversity.all_objects.count()
    assert total >= 2
