"""
Tests de selectors.py de la app tenancy.

Cubre:
- membership_list: devuelve solo membresías del tenant activo, incluyendo inactivas.
  Prueba EXPLÍCITA de que NO se filtran membresías de otra clínica.
- membership_get: happy path, DoesNotExist para id inexistente, DoesNotExist para
  membership de otro tenant (aislamiento multi-tenant: 404, nunca 403).

Patrón: AAA. Todas tocan BD → fixture db.
"""

import uuid

import pytest
from django.core.exceptions import ObjectDoesNotExist

from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from apps.tenancy.models import TenantMembership
from apps.tenancy.selectors import membership_get, membership_list
from tests.factories import TenantFactory, TenantMembershipFactory, UserFactory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _activate_tenant(tenant: "object") -> None:
    """Activa el tenant en el thread-local para que los selectors lo usen."""
    set_current_tenant(tenant)  # type: ignore[arg-type]
    set_tenant_context_active(True)


# ===========================================================================
# membership_list
# ===========================================================================


class TestMembershipList:
    """membership_list() — lista membresías del tenant activo."""

    def test_membership_list_returns_memberships_of_active_tenant(self, db: None) -> None:
        """Solo se devuelven membresías del tenant activo."""
        # Arrange
        tenant = TenantFactory()
        TenantMembershipFactory(tenant=tenant)
        TenantMembershipFactory(tenant=tenant)
        _activate_tenant(tenant)

        # Act
        qs = membership_list()

        # Assert
        assert qs.count() == 2

    def test_membership_list_does_not_return_other_tenant_memberships(self, db: None) -> None:
        """AISLAMIENTO: las membresías de otro tenant NO aparecen en la lista.

        Este es el test crítico de aislamiento multi-tenant para selectors.
        Si falla, hay una fuga de datos entre clínicas.
        """
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()

        # 2 miembros en A, 3 en B
        TenantMembershipFactory.create_batch(2, tenant=tenant_a)
        TenantMembershipFactory.create_batch(3, tenant=tenant_b)

        # Activar tenant A
        _activate_tenant(tenant_a)

        # Act
        qs = membership_list()

        # Assert — solo los 2 de A
        assert qs.count() == 2, (
            f"Fuga cross-tenant: se obtuvieron {qs.count()} membresías en lugar de 2. "
            "membership_list filtra por tenant activo."
        )
        tenant_ids = set(qs.values_list("tenant_id", flat=True))
        assert tenant_ids == {tenant_a.id}

    def test_membership_list_includes_inactive_memberships(self, db: None) -> None:
        """membership_list incluye membresías con is_active=False (bloqueo de cuenta)."""
        # Arrange
        tenant = TenantFactory()
        TenantMembershipFactory(tenant=tenant, is_active=True)
        TenantMembershipFactory(tenant=tenant, is_active=False)
        _activate_tenant(tenant)

        # Act
        qs = membership_list()

        # Assert — ambas, activa e inactiva
        assert qs.count() == 2

    def test_membership_list_prefetches_user(self, db: None) -> None:
        """El queryset tiene select_related('user') para evitar N+1."""
        # Arrange
        tenant = TenantFactory()
        TenantMembershipFactory.create_batch(3, tenant=tenant)
        _activate_tenant(tenant)

        # Act — acceder a membership.user no debe generar queries extra
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        qs = list(membership_list())  # materializar
        with CaptureQueriesContext(connection) as ctx:
            _ = [m.user.email for m in qs]

        # Assert — 0 queries adicionales (user ya cargado)
        assert len(ctx.captured_queries) == 0, (
            f"N+1 detectado: acceder a membership.user disparó {len(ctx.captured_queries)} queries. "
            "membership_list debe usar select_related('user')."
        )

    def test_membership_list_empty_when_no_members(self, db: None) -> None:
        """Lista vacía cuando el tenant no tiene miembros."""
        # Arrange
        tenant = TenantFactory()
        _activate_tenant(tenant)

        # Act
        qs = membership_list()

        # Assert
        assert qs.count() == 0


# ===========================================================================
# membership_get
# ===========================================================================


class TestMembershipGet:
    """membership_get() — recupera una membresía del tenant activo."""

    def test_membership_get_returns_membership_of_active_tenant(self, db: None) -> None:
        """Devuelve la membresía correcta cuando pertenece al tenant activo."""
        # Arrange
        tenant = TenantFactory()
        membership = TenantMembershipFactory(tenant=tenant)
        _activate_tenant(tenant)

        # Act
        result = membership_get(membership_id=membership.id)

        # Assert
        assert result.id == membership.id

    def test_membership_get_raises_does_not_exist_for_unknown_id(self, db: None) -> None:
        """UUID inexistente lanza DoesNotExist (→ 404 en la vista)."""
        # Arrange
        tenant = TenantFactory()
        _activate_tenant(tenant)

        # Act / Assert
        with pytest.raises(TenantMembership.DoesNotExist):
            membership_get(membership_id=uuid.uuid4())

    def test_membership_get_raises_does_not_exist_for_other_tenant(self, db: None) -> None:
        """AISLAMIENTO: membership de otro tenant lanza DoesNotExist, nunca se expone.

        El selector solo busca dentro del tenant activo; una ID de otro tenant
        produce DoesNotExist → la vista devuelve 404, no 403 (sin revelar existencia).
        """
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        membership_b = TenantMembershipFactory(tenant=tenant_b)

        # Activar tenant A
        _activate_tenant(tenant_a)

        # Act / Assert — la membership de B no existe desde la perspectiva de A
        with pytest.raises(TenantMembership.DoesNotExist):
            membership_get(membership_id=membership_b.id)

    def test_membership_get_prefetches_user(self, db: None) -> None:
        """El objeto devuelto tiene el user ya cargado (select_related)."""
        # Arrange
        tenant = TenantFactory()
        membership = TenantMembershipFactory(tenant=tenant)
        _activate_tenant(tenant)

        # Act
        result = membership_get(membership_id=membership.id)

        # Assert — acceder a user no dispara query adicional
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        with CaptureQueriesContext(connection) as ctx:
            _ = result.user.email

        assert len(ctx.captured_queries) == 0, (
            "membership_get debe usar select_related('user') para evitar N+1."
        )
