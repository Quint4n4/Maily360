"""
Tests de selectors de la app clinica.

Cubre:
- clinic_settings_get: retorna None si no existe, instancia si existe.
- clinic_template_list: filtra por kind; respeta tenant (no fuga datos).
- patient_category_list: solo activas; aislamiento de tenant.
- doctor_university_list: solo del doctor dado; aislamiento de tenant.
- Aislamiento multi-tenant: selector no devuelve datos de otro tenant.

Patrón: AAA. Todas tocan BD → fixture db.
"""

import uuid

import pytest

from apps.clinica.selectors import (
    clinic_settings_get,
    clinic_template_get,
    clinic_template_list,
    doctor_university_list,
    patient_category_get,
    patient_category_list,
)
from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from tests.factories import (
    ClinicSettingsFactory,
    ClinicTemplateFactory,
    DoctorFactory,
    PatientCategoryFactory,
    TenantFactory,
)


# ---------------------------------------------------------------------------
# clinic_settings_get
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_clinic_settings_get_returns_none_when_absent() -> None:
    """Retorna None si el tenant no tiene configuración."""
    tenant = TenantFactory()
    set_current_tenant(tenant)
    set_tenant_context_active(True)

    result = clinic_settings_get(tenant_id=tenant.id)

    assert result is None


@pytest.mark.django_db
def test_clinic_settings_get_returns_instance_when_present() -> None:
    """Retorna la instancia si el tenant tiene configuración."""
    settings = ClinicSettingsFactory(address="Reforma 1")
    tenant = settings.tenant
    set_current_tenant(tenant)
    set_tenant_context_active(True)

    result = clinic_settings_get(tenant_id=tenant.id)

    assert result is not None
    assert result.pk == settings.pk


@pytest.mark.django_db
def test_clinic_settings_get_does_not_return_other_tenant() -> None:
    """No retorna la config de otro tenant."""
    t1 = TenantFactory()
    t2 = TenantFactory()
    ClinicSettingsFactory(tenant=t2)  # config de t2

    result = clinic_settings_get(tenant_id=t1.id)

    assert result is None


# ---------------------------------------------------------------------------
# clinic_template_list
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_clinic_template_list_filter_by_kind() -> None:
    """Filtra por kind: solo devuelve los del tipo solicitado."""
    tenant = TenantFactory()
    set_current_tenant(tenant)
    set_tenant_context_active(True)

    ClinicTemplateFactory(tenant=tenant, kind="recipe", is_active=True)
    ClinicTemplateFactory(tenant=tenant, kind="document", is_active=True)

    result = list(clinic_template_list(kind="recipe"))

    assert all(t.kind == "recipe" for t in result)
    assert len(result) == 1


@pytest.mark.django_db
def test_clinic_template_list_excludes_inactive() -> None:
    """Plantillas inactivas no aparecen en el listado."""
    tenant = TenantFactory()
    set_current_tenant(tenant)
    set_tenant_context_active(True)

    ClinicTemplateFactory(tenant=tenant, kind="recipe", is_active=True)
    ClinicTemplateFactory(tenant=tenant, kind="recipe", is_active=False)

    result = list(clinic_template_list(kind="recipe"))

    assert len(result) == 1


@pytest.mark.django_db
def test_clinic_template_list_tenant_isolation() -> None:
    """No se filtran plantillas de otro tenant."""
    t1 = TenantFactory()
    t2 = TenantFactory()
    ClinicTemplateFactory(tenant=t2, kind="recipe", is_active=True)  # plantilla de t2

    set_current_tenant(t1)
    set_tenant_context_active(True)

    result = list(clinic_template_list())

    assert len(result) == 0


@pytest.mark.django_db
def test_clinic_template_get_raises_for_other_tenant() -> None:
    """DoesNotExist si el template pertenece a otro tenant."""
    t1 = TenantFactory()
    t2 = TenantFactory()
    tmpl = ClinicTemplateFactory(tenant=t2)

    set_current_tenant(t1)
    set_tenant_context_active(True)

    from apps.clinica.models import ClinicTemplate

    with pytest.raises(ClinicTemplate.DoesNotExist):
        clinic_template_get(template_id=tmpl.id)


# ---------------------------------------------------------------------------
# patient_category_list / patient_category_get
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_patient_category_list_returns_active_only() -> None:
    """Solo categorías activas aparecen en el listado."""
    tenant = TenantFactory()
    set_current_tenant(tenant)
    set_tenant_context_active(True)

    PatientCategoryFactory(tenant=tenant, name="A", is_active=True)
    PatientCategoryFactory(tenant=tenant, name="B", is_active=False)

    result = list(patient_category_list())

    assert len(result) == 1
    assert result[0].name == "A"


@pytest.mark.django_db
def test_patient_category_list_tenant_isolation() -> None:
    """No devuelve categorías de otro tenant."""
    t1, t2 = TenantFactory(), TenantFactory()
    PatientCategoryFactory(tenant=t2, name="Ajeno")

    set_current_tenant(t1)
    set_tenant_context_active(True)

    assert list(patient_category_list()) == []


@pytest.mark.django_db
def test_patient_category_get_other_tenant_raises() -> None:
    """DoesNotExist al intentar acceder a categoría de otro tenant."""
    t1, t2 = TenantFactory(), TenantFactory()
    cat = PatientCategoryFactory(tenant=t2)

    set_current_tenant(t1)
    set_tenant_context_active(True)

    from apps.clinica.models import PatientCategory

    with pytest.raises(PatientCategory.DoesNotExist):
        patient_category_get(category_id=cat.id)


# ---------------------------------------------------------------------------
# doctor_university_list
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_doctor_university_list_returns_only_doctor_universities() -> None:
    """Solo retorna universidades del doctor solicitado."""
    tenant = TenantFactory()
    set_current_tenant(tenant)
    set_tenant_context_active(True)

    doctor1 = DoctorFactory(tenant=tenant)
    doctor2 = DoctorFactory(tenant=tenant)

    from apps.clinica.models import DoctorUniversity
    from tests.factories import UserFactory

    DoctorUniversity.objects.create(
        tenant=tenant,
        created_by=UserFactory(),
        doctor=doctor1,
        name="UNAM",
    )
    DoctorUniversity.objects.create(
        tenant=tenant,
        created_by=UserFactory(),
        doctor=doctor2,
        name="IPN",
    )

    result = list(doctor_university_list(doctor_id=doctor1.id))

    assert len(result) == 1
    assert result[0].name == "UNAM"
