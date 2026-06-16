"""
Tests de patient_set_classification (Fase 1).

Cubre:
- Marcar un paciente como favorito.
- Marcar un paciente como VIP.
- Marcar ambos a la vez.
- Desmarcar (pasar False a un flag que estaba True).
- Llamada con ambos None: no toca BD ni crea auditoría.
- Cada llamada exitosa crea un registro de auditoría PATIENT_UPDATE.
- Los cambios se persisten correctamente en BD.

Patrón: AAA (Arrange-Act-Assert). Todas tocan BD → fixture db.
"""

import pytest

from apps.audit.models import ActionType, AuditLog
from apps.pacientes.models import Patient
from apps.pacientes.services import patient_set_classification
from tests.factories import PatientFactory, TenantFactory, UserFactory


# ===========================================================================
# Camino feliz — marcar favorito
# ===========================================================================


class TestSetClassificationFavorite:
    """patient_set_classification: flag is_favorite."""

    def test_set_favorite_true_marks_patient_as_favorite(self, db: None) -> None:
        """Pasar is_favorite=True marca al paciente como favorito."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_favorite=False)
        user = UserFactory()

        # Act
        result = patient_set_classification(patient=patient, user=user, is_favorite=True)

        # Assert — en memoria
        assert result.is_favorite is True

    def test_set_favorite_true_persists_to_database(self, db: None) -> None:
        """is_favorite=True se guarda en BD."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_favorite=False)
        user = UserFactory()

        # Act
        patient_set_classification(patient=patient, user=user, is_favorite=True)

        # Assert — desde BD
        patient.refresh_from_db()
        assert patient.is_favorite is True

    def test_set_favorite_false_unmarks_patient_as_favorite(self, db: None) -> None:
        """Pasar is_favorite=False desmarca al paciente."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_favorite=True)
        user = UserFactory()

        # Act
        result = patient_set_classification(patient=patient, user=user, is_favorite=False)

        # Assert
        assert result.is_favorite is False
        patient.refresh_from_db()
        assert patient.is_favorite is False


# ===========================================================================
# Camino feliz — marcar VIP
# ===========================================================================


class TestSetClassificationVip:
    """patient_set_classification: flag is_vip."""

    def test_set_vip_true_marks_patient_as_vip(self, db: None) -> None:
        """Pasar is_vip=True marca al paciente como VIP."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_vip=False)
        user = UserFactory()

        # Act
        result = patient_set_classification(patient=patient, user=user, is_vip=True)

        # Assert
        assert result.is_vip is True

    def test_set_vip_true_persists_to_database(self, db: None) -> None:
        """is_vip=True se guarda en BD."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_vip=False)
        user = UserFactory()

        # Act
        patient_set_classification(patient=patient, user=user, is_vip=True)

        # Assert
        patient.refresh_from_db()
        assert patient.is_vip is True

    def test_set_vip_false_unmarks_patient_as_vip(self, db: None) -> None:
        """Pasar is_vip=False desmarca el flag VIP."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_vip=True)
        user = UserFactory()

        # Act
        result = patient_set_classification(patient=patient, user=user, is_vip=False)

        # Assert
        assert result.is_vip is False
        patient.refresh_from_db()
        assert patient.is_vip is False


# ===========================================================================
# Ambos flags a la vez
# ===========================================================================


class TestSetClassificationBothFlags:
    """Se pueden modificar is_favorite e is_vip en la misma llamada."""

    def test_set_both_flags_true_in_single_call(self, db: None) -> None:
        """is_favorite=True e is_vip=True en la misma llamada."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_favorite=False, is_vip=False)
        user = UserFactory()

        # Act
        result = patient_set_classification(
            patient=patient, user=user, is_favorite=True, is_vip=True
        )

        # Assert
        assert result.is_favorite is True
        assert result.is_vip is True
        patient.refresh_from_db()
        assert patient.is_favorite is True
        assert patient.is_vip is True

    def test_set_favorite_true_vip_false_in_single_call(self, db: None) -> None:
        """Se puede marcar favorito y desmarcar VIP en la misma llamada."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_favorite=False, is_vip=True)
        user = UserFactory()

        # Act
        result = patient_set_classification(
            patient=patient, user=user, is_favorite=True, is_vip=False
        )

        # Assert
        assert result.is_favorite is True
        assert result.is_vip is False


# ===========================================================================
# Caso: ambos None — no toca BD
# ===========================================================================


class TestSetClassificationBothNone:
    """Cuando is_favorite=None e is_vip=None, no se hace ninguna escritura."""

    def test_both_none_does_not_change_patient_data(self, db: None) -> None:
        """Con ambos None el servicio devuelve el paciente sin modificar nada."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_favorite=True, is_vip=False)
        user = UserFactory()
        original_updated_at = patient.updated_at

        # Act
        result = patient_set_classification(
            patient=patient, user=user, is_favorite=None, is_vip=None
        )

        # Assert — los flags no cambiaron
        assert result.is_favorite is True
        assert result.is_vip is False

        # Verificar que updated_at no cambió (no se llamó a .save())
        patient.refresh_from_db()
        assert patient.updated_at == original_updated_at

    def test_both_none_does_not_create_audit_record(self, db: None) -> None:
        """Con ambos None no se crea ningún registro de auditoría."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()

        audit_count_before = AuditLog.all_objects.filter(
            resource_id=patient.id, action=ActionType.PATIENT_UPDATE
        ).count()

        # Act
        patient_set_classification(
            patient=patient, user=user, is_favorite=None, is_vip=None
        )

        # Assert — el conteo de auditoría no cambió
        audit_count_after = AuditLog.all_objects.filter(
            resource_id=patient.id, action=ActionType.PATIENT_UPDATE
        ).count()
        assert audit_count_after == audit_count_before


# ===========================================================================
# Auditoría
# ===========================================================================


class TestSetClassificationAudit:
    """Cada llamada exitosa con al menos un flag crea registro PATIENT_UPDATE."""

    def test_classification_creates_audit_record(self, db: None) -> None:
        """Marcar como favorito crea un AuditLog con action=PATIENT_UPDATE."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()

        # Act
        patient_set_classification(patient=patient, user=user, is_favorite=True)

        # Assert — existe al menos un registro de auditoría para este paciente
        log = AuditLog.all_objects.filter(
            resource_id=patient.id,
            action=ActionType.PATIENT_UPDATE,
            actor=user,
        ).first()
        assert log is not None

    def test_classification_audit_records_changed_field_name(self, db: None) -> None:
        """El metadata del AuditLog incluye el nombre del campo modificado."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()

        # Act
        patient_set_classification(patient=patient, user=user, is_vip=True)

        # Assert — metadata contiene 'is_vip'
        log = AuditLog.all_objects.filter(
            resource_id=patient.id,
            action=ActionType.PATIENT_UPDATE,
            actor=user,
        ).last()
        assert log is not None
        assert "is_vip" in log.metadata.get("changed_fields", [])

    def test_both_flags_audit_records_both_field_names(self, db: None) -> None:
        """Cuando se modifican ambos flags, el metadata incluye ambos nombres."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_favorite=False, is_vip=False)
        user = UserFactory()

        # Act
        patient_set_classification(
            patient=patient, user=user, is_favorite=True, is_vip=True
        )

        # Assert — metadata incluye ambos
        log = AuditLog.all_objects.filter(
            resource_id=patient.id,
            action=ActionType.PATIENT_UPDATE,
            actor=user,
        ).last()
        assert log is not None
        changed = log.metadata.get("changed_fields", [])
        assert "is_favorite" in changed
        assert "is_vip" in changed
