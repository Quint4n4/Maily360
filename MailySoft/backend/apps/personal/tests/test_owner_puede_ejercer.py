"""
Tests de regresión — el dueño (y el administrador) pueden ejercer como médicos.

Bug corregido (Fase 0 del plan de planes/entitlements):
    `doctor_create` exigía membership.role == 'doctor'. Como TenantMembership
    tiene UniqueConstraint(user, tenant) —un usuario = UN solo rol por clínica—,
    el dueño de un consultorio individual no podía tener perfil de Doctor. Y sin
    perfil de Doctor no podía:
      - emitir recetas   (Prescription.doctor es obligatorio, PROTECT)
      - recibir citas    (Appointment.doctor es obligatorio, PROTECT)

    Es decir: el consultorio de un solo médico era invendible.

La regla real NO es el rol, es la CÉDULA: quien no la tiene no puede recetar,
sea dueño o médico (NOM-004 / Art. 83 LGS).

Patrón: AAA. factory_boy. Fixtures: db.
"""

from typing import Any
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError

from apps.agenda.models import Appointment
from apps.personal.selectors import doctor_get_for_user
from apps.personal.services import doctor_create
from apps.recetas.services import prescription_create
from tests.factories import (
    PatientFactory,
    TenantFactory,
    TenantMembershipFactory,
)

_ITEMS: list[dict[str, Any]] = [
    {
        "kind": "medicamento",
        "medication_name": "Paracetamol 500 mg",
        "dose": "1 tableta",
        "frequency": "cada 8 horas",
        "route": "oral",
        "duration": "3 días",
        "indication": "",
    }
]


@pytest.mark.django_db
def test_dueno_con_cedula_emite_receta() -> None:
    """El dueño de un consultorio individual puede recetar si tiene cédula."""
    # Arrange — una sola persona: dueña y médica a la vez.
    tenant = TenantFactory()
    membership = TenantMembershipFactory(tenant=tenant, role="owner", is_active=True)
    user = membership.user
    doctor_create(
        tenant=tenant,
        user=user,
        membership=membership,
        cedula_profesional="12345678",
        specialty="Medicina General",
    )
    patient = PatientFactory(tenant=tenant)

    # Act
    with patch("apps.expediente.selectors.vital_signs_latest", return_value=None):
        receta = prescription_create(
            tenant=tenant,
            user=user,
            patient_id=patient.id,
            items_data=_ITEMS,
        )

    # Assert
    assert receta.pk is not None
    assert receta.doctor.membership_id == membership.id


@pytest.mark.django_db
def test_dueno_sin_cedula_no_puede_recetar() -> None:
    """Sin cédula no se receta, aunque sea el dueño. La cédula es la autoridad."""
    # Arrange
    tenant = TenantFactory()
    membership = TenantMembershipFactory(tenant=tenant, role="owner", is_active=True)
    user = membership.user
    doctor_create(tenant=tenant, user=user, membership=membership)
    patient = PatientFactory(tenant=tenant)

    # Act & Assert
    with pytest.raises(ValidationError, match="cédula"):
        prescription_create(
            tenant=tenant,
            user=user,
            patient_id=patient.id,
            items_data=_ITEMS,
        )


@pytest.mark.django_db
def test_dueno_puede_recibir_citas() -> None:
    """El dueño-médico puede ser el médico de una cita.

    Appointment.doctor es obligatorio; antes del arreglo no existía ningún Doctor
    al que agendarle en una clínica de una sola persona.
    """
    # Arrange
    tenant = TenantFactory()
    membership = TenantMembershipFactory(tenant=tenant, role="owner", is_active=True)
    user = membership.user
    doctor = doctor_create(
        tenant=tenant,
        user=user,
        membership=membership,
        cedula_profesional="12345678",
    )

    # Act — el selector que usan agenda y recetas para resolver "el médico del usuario".
    encontrado = doctor_get_for_user(user=user, tenant_id=tenant.id)

    # Assert
    assert encontrado is not None
    assert encontrado.id == doctor.id
    assert Appointment._meta.get_field("doctor").null is False


@pytest.mark.django_db
def test_admin_con_cedula_emite_receta() -> None:
    """El administrador de una clínica chica suele ser profesional también."""
    # Arrange
    tenant = TenantFactory()
    membership = TenantMembershipFactory(tenant=tenant, role="admin", is_active=True)
    user = membership.user
    doctor_create(
        tenant=tenant,
        user=user,
        membership=membership,
        cedula_profesional="87654321",
    )
    patient = PatientFactory(tenant=tenant)

    # Act
    with patch("apps.expediente.selectors.vital_signs_latest", return_value=None):
        receta = prescription_create(
            tenant=tenant,
            user=user,
            patient_id=patient.id,
            items_data=_ITEMS,
        )

    # Assert
    assert receta.pk is not None
