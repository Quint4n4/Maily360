"""
Orquestación de salud del sistema para el panel interno de plataforma.

Usado por GET /api/v1/plataforma/sistema/ (Fase 2 del plan de plataforma,
docs/design/plataforma-fases-plan.md). Sustituye la maqueta de la SistemaPage
del frontend por datos reales de infraestructura.

Diseño:
  - No es un selector puro (no lee de un modelo del dominio de negocio) ni un
    service de escritura: es orquestación de checks contra servicios externos
    (BD, Redis, Celery) + un selector real (cola de PdfJob). Por eso vive en
    su propio módulo dentro de apps/plataforma en vez de selectors.py/services.py.
  - Cada check está aislado con try/except: la caída de UN servicio nunca debe
    tirar el endpoint completo. El endpoint siempre responde 200 con el estado
    real (operational/degraded/down) de cada pieza.
  - Nunca se hardcodean URLs/credenciales: Redis se resuelve con la conexión
    que ya usa el proyecto (django_redis, alias "default", configurada por
    settings.CACHES con la env var REDIS_URL) y Celery con la app del proyecto
    (config.celery.app), que ya lee CELERY_BROKER_URL de settings.
"""

import logging
import os
import platform
import time
from datetime import timedelta
from typing import Any, Literal

import django
from django.conf import settings
from django.db import connection, transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.pdfs.models import PdfJob

logger = logging.getLogger("apps.plataforma.system_health")

ServiceStatus = Literal["operational", "degraded", "down"]
OverallStatus = Literal["operational", "degraded", "down"]

#: Timeout corto para no colgar el endpoint si Redis/Celery no responden.
_REDIS_PING_TIMEOUT_SECONDS: float = 2.0
_CELERY_PING_TIMEOUT_SECONDS: float = 2.0
#: Tope del SELECT 1 (SET LOCAL): connect_timeout no cubre una conexión ya
#: establecida pero colgada; sin esto el check de BD no tendría cota superior.
_DB_STATEMENT_TIMEOUT_MS: int = 3000

#: El texto crudo de una excepción de psycopg/redis-py puede incluir hostname
#: interno, puerto y hasta el usuario de la BD. Eso va SOLO a logs del servidor
#: (exc_info=True); a la API viaja este mensaje genérico (OWASP ASVS V7.4).
_GENERIC_DOWN_DETAIL: str = "Sin conexión. Revisa los logs del servidor para el detalle."


def _check_database() -> dict[str, Any]:
    """Ping a PostgreSQL con `SELECT 1`, cronometrado.

    Returns:
        Dict con key/label/status/latency_ms/detail listo para el serializer.
    """
    started_at = time.perf_counter()
    try:
        # SET LOCAL vive solo dentro de esta transacción: acota el SELECT 1 sin
        # alterar el statement_timeout de la conexión compartida (CONN_MAX_AGE).
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(f"SET LOCAL statement_timeout = {_DB_STATEMENT_TIMEOUT_MS}")
            cursor.execute("SELECT 1")
            cursor.fetchone()
        latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
        return {
            "key": "database",
            "label": "PostgreSQL",
            "status": "operational",
            "latency_ms": latency_ms,
            "detail": None,
        }
    except Exception as exc:  # noqa: BLE001 — un check aislado nunca debe tirar el endpoint.
        logger.error("system_health: database check falló — %s", exc, exc_info=True)
        return {
            "key": "database",
            "label": "PostgreSQL",
            "status": "down",
            "latency_ms": None,
            "detail": _GENERIC_DOWN_DETAIL,
        }


def _check_redis() -> dict[str, Any]:
    """Ping a Redis usando la conexión ya configurada por django-redis (cache "default").

    No se construye ninguna URL a mano: se reutiliza settings.CACHES, que ya
    lee REDIS_URL vía env(). Esto cubre el broker de Celery/cache/channels,
    que en este proyecto son la misma instancia de Redis.
    """
    started_at = time.perf_counter()
    try:
        from django_redis import get_redis_connection  # noqa: PLC0415

        client = get_redis_connection("default")
        client.ping()
        latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
        return {
            "key": "redis",
            "label": "Redis",
            "status": "operational",
            "latency_ms": latency_ms,
            "detail": None,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("system_health: redis check falló — %s", exc, exc_info=True)
        return {
            "key": "redis",
            "label": "Redis",
            "status": "down",
            "latency_ms": None,
            "detail": _GENERIC_DOWN_DETAIL,
        }


def _check_celery_worker() -> dict[str, Any]:
    """Ping a los workers de Celery vía `app.control.ping()`.

    operational si responde al menos un worker, down si ninguno responde o el
    broker no está disponible. No mide latencia individual (el ping agrega
    respuestas de N workers), solo cuenta cuántos contestaron dentro del timeout.
    """
    try:
        from config.celery import app as celery_app  # noqa: PLC0415

        replies: list[dict[str, Any]] = celery_app.control.ping(
            timeout=_CELERY_PING_TIMEOUT_SECONDS
        )
        worker_count = len(replies)
        if worker_count > 0:
            return {
                "key": "celery_worker",
                "label": "Worker Celery",
                "status": "operational",
                "latency_ms": None,
                "detail": f"{worker_count} worker(s) activo(s)",
            }
        return {
            "key": "celery_worker",
            "label": "Worker Celery",
            "status": "down",
            "latency_ms": None,
            "detail": "0 worker(s) activo(s)",
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("system_health: celery check falló — %s", exc, exc_info=True)
        return {
            "key": "celery_worker",
            "label": "Worker Celery",
            "status": "down",
            "latency_ms": None,
            "detail": _GENERIC_DOWN_DETAIL,
        }


def _compute_overall_status(services: list[dict[str, Any]]) -> OverallStatus:
    """Calcula el estado global a partir del estado de cada servicio.

    Regla (fijada en el contrato con el frontend):
      - "down" si la base de datos está down (sin BD no hay sistema).
      - "degraded" si cualquier OTRO servicio no está operational.
      - "operational" si todos los servicios están operational.
    """
    by_key = {service["key"]: service["status"] for service in services}
    if by_key.get("database") == "down":
        return "down"
    if any(status != "operational" for status in by_key.values()):
        return "degraded"
    return "operational"


def _resolve_version() -> dict[str, Any]:
    """Arma el bloque `version` de la respuesta.

    commit: variable de entorno RAILWAY_GIT_COMMIT_SHA si existe (Railway la
        inyecta en cada deploy); None si no está presente. Nunca se ejecuta
        `git` en runtime (el proceso en producción no tiene el repo .git).
    environment: SENTRY_ENVIRONMENT (ya usada por el proyecto para distinguir
        development/production) con fallback derivado de settings.DEBUG.
    """
    commit: str | None = os.environ.get("RAILWAY_GIT_COMMIT_SHA") or None
    if commit:
        commit = commit[:12]

    environment: str = os.environ.get("SENTRY_ENVIRONMENT") or (
        "development" if settings.DEBUG else "production"
    )

    return {
        "commit": commit,
        "django": django.get_version(),
        "python": platform.python_version(),
        "environment": environment,
    }


def _resolve_pdf_queue() -> dict[str, int]:
    """Conteos reales de la cola de PdfJob (cross-tenant, vía all_objects).

    pending: jobs en PENDING (aún no tomados por un worker).
    processing: jobs en PROCESSING (worker trabajando en ellos ahora).
    failed_24h: jobs en FAILED cuya actualización ocurrió en las últimas 24h
        (updated_at, que se toca en la tarea al marcar el fallo).
    """
    since = timezone.now() - timedelta(hours=24)
    # Una sola query agregada en vez de tres .count() (el panel refresca cada 30s).
    counts = PdfJob.all_objects.aggregate(
        pending=Count("id", filter=Q(status=PdfJob.Status.PENDING)),
        processing=Count("id", filter=Q(status=PdfJob.Status.PROCESSING)),
        failed_24h=Count(
            "id", filter=Q(status=PdfJob.Status.FAILED, updated_at__gte=since)
        ),
    )
    return {
        "pending": counts["pending"],
        "processing": counts["processing"],
        "failed_24h": counts["failed_24h"],
    }


def system_health_get() -> dict[str, Any]:
    """Arma el snapshot completo de salud del sistema para el panel de plataforma.

    Cada check está aislado: si uno falla, los demás se siguen evaluando y el
    resultado siempre es un dict completo y serializable (nunca lanza).

    Returns:
        Dict con generated_at/overall_status/services/version/pdf_queue,
        listo para SystemHealthOutputSerializer.
    """
    services = [
        _check_database(),
        _check_redis(),
        _check_celery_worker(),
    ]

    try:
        pdf_queue = _resolve_pdf_queue()
    except Exception as exc:  # noqa: BLE001 — la cola de PDFs no debe tirar el endpoint.
        logger.error("system_health: pdf_queue check falló — %s", exc, exc_info=True)
        pdf_queue = {"pending": 0, "processing": 0, "failed_24h": 0}

    return {
        "generated_at": timezone.now(),
        "overall_status": _compute_overall_status(services),
        "services": services,
        "version": _resolve_version(),
        "pdf_queue": pdf_queue,
    }
