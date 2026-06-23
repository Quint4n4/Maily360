"""
Tests de patient_set_classification (Fase 1).

Cubre:
- Marcar un paciente como favorito.
- Marcar un paciente como VIP.
- Marcar ambos a la vez.
- Desmarcar (pasar False a un flag que estaba True).
- Llamada con ambos None: no agrega etiquetas ni crea auditoría.
- Cada llamada exitosa crea un registro de auditoría PATIENT_UPDATE.
- Los cambios se persisten correctamente en BD (etiquetas M2M).

Patrón: AAA (Arrange-Act-Assert). Todas tocan BD → fixture db.

NOTA DE MIGRACIÓN (2026-06-23):
  is_favorite e is_vip ya NO son campos BooleanField del modelo Patient.
  Son etiquetas del sistema (PatientCategory kind="favorite"/"vip") en la
  relación M2M `Patient.categories`. Las aserciones verifican la existencia
  de la etiqueta via patient.categories.filter(kind=...).exists().
  El metadata de auditoría ahora es {"classification": ["favorite"|"vip"|...]}.
"""

import pytest

from apps.audit.models import ActionType, AuditLog
from apps.clinica.models import PatientCategory
from apps.pacientes.services import patient_set_classification
from tests.factories import PatientCategoryFactory, PatientFactory, TenantFactory, UserFactory


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _seed_system_categories(tenant: object) -> None:
    """Crea las etiquetas de sistema favorite/VIP para el tenant dado.

    patient_set_classification las auto-siembra via seed_system_patient_categories,
    pero en el Arrange de los tests que parten de un paciente ya clasificado es más
    limpio crearlas explícitamente para controlar el estado inicial.
    """
    for kind in (PatientCategory.Kind.FAVORITE, PatientCategory.Kind.VIP):
        PatientCategory.objects.get_or_create(
            tenant=tenant,  # type: ignore[misc]
            kind=kind,
            deleted_at=None,
            defaults={
                "name": kind.label,
                "created_by": None,
            },
        )


def _is_favorite(patient: object) -> bool:
    """Verifica si el paciente tiene la etiqueta de sistema 'favorite'."""
    return patient.categories.filter(kind=PatientCategory.Kind.FAVORITE).exists()  # type: ignore[union-attr]


def _is_vip(patient: object) -> bool:
    """Verifica si el paciente tiene la etiqueta de sistema 'vip'."""
    return patient.categories.filter(kind=PatientCategory.Kind.VIP).exists()  # type: ignore[union-attr]


# ===========================================================================
# Camino feliz — marcar favorito
# ===========================================================================


class TestSetClassificationFavorite:
    """patient_set_classification: etiqueta kind=favorite."""

    def test_set_favorite_true_marks_patient_as_favorite(self, db: None) -> None:
        """Pasar is_favorite=True agrega la etiqueta 'favorite' al paciente."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()

        # Act
        result = patient_set_classification(patient=patient, user=user, is_favorite=True)

        # Assert — en memoria / relación M2M
        assert _is_favorite(result) is True

    def test_set_favorite_true_persists_to_database(self, db: None) -> None:
        """La etiqueta 'favorite' se persiste en la BD (relación M2M)."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()

        # Act
        patient_set_classification(patient=patient, user=user, is_favorite=True)

        # Assert — verificar directamente la BD usando el QuerySet fresco
        assert patient.categories.filter(kind=PatientCategory.Kind.FAVORITE).exists()

    def test_set_favorite_false_removes_favorite_label(self, db: None) -> None:
        """Pasar is_favorite=False quita la etiqueta 'favorite' del paciente."""
        # Arrange — paciente que ya tiene la etiqueta de favorito
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        _seed_system_categories(tenant)
        fav_cat = PatientCategory.objects.get(tenant=tenant, kind=PatientCategory.Kind.FAVORITE)
        patient.categories.add(fav_cat)
        assert _is_favorite(patient) is True  # precondición

        # Act
        result = patient_set_classification(patient=patient, user=user, is_favorite=False)

        # Assert
        assert _is_favorite(result) is False
        assert patient.categories.filter(kind=PatientCategory.Kind.FAVORITE).exists() is False


# ===========================================================================
# Camino feliz — marcar VIP
# ===========================================================================


class TestSetClassificationVip:
    """patient_set_classification: etiqueta kind=vip."""

    def test_set_vip_true_marks_patient_as_vip(self, db: None) -> None:
        """Pasar is_vip=True agrega la etiqueta 'vip' al paciente."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()

        # Act
        result = patient_set_classification(patient=patient, user=user, is_vip=True)

        # Assert
        assert _is_vip(result) is True

    def test_set_vip_true_persists_to_database(self, db: None) -> None:
        """La etiqueta 'vip' se persiste en la BD (relación M2M)."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()

        # Act
        patient_set_classification(patient=patient, user=user, is_vip=True)

        # Assert
        assert patient.categories.filter(kind=PatientCategory.Kind.VIP).exists()

    def test_set_vip_false_removes_vip_label(self, db: None) -> None:
        """Pasar is_vip=False quita la etiqueta 'vip' del paciente."""
        # Arrange — paciente que ya tiene la etiqueta VIP
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        _seed_system_categories(tenant)
        vip_cat = PatientCategory.objects.get(tenant=tenant, kind=PatientCategory.Kind.VIP)
        patient.categories.add(vip_cat)
        assert _is_vip(patient) is True  # precondición

        # Act
        result = patient_set_classification(patient=patient, user=user, is_vip=False)

        # Assert
        assert _is_vip(result) is False
        assert patient.categories.filter(kind=PatientCategory.Kind.VIP).exists() is False


# ===========================================================================
# Ambos flags a la vez
# ===========================================================================


class TestSetClassificationBothFlags:
    """Se pueden modificar is_favorite e is_vip en la misma llamada."""

    def test_set_both_flags_true_in_single_call(self, db: None) -> None:
        """is_favorite=True e is_vip=True en la misma llamada agrega ambas etiquetas."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()

        # Act
        result = patient_set_classification(
            patient=patient, user=user, is_favorite=True, is_vip=True
        )

        # Assert
        assert _is_favorite(result) is True
        assert _is_vip(result) is True
        assert patient.categories.filter(kind=PatientCategory.Kind.FAVORITE).exists()
        assert patient.categories.filter(kind=PatientCategory.Kind.VIP).exists()

    def test_set_favorite_true_vip_false_in_single_call(self, db: None) -> None:
        """Se puede marcar favorito y desmarcar VIP en la misma llamada."""
        # Arrange — paciente con VIP ya asignado, sin favorito
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        _seed_system_categories(tenant)
        vip_cat = PatientCategory.objects.get(tenant=tenant, kind=PatientCategory.Kind.VIP)
        patient.categories.add(vip_cat)

        # Act
        result = patient_set_classification(
            patient=patient, user=user, is_favorite=True, is_vip=False
        )

        # Assert
        assert _is_favorite(result) is True
        assert _is_vip(result) is False


# ===========================================================================
# Caso: ambos None — no toca BD
# ===========================================================================


class TestSetClassificationBothNone:
    """Cuando is_favorite=None e is_vip=None, no se hace ninguna escritura."""

    def test_both_none_does_not_add_or_remove_labels(self, db: None) -> None:
        """Con ambos None el servicio devuelve el paciente sin modificar etiquetas."""
        # Arrange — paciente con etiqueta favorite ya asignada
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        _seed_system_categories(tenant)
        fav_cat = PatientCategory.objects.get(tenant=tenant, kind=PatientCategory.Kind.FAVORITE)
        patient.categories.add(fav_cat)

        # Act
        result = patient_set_classification(
            patient=patient, user=user, is_favorite=None, is_vip=None
        )

        # Assert — la etiqueta favorite sigue presente, VIP sigue ausente
        assert _is_favorite(result) is True
        assert _is_vip(result) is False

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

    def test_classification_audit_records_kind_in_metadata(self, db: None) -> None:
        """El metadata del AuditLog incluye el kind 'vip' en la clave 'classification'."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()

        # Act
        patient_set_classification(patient=patient, user=user, is_vip=True)

        # Assert — metadata contiene 'vip' en la lista classification
        log = AuditLog.all_objects.filter(
            resource_id=patient.id,
            action=ActionType.PATIENT_UPDATE,
            actor=user,
        ).last()
        assert log is not None
        assert "vip" in log.metadata.get("classification", [])

    def test_both_flags_audit_records_both_kinds(self, db: None) -> None:
        """Cuando se modifican ambos flags, el metadata incluye ambos kinds."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()

        # Act
        patient_set_classification(
            patient=patient, user=user, is_favorite=True, is_vip=True
        )

        # Assert — metadata incluye 'favorite' y 'vip'
        log = AuditLog.all_objects.filter(
            resource_id=patient.id,
            action=ActionType.PATIENT_UPDATE,
            actor=user,
        ).last()
        assert log is not None
        classification = log.metadata.get("classification", [])
        assert "favorite" in classification
        assert "vip" in classification
