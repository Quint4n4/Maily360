"""
Tests de gestión del catálogo de planes (Fase 3.1 — alta y edición).

Cubre:
  - POST /api/v1/plataforma/planes/
  - PATCH /api/v1/plataforma/planes/<plan_id>/
  - DELETE → 405 (no hay borrado físico; Plan tiene PROTECT desde
    TenantSubscription — desactivar es is_active=False vía PATCH).

Valida:
  - Permisos: clinic_member/engineering/sales → 403 en POST y PATCH;
    sales → 200 en GET (lista completa, incluye inactivos);
    super_admin → 201 en POST, 200 en PATCH.
  - Slug único con sufijo -2, -3...
  - Defaults: order autoincremental, description vacía si no se manda.
  - Validaciones 400: precio negativo, features no-lista / con elementos
    vacíos, name vacío.
  - PATCH parcial: solo cambiar price_monthly no toca el resto de campos.
  - Slug inmutable: PATCH con name distinto no cambia el slug.
  - Desactivar (is_active=False) vía PATCH: el GET de plataforma lo sigue
    listando; tenant_subscription_set lo rechaza.
  - Auditoría: AuditLog con action PLAN_CREATE/PLAN_UPDATE, metadata sin
    datos sensibles.
  - DELETE → 405.
  - Contrato exacto de campos en la respuesta.

Fixtures locales (no compartidas vía conftest.py), replicando la misma
convención de test_suscripciones.py.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import ActionType, AuditLog
from apps.plataforma.services import tenant_subscription_set
from apps.tenancy.models import Plan
from tests.factories import (
    PlanFactory,
    PlatformStaffFactory,
    TenantFactory,
    UserFactory,
)

PLANES_URL_NAME = "platform-planes-list"


def _plan_detail_url(plan_id: Any) -> str:
    return reverse("platform-plan-detail", kwargs={"plan_id": plan_id})


# ---------------------------------------------------------------------------
# Fixtures específicas (replicadas de test_suscripciones.py)
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
    """Usuario de plataforma con rol engineering (fuera de la escritura de planes)."""
    return PlatformStaffFactory()  # platform_role="engineering"


@pytest.fixture
def clinic_member(db: Any) -> Any:
    """Usuario miembro de una clínica SIN is_platform_staff."""
    return UserFactory(is_platform_staff=False)


def _valid_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "Plan Especial",
        "price_monthly": "999.00",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Permisos — POST /planes/
# ---------------------------------------------------------------------------


def test_crear_plan_clinic_member_is_rejected(db: Any, clinic_member: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=clinic_member)
    response = client.post(reverse(PLANES_URL_NAME), _valid_payload(), format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_crear_plan_engineering_is_rejected(db: Any, engineering_user: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=engineering_user)
    response = client.post(reverse(PLANES_URL_NAME), _valid_payload(), format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_crear_plan_sales_is_rejected(db: Any, sales_user: Any) -> None:
    """Sales lee y asigna planes existentes, pero NO define precios (solo super_admin)."""
    client = APIClient()
    client.force_authenticate(user=sales_user)
    response = client.post(reverse(PLANES_URL_NAME), _valid_payload(), format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_crear_plan_super_admin_ok(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)
    response = client.post(reverse(PLANES_URL_NAME), _valid_payload(), format="json")
    assert response.status_code == status.HTTP_201_CREATED


def test_planes_sales_puede_leer_lista_completa(db: Any, sales_user: Any) -> None:
    """Sales SÍ puede leer (GET), incluyendo planes inactivos."""
    PlanFactory(slug="activo-sales", is_active=True)
    PlanFactory(slug="inactivo-sales", is_active=False)
    client = APIClient()
    client.force_authenticate(user=sales_user)

    response = client.get(reverse(PLANES_URL_NAME))

    assert response.status_code == status.HTTP_200_OK
    slugs = [p["slug"] for p in response.data]
    assert "activo-sales" in slugs
    assert "inactivo-sales" in slugs


# ---------------------------------------------------------------------------
# Permisos — PATCH /planes/<id>/
# ---------------------------------------------------------------------------


def test_editar_plan_clinic_member_is_rejected(db: Any, clinic_member: Any) -> None:
    plan = PlanFactory()
    client = APIClient()
    client.force_authenticate(user=clinic_member)
    response = client.patch(_plan_detail_url(plan.id), {"price_monthly": "100.00"}, format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_editar_plan_engineering_is_rejected(db: Any, engineering_user: Any) -> None:
    plan = PlanFactory()
    client = APIClient()
    client.force_authenticate(user=engineering_user)
    response = client.patch(_plan_detail_url(plan.id), {"price_monthly": "100.00"}, format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_editar_plan_sales_is_rejected(db: Any, sales_user: Any) -> None:
    plan = PlanFactory()
    client = APIClient()
    client.force_authenticate(user=sales_user)
    response = client.patch(_plan_detail_url(plan.id), {"price_monthly": "100.00"}, format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_editar_plan_super_admin_ok(db: Any, super_admin: Any) -> None:
    plan = PlanFactory()
    client = APIClient()
    client.force_authenticate(user=super_admin)
    response = client.patch(_plan_detail_url(plan.id), {"price_monthly": "1234.00"}, format="json")
    assert response.status_code == status.HTTP_200_OK


def test_editar_plan_inexistente_404(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)
    response = client.patch(
        _plan_detail_url("00000000-0000-0000-0000-000000000000"),
        {"price_monthly": "100.00"},
        format="json",
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# Anónimo y método no permitido
# ---------------------------------------------------------------------------


def test_crear_plan_anonymous_is_rejected(db: Any) -> None:
    client = APIClient()
    response = client.post(reverse(PLANES_URL_NAME), _valid_payload(), format="json")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_plan_delete_not_allowed(db: Any, super_admin: Any) -> None:
    plan = PlanFactory()
    client = APIClient()
    client.force_authenticate(user=super_admin)
    response = client.delete(_plan_detail_url(plan.id))
    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


def test_plan_put_not_allowed(db: Any, super_admin: Any) -> None:
    plan = PlanFactory()
    client = APIClient()
    client.force_authenticate(user=super_admin)
    response = client.put(_plan_detail_url(plan.id), {}, format="json")
    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


# ---------------------------------------------------------------------------
# Slug único
# ---------------------------------------------------------------------------


def test_slug_unico_con_sufijo(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)

    r1 = client.post(reverse(PLANES_URL_NAME), _valid_payload(name="Plan Oro"), format="json")
    r2 = client.post(reverse(PLANES_URL_NAME), _valid_payload(name="Plan Oro"), format="json")

    assert r1.status_code == status.HTTP_201_CREATED
    assert r2.status_code == status.HTTP_201_CREATED
    assert r1.data["slug"] == "plan-oro"
    assert r2.data["slug"] == "plan-oro-2"


def test_slug_inmutable_en_patch(db: Any, super_admin: Any) -> None:
    """PATCH con name distinto NO cambia el slug (slug es inmutable)."""
    plan = PlanFactory(slug="plan-fijo", name="Nombre Original")
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.patch(_plan_detail_url(plan.id), {"name": "Nombre Nuevo"}, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["slug"] == "plan-fijo"
    assert response.data["name"] == "Nombre Nuevo"


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_crear_plan_order_autoincremental(db: Any, super_admin: Any) -> None:
    PlanFactory(order=5)
    PlanFactory(order=9)
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.post(
        reverse(PLANES_URL_NAME), _valid_payload(name="Plan Sin Order"), format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["order"] == 10


def test_crear_plan_description_vacia_por_defecto(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.post(
        reverse(PLANES_URL_NAME), _valid_payload(name="Plan Sin Desc"), format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["description"] == ""


def test_crear_plan_order_explicito_respetado(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.post(
        reverse(PLANES_URL_NAME),
        _valid_payload(name="Plan Con Order", order=3),
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["order"] == 3


# ---------------------------------------------------------------------------
# Validaciones 400
# ---------------------------------------------------------------------------


def test_crear_plan_precio_negativo_400(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.post(
        reverse(PLANES_URL_NAME),
        _valid_payload(price_monthly="-10.00"),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_crear_plan_name_vacio_400(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.post(reverse(PLANES_URL_NAME), _valid_payload(name="   "), format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_crear_plan_features_no_lista_400(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.post(
        reverse(PLANES_URL_NAME),
        _valid_payload(features="no-es-lista"),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_crear_plan_features_con_elemento_vacio_400(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.post(
        reverse(PLANES_URL_NAME),
        _valid_payload(features=["Bueno", ""]),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_editar_plan_precio_negativo_400(db: Any, super_admin: Any) -> None:
    plan = PlanFactory()
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.patch(_plan_detail_url(plan.id), {"price_monthly": "-1.00"}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_editar_plan_name_vacio_400(db: Any, super_admin: Any) -> None:
    plan = PlanFactory()
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.patch(_plan_detail_url(plan.id), {"name": ""}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_editar_plan_slug_en_payload_se_ignora(db: Any, super_admin: Any) -> None:
    """Intentar mandar slug en el PATCH debe ser rechazado (campo inmutable).

    El InputSerializer de PATCH no declara `slug`, así que DRF lo ignora
    silenciosamente si viene en el payload (no es un campo reconocido) — se
    valida que el slug efectivamente NO cambie, que es la garantía real.
    """
    plan = PlanFactory(slug="plan-protegido")
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.patch(
        _plan_detail_url(plan.id),
        {"slug": "otro-slug", "price_monthly": "500.00"},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    plan.refresh_from_db()
    assert plan.slug == "plan-protegido"


# ---------------------------------------------------------------------------
# PATCH parcial
# ---------------------------------------------------------------------------


def test_patch_parcial_solo_cambia_price_monthly(db: Any, super_admin: Any) -> None:
    plan = PlanFactory(
        name="Plan Intacto",
        description="Descripción original",
        price_monthly=Decimal("500.00"),
        is_featured=True,
        features=["A", "B"],
        is_active=True,
        order=7,
    )
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.patch(_plan_detail_url(plan.id), {"price_monthly": "750.00"}, format="json")

    assert response.status_code == status.HTTP_200_OK
    plan.refresh_from_db()
    assert plan.price_monthly == Decimal("750.00")
    assert plan.name == "Plan Intacto"
    assert plan.description == "Descripción original"
    assert plan.is_featured is True
    assert plan.features == ["A", "B"]
    assert plan.is_active is True
    assert plan.order == 7


# ---------------------------------------------------------------------------
# Desactivar vía PATCH (excepción documentada)
# ---------------------------------------------------------------------------


def test_desactivar_plan_via_patch(db: Any, super_admin: Any) -> None:
    plan = PlanFactory(is_active=True)
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.patch(_plan_detail_url(plan.id), {"is_active": False}, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["is_active"] is False
    plan.refresh_from_db()
    assert plan.is_active is False


def test_plan_desactivado_sigue_en_get_de_plataforma(db: Any, super_admin: Any) -> None:
    plan = PlanFactory(slug="a-desactivar", is_active=True)
    client = APIClient()
    client.force_authenticate(user=super_admin)

    client.patch(_plan_detail_url(plan.id), {"is_active": False}, format="json")

    response = client.get(reverse(PLANES_URL_NAME))
    slugs = [p["slug"] for p in response.data]
    assert "a-desactivar" in slugs


def test_plan_desactivado_rechazado_en_asignacion_de_suscripcion(db: Any, super_admin: Any) -> None:
    """tenant_subscription_set sigue rechazando planes inactivos tras el PATCH."""
    plan = PlanFactory(is_active=True)
    tenant = TenantFactory()

    # Desactivar vía el flujo de plataforma (mismo servicio que usa la vista).
    from apps.plataforma.services import plan_update

    plan_update(actor=super_admin, plan_id=plan.id, is_active=False)

    with pytest.raises(DjangoValidationError):
        tenant_subscription_set(
            tenant=tenant,
            actor=super_admin,
            plan_id=plan.id,
            billing_cycle="monthly",
            current_period_end=date.today() + timedelta(days=30),
        )


# ---------------------------------------------------------------------------
# Auditoría
# ---------------------------------------------------------------------------


def test_crear_plan_registra_auditoria(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.post(
        reverse(PLANES_URL_NAME),
        _valid_payload(name="Plan Auditado"),
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    log = AuditLog.all_objects.filter(action=ActionType.PLAN_CREATE).latest("created_at")
    assert log.actor_id == super_admin.id
    assert log.metadata["slug"] == response.data["slug"]
    assert "price" in log.metadata
    # Shape esperado: sin datos sensibles ni PII (catálogo, no expediente).
    assert set(log.metadata.keys()) == {"slug", "price"}
    assert "password" not in log.metadata


def test_editar_plan_registra_auditoria_con_precio_old_new(db: Any, super_admin: Any) -> None:
    plan = PlanFactory(price_monthly=Decimal("500.00"))
    client = APIClient()
    client.force_authenticate(user=super_admin)

    client.patch(_plan_detail_url(plan.id), {"price_monthly": "800.00"}, format="json")

    log = AuditLog.all_objects.filter(action=ActionType.PLAN_UPDATE).latest("created_at")
    assert log.actor_id == super_admin.id
    assert log.metadata["slug"] == plan.slug
    assert log.metadata["price_old"] == "500.00"
    assert log.metadata["price_new"] == "800.00"
    assert "cambios" in log.metadata
    assert "password" not in log.metadata


def test_editar_plan_sin_cambiar_precio_no_incluye_price_old_new(db: Any, super_admin: Any) -> None:
    plan = PlanFactory(name="Plan Sin Cambio de Precio")
    client = APIClient()
    client.force_authenticate(user=super_admin)

    client.patch(_plan_detail_url(plan.id), {"description": "Nueva descripción"}, format="json")

    log = AuditLog.all_objects.filter(action=ActionType.PLAN_UPDATE).latest("created_at")
    assert "price_old" not in log.metadata
    assert "price_new" not in log.metadata


# ---------------------------------------------------------------------------
# Contrato exacto de campos
# ---------------------------------------------------------------------------


def test_contrato_campos_respuesta_post(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.post(
        reverse(PLANES_URL_NAME),
        _valid_payload(name="Plan Contrato"),
        format="json",
    )

    expected_fields = {
        "id",
        "slug",
        "name",
        "description",
        "price_monthly",
        "is_featured",
        "features",
        "is_active",
        "order",
    }
    assert set(response.data.keys()) == expected_fields


def test_contrato_campos_respuesta_patch(db: Any, super_admin: Any) -> None:
    plan = PlanFactory()
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.patch(_plan_detail_url(plan.id), {"price_monthly": "321.00"}, format="json")

    expected_fields = {
        "id",
        "slug",
        "name",
        "description",
        "price_monthly",
        "is_featured",
        "features",
        "is_active",
        "order",
    }
    assert set(response.data.keys()) == expected_fields


# ---------------------------------------------------------------------------
# Verificación explícita: el modelo realmente persiste lo creado
# ---------------------------------------------------------------------------


def test_crear_plan_persiste_en_bd(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.post(
        reverse(PLANES_URL_NAME),
        _valid_payload(
            name="Plan Persistente",
            description="Una descripción",
            is_featured=True,
            features=["Uno", "Dos"],
        ),
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    plan = Plan.objects.get(id=response.data["id"])
    assert plan.name == "Plan Persistente"
    assert plan.description == "Una descripción"
    assert plan.is_featured is True
    assert plan.features == ["Uno", "Dos"]
