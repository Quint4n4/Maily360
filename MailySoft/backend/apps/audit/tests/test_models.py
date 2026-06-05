"""
Tests del modelo AuditLog — foco en inmutabilidad (la garantía más crítica).

La bitácora NOM-024 es append-only: cualquier UPDATE o DELETE viola el
requisito legal. Probamos la doble barrera Python (save/delete overrides).

Patrón: AAA. Todos tocan BD → fixture db.
"""

import pytest

from apps.audit.models import ActionType, AuditLog
from tests.factories import AuditLogFactory, TenantFactory, UserFactory


# ===========================================================================
# Creación exitosa
# ===========================================================================


class TestAuditLogCreate:
    """AuditLog se puede crear (INSERT) sin restricciones."""

    def test_audit_log_create_ok(self, db: None) -> None:
        """Un AuditLog nuevo se persiste correctamente en la BD."""
        # Arrange
        tenant = TenantFactory()
        actor = UserFactory()

        # Act
        log = AuditLogFactory(
            tenant=tenant,
            actor=actor,
            action=ActionType.PATIENT_CREATE,
            resource_type="Patient",
        )

        # Assert — el objeto fue guardado con pk y campos correctos
        assert log.pk is not None
        assert AuditLog.all_objects.filter(pk=log.pk).exists()
        assert log.action == ActionType.PATIENT_CREATE
        assert log.resource_type == "Patient"
        assert log.tenant_id == tenant.id
        assert log.actor_id == actor.id

    def test_tenant_can_be_null(self, db: None) -> None:
        """Un log con tenant=None es válido (ej. LOGIN_FAILED sin tenant resuelto)."""
        # Arrange / Act
        log = AuditLogFactory(
            tenant=None,
            actor=None,
            action=ActionType.LOGIN_FAILED,
            resource_type="User",
        )

        # Assert
        assert log.pk is not None
        assert log.tenant_id is None
        assert log.actor_id is None
        assert AuditLog.all_objects.filter(pk=log.pk).exists()


# ===========================================================================
# Inmutabilidad — UPDATE prohibido
# ===========================================================================


class TestAuditLogImmutabilityUpdate:
    """save() sobre un AuditLog existente siempre lanza RuntimeError."""

    def test_audit_log_update_raises_runtimeerror(self, db: None) -> None:
        """Intentar actualizar un AuditLog existente lanza RuntimeError.

        Este es el contrato central del modelo: una vez INSERT-eado,
        el registro es inmutable a nivel Python.
        """
        # Arrange — crear un log válido
        log = AuditLogFactory()
        original_pk = log.pk

        # Act + Assert — cualquier save() sobre pk existente debe lanzar
        log.description = "intento de modificacion"
        with pytest.raises(RuntimeError, match="append-only"):
            log.save()

        # El registro en BD no cambió
        from_db = AuditLog.all_objects.get(pk=original_pk)
        assert from_db.description != "intento de modificacion"

    def test_audit_log_update_via_save_update_fields_raises_runtimeerror(
        self, db: None
    ) -> None:
        """save(update_fields=...) también está prohibido — la guarda no importa."""
        # Arrange
        log = AuditLogFactory()

        # Act + Assert — RuntimeError incluso con update_fields
        with pytest.raises(RuntimeError, match="append-only"):
            log.save(update_fields=["description"])


# ===========================================================================
# Inmutabilidad — DELETE prohibido
# ===========================================================================


class TestAuditLogImmutabilityDelete:
    """delete() sobre un AuditLog siempre lanza RuntimeError."""

    def test_audit_log_delete_raises_runtimeerror(self, db: None) -> None:
        """Intentar eliminar un AuditLog lanza RuntimeError siempre.

        El registro debe seguir en BD después del intento fallido.
        """
        # Arrange
        log = AuditLogFactory()
        pk = log.pk

        # Act + Assert
        with pytest.raises(RuntimeError, match="append-only"):
            log.delete()

        # El registro aún existe en BD — no fue borrado
        assert AuditLog.all_objects.filter(pk=pk).exists()

    def test_audit_log_queryset_delete_raises_runtimeerror(self, db: None) -> None:
        """FIX-2: QuerySet.delete() masivo está bloqueado a nivel Python.

        Antes el override de delete() solo protegía la instancia; ahora el
        AuditLogQuerySet bloquea también el borrado masivo (.filter().delete()),
        cerrando la brecha. La RLS + REVOKE en PostgreSQL es la segunda barrera.
        """
        from apps.audit.models import AuditLog

        AuditLogFactory()
        with pytest.raises(RuntimeError, match="append-only"):
            AuditLog.all_objects.all().delete()

    def test_audit_log_queryset_update_raises_runtimeerror(self, db: None) -> None:
        """FIX-2: QuerySet.update() masivo está bloqueado a nivel Python."""
        from apps.audit.models import AuditLog

        AuditLogFactory()
        with pytest.raises(RuntimeError, match="append-only"):
            AuditLog.all_objects.all().update(description="hack")


# ===========================================================================
# __str__
# ===========================================================================


class TestAuditLogStr:
    """El __str__ devuelve un formato legible con los campos clave."""

    def test_audit_log_str(self, db: None) -> None:
        """__str__ incluye la acción, resource_type, resource_id y el actor."""
        # Arrange
        log = AuditLogFactory(
            action=ActionType.PATIENT_READ,
            resource_type="Patient",
        )

        # Act
        text = str(log)

        # Assert — deben aparecer los fragmentos clave
        assert "PATIENT_READ" in text
        assert "Patient" in text
        # created_at puede ser "?" si el campo aún no se llenó, pero con factory sí hay fecha
        assert log.action in text

    def test_audit_log_str_with_null_tenant_and_actor(self, db: None) -> None:
        """__str__ con tenant=None y actor=None usa 'global' y 'anon'."""
        # Arrange
        log = AuditLogFactory(tenant=None, actor=None)

        # Act
        text = str(log)

        # Assert
        assert "global" in text
        assert "anon" in text
