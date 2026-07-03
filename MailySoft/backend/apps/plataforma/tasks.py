"""
Tarea Celery beat de la app plataforma.

avisar_vencimientos — SOLO AVISA de trials y periodos de suscripción vencidos.

DECISIÓN DE NEGOCIO (dueño, 2026-07-02): la suspensión/cancelación de una
clínica vencida es MANUAL. Esta tarea NUNCA cambia Tenant.status ni ningún
otro estado operativo: únicamente registra un evento de auditoría
(TRIAL_EXPIRED / SUBSCRIPTION_EXPIRED) para que el super-admin/sales lo vea
en el portal y decida qué hacer.

IDEMPOTENCIA:
    Cada aviso se marca con una columna *_notified_at. Correr la tarea dos
    veces el mismo día (o el mismo minuto) NO duplica eventos de auditoría:
    - Tenant.trial_expired_notified_at
    - TenantSubscription.period_expired_notified_at
    Ambas se resetean a None cuando se extiende el trial o se renueva la
    suscripción con una fecha futura (ver tenant_subscription_set), así una
    extensión SÍ vuelve a poder avisar si vuelve a vencer.

CONTEXTO DE TENANT EN CELERY:
    El worker corre sin request HTTP. Tenant y TenantSubscription NO son
    TenantAwareModel (ver docstrings en apps/tenancy/models.py), así que no
    hay TenantManager que resolver ni GUC que setear: se consultan con el
    Manager estándar (`Tenant.objects`, `TenantSubscription.objects`)
    directamente, igual que en los selectors de plataforma.

PERFORMANCE (reviewer, Fase 3):
    El UPDATE de las columnas *_notified_at se acumula en una lista y se
    aplica con un único bulk_update() por función, en vez de un save() fila
    por fila. bulk_update() NO dispara auto_now, así que updated_at se
    setea a mano con el mismo `reference_now` usado para el marcado de
    idempotencia. audit_record() se queda dentro del loop a propósito: cada
    vencimiento sigue generando su propio evento de auditoría individual.
"""

import logging

from celery import shared_task
from django.utils.timezone import now

from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.tenancy.models import Tenant, TenantSubscription

logger = logging.getLogger("apps.plataforma.tasks")


@shared_task
def avisar_vencimientos() -> dict[str, int]:
    """Registra avisos de auditoría para trials y periodos vencidos. No suspende nada.

    Returns:
        Dict con conteos {"trials_avisados": int, "periodos_avisados": int}
        para trazabilidad en logs/beat.
    """
    trials_avisados = _avisar_trials_vencidos()
    periodos_avisados = _avisar_periodos_vencidos()

    logger.info(
        "avisar_vencimientos: trials_avisados=%s periodos_avisados=%s",
        trials_avisados,
        periodos_avisados,
    )
    return {"trials_avisados": trials_avisados, "periodos_avisados": periodos_avisados}


def _avisar_trials_vencidos() -> int:
    """Avisa (auditoría TRIAL_EXPIRED) los trials vencidos no avisados aún.

    Condición de idempotencia: trial_expired_notified_at is NULL, o quedó
    marcado ANTES del trial_ends_at actual (cubre el caso de una extensión de
    trial: se movió trial_ends_at hacia adelante después del último aviso,
    así que si vuelve a vencer debe poder avisar de nuevo).

    Performance: el audit_record() se queda dentro del loop (un evento de
    auditoría por vencimiento), pero el UPDATE de trial_expired_notified_at
    se acumula y se aplica con un único bulk_update() al final en vez de un
    save() por fila. bulk_update() NO dispara auto_now, así que updated_at
    se setea a mano con el mismo reference_now usado para el marcado.
    """
    reference_now = now()
    candidatos = list(
        Tenant.objects.filter(
            status=Tenant.Status.TRIAL,
            trial_ends_at__lt=reference_now,
        )
    )

    pendientes: list[Tenant] = []
    for tenant in candidatos:
        if (
            tenant.trial_expired_notified_at is not None
            and tenant.trial_expired_notified_at >= tenant.trial_ends_at
        ):
            continue  # ya avisado para este vencimiento concreto

        audit_record(
            action=ActionType.TRIAL_EXPIRED,
            resource_type="Tenant",
            actor=None,
            tenant=None,  # evento de plataforma, no de la clínica misma
            resource_id=tenant.id,
            resource_repr=str(tenant),
            description=(
                f"El periodo de prueba de la clínica '{tenant.name}' "
                f"(slug='{tenant.slug}') venció el {tenant.trial_ends_at:%Y-%m-%d %H:%M}. "
                "Aviso automático: la suspensión es manual."
            ),
            metadata={
                "tenant_id": str(tenant.id),
                "tenant_slug": tenant.slug,
                "trial_ends_at": tenant.trial_ends_at.isoformat(),
            },
        )
        tenant.trial_expired_notified_at = reference_now
        tenant.updated_at = reference_now
        pendientes.append(tenant)

    if pendientes:
        Tenant.objects.bulk_update(pendientes, ["trial_expired_notified_at", "updated_at"])

    return len(pendientes)


def _avisar_periodos_vencidos() -> int:
    """Avisa (auditoría SUBSCRIPTION_EXPIRED) los periodos de suscripción vencidos.

    Misma lógica de idempotencia que los trials, pero comparando fechas
    (current_period_end es DateField) en vez de datetimes.

    Performance: mismo patrón que _avisar_trials_vencidos — audit_record()
    dentro del loop (un evento por vencimiento) y el UPDATE de
    period_expired_notified_at acumulado en un único bulk_update() al final.
    bulk_update() NO dispara auto_now: updated_at se setea a mano.
    """
    reference_now = now()
    today = reference_now.date()

    candidatos = list(
        TenantSubscription.objects.select_related("tenant", "plan").filter(
            current_period_end__lt=today,
        )
    )

    pendientes: list[TenantSubscription] = []
    for subscription in candidatos:
        if (
            subscription.period_expired_notified_at is not None
            and subscription.period_expired_notified_at.date() >= subscription.current_period_end
        ):
            continue  # ya avisado para este vencimiento concreto

        tenant = subscription.tenant
        audit_record(
            action=ActionType.SUBSCRIPTION_EXPIRED,
            resource_type="TenantSubscription",
            actor=None,
            tenant=None,  # evento de plataforma, no de la clínica misma
            resource_id=subscription.id,
            resource_repr=str(subscription),
            description=(
                f"El periodo de suscripción de la clínica '{tenant.name}' "
                f"(slug='{tenant.slug}', plan='{subscription.plan.slug}') venció el "
                f"{subscription.current_period_end:%Y-%m-%d}. "
                "Aviso automático: la suspensión es manual."
            ),
            metadata={
                "tenant_id": str(tenant.id),
                "tenant_slug": tenant.slug,
                "plan_slug": subscription.plan.slug,
                "current_period_end": subscription.current_period_end.isoformat(),
            },
        )
        subscription.period_expired_notified_at = reference_now
        subscription.updated_at = reference_now
        pendientes.append(subscription)

    if pendientes:
        TenantSubscription.objects.bulk_update(
            pendientes, ["period_expired_notified_at", "updated_at"]
        )

    return len(pendientes)
