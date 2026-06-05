"""
Tests del selector audit_log_list.

Prioridad crítica: verificar que el TenantManager filtra por tenant activo
y que los logs de un tenant NO son visibles desde el contexto del otro.

Patrón: AAA. Todos tocan BD → fixture db.
"""

import datetime
import uuid

import pytest
from freezegun import freeze_time

from apps.audit.models import ActionType, AuditLog
from apps.audit.selectors import audit_log_list
from apps.core.tenant_context import (
    set_current_tenant,
    set_tenant_context_active,
)
from tests.factories import AuditLogFactory, TenantFactory, UserFactory


# ---------------------------------------------------------------------------
# Helper: activar contexto de tenant para que TenantManager filtre
# ---------------------------------------------------------------------------


def _activate_tenant(tenant: object) -> None:
    """Simula el efecto de TenantAPIView: fija el tenant en thread-local."""
    set_current_tenant(tenant)  # type: ignore[arg-type]
    set_tenant_context_active(True)


# ===========================================================================
# Filtros individuales
# ===========================================================================


class TestAuditLogListFilters:
    """audit_log_list filtra correctamente por cada parámetro opcional."""

    def test_audit_log_list_filter_by_action(self, db: None) -> None:
        """Filtrar por action devuelve solo los logs con esa acción."""
        # Arrange
        tenant = TenantFactory()
        _activate_tenant(tenant)
        AuditLogFactory(tenant=tenant, action=ActionType.PATIENT_CREATE)
        AuditLogFactory(tenant=tenant, action=ActionType.PATIENT_UPDATE)
        AuditLogFactory(tenant=tenant, action=ActionType.PATIENT_UPDATE)

        # Act
        qs = audit_log_list(action=ActionType.PATIENT_UPDATE)

        # Assert
        assert qs.count() == 2
        assert all(log.action == ActionType.PATIENT_UPDATE for log in qs)

    def test_audit_log_list_filter_by_resource_type(self, db: None) -> None:
        """Filtrar por resource_type devuelve solo los logs de ese recurso."""
        # Arrange
        tenant = TenantFactory()
        _activate_tenant(tenant)
        AuditLogFactory(tenant=tenant, resource_type="Patient")
        AuditLogFactory(tenant=tenant, resource_type="Appointment")

        # Act
        qs = audit_log_list(resource_type="Patient")

        # Assert
        assert qs.count() == 1
        assert qs.first().resource_type == "Patient"

    def test_audit_log_list_filter_by_resource_id(self, db: None) -> None:
        """Filtrar por resource_id devuelve solo el log con ese UUID."""
        # Arrange
        tenant = TenantFactory()
        _activate_tenant(tenant)
        target_id = uuid.uuid4()
        AuditLogFactory(tenant=tenant, resource_id=target_id)
        AuditLogFactory(tenant=tenant, resource_id=uuid.uuid4())

        # Act
        qs = audit_log_list(resource_id=target_id)

        # Assert
        assert qs.count() == 1
        assert qs.first().resource_id == target_id

    def test_audit_log_list_filter_by_actor_id(self, db: None) -> None:
        """Filtrar por actor_id devuelve solo los logs de ese actor."""
        # Arrange
        tenant = TenantFactory()
        actor_a = UserFactory()
        actor_b = UserFactory()
        _activate_tenant(tenant)
        AuditLogFactory(tenant=tenant, actor=actor_a)
        AuditLogFactory(tenant=tenant, actor=actor_b)
        AuditLogFactory(tenant=tenant, actor=actor_a)

        # Act
        qs = audit_log_list(actor_id=actor_a.id)

        # Assert
        assert qs.count() == 2
        assert all(log.actor_id == actor_a.id for log in qs)

    def test_audit_log_list_filter_by_date_from(self, db: None) -> None:
        """date_from filtra logs creados a partir de esa fecha (inclusive)."""
        # Arrange
        tenant = TenantFactory()
        _activate_tenant(tenant)

        # Crear el log viejo con el reloj congelado en 2020 (created_at = auto_now_add
        # toma la fecha congelada al INSERT). No usamos update(): la bitácora es append-only.
        with freeze_time("2020-01-01"):
            old_log = AuditLogFactory(tenant=tenant, action=ActionType.PATIENT_READ)
        recent_log = AuditLogFactory(tenant=tenant, action=ActionType.PATIENT_UPDATE)

        # Act — solo logs desde 2024 en adelante
        qs = audit_log_list(date_from=datetime.date(2024, 1, 1))

        # Assert — el log viejo no aparece
        pks = list(qs.values_list("pk", flat=True))
        assert recent_log.pk in pks
        assert old_log.pk not in pks

    def test_audit_log_list_filter_by_date_to(self, db: None) -> None:
        """date_to filtra logs creados hasta esa fecha (inclusive)."""
        # Arrange
        tenant = TenantFactory()
        _activate_tenant(tenant)

        with freeze_time("2020-06-15"):
            old_log = AuditLogFactory(tenant=tenant)
        recent_log = AuditLogFactory(tenant=tenant)  # created_at = now (~2026)

        # Act — solo hasta 2021
        qs = audit_log_list(date_to=datetime.date(2021, 1, 1))

        # Assert
        pks = list(qs.values_list("pk", flat=True))
        assert old_log.pk in pks
        assert recent_log.pk not in pks

    def test_audit_log_list_no_filters_returns_all_tenant_logs(
        self, db: None
    ) -> None:
        """Sin filtros devuelve todos los logs del tenant activo."""
        # Arrange
        tenant = TenantFactory()
        _activate_tenant(tenant)
        AuditLogFactory.create_batch(4, tenant=tenant)

        # Act
        qs = audit_log_list()

        # Assert
        assert qs.count() == 4

    def test_audit_log_list_ordered_by_created_at_desc(self, db: None) -> None:
        """Los logs se devuelven ordenados por -created_at (más reciente primero)."""
        # Arrange
        tenant = TenantFactory()
        _activate_tenant(tenant)
        log_a = AuditLogFactory(tenant=tenant)
        log_b = AuditLogFactory(tenant=tenant)
        log_c = AuditLogFactory(tenant=tenant)

        # Act
        qs = list(audit_log_list())

        # Assert — las PKs no determinan el orden; el order_by es -created_at.
        # La factory inserta secuencialmente así que log_c tiene el created_at más alto.
        # Verificamos que el queryset viene en orden descendente de created_at.
        dates = [log.created_at for log in qs]
        assert dates == sorted(dates, reverse=True)


# ===========================================================================
# AISLAMIENTO MULTI-TENANT — el test más crítico
# ===========================================================================


class TestAuditLogTenantIsolation:
    """Los logs de un tenant NO son visibles desde el contexto del otro.

    Este es el requisito de seguridad más crítico de la bitácora.
    Una fuga cross-tenant viola HIPAA/NOM-024 y expone expedientes de otras clínicas.
    """

    def test_audit_log_list_only_current_tenant(self, db: None) -> None:
        """Con contexto del tenant A, los logs del tenant B son invisibles."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()

        # Crear logs en ambos tenants
        log_a1 = AuditLogFactory(tenant=tenant_a, action=ActionType.PATIENT_READ)
        log_a2 = AuditLogFactory(tenant=tenant_a, action=ActionType.PATIENT_CREATE)
        log_b1 = AuditLogFactory(tenant=tenant_b, action=ActionType.APPOINTMENT_CREATE)

        # Act — activar contexto del tenant A
        _activate_tenant(tenant_a)
        qs = audit_log_list()
        pks_visible = set(qs.values_list("pk", flat=True))

        # Assert — logs de A visibles, log de B invisible
        assert log_a1.pk in pks_visible
        assert log_a2.pk in pks_visible
        assert log_b1.pk not in pks_visible

    def test_audit_log_list_tenant_b_does_not_see_tenant_a(
        self, db: None
    ) -> None:
        """Con contexto del tenant B, los logs del tenant A son invisibles (inverso)."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()

        log_a = AuditLogFactory(tenant=tenant_a)
        log_b = AuditLogFactory(tenant=tenant_b)

        # Act — contexto del tenant B
        _activate_tenant(tenant_b)
        qs = audit_log_list()
        pks_visible = set(qs.values_list("pk", flat=True))

        # Assert
        assert log_b.pk in pks_visible
        assert log_a.pk not in pks_visible

    def test_audit_log_list_combined_filters_respect_tenant_isolation(
        self, db: None
    ) -> None:
        """Los filtros por action/resource_type no rompen el aislamiento de tenant."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()

        # Ambos tenants tienen logs del mismo tipo de acción
        log_a = AuditLogFactory(
            tenant=tenant_a, action=ActionType.PATIENT_CREATE
        )
        log_b = AuditLogFactory(
            tenant=tenant_b, action=ActionType.PATIENT_CREATE
        )

        # Act — contexto A, filtrar por la misma acción que tiene B
        _activate_tenant(tenant_a)
        qs = audit_log_list(action=ActionType.PATIENT_CREATE)
        pks_visible = set(qs.values_list("pk", flat=True))

        # Assert — solo el log de A aparece, aunque el filtro sea genérico
        assert log_a.pk in pks_visible
        assert log_b.pk not in pks_visible
