"""
Tests del endpoint GET /api/v1/plataforma/auditoria/ (panel interno de plataforma).

Valida:
  - Permisos: clinic_member y sales → 403; engineering y super_admin → 200.
  - Cross-tenant: super_admin ve logs de más de un tenant en una sola respuesta.
  - Filtros: tenant_id, action, date_from/date_to, search.
  - Paginación: respeta page_size con tope de 100 (max_page_size).
  - Métodos no permitidos (POST/PUT/DELETE) → 405.
  - Contrato de campos de salida exacto (sin fugas ni faltantes).

Fixtures locales (no compartidas vía conftest.py): replican exactamente las
definidas en apps/plataforma/tests/test_security.py, siguiendo la misma
convención de ese archivo.
"""

import pytest
from django.urls import reverse
from freezegun import freeze_time
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import ActionType
from tests.factories import (
    AuditLogFactory,
    PlatformStaffFactory,
    TenantFactory,
    UserFactory,
)


# ---------------------------------------------------------------------------
# Fixtures específicas de plataforma (replicadas de test_security.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def super_admin(db):
    """Usuario de plataforma con rol super_admin."""
    return UserFactory(
        is_platform_staff=True,
        is_staff=True,
        platform_role="super_admin",
    )


@pytest.fixture
def sales_user(db):
    """Usuario de plataforma con rol sales."""
    return UserFactory(
        is_platform_staff=True,
        platform_role="sales",
    )


@pytest.fixture
def engineering_user(db):
    """Usuario de plataforma con rol engineering (PlatformStaffFactory usa este rol por defecto)."""
    return PlatformStaffFactory()  # platform_role="engineering"


@pytest.fixture
def clinic_member(db):
    """Usuario miembro de una clínica SIN is_platform_staff."""
    return UserFactory(is_platform_staff=False)


# ---------------------------------------------------------------------------
# Permisos
# ---------------------------------------------------------------------------


def test_clinic_member_is_rejected(db, clinic_member) -> None:
    """Un usuario sin is_platform_staff recibe 403."""
    client = APIClient()
    client.force_authenticate(user=clinic_member)

    response = client.get(reverse("platform-auditoria-list"))

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_sales_is_rejected(db, sales_user) -> None:
    """sales queda fuera de la auditoría: 403."""
    client = APIClient()
    client.force_authenticate(user=sales_user)

    response = client.get(reverse("platform-auditoria-list"))

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_engineering_can_read(db, engineering_user) -> None:
    """engineering sí puede ver la bitácora."""
    client = APIClient()
    client.force_authenticate(user=engineering_user)

    response = client.get(reverse("platform-auditoria-list"))

    assert response.status_code == status.HTTP_200_OK


def test_super_admin_can_read(db, super_admin) -> None:
    """super_admin sí puede ver la bitácora."""
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse("platform-auditoria-list"))

    assert response.status_code == status.HTTP_200_OK


def test_anonymous_user_is_rejected(db) -> None:
    """Sin JWT → 401."""
    client = APIClient()
    response = client.get(reverse("platform-auditoria-list"))
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


# ---------------------------------------------------------------------------
# Cross-tenant
# ---------------------------------------------------------------------------


def test_super_admin_sees_logs_from_multiple_tenants(db, super_admin) -> None:
    """Un solo GET debe traer eventos de dos tenants distintos."""
    tenant_a = TenantFactory(name="Clínica Alpha", slug="alpha-audit")
    tenant_b = TenantFactory(name="Clínica Beta", slug="beta-audit")
    log_a = AuditLogFactory(tenant=tenant_a, description="Evento en Alpha")
    log_b = AuditLogFactory(tenant=tenant_b, description="Evento en Beta")

    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse("platform-auditoria-list"))

    assert response.status_code == status.HTTP_200_OK
    ids = {item["id"] for item in response.data["results"]}
    assert str(log_a.pk) in ids
    assert str(log_b.pk) in ids


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------


def test_filter_by_tenant_id(db, super_admin) -> None:
    """El filtro tenant_id solo trae logs de ese tenant."""
    tenant_a = TenantFactory()
    tenant_b = TenantFactory()
    log_a = AuditLogFactory(tenant=tenant_a)
    AuditLogFactory(tenant=tenant_b)

    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(
        reverse("platform-auditoria-list"), {"tenant_id": str(tenant_a.id)}
    )

    assert response.status_code == status.HTTP_200_OK
    ids = {item["id"] for item in response.data["results"]}
    assert ids == {str(log_a.pk)}


def test_filter_by_action(db, super_admin) -> None:
    """El filtro action solo trae logs con esa action exacta."""
    tenant = TenantFactory()
    log_create = AuditLogFactory(tenant=tenant, action=ActionType.PATIENT_CREATE)
    AuditLogFactory(tenant=tenant, action=ActionType.PATIENT_READ)

    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(
        reverse("platform-auditoria-list"), {"action": ActionType.PATIENT_CREATE}
    )

    assert response.status_code == status.HTTP_200_OK
    ids = {item["id"] for item in response.data["results"]}
    assert ids == {str(log_create.pk)}


def test_filter_by_date_range_excludes_out_of_range_logs(db, super_admin) -> None:
    """date_from/date_to excluyen logs creados fuera del rango.

    created_at usa auto_now_add=True (BaseModel), así que se fija con
    freeze_time en el momento de la creación (igual que apps/audit/tests/test_selectors.py).
    """
    tenant = TenantFactory()

    with freeze_time("2020-01-01T00:00:00Z"):
        old_log = AuditLogFactory(tenant=tenant, description="Viejo")

    with freeze_time("2026-01-01T00:00:00Z"):
        recent_log = AuditLogFactory(tenant=tenant, description="Reciente")

    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(
        reverse("platform-auditoria-list"),
        {
            "date_from": "2025-01-01T00:00:00Z",
            "date_to": "2026-12-31T23:59:59Z",
        },
    )

    assert response.status_code == status.HTTP_200_OK
    ids = {item["id"] for item in response.data["results"]}
    assert str(recent_log.pk) in ids
    assert str(old_log.pk) not in ids


def test_filter_by_search_matches_description(db, super_admin) -> None:
    """search hace icontains sobre description."""
    tenant = TenantFactory()
    log_match = AuditLogFactory(tenant=tenant, description="Paciente reactivado manualmente")
    AuditLogFactory(tenant=tenant, description="Otro evento cualquiera")

    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse("platform-auditoria-list"), {"search": "reactivado"})

    assert response.status_code == status.HTTP_200_OK
    ids = {item["id"] for item in response.data["results"]}
    assert ids == {str(log_match.pk)}


def test_filter_by_search_matches_actor_email(db, super_admin) -> None:
    """search hace icontains sobre el email del actor."""
    tenant = TenantFactory()
    actor = UserFactory(email="doctora.especial@maily.test")
    log_match = AuditLogFactory(tenant=tenant, actor=actor, description="")
    AuditLogFactory(tenant=tenant, description="")

    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(
        reverse("platform-auditoria-list"), {"search": "doctora.especial"}
    )

    assert response.status_code == status.HTTP_200_OK
    ids = {item["id"] for item in response.data["results"]}
    assert ids == {str(log_match.pk)}


def test_filter_invalid_tenant_id_returns_400(db, super_admin) -> None:
    """Un tenant_id con formato inválido devuelve 400, no 500."""
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(
        reverse("platform-auditoria-list"), {"tenant_id": "no-es-un-uuid"}
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_filter_invalid_date_returns_400(db, super_admin) -> None:
    """Un date_from con formato inválido devuelve 400, no 500."""
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(
        reverse("platform-auditoria-list"), {"date_from": "no-es-una-fecha"}
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# Paginación
# ---------------------------------------------------------------------------


def test_page_size_is_capped_at_max(db, super_admin) -> None:
    """page_size=500 no debe servir más de 100 resultados (max_page_size)."""
    tenant = TenantFactory()
    AuditLogFactory.create_batch(120, tenant=tenant)

    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(
        reverse("platform-auditoria-list"), {"page_size": 500}
    )

    assert response.status_code == status.HTTP_200_OK
    assert len(response.data["results"]) == 100


# ---------------------------------------------------------------------------
# Métodos no permitidos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("http_method", ["post", "put", "delete"])
def test_write_methods_are_not_allowed(db, super_admin, http_method) -> None:
    """AuditLog es append-only: el endpoint solo expone GET."""
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = getattr(client, http_method)(reverse("platform-auditoria-list"))

    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


# ---------------------------------------------------------------------------
# Contrato de salida
# ---------------------------------------------------------------------------


def test_output_contract_has_exact_fields(db, super_admin) -> None:
    """La respuesta no expone campos fuera del contrato fijo con el frontend."""
    tenant = TenantFactory()
    AuditLogFactory(tenant=tenant, description="Para verificar contrato")

    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse("platform-auditoria-list"))

    assert response.status_code == status.HTTP_200_OK
    assert response.data["results"], "Debe haber al menos un resultado para verificar el contrato"

    expected_fields = {
        "id",
        "created_at",
        "action",
        "action_display",
        "actor_email",
        "actor_role",
        "tenant_id",
        "tenant_name",
        "resource_type",
        "resource_id",
        "description",
        "ip_address",
        "metadata",
    }
    assert set(response.data["results"][0].keys()) == expected_fields


def test_output_actor_email_is_none_when_actor_is_null(db, super_admin) -> None:
    """Eventos sin actor (anónimos) devuelven actor_email=None sin explotar."""
    tenant = TenantFactory()
    log = AuditLogFactory(tenant=tenant, actor=None, description="Login fallido")

    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse("platform-auditoria-list"))

    assert response.status_code == status.HTTP_200_OK
    item = next(i for i in response.data["results"] if i["id"] == str(log.pk))
    assert item["actor_email"] is None


def test_output_tenant_name_is_none_for_global_event(db, super_admin) -> None:
    """Eventos globales (tenant=None) devuelven tenant_name=None sin explotar."""
    log = AuditLogFactory(tenant=None, description="Evento global")

    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse("platform-auditoria-list"))

    assert response.status_code == status.HTTP_200_OK
    item = next(i for i in response.data["results"] if i["id"] == str(log.pk))
    assert item["tenant_id"] is None
    assert item["tenant_name"] is None
