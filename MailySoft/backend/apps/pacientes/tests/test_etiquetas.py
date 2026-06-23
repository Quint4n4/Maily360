"""
Tests de etiquetas de pacientes (M2M Patient.categories ↔ PatientCategory).

Cubre:
  - Asignación de etiquetas vía patient_update(category_ids=...).
  - Vaciado de etiquetas con lista vacía.
  - Filtro del selector patient_list(category_id=...).
  - Aislamiento cross-tenant: no se asigna una categoría de otra clínica.

Patrón AAA. Se activa el tenant en el thread-local para que TenantManager filtre.
"""

import pytest

from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from apps.pacientes.selectors import patient_list
from apps.pacientes.services import patient_update
from tests.factories import (
    PatientCategoryFactory,
    PatientFactory,
    TenantFactory,
    UserFactory,
)


def _activate(tenant: object) -> None:
    set_current_tenant(tenant)  # type: ignore[arg-type]
    set_tenant_context_active(True)


@pytest.mark.django_db
def test_patient_update_asigna_etiquetas() -> None:
    tenant = TenantFactory()
    _activate(tenant)
    user = UserFactory()
    patient = PatientFactory(tenant=tenant)
    cat_a = PatientCategoryFactory(tenant=tenant, name="Premium")
    cat_b = PatientCategoryFactory(tenant=tenant, name="Pediátrico")

    patient_update(patient=patient, user=user, category_ids=[cat_a.id, cat_b.id])

    assert set(patient.categories.values_list("id", flat=True)) == {cat_a.id, cat_b.id}


@pytest.mark.django_db
def test_patient_update_lista_vacia_quita_etiquetas() -> None:
    tenant = TenantFactory()
    _activate(tenant)
    user = UserFactory()
    patient = PatientFactory(tenant=tenant)
    cat = PatientCategoryFactory(tenant=tenant, name="VIP")
    patient.categories.set([cat])

    patient_update(patient=patient, user=user, category_ids=[])

    assert patient.categories.count() == 0


@pytest.mark.django_db
def test_patient_update_sin_category_ids_no_toca_etiquetas() -> None:
    """Un PATCH que no envía category_ids deja las etiquetas intactas."""
    tenant = TenantFactory()
    _activate(tenant)
    user = UserFactory()
    patient = PatientFactory(tenant=tenant)
    cat = PatientCategoryFactory(tenant=tenant, name="Premium")
    patient.categories.set([cat])

    patient_update(patient=patient, user=user, occupation="Ingeniero")

    assert list(patient.categories.values_list("id", flat=True)) == [cat.id]


@pytest.mark.django_db
def test_patient_list_filtra_por_etiqueta() -> None:
    tenant = TenantFactory()
    _activate(tenant)
    cat = PatientCategoryFactory(tenant=tenant, name="Premium")
    con_etiqueta = PatientFactory(tenant=tenant)
    con_etiqueta.categories.set([cat])
    PatientFactory(tenant=tenant)  # sin etiqueta → no debe aparecer

    result = list(patient_list(category_id=cat.id))

    assert [p.id for p in result] == [con_etiqueta.id]


@pytest.mark.django_db
def test_patient_update_ignora_categoria_de_otro_tenant() -> None:
    """Defensa multi-tenant: una categoría de otra clínica no se asigna."""
    tenant_a = TenantFactory()
    tenant_b = TenantFactory()
    _activate(tenant_a)
    user = UserFactory()
    patient = PatientFactory(tenant=tenant_a)
    cat_ajena = PatientCategoryFactory(tenant=tenant_b, name="Ajena")

    patient_update(patient=patient, user=user, category_ids=[cat_ajena.id])

    assert patient.categories.count() == 0
