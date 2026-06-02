"""
Tests de services.py de la app pacientes.

Cubre:
- patient_create: consecutivo, unicidad CURP, CURP vacía, created_by, sexo inválido.
- patient_update: campo inmutable, revalidación CURP.
- patient_deactivate: soft-disable.
- _next_record_number: consecutivos únicos en serie.

Patrón: AAA (Arrange-Act-Assert). Todas tocan BD → fixture db.
"""

import datetime
from typing import Any

import pytest
from django.core.exceptions import ValidationError

from apps.core.tenant_context import clear_current_tenant
from apps.pacientes.models import Patient, PatientSequence
from apps.pacientes.services import patient_create, patient_deactivate, patient_update
from tests.factories import PatientFactory, TenantFactory, UserFactory


# ---------------------------------------------------------------------------
# Helpers internos del test
# ---------------------------------------------------------------------------


def _create_patient(tenant: Any, user: Any, **overrides: Any) -> Patient:
    """Llama a patient_create con datos mínimos válidos, aplicando overrides."""
    defaults: dict[str, Any] = {
        "first_name": "Rosa",
        "paternal_surname": "López",
        "maternal_surname": "García",
        "date_of_birth": datetime.date(1990, 5, 15),
        "sex": "F",
        "phone": "5512340001",
        "curp": "",
        "email": "",
        "notes": "",
    }
    defaults.update(overrides)
    return patient_create(tenant=tenant, user=user, **defaults)


# ===========================================================================
# patient_create
# ===========================================================================


class TestPatientCreate:
    """Casos de uso del servicio patient_create."""

    def test_patient_create_generates_sequential_record_number(self, db: None) -> None:
        """El primer paciente recibe EXP-{year}-00001 y el segundo EXP-{year}-00002."""
        # Arrange
        from django.utils import timezone

        tenant = TenantFactory()
        user = UserFactory()
        year = timezone.now().year

        # Act
        patient_a = _create_patient(tenant, user)
        patient_b = _create_patient(tenant, user, phone="5512340002")

        # Assert
        assert patient_a.record_number == f"EXP-{year}-00001"
        assert patient_b.record_number == f"EXP-{year}-00002"

    def test_patient_create_rejects_duplicate_curp_in_same_tenant(self, db: None) -> None:
        """Dos pacientes con la misma CURP en el mismo tenant deben rechazarse."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        curp = "LORG900515MDFLRS09"
        _create_patient(tenant, user, curp=curp, phone="5512340001")

        # Act & Assert
        with pytest.raises(ValidationError, match="CURP"):
            _create_patient(tenant, user, curp=curp, phone="5512340002")

    def test_patient_create_allows_same_curp_in_different_tenant(self, db: None) -> None:
        """La misma CURP puede existir en tenants distintos (unicidad es por tenant)."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user = UserFactory()
        curp = "LORG900515MDFLRS09"

        # Act — no debe lanzar
        patient_a = _create_patient(tenant_a, user, curp=curp, phone="5512340001")
        patient_b = _create_patient(tenant_b, user, curp=curp, phone="5512340002")

        # Assert
        assert patient_a.curp == curp
        assert patient_b.curp == curp
        assert patient_a.tenant_id != patient_b.tenant_id

    def test_patient_create_sets_created_by(self, db: None) -> None:
        """El campo created_by debe quedar ligado al usuario que hace la llamada."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act
        patient = _create_patient(tenant, user)

        # Assert
        assert patient.created_by_id == user.id

    def test_patient_create_empty_curp_does_not_collide(self, db: None) -> None:
        """Dos pacientes con curp='' (vacío) deben crearse sin error de unicidad."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act — ambos con curp vacío; no debe lanzar
        p1 = _create_patient(tenant, user, curp="", phone="5512340001")
        p2 = _create_patient(tenant, user, curp="", phone="5512340002")

        # Assert
        assert p1.curp == ""
        assert p2.curp == ""
        assert Patient.all_objects.filter(tenant=tenant).count() == 2

    def test_patient_create_invalid_sex_raises_validation_error(self, db: None) -> None:
        """Un valor de sexo que no sea M/F/X debe lanzar ValidationError inmediatamente."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act & Assert
        with pytest.raises(ValidationError, match="[Ss]exo"):
            _create_patient(tenant, user, sex="Z")

    def test_patient_create_persists_all_fields(self, db: None) -> None:
        """Todos los campos opcionales deben persistirse correctamente."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act
        patient = _create_patient(
            tenant,
            user,
            first_name="Juan",
            paternal_surname="Pérez",
            maternal_surname="Soto",
            date_of_birth=datetime.date(1985, 3, 20),
            sex="M",
            phone="5512340099",
            curp="PESJ850320HDFRTN09",
            email="juan@example.com",
            notes="Alérgico a penicilina",
        )

        # Assert — refrescar desde BD para confirmar persistencia
        patient.refresh_from_db()
        assert patient.first_name == "Juan"
        assert patient.paternal_surname == "Pérez"
        assert patient.maternal_surname == "Soto"
        assert patient.sex == "M"
        assert patient.curp == "PESJ850320HDFRTN09"
        assert patient.email == "juan@example.com"
        assert patient.notes == "Alérgico a penicilina"
        assert patient.is_active is True


# ===========================================================================
# patient_update
# ===========================================================================


class TestPatientUpdate:
    """Casos de uso del servicio patient_update."""

    def test_patient_update_cannot_change_record_number(self, db: None) -> None:
        """Intentar cambiar record_number debe lanzar ValidationError."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        patient = _create_patient(tenant, user)
        original_record = patient.record_number

        # Act & Assert
        with pytest.raises(ValidationError, match="record_number"):
            patient_update(patient=patient, user=user, record_number="OTRO-001")

        # El record_number no debe haber cambiado en memoria ni en BD
        patient.refresh_from_db()
        assert patient.record_number == original_record

    def test_patient_update_cannot_change_tenant(self, db: None) -> None:
        """Intentar cambiar tenant debe lanzar ValidationError."""
        # Arrange
        tenant = TenantFactory()
        other_tenant = TenantFactory()
        user = UserFactory()
        patient = _create_patient(tenant, user)

        # Act & Assert
        with pytest.raises(ValidationError, match="tenant"):
            patient_update(patient=patient, user=user, tenant=other_tenant)

    def test_patient_update_revalidates_curp_uniqueness(self, db: None) -> None:
        """Cambiar la CURP a una ya usada por otro paciente en el tenant debe fallar."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        existing = _create_patient(tenant, user, curp="AAAB900101HDFRRR09", phone="5512340001")
        patient_to_update = _create_patient(tenant, user, curp="", phone="5512340002")

        # Act & Assert — intentar poner la CURP del primer paciente en el segundo
        with pytest.raises(ValidationError, match="CURP"):
            patient_update(patient=patient_to_update, user=user, curp=existing.curp)

    def test_patient_update_allows_same_curp_on_same_patient(self, db: None) -> None:
        """Actualizar un paciente con su propia CURP actual no debe lanzar error."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        patient = _create_patient(tenant, user, curp="AAAB900101HDFRRR09")

        # Act — no debe lanzar
        updated = patient_update(patient=patient, user=user, curp="AAAB900101HDFRRR09")

        # Assert
        assert updated.curp == "AAAB900101HDFRRR09"

    def test_patient_update_applies_allowed_fields(self, db: None) -> None:
        """Campos permitidos deben actualizarse y persistirse en BD."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        patient = _create_patient(tenant, user, phone="5500000001", notes="")

        # Act
        updated = patient_update(patient=patient, user=user, phone="5599999999", notes="Nueva nota")

        # Assert
        updated.refresh_from_db()
        assert updated.phone == "5599999999"
        assert updated.notes == "Nueva nota"

    def test_patient_update_invalid_sex_raises_validation_error(self, db: None) -> None:
        """Cambiar sex a un valor inválido debe lanzar ValidationError."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        patient = _create_patient(tenant, user)

        # Act & Assert
        with pytest.raises(ValidationError, match="[Ss]exo"):
            patient_update(patient=patient, user=user, sex="Q")


# ===========================================================================
# patient_deactivate
# ===========================================================================


class TestPatientDeactivate:
    """Casos de uso del servicio patient_deactivate."""

    def test_patient_deactivate_sets_inactive_not_deleted(self, db: None) -> None:
        """Desactivar un paciente pone is_active=False pero NO borra el registro."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        patient = _create_patient(tenant, user)
        patient_id = patient.id

        # Act
        deactivated = patient_deactivate(patient=patient, _user=user)

        # Assert — is_active=False
        assert deactivated.is_active is False

        # El registro sigue existiendo en all_objects (no se borró lógicamente)
        assert Patient.all_objects.filter(id=patient_id).exists()

        # deleted_at sigue siendo None (deactivate NO es soft-delete)
        deactivated.refresh_from_db()
        assert deactivated.deleted_at is None

    def test_patient_deactivate_is_idempotent(self, db: None) -> None:
        """Desactivar un paciente ya inactivo no debe lanzar error."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        patient = _create_patient(tenant, user)
        patient_deactivate(patient=patient, _user=user)

        # Act — segunda llamada, no debe lanzar
        patient_deactivate(patient=patient, _user=user)

        # Assert
        patient.refresh_from_db()
        assert patient.is_active is False


# ===========================================================================
# Consecutivo: unicidad en serie
# ===========================================================================


class TestConsecutivoRecordNumber:
    """El consecutivo de expedientes debe ser único y sin huecos dentro de un tenant."""

    def test_record_numbers_are_unique_and_sequential_in_series(self, db: None) -> None:
        """Crear N pacientes en serie produce N record_number distintos y consecutivos."""
        # Arrange
        from django.utils import timezone

        tenant = TenantFactory()
        user = UserFactory()
        n = 10
        year = timezone.now().year

        # Act
        patients = [_create_patient(tenant, user, phone=f"551234{i:04d}") for i in range(n)]

        # Assert — todos los record_number son distintos
        record_numbers = [p.record_number for p in patients]
        assert len(set(record_numbers)) == n, "Se encontraron record_numbers duplicados"

        # Assert — son consecutivos a partir de 1
        expected = [f"EXP-{year}-{i:05d}" for i in range(1, n + 1)]
        assert record_numbers == expected

    def test_sequence_is_independent_per_tenant(self, db: None) -> None:
        """El consecutivo de cada tenant arranca en 1 de forma independiente."""
        # Arrange
        from django.utils import timezone

        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user = UserFactory()
        year = timezone.now().year

        # Act
        pa = _create_patient(tenant_a, user, phone="5512340001")
        pb = _create_patient(tenant_b, user, phone="5512340002")

        # Assert — ambos son EXP-{year}-00001 (secuencia independiente)
        assert pa.record_number == f"EXP-{year}-00001"
        assert pb.record_number == f"EXP-{year}-00001"

    def test_patient_sequence_row_created_on_first_patient(self, db: None) -> None:
        """Crear el primer paciente de un tenant debe crear su PatientSequence."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Pre-condition: no existe secuencia aún
        assert not PatientSequence.all_objects.filter(tenant=tenant).exists()

        # Act
        _create_patient(tenant, user)

        # Assert
        seq = PatientSequence.all_objects.get(tenant=tenant)
        assert seq.last_number == 1
