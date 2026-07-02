"""
Tests del endpoint GET /api/v1/plataforma/sistema/ (panel interno de plataforma).

Valida:
  - Permisos: clinic_member y sales → 403; engineering y super_admin → 200.
  - Métodos no permitidos (POST) → 405.
  - Contrato de campos de salida exacto (nivel superior y de cada service).
  - overall_status según la matriz: database down → down; cualquier otro
    servicio no operational → degraded; todos operational → operational.
  - pdf_queue con conteos reales de PdfJob (pending/processing/failed_24h).

Fixtures locales (no compartidas vía conftest.py): replican las mismas
definidas en apps/plataforma/tests/test_auditoria.py, siguiendo su convención.
"""

from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.pdfs.models import PdfJob
from tests.factories import PlatformStaffFactory, TenantFactory, UserFactory

SISTEMA_URL_NAME = "platform-sistema"


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
    """Usuario de plataforma con rol engineering (PlatformStaffFactory usa este rol por defecto)."""
    return PlatformStaffFactory()  # platform_role="engineering"


@pytest.fixture
def clinic_member(db: Any) -> Any:
    """Usuario miembro de una clínica SIN is_platform_staff."""
    return UserFactory(is_platform_staff=False)


# ---------------------------------------------------------------------------
# Helpers de mock — checks "siempre arriba" / "siempre abajo" para aislar
# overall_status de la infraestructura real de test (que sí tiene BD/Redis).
# ---------------------------------------------------------------------------


def _operational_redis() -> dict[str, Any]:
    return {
        "key": "redis",
        "label": "Redis",
        "status": "operational",
        "latency_ms": 0.5,
        "detail": None,
    }


def _down_redis() -> dict[str, Any]:
    return {
        "key": "redis",
        "label": "Redis",
        "status": "down",
        "latency_ms": None,
        "detail": "Connection refused",
    }


def _operational_celery() -> dict[str, Any]:
    return {
        "key": "celery_worker",
        "label": "Worker Celery",
        "status": "operational",
        "latency_ms": None,
        "detail": "1 worker(s) activo(s)",
    }


def _down_celery() -> dict[str, Any]:
    return {
        "key": "celery_worker",
        "label": "Worker Celery",
        "status": "down",
        "latency_ms": None,
        "detail": "0 worker(s) activo(s)",
    }


def _down_database() -> dict[str, Any]:
    return {
        "key": "database",
        "label": "PostgreSQL",
        "status": "down",
        "latency_ms": None,
        "detail": "connection refused",
    }


# ---------------------------------------------------------------------------
# Permisos
# ---------------------------------------------------------------------------


def test_clinic_member_is_rejected(db: Any, clinic_member: Any) -> None:
    """Un usuario sin is_platform_staff recibe 403."""
    client = APIClient()
    client.force_authenticate(user=clinic_member)

    response = client.get(reverse(SISTEMA_URL_NAME))

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_sales_is_rejected(db: Any, sales_user: Any) -> None:
    """sales queda fuera de la salud del sistema: 403."""
    client = APIClient()
    client.force_authenticate(user=sales_user)

    response = client.get(reverse(SISTEMA_URL_NAME))

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_engineering_can_read(db: Any, engineering_user: Any) -> None:
    """engineering sí puede ver la salud del sistema."""
    client = APIClient()
    client.force_authenticate(user=engineering_user)

    response = client.get(reverse(SISTEMA_URL_NAME))

    assert response.status_code == status.HTTP_200_OK


def test_super_admin_can_read(db: Any, super_admin: Any) -> None:
    """super_admin sí puede ver la salud del sistema."""
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse(SISTEMA_URL_NAME))

    assert response.status_code == status.HTTP_200_OK


def test_anonymous_user_is_rejected(db: Any) -> None:
    """Sin JWT → 401."""
    client = APIClient()
    response = client.get(reverse(SISTEMA_URL_NAME))
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


# ---------------------------------------------------------------------------
# Métodos no permitidos
# ---------------------------------------------------------------------------


def test_post_is_not_allowed(db: Any, super_admin: Any) -> None:
    """El endpoint es solo lectura: POST devuelve 405."""
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.post(reverse(SISTEMA_URL_NAME))

    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


# ---------------------------------------------------------------------------
# Contrato de salida
# ---------------------------------------------------------------------------


def test_output_contract_has_exact_top_level_fields(db: Any, super_admin: Any) -> None:
    """La respuesta no expone campos fuera del contrato fijo con el frontend."""
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse(SISTEMA_URL_NAME))

    assert response.status_code == status.HTTP_200_OK
    expected_top_level = {
        "generated_at",
        "overall_status",
        "services",
        "version",
        "pdf_queue",
    }
    assert set(response.data.keys()) == expected_top_level


def test_output_contract_service_has_exact_fields(db: Any, super_admin: Any) -> None:
    """Cada entrada de `services` respeta el contrato de campos."""
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse(SISTEMA_URL_NAME))

    assert response.status_code == status.HTTP_200_OK
    assert response.data["services"], "Debe haber al menos un servicio reportado"
    expected_service_fields = {"key", "label", "status", "latency_ms", "detail"}
    for service in response.data["services"]:
        assert set(service.keys()) == expected_service_fields

    service_keys = {service["key"] for service in response.data["services"]}
    assert service_keys == {"database", "redis", "celery_worker"}


def test_output_contract_version_has_exact_fields(db: Any, super_admin: Any) -> None:
    """El bloque `version` respeta el contrato de campos."""
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse(SISTEMA_URL_NAME))

    assert response.status_code == status.HTTP_200_OK
    expected_version_fields = {"commit", "django", "python", "environment"}
    assert set(response.data["version"].keys()) == expected_version_fields
    assert response.data["version"]["django"]
    assert response.data["version"]["python"]


def test_output_contract_pdf_queue_has_exact_fields(db: Any, super_admin: Any) -> None:
    """El bloque `pdf_queue` respeta el contrato de campos."""
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse(SISTEMA_URL_NAME))

    assert response.status_code == status.HTTP_200_OK
    expected_pdf_queue_fields = {"pending", "processing", "failed_24h"}
    assert set(response.data["pdf_queue"].keys()) == expected_pdf_queue_fields


# ---------------------------------------------------------------------------
# overall_status — matriz de estados
# ---------------------------------------------------------------------------


def test_overall_status_is_operational_when_everything_is_up(
    db: Any, super_admin: Any
) -> None:
    """Con BD real (up en test) + Redis/Celery mockeados operational → operational."""
    client = APIClient()
    client.force_authenticate(user=super_admin)

    with patch(
        "apps.plataforma.system_health._check_redis", side_effect=_operational_redis
    ), patch(
        "apps.plataforma.system_health._check_celery_worker",
        side_effect=_operational_celery,
    ):
        response = client.get(reverse(SISTEMA_URL_NAME))

    assert response.status_code == status.HTTP_200_OK
    assert response.data["overall_status"] == "operational"


def test_overall_status_is_degraded_when_redis_is_down(
    db: Any, super_admin: Any
) -> None:
    """BD arriba + Redis abajo + Celery arriba → degraded (no down)."""
    client = APIClient()
    client.force_authenticate(user=super_admin)

    with patch(
        "apps.plataforma.system_health._check_redis", side_effect=_down_redis
    ), patch(
        "apps.plataforma.system_health._check_celery_worker",
        side_effect=_operational_celery,
    ):
        response = client.get(reverse(SISTEMA_URL_NAME))

    assert response.status_code == status.HTTP_200_OK
    assert response.data["overall_status"] == "degraded"
    redis_entry = next(s for s in response.data["services"] if s["key"] == "redis")
    assert redis_entry["status"] == "down"


def test_overall_status_is_degraded_when_celery_is_down(
    db: Any, super_admin: Any
) -> None:
    """BD arriba + Redis arriba + Celery abajo → degraded (no down)."""
    client = APIClient()
    client.force_authenticate(user=super_admin)

    with patch(
        "apps.plataforma.system_health._check_redis", side_effect=_operational_redis
    ), patch(
        "apps.plataforma.system_health._check_celery_worker",
        side_effect=_down_celery,
    ):
        response = client.get(reverse(SISTEMA_URL_NAME))

    assert response.status_code == status.HTTP_200_OK
    assert response.data["overall_status"] == "degraded"


def test_overall_status_is_down_when_database_is_down(
    db: Any, super_admin: Any
) -> None:
    """BD abajo manda: overall_status es down sin importar Redis/Celery."""
    client = APIClient()
    client.force_authenticate(user=super_admin)

    with patch(
        "apps.plataforma.system_health._check_database", side_effect=_down_database
    ), patch(
        "apps.plataforma.system_health._check_redis", side_effect=_operational_redis
    ), patch(
        "apps.plataforma.system_health._check_celery_worker",
        side_effect=_operational_celery,
    ):
        response = client.get(reverse(SISTEMA_URL_NAME))

    assert response.status_code == status.HTTP_200_OK
    assert response.data["overall_status"] == "down"
    db_entry = next(s for s in response.data["services"] if s["key"] == "database")
    assert db_entry["status"] == "down"


def test_check_redis_internal_exception_is_caught_and_reported_as_down(
    db: Any, super_admin: Any
) -> None:
    """Una excepción DENTRO del cliente de Redis se traduce a status=down, sin 500."""
    client = APIClient()
    client.force_authenticate(user=super_admin)

    with patch(
        "django_redis.get_redis_connection", side_effect=RuntimeError("boom")
    ):
        response = client.get(reverse(SISTEMA_URL_NAME))

    assert response.status_code == status.HTTP_200_OK
    redis_entry = next(s for s in response.data["services"] if s["key"] == "redis")
    assert redis_entry["status"] == "down"
    assert response.data["overall_status"] == "degraded"


def test_down_detail_never_leaks_exception_text(db: Any, super_admin: Any) -> None:
    """El detail de un servicio caído es genérico: el texto de la excepción
    puede incluir hostname interno, puerto o usuario de la BD (redis-py y
    psycopg los incluyen) y solo debe ir a logs del servidor, nunca a la API."""
    from apps.plataforma.system_health import _GENERIC_DOWN_DETAIL

    client = APIClient()
    client.force_authenticate(user=super_admin)

    secreto = "redis-prod.railway.internal:6379 user=mailyuser"
    with patch(
        "django_redis.get_redis_connection", side_effect=RuntimeError(secreto)
    ):
        response = client.get(reverse(SISTEMA_URL_NAME))

    assert response.status_code == status.HTTP_200_OK
    redis_entry = next(s for s in response.data["services"] if s["key"] == "redis")
    assert redis_entry["detail"] == _GENERIC_DOWN_DETAIL
    assert secreto not in str(response.data)


# ---------------------------------------------------------------------------
# pdf_queue — conteos reales
# ---------------------------------------------------------------------------


def test_pdf_queue_counts_pending_processing_and_failed_24h(
    db: Any, super_admin: Any
) -> None:
    """pending/processing/failed_24h reflejan registros reales de PdfJob."""
    tenant = TenantFactory()

    PdfJob.all_objects.create(tenant=tenant, kind="book", status=PdfJob.Status.PENDING)
    PdfJob.all_objects.create(tenant=tenant, kind="book", status=PdfJob.Status.PENDING)
    PdfJob.all_objects.create(
        tenant=tenant, kind="quote", status=PdfJob.Status.PROCESSING
    )
    recent_failed = PdfJob.all_objects.create(
        tenant=tenant, kind="quote", status=PdfJob.Status.FAILED
    )
    # Fallido hace más de 24h: no debe contar en failed_24h.
    old_failed = PdfJob.all_objects.create(
        tenant=tenant, kind="quote", status=PdfJob.Status.FAILED
    )
    # updated_at usa auto_now=True: save() lo pisa siempre con "ahora", así
    # que se actualiza a nivel queryset (bypasea auto_now) para simular un
    # fallo ocurrido hace más de 24h.
    PdfJob.all_objects.filter(id=old_failed.id).update(
        updated_at=timezone.now() - timedelta(hours=30)
    )
    # DONE no debe contar en ninguno de los tres conteos.
    PdfJob.all_objects.create(tenant=tenant, kind="book", status=PdfJob.Status.DONE)

    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse(SISTEMA_URL_NAME))

    assert response.status_code == status.HTTP_200_OK
    assert response.data["pdf_queue"]["pending"] == 2
    assert response.data["pdf_queue"]["processing"] == 1
    assert response.data["pdf_queue"]["failed_24h"] == 1
    assert recent_failed.status == PdfJob.Status.FAILED
