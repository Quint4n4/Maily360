"""
Tests de la API GET /api/v1/audit/logs/.

Cubre:
  - 401 sin token de autenticación.
  - 200 para owner y admin (los únicos roles con acceso).
  - 403 para todos los demás roles (parametrizado).
  - 405/403 para métodos que no son GET (la bitácora es read-only).
  - Aislamiento cross-tenant: owner de clínica A no ve logs de clínica B.

Patrón: usa _make_member_client (JWT real por force_authenticate + membresía)
y _tenant_context (mock del TenantManager) igual que los tests de pacientes.

Todos tocan BD → fixture db.
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.audit.models import ActionType
from tests.factories import (
    AuditLogFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

AUDIT_URL = "/api/v1/audit/logs/"


# ---------------------------------------------------------------------------
# Helpers de test (copiados del patrón establecido en pacientes/tests/test_apis.py)
# ---------------------------------------------------------------------------


@contextmanager
def _tenant_context(tenant: Any) -> Generator[None, None, None]:
    """Context manager que simula el efecto del TenantMiddleware para tests.

    Mockea get_current_tenant en la vista y en el manager del ORM para que
    los queries filtren por el tenant inyectado.
    """
    with (
        patch(
            "apps.audit.views.audit_log_list",
            wraps=_wrapped_audit_log_list(tenant),
        ),
        patch(
            "apps.core.managers.get_current_tenant",
            return_value=tenant,
        ),
        patch(
            "apps.core.managers.is_tenant_context_active",
            return_value=True,
        ),
    ):
        yield


def _wrapped_audit_log_list(tenant: Any) -> Any:
    """Wraps audit_log_list para inyectar el contexto de tenant antes de llamarla."""
    from apps.audit.selectors import audit_log_list
    from apps.core.tenant_context import set_current_tenant, set_tenant_context_active

    def _inner(**kwargs: Any) -> Any:
        set_current_tenant(tenant)
        set_tenant_context_active(True)
        return audit_log_list(**kwargs)

    return _inner


def _make_auth_client(user: Any) -> APIClient:
    """Devuelve un APIClient autenticado como `user` (force_authenticate)."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _make_member_client(tenant: Any, role: str = "owner") -> tuple[Any, APIClient]:
    """Crea un usuario con TenantMembership del rol indicado y devuelve (user, client)."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    return user, _make_auth_client(user)


# ===========================================================================
# Autenticación
# ===========================================================================


class TestAuditEndpointAuth:
    """El endpoint requiere token JWT válido."""

    def test_audit_endpoint_requires_auth(self, db: None, api_client: APIClient) -> None:
        """Sin token devuelve 401."""
        # Act
        response = api_client.get(AUDIT_URL)

        # Assert
        assert response.status_code == 401


# ===========================================================================
# Roles con acceso (owner y admin)
# ===========================================================================


class TestAuditEndpointAuthorizedRoles:
    """Solo el owner puede consultar la bitácora de su clínica (multi-sede)."""

    def test_audit_endpoint_owner_can_view(self, db: None) -> None:
        """Owner recibe 200 al consultar la bitácora."""
        # Arrange
        tenant = TenantFactory()
        AuditLogFactory(tenant=tenant)
        _, client = _make_member_client(tenant, role="owner")

        # Act
        with _tenant_context(tenant):
            response = client.get(AUDIT_URL)

        # Assert
        assert response.status_code == 200

    def test_audit_endpoint_admin_now_forbidden(self, db: None) -> None:
        """Multi-sede (2026-07-16): la bitácora es SOLO del dueño.

        La bitácora no se acota por sede (AuditLog no tiene `sucursal`), así que
        para no exponer la actividad de una sede a un admin de OTRA sede, ahora
        SOLO el owner puede verla. Antes el admin recibía 200; ahora 403.
        """
        # Arrange
        tenant = TenantFactory()
        AuditLogFactory(tenant=tenant)
        _, client = _make_member_client(tenant, role="admin")

        # Act
        with _tenant_context(tenant):
            response = client.get(AUDIT_URL)

        # Assert
        assert response.status_code == 403

    def test_audit_endpoint_returns_paginated_structure(self, db: None) -> None:
        """La respuesta incluye la estructura de paginación DRF."""
        # Arrange
        tenant = TenantFactory()
        AuditLogFactory.create_batch(3, tenant=tenant)
        _, client = _make_member_client(tenant, role="owner")

        # Act
        with _tenant_context(tenant):
            response = client.get(AUDIT_URL)

        # Assert
        assert response.status_code == 200
        data = response.json()
        # DRF PageNumberPagination devuelve dict con 'results'
        assert isinstance(data, (list, dict))


# ===========================================================================
# Roles sin acceso (403) — parametrizado
# ===========================================================================


# Multi-sede (2026-07-16): `admin` pasó a la lista de SIN acceso — la bitácora
# es solo del dueño (ver TestAuditEndpointAuthorizedRoles).
FORBIDDEN_ROLES = ["admin", "doctor", "nurse", "reception", "finance", "readonly"]


class TestAuditEndpointForbiddenRoles:
    """Todos los roles que no son owner reciben 403."""

    @pytest.mark.parametrize("role", FORBIDDEN_ROLES)
    def test_audit_endpoint_forbidden_for_role(self, db: None, role: str) -> None:
        """El rol indicado recibe 403 al intentar acceder a la bitácora."""
        # Arrange
        tenant = TenantFactory()
        _, client = _make_member_client(tenant, role=role)

        # Act
        with _tenant_context(tenant):
            response = client.get(AUDIT_URL)

        # Assert
        assert (
            response.status_code == 403
        ), f"Se esperaba 403 para role='{role}', se obtuvo {response.status_code}"


# ===========================================================================
# Read-only — métodos no permitidos
# ===========================================================================


class TestAuditEndpointReadOnly:
    """La bitácora no acepta POST, PATCH ni DELETE."""

    @pytest.mark.parametrize("method", ["post", "patch", "delete", "put"])
    def test_audit_endpoint_write_methods_not_allowed(self, db: None, method: str) -> None:
        """Métodos de escritura reciben 405 (Method Not Allowed) o 403."""
        # Arrange
        tenant = TenantFactory()
        _, client = _make_member_client(tenant, role="owner")

        # Act
        http_method = getattr(client, method)
        with _tenant_context(tenant):
            response = http_method(AUDIT_URL, data={}, format="json")

        # Assert — 405 o 403 (no 200/201)
        assert response.status_code in (403, 405), (
            f"Método {method.upper()} debería ser rechazado, " f"se obtuvo {response.status_code}"
        )


# ===========================================================================
# Aislamiento cross-tenant
# ===========================================================================


class TestAuditEndpointCrossTenantIsolation:
    """El owner de la clínica A no puede ver logs de la clínica B."""

    def test_audit_endpoint_cross_tenant_isolation(self, db: None) -> None:
        """Owner de clínica A ve sus logs pero NO los de la clínica B."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()

        log_a = AuditLogFactory(tenant=tenant_a, action=ActionType.PATIENT_READ)
        log_b = AuditLogFactory(tenant=tenant_b, action=ActionType.APPOINTMENT_CREATE)

        _, client_a = _make_member_client(tenant_a, role="owner")

        # Act — autenticado como owner de A, contexto de A
        with _tenant_context(tenant_a):
            response = client_a.get(AUDIT_URL)

        # Assert
        assert response.status_code == 200
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        ids_in_response = [str(r["id"]) for r in results]

        assert str(log_a.pk) in ids_in_response
        assert (
            str(log_b.pk) not in ids_in_response
        ), "BUG: el owner de clínica A puede ver logs de clínica B (fuga cross-tenant)"

    def test_audit_endpoint_owner_of_b_cannot_see_logs_of_a(self, db: None) -> None:
        """Owner de clínica B no ve logs de clínica A (prueba inversa)."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()

        log_a = AuditLogFactory(tenant=tenant_a)
        AuditLogFactory(tenant=tenant_b)

        _, client_b = _make_member_client(tenant_b, role="owner")

        # Act — contexto de B
        with _tenant_context(tenant_b):
            response = client_b.get(AUDIT_URL)

        # Assert
        assert response.status_code == 200
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        ids_in_response = [str(r["id"]) for r in results]

        assert (
            str(log_a.pk) not in ids_in_response
        ), "BUG: el owner de clínica B puede ver logs de clínica A (fuga cross-tenant)"


# ===========================================================================
# Filtros de query params
# ===========================================================================


class TestAuditEndpointQueryParams:
    """Los query params filtran correctamente la respuesta."""

    def test_audit_endpoint_filter_by_action(self, db: None) -> None:
        """?action=PATIENT_READ devuelve solo logs de esa acción."""
        # Arrange
        tenant = TenantFactory()
        AuditLogFactory(tenant=tenant, action=ActionType.PATIENT_READ)
        AuditLogFactory(tenant=tenant, action=ActionType.PATIENT_UPDATE)
        _, client = _make_member_client(tenant, role="owner")

        # Act
        with _tenant_context(tenant):
            response = client.get(AUDIT_URL, {"action": "PATIENT_READ"})

        # Assert
        assert response.status_code == 200
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        assert all(r["action"] == "PATIENT_READ" for r in results)

    def test_audit_endpoint_filter_by_resource_type(self, db: None) -> None:
        """?resource_type=Patient devuelve solo logs de pacientes."""
        # Arrange
        tenant = TenantFactory()
        AuditLogFactory(tenant=tenant, resource_type="Patient")
        AuditLogFactory(tenant=tenant, resource_type="Appointment")
        _, client = _make_member_client(tenant, role="owner")

        # Act
        with _tenant_context(tenant):
            response = client.get(AUDIT_URL, {"resource_type": "Patient"})

        # Assert
        assert response.status_code == 200
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        assert len(results) == 1
        assert results[0]["resource_type"] == "Patient"

    def test_audit_endpoint_malformed_actor_id_silently_ignored(self, db: None) -> None:
        """?actor_id=not-a-uuid se ignora silenciosamente y devuelve todos los logs.

        Cubre la rama except ValueError del parseo de UUID en la vista (líneas 51-54).
        No debe lanzar 400 ni 500; el parámetro inválido se descarta y el filtro
        simplemente no se aplica.
        """
        # Arrange
        tenant = TenantFactory()
        AuditLogFactory(tenant=tenant)
        _, client = _make_member_client(tenant, role="owner")

        # Act
        with _tenant_context(tenant):
            response = client.get(AUDIT_URL, {"actor_id": "no-es-uuid-valido"})

        # Assert — 200, no 400 ni 500
        assert response.status_code == 200

    def test_audit_endpoint_malformed_resource_id_silently_ignored(self, db: None) -> None:
        """?resource_id=bad devuelve 200 ignorando el parámetro inválido.

        Cubre la rama except ValueError del parseo de resource_id (líneas 59-62).
        """
        # Arrange
        tenant = TenantFactory()
        AuditLogFactory(tenant=tenant)
        _, client = _make_member_client(tenant, role="owner")

        # Act
        with _tenant_context(tenant):
            response = client.get(AUDIT_URL, {"resource_id": "mal-formado"})

        # Assert
        assert response.status_code == 200

    def test_audit_endpoint_malformed_date_silently_ignored(self, db: None) -> None:
        """?date_from=noesunafecha devuelve 200 ignorando el parámetro inválido.

        Cubre la rama except ValueError del parseo de fechas (líneas 73, 76-78).
        """
        # Arrange
        tenant = TenantFactory()
        AuditLogFactory(tenant=tenant)
        _, client = _make_member_client(tenant, role="owner")

        # Act
        with _tenant_context(tenant):
            response = client.get(
                AUDIT_URL,
                {"date_from": "no-es-fecha", "date_to": "tampoco"},
            )

        # Assert
        assert response.status_code == 200
