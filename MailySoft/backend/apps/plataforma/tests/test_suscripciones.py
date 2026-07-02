"""
Tests de Suscripciones y planes (Fase 3 — docs/design/plataforma-fases-plan.md).

Cubre:
  - GET  /api/v1/plataforma/planes/
  - GET  /api/v1/plataforma/suscripciones/
  - GET  /api/v1/plataforma/suscripciones/resumen/
  - POST /api/v1/plataforma/clinicas/<tenant_id>/suscripcion/
  - Tarea Celery apps.plataforma.tasks.avisar_vencimientos

Valida:
  - Permisos: clinic_member y engineering → 403; sales y super_admin → 200.
  - Planes sembrados por la data migration y su orden.
  - Listado de suscripciones con y sin TenantSubscription (left join lógico).
  - Cálculo de `alerta` para cada uno de los 4 valores + None (freezegun).
  - Filtros search / plan_id / alerta.
  - Resumen: conteos, mrr_estimado (solo tenants ACTIVE).
  - Asignar plan: crea, cambia, 400 (plan inactivo / fecha pasada), 404 tenant,
    auditoría SUBSCRIPTION_CHANGE registrada.
  - Tarea de avisos: crea auditoría, idempotente en segunda corrida, respeta
    extensión de trial/renovación de periodo.
  - Métodos no permitidos → 405.
  - Contrato exacto de campos de una fila de suscripción.

Fixtures locales (no compartidas vía conftest.py): replican la misma
convención de test_auditoria.py / test_sistema.py.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import ActionType, AuditLog
from apps.plataforma.tasks import avisar_vencimientos
from apps.tenancy.models import Tenant, TenantSubscription
from tests.factories import (
    PlanFactory,
    PlatformStaffFactory,
    TenantFactory,
    TenantSubscriptionFactory,
    UserFactory,
)

PLANES_URL_NAME = "platform-planes-list"
SUSCRIPCIONES_URL_NAME = "platform-suscripciones-list"
RESUMEN_URL_NAME = "platform-suscripciones-resumen"


def _suscripcion_url(tenant_id: Any) -> str:
    return reverse("platform-clinica-suscripcion", kwargs={"tenant_id": tenant_id})


# ---------------------------------------------------------------------------
# Fixtures específicas de plataforma (replicadas de test_auditoria.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def super_admin(db: Any) -> Any:
    """Usuario de plataforma con rol super_admin."""
    return UserFactory(
        is_platform_staff=True,
        is_staff=True,
        platform_role="super_admin",
    )


@pytest.fixture
def sales_user(db: Any) -> Any:
    """Usuario de plataforma con rol sales."""
    return UserFactory(
        is_platform_staff=True,
        platform_role="sales",
    )


@pytest.fixture
def engineering_user(db: Any) -> Any:
    """Usuario de plataforma con rol engineering (fuera de suscripciones)."""
    return PlatformStaffFactory()  # platform_role="engineering"


@pytest.fixture
def clinic_member(db: Any) -> Any:
    """Usuario miembro de una clínica SIN is_platform_staff."""
    return UserFactory(is_platform_staff=False)


# ---------------------------------------------------------------------------
# Permisos — GET /planes/
# ---------------------------------------------------------------------------


def test_planes_clinic_member_is_rejected(db: Any, clinic_member: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=clinic_member)
    response = client.get(reverse(PLANES_URL_NAME))
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_planes_engineering_is_rejected(db: Any, engineering_user: Any) -> None:
    """engineering queda fuera de suscripciones (matriz del frontend)."""
    client = APIClient()
    client.force_authenticate(user=engineering_user)
    response = client.get(reverse(PLANES_URL_NAME))
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_planes_sales_can_read(db: Any, sales_user: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=sales_user)
    response = client.get(reverse(PLANES_URL_NAME))
    assert response.status_code == status.HTTP_200_OK


def test_planes_super_admin_can_read(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)
    response = client.get(reverse(PLANES_URL_NAME))
    assert response.status_code == status.HTTP_200_OK


def test_planes_anonymous_is_rejected(db: Any) -> None:
    client = APIClient()
    response = client.get(reverse(PLANES_URL_NAME))
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


# NOTA (Fase 3.1): POST /planes/ dejó de ser 405 — ahora crea un plan
# (solo super_admin). Cobertura completa en test_planes_crud.py.


# ---------------------------------------------------------------------------
# Planes — sembrados y ordenados
# ---------------------------------------------------------------------------


def test_planes_seed_esta_presente_y_ordenado(db: Any, super_admin: Any) -> None:
    """La data migration sembró basico/pro/premium; el listado no pagina y respeta `order`."""
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse(PLANES_URL_NAME))

    assert response.status_code == status.HTTP_200_OK
    assert isinstance(response.data, list)  # sin paginar
    slugs = [p["slug"] for p in response.data]
    assert slugs == ["basico", "pro", "premium"]

    pro = next(p for p in response.data if p["slug"] == "pro")
    assert pro["is_featured"] is True
    assert Decimal(pro["price_monthly"]) == Decimal("4500.00")
    assert pro["features"] == [
        "Hasta 5 consultorios",
        "Usuarios ilimitados",
        "Expedientes completos",
        "Finanzas y reportes",
    ]


def test_planes_incluye_inactivos(db: Any, super_admin: Any) -> None:
    """El listado de plataforma incluye planes inactivos (a diferencia de un catálogo público)."""
    PlanFactory(slug="descontinuado", is_active=False, order=99)
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse(PLANES_URL_NAME))

    slugs = [p["slug"] for p in response.data]
    assert "descontinuado" in slugs


# ---------------------------------------------------------------------------
# Permisos — GET /suscripciones/ y /suscripciones/resumen/
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url_name", [SUSCRIPCIONES_URL_NAME, RESUMEN_URL_NAME])
def test_suscripciones_clinic_member_is_rejected(
    db: Any, clinic_member: Any, url_name: str
) -> None:
    client = APIClient()
    client.force_authenticate(user=clinic_member)
    response = client.get(reverse(url_name))
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.parametrize("url_name", [SUSCRIPCIONES_URL_NAME, RESUMEN_URL_NAME])
def test_suscripciones_engineering_is_rejected(
    db: Any, engineering_user: Any, url_name: str
) -> None:
    client = APIClient()
    client.force_authenticate(user=engineering_user)
    response = client.get(reverse(url_name))
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.parametrize("url_name", [SUSCRIPCIONES_URL_NAME, RESUMEN_URL_NAME])
def test_suscripciones_sales_can_read(db: Any, sales_user: Any, url_name: str) -> None:
    client = APIClient()
    client.force_authenticate(user=sales_user)
    response = client.get(reverse(url_name))
    assert response.status_code == status.HTTP_200_OK


@pytest.mark.parametrize("url_name", [SUSCRIPCIONES_URL_NAME, RESUMEN_URL_NAME])
def test_suscripciones_super_admin_can_read(db: Any, super_admin: Any, url_name: str) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)
    response = client.get(reverse(url_name))
    assert response.status_code == status.HTTP_200_OK


def test_suscripciones_post_not_allowed(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)
    response = client.post(reverse(SUSCRIPCIONES_URL_NAME), {})
    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


# ---------------------------------------------------------------------------
# Permisos — POST /clinicas/<id>/suscripcion/
# ---------------------------------------------------------------------------


def test_asignar_plan_clinic_member_is_rejected(db: Any, clinic_member: Any) -> None:
    tenant = TenantFactory()
    client = APIClient()
    client.force_authenticate(user=clinic_member)
    response = client.post(_suscripcion_url(tenant.id), {}, format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_asignar_plan_engineering_is_rejected(db: Any, engineering_user: Any) -> None:
    tenant = TenantFactory()
    client = APIClient()
    client.force_authenticate(user=engineering_user)
    response = client.post(_suscripcion_url(tenant.id), {}, format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_asignar_plan_get_not_allowed(db: Any, super_admin: Any) -> None:
    tenant = TenantFactory()
    client = APIClient()
    client.force_authenticate(user=super_admin)
    response = client.get(_suscripcion_url(tenant.id))
    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


# ---------------------------------------------------------------------------
# Listado — left join lógico (con y sin suscripción)
# ---------------------------------------------------------------------------


def test_listado_incluye_tenants_sin_suscripcion(db: Any, super_admin: Any) -> None:
    tenant_sin_plan = TenantFactory(status="active")
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse(SUSCRIPCIONES_URL_NAME))

    assert response.status_code == status.HTTP_200_OK
    row = next(r for r in response.data["results"] if r["tenant_id"] == str(tenant_sin_plan.id))
    assert row["plan_id"] is None
    assert row["plan_name"] is None
    assert row["billing_cycle"] is None
    assert row["current_period_end"] is None
    assert row["plan_price_monthly"] is None


def test_listado_incluye_tenants_con_suscripcion(db: Any, super_admin: Any) -> None:
    plan = PlanFactory(slug="pro-test", name="Pro Test", price_monthly=Decimal("4500.00"))
    sub = TenantSubscriptionFactory(plan=plan, billing_cycle="annual")
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse(SUSCRIPCIONES_URL_NAME))

    row = next(r for r in response.data["results"] if r["tenant_id"] == str(sub.tenant_id))
    assert row["plan_id"] == str(plan.id)
    assert row["plan_name"] == "Pro Test"
    assert row["plan_slug"] == "pro-test"
    assert row["billing_cycle"] == "annual"
    assert Decimal(row["plan_price_monthly"]) == Decimal("4500.00")


def test_listado_paginado(db: Any, super_admin: Any) -> None:
    for _ in range(3):
        TenantFactory()
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse(SUSCRIPCIONES_URL_NAME), {"page_size": 2})

    assert response.status_code == status.HTTP_200_OK
    assert "results" in response.data
    assert "count" in response.data
    assert len(response.data["results"]) == 2


# ---------------------------------------------------------------------------
# Contrato exacto de campos
# ---------------------------------------------------------------------------


def test_contrato_campos_fila_suscripcion(db: Any, super_admin: Any) -> None:
    TenantFactory()
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse(SUSCRIPCIONES_URL_NAME))

    expected_fields = {
        "tenant_id",
        "tenant_name",
        "tenant_slug",
        "tenant_status",
        "trial_ends_at",
        "plan_id",
        "plan_name",
        "plan_slug",
        "billing_cycle",
        "current_period_end",
        "plan_price_monthly",
        "alerta",
    }
    assert response.data["results"], "Debe haber al menos una fila"
    for row in response.data["results"]:
        assert set(row.keys()) == expected_fields


# ---------------------------------------------------------------------------
# Cálculo de `alerta` — cada valor posible
# ---------------------------------------------------------------------------


@freeze_time("2026-07-02 12:00:00")
def test_alerta_trial_vencido(db: Any, super_admin: Any) -> None:
    tenant = TenantFactory(
        status="trial",
        trial_ends_at=timezone.now() - timedelta(days=1),
    )
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse(SUSCRIPCIONES_URL_NAME))

    row = next(r for r in response.data["results"] if r["tenant_id"] == str(tenant.id))
    assert row["alerta"] == "trial_vencido"


@freeze_time("2026-07-02 12:00:00")
def test_alerta_trial_por_vencer(db: Any, super_admin: Any) -> None:
    tenant = TenantFactory(
        status="trial",
        trial_ends_at=timezone.now() + timedelta(days=3),
    )
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse(SUSCRIPCIONES_URL_NAME))

    row = next(r for r in response.data["results"] if r["tenant_id"] == str(tenant.id))
    assert row["alerta"] == "trial_por_vencer"


@freeze_time("2026-07-02 12:00:00")
def test_alerta_trial_vigente_sin_alerta(db: Any, super_admin: Any) -> None:
    tenant = TenantFactory(
        status="trial",
        trial_ends_at=timezone.now() + timedelta(days=30),
    )
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse(SUSCRIPCIONES_URL_NAME))

    row = next(r for r in response.data["results"] if r["tenant_id"] == str(tenant.id))
    assert row["alerta"] is None


@freeze_time("2026-07-02 12:00:00")
def test_alerta_periodo_vencido(db: Any, super_admin: Any) -> None:
    sub = TenantSubscriptionFactory(
        tenant=TenantFactory(status="active"),
        current_period_end=date(2026, 6, 1),
    )
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse(SUSCRIPCIONES_URL_NAME))

    row = next(r for r in response.data["results"] if r["tenant_id"] == str(sub.tenant_id))
    assert row["alerta"] == "periodo_vencido"


@freeze_time("2026-07-02 12:00:00")
def test_alerta_periodo_por_vencer(db: Any, super_admin: Any) -> None:
    sub = TenantSubscriptionFactory(
        tenant=TenantFactory(status="active"),
        current_period_end=date(2026, 7, 5),
    )
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse(SUSCRIPCIONES_URL_NAME))

    row = next(r for r in response.data["results"] if r["tenant_id"] == str(sub.tenant_id))
    assert row["alerta"] == "periodo_por_vencer"


@freeze_time("2026-07-02 12:00:00")
def test_alerta_periodo_vigente_sin_alerta(db: Any, super_admin: Any) -> None:
    sub = TenantSubscriptionFactory(
        tenant=TenantFactory(status="active"),
        current_period_end=date(2026, 12, 1),
    )
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse(SUSCRIPCIONES_URL_NAME))

    row = next(r for r in response.data["results"] if r["tenant_id"] == str(sub.tenant_id))
    assert row["alerta"] is None


@freeze_time("2026-07-02 12:00:00")
def test_alerta_prioridad_vencido_sobre_por_vencer(db: Any, super_admin: Any) -> None:
    """Trial vencido Y periodo por vencer a la vez → prioriza trial_vencido."""
    tenant = TenantFactory(
        status="trial",
        trial_ends_at=timezone.now() - timedelta(days=1),
    )
    TenantSubscriptionFactory(tenant=tenant, current_period_end=date(2026, 7, 5))
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse(SUSCRIPCIONES_URL_NAME))

    row = next(r for r in response.data["results"] if r["tenant_id"] == str(tenant.id))
    assert row["alerta"] == "trial_vencido"


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------


def test_filtro_search_por_nombre(db: Any, super_admin: Any) -> None:
    objetivo = TenantFactory(name="Clínica San José", slug="clinica-san-jose-x")
    TenantFactory(name="Otra Clínica")
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse(SUSCRIPCIONES_URL_NAME), {"search": "San José"})

    ids = {r["tenant_id"] for r in response.data["results"]}
    assert str(objetivo.id) in ids
    assert len(response.data["results"]) == 1


def test_filtro_plan_id(db: Any, super_admin: Any) -> None:
    plan_a = PlanFactory(slug="plan-a")
    plan_b = PlanFactory(slug="plan-b")
    sub_a = TenantSubscriptionFactory(plan=plan_a)
    TenantSubscriptionFactory(plan=plan_b)
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse(SUSCRIPCIONES_URL_NAME), {"plan_id": str(plan_a.id)})

    ids = {r["tenant_id"] for r in response.data["results"]}
    assert ids == {str(sub_a.tenant_id)}


@freeze_time("2026-07-02 12:00:00")
def test_filtro_alerta_vencidas(db: Any, super_admin: Any) -> None:
    vencido = TenantFactory(status="trial", trial_ends_at=timezone.now() - timedelta(days=1))
    por_vencer = TenantFactory(status="trial", trial_ends_at=timezone.now() + timedelta(days=2))
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse(SUSCRIPCIONES_URL_NAME), {"alerta": "vencidas"})

    ids = {r["tenant_id"] for r in response.data["results"]}
    assert str(vencido.id) in ids
    assert str(por_vencer.id) not in ids


@freeze_time("2026-07-02 12:00:00")
def test_filtro_alerta_por_vencer(db: Any, super_admin: Any) -> None:
    vencido = TenantFactory(status="trial", trial_ends_at=timezone.now() - timedelta(days=1))
    por_vencer = TenantFactory(status="trial", trial_ends_at=timezone.now() + timedelta(days=2))
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse(SUSCRIPCIONES_URL_NAME), {"alerta": "por_vencer"})

    ids = {r["tenant_id"] for r in response.data["results"]}
    assert str(por_vencer.id) in ids
    assert str(vencido.id) not in ids


def test_filtro_alerta_invalido_400(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse(SUSCRIPCIONES_URL_NAME), {"alerta": "no-existe"})

    assert response.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------------


def test_resumen_conteos_y_mrr(db: Any, super_admin: Any) -> None:
    plan = PlanFactory(slug="plan-resumen", price_monthly=Decimal("1000.00"))

    activo_con_plan = TenantFactory(status="active")
    TenantSubscriptionFactory(tenant=activo_con_plan, plan=plan)

    trial_con_plan = TenantFactory(status="trial")
    TenantSubscriptionFactory(tenant=trial_con_plan, plan=plan)

    TenantFactory(status="active")  # activo SIN plan: no debe sumar a mrr

    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse(RESUMEN_URL_NAME))

    assert response.status_code == status.HTTP_200_OK
    data = response.data
    assert data["total_clinicas"] >= 3
    assert data["sin_plan"] >= 1
    # Solo el tenant ACTIVE con suscripción cuenta en el MRR (el trial con
    # plan asignado NO es ingreso recurrente activo todavía).
    assert Decimal(data["mrr_estimado"]) == Decimal("1000.00")
    assert set(data["alertas"].keys()) == {
        "trial_vencido",
        "trial_por_vencer",
        "periodo_vencido",
        "periodo_por_vencer",
    }


def test_resumen_contrato_campos(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse(RESUMEN_URL_NAME))

    assert set(response.data.keys()) == {
        "total_clinicas",
        "sin_plan",
        "por_plan",
        "alertas",
        "mrr_estimado",
    }


# ---------------------------------------------------------------------------
# Asignar / cambiar plan
# ---------------------------------------------------------------------------


def test_asignar_plan_crea_suscripcion(db: Any, super_admin: Any) -> None:
    tenant = TenantFactory()
    plan = PlanFactory(slug="plan-nuevo")
    client = APIClient()
    client.force_authenticate(user=super_admin)

    payload = {
        "plan_id": str(plan.id),
        "billing_cycle": "annual",
        "current_period_end": (date.today() + timedelta(days=330)).isoformat(),
    }
    response = client.post(_suscripcion_url(tenant.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["plan_id"] == str(plan.id)
    assert response.data["billing_cycle"] == "annual"
    assert TenantSubscription.objects.filter(tenant=tenant, plan=plan).exists()


def test_asignar_plan_cambia_suscripcion_existente(db: Any, super_admin: Any) -> None:
    plan_viejo = PlanFactory(slug="plan-viejo")
    plan_nuevo = PlanFactory(slug="plan-nuevo-2")
    sub = TenantSubscriptionFactory(plan=plan_viejo)
    client = APIClient()
    client.force_authenticate(user=super_admin)

    payload = {
        "plan_id": str(plan_nuevo.id),
        "billing_cycle": "monthly",
        "current_period_end": (date.today() + timedelta(days=30)).isoformat(),
    }
    response = client.post(_suscripcion_url(sub.tenant_id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK
    # No se duplica: sigue siendo una sola fila (OneToOne).
    assert TenantSubscription.objects.filter(tenant_id=sub.tenant_id).count() == 1
    updated = TenantSubscription.objects.get(tenant_id=sub.tenant_id)
    assert updated.plan_id == plan_nuevo.id


def test_asignar_plan_inactivo_400(db: Any, super_admin: Any) -> None:
    tenant = TenantFactory()
    plan_inactivo = PlanFactory(slug="inactivo", is_active=False)
    client = APIClient()
    client.force_authenticate(user=super_admin)

    payload = {
        "plan_id": str(plan_inactivo.id),
        "billing_cycle": "monthly",
        "current_period_end": (date.today() + timedelta(days=30)).isoformat(),
    }
    response = client.post(_suscripcion_url(tenant.id), payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_asignar_plan_fecha_pasada_400(db: Any, super_admin: Any) -> None:
    tenant = TenantFactory()
    plan = PlanFactory(slug="plan-fecha-pasada")
    client = APIClient()
    client.force_authenticate(user=super_admin)

    payload = {
        "plan_id": str(plan.id),
        "billing_cycle": "monthly",
        "current_period_end": (date.today() - timedelta(days=1)).isoformat(),
    }
    response = client.post(_suscripcion_url(tenant.id), payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_asignar_plan_tenant_inexistente_404(db: Any, super_admin: Any) -> None:
    plan = PlanFactory(slug="plan-404")
    client = APIClient()
    client.force_authenticate(user=super_admin)

    payload = {
        "plan_id": str(plan.id),
        "billing_cycle": "monthly",
        "current_period_end": (date.today() + timedelta(days=30)).isoformat(),
    }
    response = client.post(
        _suscripcion_url("00000000-0000-0000-0000-000000000000"), payload, format="json"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_asignar_plan_campos_obligatorios_400(db: Any, super_admin: Any) -> None:
    tenant = TenantFactory()
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.post(_suscripcion_url(tenant.id), {}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "plan_id" in response.data
    assert "billing_cycle" in response.data
    assert "current_period_end" in response.data


def test_asignar_plan_registra_auditoria(db: Any, super_admin: Any) -> None:
    tenant = TenantFactory()
    plan = PlanFactory(slug="plan-auditado")
    client = APIClient()
    client.force_authenticate(user=super_admin)

    payload = {
        "plan_id": str(plan.id),
        "billing_cycle": "annual",
        "current_period_end": (date.today() + timedelta(days=365)).isoformat(),
    }
    client.post(_suscripcion_url(tenant.id), payload, format="json")

    log = AuditLog.all_objects.filter(action=ActionType.SUBSCRIPTION_CHANGE).latest("created_at")
    assert log.actor_id == super_admin.id
    assert log.metadata["tenant_id"] == str(tenant.id)
    assert log.metadata["new_plan_slug"] == "plan-auditado"
    # Sin datos sensibles en metadata.
    assert "password" not in log.metadata


def test_asignar_plan_resetea_notificacion_de_vencimiento(db: Any, super_admin: Any) -> None:
    """Renovar con fecha futura resetea period_expired_notified_at (D-3)."""
    plan = PlanFactory(slug="plan-reset")
    sub = TenantSubscriptionFactory(
        plan=plan,
        current_period_end=date(2026, 1, 1),
        period_expired_notified_at=timezone.now(),
    )
    client = APIClient()
    client.force_authenticate(user=super_admin)

    payload = {
        "plan_id": str(plan.id),
        "billing_cycle": "annual",
        "current_period_end": (date.today() + timedelta(days=365)).isoformat(),
    }
    client.post(_suscripcion_url(sub.tenant_id), payload, format="json")

    sub.refresh_from_db()
    assert sub.period_expired_notified_at is None


def test_asignar_plan_sales_puede_escribir(db: Any, sales_user: Any) -> None:
    tenant = TenantFactory()
    plan = PlanFactory(slug="plan-sales")
    client = APIClient()
    client.force_authenticate(user=sales_user)

    payload = {
        "plan_id": str(plan.id),
        "billing_cycle": "monthly",
        "current_period_end": (date.today() + timedelta(days=30)).isoformat(),
    }
    response = client.post(_suscripcion_url(tenant.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK


# ---------------------------------------------------------------------------
# Tarea Celery: avisar_vencimientos
# ---------------------------------------------------------------------------


@freeze_time("2026-07-02 12:00:00")
def test_tarea_avisa_trial_vencido(db: Any) -> None:
    tenant = TenantFactory(status="trial", trial_ends_at=timezone.now() - timedelta(days=1))

    result = avisar_vencimientos()

    assert result["trials_avisados"] == 1
    tenant.refresh_from_db()
    assert tenant.trial_expired_notified_at is not None
    log = AuditLog.all_objects.get(action=ActionType.TRIAL_EXPIRED, resource_id=tenant.id)
    assert log.actor is None
    assert log.metadata["tenant_slug"] == tenant.slug


@freeze_time("2026-07-02 12:00:00")
def test_tarea_avisa_periodo_vencido(db: Any) -> None:
    sub = TenantSubscriptionFactory(current_period_end=date(2026, 6, 1))

    result = avisar_vencimientos()

    assert result["periodos_avisados"] == 1
    sub.refresh_from_db()
    assert sub.period_expired_notified_at is not None
    log = AuditLog.all_objects.get(action=ActionType.SUBSCRIPTION_EXPIRED, resource_id=sub.id)
    assert log.actor is None


@freeze_time("2026-07-02 12:00:00")
def test_tarea_no_avisa_trial_vigente(db: Any) -> None:
    TenantFactory(status="trial", trial_ends_at=timezone.now() + timedelta(days=10))

    result = avisar_vencimientos()

    assert result["trials_avisados"] == 0


@freeze_time("2026-07-02 12:00:00")
def test_tarea_no_avisa_periodo_vigente(db: Any) -> None:
    TenantSubscriptionFactory(current_period_end=date(2026, 12, 1))

    result = avisar_vencimientos()

    assert result["periodos_avisados"] == 0


@freeze_time("2026-07-02 12:00:00")
def test_tarea_no_suspende_nada(db: Any) -> None:
    """Decisión del dueño: la tarea SOLO avisa, jamás cambia Tenant.status."""
    tenant = TenantFactory(status="trial", trial_ends_at=timezone.now() - timedelta(days=5))

    avisar_vencimientos()

    tenant.refresh_from_db()
    assert tenant.status == Tenant.Status.TRIAL


@freeze_time("2026-07-02 12:00:00")
def test_tarea_es_idempotente_segunda_corrida(db: Any) -> None:
    """Correr la tarea dos veces el mismo día no duplica auditoría."""
    TenantFactory(status="trial", trial_ends_at=timezone.now() - timedelta(days=1))
    TenantSubscriptionFactory(current_period_end=date(2026, 6, 1))

    first = avisar_vencimientos()
    second = avisar_vencimientos()

    assert first["trials_avisados"] == 1
    assert first["periodos_avisados"] == 1
    assert second["trials_avisados"] == 0
    assert second["periodos_avisados"] == 0

    assert AuditLog.all_objects.filter(action=ActionType.TRIAL_EXPIRED).count() == 1
    assert AuditLog.all_objects.filter(action=ActionType.SUBSCRIPTION_EXPIRED).count() == 1


def test_tarea_respeta_extension_de_trial(db: Any) -> None:
    """Si el trial vence, se avisa; si luego se EXTIENDE (nueva fecha futura) y
    vuelve a vencer, la tarea debe poder avisar de nuevo (no queda "quemada")."""
    with freeze_time("2026-07-02 12:00:00"):
        tenant = TenantFactory(status="trial", trial_ends_at=timezone.now() - timedelta(days=1))
        result = avisar_vencimientos()
        assert result["trials_avisados"] == 1

    # Extensión del trial: nueva fecha futura respecto al aviso anterior.
    with freeze_time("2026-07-03 12:00:00"):
        tenant.trial_ends_at = timezone.now() + timedelta(days=5)
        tenant.save(update_fields=["trial_ends_at"])

    # El trial vuelve a vencer más adelante.
    with freeze_time("2026-07-10 12:00:00"):
        result = avisar_vencimientos()
        assert result["trials_avisados"] == 1

    assert AuditLog.all_objects.filter(action=ActionType.TRIAL_EXPIRED).count() == 2


def test_tarea_respeta_renovacion_de_periodo(db: Any) -> None:
    """Igual que el trial, pero para current_period_end de la suscripción."""
    with freeze_time("2026-07-02 12:00:00"):
        sub = TenantSubscriptionFactory(current_period_end=date(2026, 6, 1))
        result = avisar_vencimientos()
        assert result["periodos_avisados"] == 1

    # Renovación con fecha futura (simula lo que hace tenant_subscription_set:
    # resetea period_expired_notified_at a None).
    sub.current_period_end = date(2026, 8, 1)
    sub.period_expired_notified_at = None
    sub.save(update_fields=["current_period_end", "period_expired_notified_at"])

    with freeze_time("2026-08-05 12:00:00"):
        result = avisar_vencimientos()
        assert result["periodos_avisados"] == 1

    assert AuditLog.all_objects.filter(action=ActionType.SUBSCRIPTION_EXPIRED).count() == 2
