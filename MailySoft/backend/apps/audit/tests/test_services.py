"""
Tests del service audit_record.

Principios clave bajo prueba:
  1. Nunca lanza excepciones al caller (absorbe fallos internos).
  2. Lee ip/user_agent/request_id del thread-local sin acoplar al HTTP.
  3. Guarda metadata exactamente como se pasa (sin PII).
  4. Captura el actor_role como snapshot.

Patrón: AAA. Todos tocan BD → fixture db.
"""

import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from apps.audit.models import ActionType, AuditLog
from apps.audit.services import audit_record
from apps.core.tenant_context import clear_request_context, set_request_context
from tests.factories import TenantFactory, UserFactory


# ===========================================================================
# Camino feliz
# ===========================================================================


class TestAuditRecordCreateLog:
    """audit_record crea un AuditLog con todos los campos correctos."""

    def test_audit_record_creates_log(self, db: None) -> None:
        """audit_record con parámetros válidos persiste un AuditLog en BD."""
        # Arrange
        tenant = TenantFactory()
        actor = UserFactory()
        resource_id = uuid.uuid4()

        # Act
        log = audit_record(
            action=ActionType.PATIENT_CREATE,
            resource_type="Patient",
            actor=actor,
            tenant=tenant,
            resource_id=resource_id,
            resource_repr="García López, Ana",
            description="Paciente creado",
        )

        # Assert — devuelve la instancia y está persistida
        assert log is not None
        assert log.pk is not None
        assert AuditLog.all_objects.filter(pk=log.pk).exists()
        assert log.action == ActionType.PATIENT_CREATE
        assert log.resource_type == "Patient"
        assert log.resource_id == resource_id
        assert log.tenant_id == tenant.id
        assert log.actor_id == actor.id
        assert log.resource_repr == "García López, Ana"
        assert log.description == "Paciente creado"

    def test_audit_record_with_null_tenant_creates_log(self, db: None) -> None:
        """audit_record con tenant=None crea un log global (ej. LOGIN_FAILED)."""
        # Arrange / Act
        log = audit_record(
            action=ActionType.LOGIN_FAILED,
            resource_type="User",
            tenant=None,
            actor=None,
        )

        # Assert
        assert log is not None
        assert log.tenant_id is None
        assert log.actor_id is None
        assert log.action == ActionType.LOGIN_FAILED


# ===========================================================================
# Contexto HTTP desde thread-local
# ===========================================================================


class TestAuditRecordReadsRequestContext:
    """audit_record lee ip/user_agent/request_id del contexto thread-local."""

    def test_audit_record_reads_ip_from_request_context(self, db: None) -> None:
        """El log guarda la ip/user_agent/request_id del contexto HTTP thread-local."""
        # Arrange — poblar el contexto como lo haría TenantAPIView.check_permissions()
        set_request_context(
            ip="192.168.1.100",
            user_agent="Mozilla/5.0 (test)",
            request_id="abc123req",
        )

        try:
            # Act
            log = audit_record(
                action=ActionType.PATIENT_READ,
                resource_type="Patient",
            )

            # Assert
            assert log is not None
            assert log.ip_address == "192.168.1.100"
            assert log.user_agent == "Mozilla/5.0 (test)"
            assert log.request_id == "abc123req"
        finally:
            clear_request_context()

    def test_audit_record_ip_empty_string_stored_as_null(self, db: None) -> None:
        """Una ip vacía en el contexto se convierte a None (GenericIPAddressField)."""
        # Arrange — contexto sin ip
        set_request_context(ip="", user_agent="agent", request_id="req1")

        try:
            # Act
            log = audit_record(
                action=ActionType.PATIENT_READ,
                resource_type="Patient",
            )

            # Assert — GenericIPAddressField requiere None, no cadena vacía
            assert log is not None
            assert log.ip_address is None
        finally:
            clear_request_context()

    def test_audit_record_without_request_context_stores_empty_fields(
        self, db: None
    ) -> None:
        """Sin contexto HTTP (Celery, tests), ip/user_agent/request_id quedan vacíos."""
        # Arrange — sin set_request_context (estado inicial limpio por autouse fixture)

        # Act
        log = audit_record(
            action=ActionType.PATIENT_CREATE,
            resource_type="Patient",
        )

        # Assert
        assert log is not None
        assert log.ip_address is None
        assert log.user_agent == ""
        assert log.request_id == ""


# ===========================================================================
# Absorción de excepciones — NUNCA propaga al caller
# ===========================================================================


class TestAuditRecordNeverRaises:
    """audit_record absorbe cualquier excepción interna y devuelve None."""

    def test_audit_record_never_raises_to_caller_on_db_failure(
        self, db: None
    ) -> None:
        """Si el INSERT falla (mock), audit_record devuelve None sin lanzar.

        Este es el contrato central del service: una falla de auditoría
        NO debe tumbar la operación de negocio que la invocó.
        """
        # Arrange — mockear AuditLog.save para simular fallo de BD
        with patch.object(
            AuditLog,
            "save",
            side_effect=Exception("Fallo simulado de BD"),
        ):
            # Act — llamada que normalmente crearía un log
            result = audit_record(
                action=ActionType.PATIENT_CREATE,
                resource_type="Patient",
            )

        # Assert — devuelve None, NO lanza excepción
        assert result is None

    def test_audit_record_never_raises_on_invalid_action(self, db: None) -> None:
        """Si la acción no es válida a nivel BD, audit_record devuelve None."""
        # Arrange — acción que no existe en ActionType.choices
        # (provocará un error de validación de BD en producción)
        with patch.object(
            AuditLog,
            "save",
            side_effect=ValueError("Valor de acción inválido"),
        ):
            result = audit_record(
                action="INVALID_ACTION_XYZ",
                resource_type="Patient",
            )

        # Assert
        assert result is None


# ===========================================================================
# Metadata
# ===========================================================================


class TestAuditRecordMetadata:
    """audit_record guarda metadata exactamente tal cual se pasa."""

    def test_audit_record_metadata_stored(self, db: None) -> None:
        """La metadata se guarda como JSON sin transformaciones."""
        # Arrange
        metadata: dict[str, Any] = {
            "changed_fields": ["first_name", "phone"],
            "old_status": "SCHEDULED",
            "new_status": "CONFIRMED",
        }

        # Act
        log = audit_record(
            action=ActionType.APPOINTMENT_STATUS,
            resource_type="Appointment",
            metadata=metadata,
        )

        # Assert
        assert log is not None
        assert log.metadata == metadata
        assert log.metadata["changed_fields"] == ["first_name", "phone"]
        assert log.metadata["old_status"] == "SCHEDULED"

    def test_audit_record_metadata_none_stored_as_empty_dict(
        self, db: None
    ) -> None:
        """Si no se pasa metadata (None), se guarda como {} (no null)."""
        # Act
        log = audit_record(
            action=ActionType.PATIENT_READ,
            resource_type="Patient",
            metadata=None,
        )

        # Assert
        assert log is not None
        assert log.metadata == {}

    def test_audit_record_metadata_no_pii_contract(self, db: None) -> None:
        """La metadata puede incluir changed_fields pero NO debe incluir PII directamente.

        Este test verifica que audit_record no agrega PII por su cuenta.
        La responsabilidad de no pasar PII es del caller; audit_record solo almacena.
        (Prueba de regresión: si se detecta PII en metadata en test_integration.py,
        eso es un bug en el caller, no en audit_record).
        """
        # Arrange — metadata limpia sin PII
        metadata_sin_pii = {"changed_fields": ["phone"], "record_number": "EXP-2026-00001"}

        # Act
        log = audit_record(
            action=ActionType.PATIENT_UPDATE,
            resource_type="Patient",
            metadata=metadata_sin_pii,
        )

        # Assert — audit_record no inyecta campos PII extra
        assert log is not None
        assert "curp" not in log.metadata
        assert "password" not in log.metadata
        assert "email" not in log.metadata


# ===========================================================================
# Actor role snapshot
# ===========================================================================


class TestAuditRecordActorRole:
    """audit_record guarda el actor_role como snapshot del momento del evento."""

    def test_audit_record_actor_role_snapshot(self, db: None) -> None:
        """El actor_role se guarda tal cual se pasa (snapshot inmutable)."""
        # Arrange
        actor = UserFactory()

        # Act — registrar con role 'doctor'
        log = audit_record(
            action=ActionType.PATIENT_READ,
            resource_type="Patient",
            actor=actor,
            actor_role="doctor",
        )

        # Assert
        assert log is not None
        assert log.actor_role == "doctor"

    def test_audit_record_actor_role_empty_when_not_provided(
        self, db: None
    ) -> None:
        """Si no se pasa actor_role, el campo queda como cadena vacía."""
        # Act
        log = audit_record(
            action=ActionType.PATIENT_READ,
            resource_type="Patient",
        )

        # Assert
        assert log is not None
        assert log.actor_role == ""
