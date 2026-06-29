"""
Selectors del dominio finanzas.

Lecturas/queries: NUNCA modifican datos. Las vistas que necesiten leer entidades
de finanzas deben pasar por aquí, nunca hacer queries directas.

El TenantManager (objects) filtra automáticamente por el tenant activo. Toda
agregación se hace con el ORM (Sum/Count/TruncDate) — cero N+1, sin SQL crudo.

Incluye los selectors analíticos:
  - account_statement_build: estado de cuenta de un paciente (movimientos + saldos).
  - finance_dashboard_metrics: KPIs + series para las gráficas interactivas.
  - finance_period_report: dataset completo para reporte de periodo (Fase 2).
  - finance_daily_sheet: cierre diario con movimientos del día (Fase 2).
"""

import datetime
import uuid
from decimal import Decimal
from typing import Any, Optional

from django.db.models import (
    Count,
    DecimalField,
    F,
    Q,
    QuerySet,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce, TruncDate, TruncWeek, TruncMonth
from django.utils import timezone

from apps.core.tenant_context import get_current_tenant
from apps.finanzas.cache import DASHBOARD_TTL, finance_cache_get_or_set
from apps.finanzas.models import (
    CfdiDocument,
    Charge,
    Payment,
    Quote,
    ServiceConcept,
)

ZERO = Decimal("0.00")
_DEC = DecimalField(max_digits=14, decimal_places=2)


def _sum(qs: QuerySet[Any], field: str) -> Decimal:
    """Suma un campo decimal de un queryset, devolviendo 0.00 si está vacío."""
    return qs.aggregate(
        total=Coalesce(Sum(field), Value(ZERO), output_field=_DEC)
    )["total"]


# ---------------------------------------------------------------------------
# Conceptos (catálogo)
# ---------------------------------------------------------------------------


def concept_get(*, concept_id: uuid.UUID) -> ServiceConcept:
    """Retorna un concepto cobrable por su UUID (filtrado por tenant activo).

    Raises:
        ServiceConcept.DoesNotExist: si no existe en el tenant activo.
    """
    return ServiceConcept.objects.get(id=concept_id)


def concept_list(*, only_active: bool = True) -> QuerySet[ServiceConcept]:
    """Retorna el catálogo de conceptos del tenant actual.

    Args:
        only_active: si True (default), excluye conceptos desactivados.
    """
    qs: QuerySet[ServiceConcept] = ServiceConcept.objects.all()
    if only_active:
        qs = qs.filter(is_active=True)
    return qs.order_by("name")


# ---------------------------------------------------------------------------
# Cotizaciones
# ---------------------------------------------------------------------------


def quote_get(*, quote_id: uuid.UUID) -> Quote:
    """Retorna una cotización por su UUID (con sus items precargados).

    Raises:
        Quote.DoesNotExist: si no existe en el tenant activo.
    """
    return Quote.objects.prefetch_related("items").get(id=quote_id)


def quote_list(
    *,
    patient_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
) -> QuerySet[Quote]:
    """Lista cotizaciones del tenant actual, con filtros opcionales.

    Args:
        patient_id: si se provee, filtra por paciente.
        status:     si se provee, filtra por estado (draft/sent/...).
    """
    qs: QuerySet[Quote] = Quote.objects.all()
    if patient_id is not None:
        qs = qs.filter(patient_id=patient_id)
    if status:
        qs = qs.filter(status=status)
    return qs.order_by("-created_at")


# ---------------------------------------------------------------------------
# Cargos
# ---------------------------------------------------------------------------


def charge_get(*, charge_id: uuid.UUID) -> Charge:
    """Retorna un cargo por su UUID (filtrado por tenant activo).

    Raises:
        Charge.DoesNotExist: si no existe en el tenant activo.
    """
    return Charge.objects.get(id=charge_id)


def charge_list(
    *,
    patient_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
    appointment_id: Optional[uuid.UUID] = None,
) -> QuerySet[Charge]:
    """Lista cargos del tenant actual, con filtros opcionales.

    Args:
        patient_id:     si se provee, filtra por paciente.
        status:         si se provee, filtra por estado (pending/partial/paid/cancelled).
        appointment_id: si se provee, filtra por la cita a la que está ligado el cargo.
                        Útil para el bloque «estado de cuenta de la visita» del libro.
    """
    qs: QuerySet[Charge] = Charge.objects.all()
    if patient_id is not None:
        qs = qs.filter(patient_id=patient_id)
    if status:
        qs = qs.filter(status=status)
    if appointment_id is not None:
        qs = qs.filter(appointment_id=appointment_id)
    return qs.order_by("-issued_at")


# ---------------------------------------------------------------------------
# Pagos
# ---------------------------------------------------------------------------


def payment_get(*, payment_id: uuid.UUID) -> Payment:
    """Retorna un pago por su UUID (con sus aplicaciones precargadas).

    Raises:
        Payment.DoesNotExist: si no existe en el tenant activo.
    """
    return Payment.objects.prefetch_related("allocations").get(id=payment_id)


def payment_list(
    *,
    patient_id: Optional[uuid.UUID] = None,
    method: Optional[str] = None,
) -> QuerySet[Payment]:
    """Lista pagos del tenant actual, con filtros opcionales."""
    qs: QuerySet[Payment] = Payment.objects.all()
    if patient_id is not None:
        qs = qs.filter(patient_id=patient_id)
    if method:
        qs = qs.filter(method=method)
    return qs.order_by("-received_at")


# ---------------------------------------------------------------------------
# CFDI
# ---------------------------------------------------------------------------


def cfdi_get(*, cfdi_id: uuid.UUID) -> CfdiDocument:
    """Retorna un CFDI por su UUID (filtrado por tenant activo).

    Raises:
        CfdiDocument.DoesNotExist: si no existe en el tenant activo.
    """
    return CfdiDocument.objects.get(id=cfdi_id)


def cfdi_list(
    *,
    patient_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
) -> QuerySet[CfdiDocument]:
    """Lista comprobantes CFDI del tenant actual, con filtros opcionales."""
    qs: QuerySet[CfdiDocument] = CfdiDocument.objects.all()
    if patient_id is not None:
        qs = qs.filter(patient_id=patient_id)
    if status:
        qs = qs.filter(status=status)
    return qs.order_by("-created_at")


# ---------------------------------------------------------------------------
# Estado de cuenta
# ---------------------------------------------------------------------------


def account_statement_build(
    *,
    patient_id: uuid.UUID,
    date_from: Optional[datetime.date] = None,
    date_to: Optional[datetime.date] = None,
) -> dict[str, Any]:
    """Construye el estado de cuenta de un paciente en un rango de fechas.

    Combina cargos (débitos) y pagos (créditos) ordenados cronológicamente y
    calcula el saldo corriente. Devuelve también totales para el apartado visual.

    Args:
        patient_id: paciente del estado de cuenta.
        date_from:  fecha inicial inclusiva (opcional).
        date_to:    fecha final inclusiva (opcional).

    Returns:
        dict con:
          - movements: lista de movimientos {date, type, description, charge,
            payment, balance} ordenada por fecha con saldo corriente.
          - total_charged / total_paid / balance: totales del rango.
          - charges_count / payments_count.
    """
    charges_qs = charge_list(patient_id=patient_id).exclude(
        status=Charge.Status.CANCELLED
    )
    payments_qs = payment_list(patient_id=patient_id)

    if date_from is not None:
        charges_qs = charges_qs.filter(issued_at__date__gte=date_from)
        payments_qs = payments_qs.filter(received_at__date__gte=date_from)
    if date_to is not None:
        charges_qs = charges_qs.filter(issued_at__date__lte=date_to)
        payments_qs = payments_qs.filter(received_at__date__lte=date_to)

    # Construir movimientos unificados (débito = cargo, crédito = pago).
    movements: list[dict[str, Any]] = []
    for charge in charges_qs:
        movements.append(
            {
                "at": charge.issued_at,
                "type": "charge",
                "description": charge.description,
                "charge": charge.amount,
                "payment": ZERO,
                "reference": "",
                "id": str(charge.id),
            }
        )
    for payment in payments_qs:
        movements.append(
            {
                "at": payment.received_at,
                "type": "payment",
                "description": f"Pago ({payment.get_method_display()})",
                "charge": ZERO,
                "payment": payment.amount,
                "reference": payment.reference,
                "id": str(payment.id),
            }
        )

    # Orden cronológico y cálculo del saldo corriente.
    movements.sort(key=lambda m: m["at"])
    running = ZERO
    for mov in movements:
        running = running + mov["charge"] - mov["payment"]
        mov["balance"] = running
        # Serializar la fecha a ISO para la respuesta JSON.
        mov["date"] = mov.pop("at").isoformat()

    total_charged = _sum(charges_qs, "amount")
    total_paid = _sum(payments_qs, "amount")

    return {
        "movements": movements,
        "total_charged": total_charged,
        "total_paid": total_paid,
        "balance": total_charged - total_paid,
        "charges_count": charges_qs.count(),
        "payments_count": payments_qs.count(),
    }


# ---------------------------------------------------------------------------
# Dashboard (métricas + series para gráficas interactivas)
# ---------------------------------------------------------------------------


def finance_dashboard_metrics(
    *,
    date_from: Optional[datetime.date] = None,
    date_to: Optional[datetime.date] = None,
) -> dict[str, Any]:
    """Calcula KPIs y series para el panel financiero del tenant actual.

    Todas las series están pensadas para alimentar gráficas interactivas con
    drill-down (cada punto/segmento mapea a un filtro de la tabla del frontend).

    Rango por defecto: últimos 30 días si no se especifica.

    Returns:
        dict con:
          - range: {date_from, date_to}
          - kpis: {total_income, total_charged, outstanding, average_ticket,
                   collection_rate, payments_count}
          - income_by_day:    [{date, amount}]      (gráfica de ingresos por periodo)
          - income_by_concept:[{concept, amount}]   (barras por concepto)
          - income_by_method: [{method, label, amount, count}] (dona por método)
          - aging:            [{bucket, amount, count}] (barras apiladas de CxC)
          - quotes_funnel:    {sent, accepted, rejected, draft, expired, conversion_rate}

    Resultado cacheado en Redis por (tenant, rango) con TTL de seguridad; se
    invalida al crear/editar/borrar Payment/Charge/Quote (ver apps.finanzas.cache).
    """
    today = timezone.now().date()
    if date_to is None:
        date_to = today
    if date_from is None:
        date_from = date_to - datetime.timedelta(days=30)

    tenant = get_current_tenant()
    if tenant is None:
        # Sin contexto de tenant (p. ej. management command) → sin caché.
        return _finance_dashboard_compute(date_from=date_from, date_to=date_to)
    return finance_cache_get_or_set(
        tenant_id=tenant.id,
        suffix=f"dash:{date_from.isoformat()}:{date_to.isoformat()}",
        ttl=DASHBOARD_TTL,
        compute=lambda: _finance_dashboard_compute(date_from=date_from, date_to=date_to),
    )


def _finance_dashboard_compute(
    *, date_from: datetime.date, date_to: datetime.date
) -> dict[str, Any]:
    """Computa las métricas del dashboard (sin caché). Rango ya normalizado."""
    today = timezone.now().date()
    payments_qs = Payment.objects.filter(
        received_at__date__gte=date_from,
        received_at__date__lte=date_to,
    )
    charges_qs = Charge.objects.filter(
        issued_at__date__gte=date_from,
        issued_at__date__lte=date_to,
    ).exclude(status=Charge.Status.CANCELLED)

    total_income = _sum(payments_qs, "amount")
    total_charged = _sum(charges_qs, "amount")
    payments_count = payments_qs.count()
    average_ticket = (total_income / payments_count) if payments_count else ZERO

    # Saldo pendiente global (todas las CxC abiertas, sin filtrar por fecha).
    outstanding_qs = Charge.objects.filter(
        status__in=[Charge.Status.PENDING, Charge.Status.PARTIAL]
    )
    outstanding = outstanding_qs.aggregate(
        total=Coalesce(
            Sum(F("amount") - F("amount_paid"), output_field=_DEC),
            Value(ZERO),
            output_field=_DEC,
        )
    )["total"]

    collection_rate = (
        (total_income / total_charged) if total_charged > ZERO else ZERO
    )

    # --- Serie: ingresos por día ---
    income_by_day = [
        {"date": row["day"].isoformat(), "amount": row["amount"]}
        for row in payments_qs.annotate(day=TruncDate("received_at"))
        .values("day")
        .annotate(amount=Coalesce(Sum("amount"), Value(ZERO), output_field=_DEC))
        .order_by("day")
    ]

    # --- Serie: ingresos por concepto (desde cargos del rango) ---
    income_by_concept = [
        {"concept": row["description"], "amount": row["amount"]}
        for row in charges_qs.values("description")
        .annotate(amount=Coalesce(Sum("amount"), Value(ZERO), output_field=_DEC))
        .order_by("-amount")[:12]
    ]

    # --- Serie: ingresos por método de pago ---
    method_labels = dict(Payment.Method.choices)
    income_by_method = [
        {
            "method": row["method"],
            "label": method_labels.get(row["method"], row["method"]),
            "amount": row["amount"],
            "count": row["count"],
        }
        for row in payments_qs.values("method")
        .annotate(
            amount=Coalesce(Sum("amount"), Value(ZERO), output_field=_DEC),
            count=Count("id"),
        )
        .order_by("-amount")
    ]

    # --- Serie: aging de cuentas por cobrar (0-30 / 31-60 / 61-90 / 90+) ---
    aging = _aging_buckets(outstanding_qs, today=today)

    # --- Embudo de cotizaciones ---
    quotes_funnel = _quotes_funnel(date_from=date_from, date_to=date_to)

    return {
        "range": {"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
        "kpis": {
            "total_income": total_income,
            "total_charged": total_charged,
            "outstanding": outstanding,
            "average_ticket": average_ticket,
            "collection_rate": collection_rate,
            "payments_count": payments_count,
        },
        "income_by_day": income_by_day,
        "income_by_concept": income_by_concept,
        "income_by_method": income_by_method,
        "aging": aging,
        "quotes_funnel": quotes_funnel,
    }


def _aging_buckets(
    outstanding_qs: QuerySet[Charge],
    *,
    today: datetime.date,
) -> list[dict[str, Any]]:
    """Agrupa el saldo pendiente en buckets de antigüedad por issued_at."""
    buckets = [
        ("0-30", today - datetime.timedelta(days=30), None),
        ("31-60", today - datetime.timedelta(days=60), today - datetime.timedelta(days=30)),
        ("61-90", today - datetime.timedelta(days=90), today - datetime.timedelta(days=60)),
        ("90+", None, today - datetime.timedelta(days=90)),
    ]
    result: list[dict[str, Any]] = []
    for label, gte, lt in buckets:
        qs = outstanding_qs
        if gte is not None:
            qs = qs.filter(issued_at__date__gte=gte)
        if lt is not None:
            qs = qs.filter(issued_at__date__lt=lt)
        amount = qs.aggregate(
            total=Coalesce(
                Sum(F("amount") - F("amount_paid"), output_field=_DEC),
                Value(ZERO),
                output_field=_DEC,
            )
        )["total"]
        result.append({"bucket": label, "amount": amount, "count": qs.count()})
    return result


def _quotes_funnel(
    *,
    date_from: datetime.date,
    date_to: datetime.date,
) -> dict[str, Any]:
    """Conteo de cotizaciones por estado en el rango + tasa de conversión."""
    qs = Quote.objects.filter(
        created_at__date__gte=date_from,
        created_at__date__lte=date_to,
    )
    counts = {row["status"]: row["n"] for row in qs.values("status").annotate(n=Count("id"))}
    sent = counts.get(Quote.Status.SENT, 0)
    accepted = counts.get(Quote.Status.ACCEPTED, 0)
    # Denominador de conversión: enviadas + aceptadas + rechazadas + vencidas.
    decided = (
        sent
        + accepted
        + counts.get(Quote.Status.REJECTED, 0)
        + counts.get(Quote.Status.EXPIRED, 0)
    )
    conversion_rate = (accepted / decided) if decided else 0.0
    return {
        "draft": counts.get(Quote.Status.DRAFT, 0),
        "sent": sent,
        "accepted": accepted,
        "rejected": counts.get(Quote.Status.REJECTED, 0),
        "expired": counts.get(Quote.Status.EXPIRED, 0),
        "conversion_rate": round(conversion_rate, 4),
    }


# ---------------------------------------------------------------------------
# Fase 2 — Reporte de periodo
# ---------------------------------------------------------------------------

# Agrupaciones de serie temporal soportadas.
_GROUP_TRUNC: dict[str, Any] = {
    "day": TruncDate,
    "week": TruncWeek,
    "month": TruncMonth,
}

# Nº máximo de servicios en el ranking (top-N).
_TOP_SERVICES = 15


def finance_period_report(
    *,
    date_from: datetime.date,
    date_to: datetime.date,
    group: str = "day",
) -> dict[str, Any]:
    """Dataset completo de métricas para el reporte financiero de un periodo.

    Todas las agregaciones se ejecutan en base de datos (aggregate/annotate). No hay
    bucles Python sobre resultados grandes; los buckets de aging usan filtros separados
    (4 queries ligeras en lugar de una iteración en memoria).

    El selector AMPLIA (no duplica) el dashboard existente:
      - Agrega serie temporal agrupable (day/week/month).
      - Agrega comparativa con el periodo inmediatamente anterior (mismo tamaño).
      - Agrega por doctor (via appointment__doctor cuando Charge.appointment no es None).
      - Ticket promedio = producción / nº de cargos (no de pacientes): es la métrica
        de «precio por servicio» más relevante para una clínica de actos médicos.

    Métricas incluidas:
      range              — Fechas del periodo actual.
      prev_range         — Fechas del periodo anterior (mismo tamaño, inmediatamente anterior).
      production         — Suma de Charge.amount (sin CANCELLED) en el periodo.
      collection         — Suma de Payment.amount recibidos en el periodo.
      collection_pct     — collection / production (porcentaje de cobranza).
      ar_total           — Saldo pendiente global (A/R: todos los Charges con balance>0).
      aging              — A/R desglosado en 0-30 / 31-60 / 61-90 / 90+ días.
      average_ticket     — production / nº de cargos del periodo.
      prev_production    — Producción del periodo anterior.
      prev_collection    — Cobranza del periodo anterior.
      prev_collection_pct — % cobranza del periodo anterior.
      delta_production_pct — Δ% de producción vs periodo anterior.
      delta_collection_pct — Δ% de cobranza vs periodo anterior.
      delta_collection_rate_ppt — Δ puntos porcentuales de collection_pct.
      by_method          — [{method, label, amount, count}] por método de pago.
      by_service         — [{concept_id, name, amount, count}] top servicios (cargos).
      by_doctor          — [{doctor_id, name, amount, count}] por doctor (solo si hay appointment).
      series             — [{period, production, collection}] agrupado por group.
      adjustments_note   — str: nota sobre ajustes (no hay modelo Adjustment aún).

    Args:
        date_from: Inicio del periodo (inclusivo).
        date_to:   Fin del periodo (inclusivo).
        group:     Granularidad de la serie temporal: 'day' | 'week' | 'month'.

    Returns:
        dict con todos los campos descritos arriba.

    Resultado cacheado en Redis por (tenant, rango, group); se invalida igual que el
    dashboard al escribir Payment/Charge/Quote (ver apps.finanzas.cache).
    """
    tenant = get_current_tenant()
    if tenant is None:
        return _finance_period_report_compute(
            date_from=date_from, date_to=date_to, group=group
        )
    return finance_cache_get_or_set(
        tenant_id=tenant.id,
        suffix=f"report:{date_from.isoformat()}:{date_to.isoformat()}:{group}",
        ttl=DASHBOARD_TTL,
        compute=lambda: _finance_period_report_compute(
            date_from=date_from, date_to=date_to, group=group
        ),
    )


def _finance_period_report_compute(
    *, date_from: datetime.date, date_to: datetime.date, group: str = "day"
) -> dict[str, Any]:
    """Computa el dataset del reporte de periodo (sin caché)."""
    if group not in _GROUP_TRUNC:
        group = "day"

    today = timezone.now().date()
    delta = (date_to - date_from).days + 1  # días en el periodo actual

    # --- Periodo anterior (mismo tamaño, inmediatamente anterior) ---
    prev_date_to = date_from - datetime.timedelta(days=1)
    prev_date_from = prev_date_to - datetime.timedelta(days=delta - 1)

    # --- Querysets base del periodo actual ---
    charges_qs = Charge.objects.filter(
        issued_at__date__gte=date_from,
        issued_at__date__lte=date_to,
    ).exclude(status=Charge.Status.CANCELLED)

    payments_qs = Payment.objects.filter(
        received_at__date__gte=date_from,
        received_at__date__lte=date_to,
    )

    # --- Querysets base del periodo anterior ---
    prev_charges_qs = Charge.objects.filter(
        issued_at__date__gte=prev_date_from,
        issued_at__date__lte=prev_date_to,
    ).exclude(status=Charge.Status.CANCELLED)

    prev_payments_qs = Payment.objects.filter(
        received_at__date__gte=prev_date_from,
        received_at__date__lte=prev_date_to,
    )

    # --- KPIs periodo actual ---
    production = _sum(charges_qs, "amount")
    collection = _sum(payments_qs, "amount")
    charges_count = charges_qs.count()
    collection_pct = (collection / production) if production > ZERO else ZERO
    average_ticket = (production / charges_count) if charges_count else ZERO

    # --- KPIs periodo anterior ---
    prev_production = _sum(prev_charges_qs, "amount")
    prev_collection = _sum(prev_payments_qs, "amount")
    prev_collection_pct = (
        (prev_collection / prev_production) if prev_production > ZERO else ZERO
    )

    # --- Δ% ---
    def _delta_pct(current: Decimal, previous: Decimal) -> Optional[Decimal]:
        """Variación % respecto al periodo anterior; None si anterior es cero."""
        if previous == ZERO:
            return None
        return round(((current - previous) / previous) * Decimal("100"), 2)

    delta_production_pct = _delta_pct(production, prev_production)
    delta_collection_pct = _delta_pct(collection, prev_collection)
    # Δ en puntos porcentuales del collection rate.
    delta_collection_rate_ppt: Optional[Decimal] = round(
        collection_pct - prev_collection_pct, 4
    )

    # --- A/R total (todos los cargos con saldo > 0, sin filtro de fecha) ---
    outstanding_qs = Charge.objects.filter(
        status__in=[Charge.Status.PENDING, Charge.Status.PARTIAL]
    )
    ar_total = outstanding_qs.aggregate(
        total=Coalesce(
            Sum(F("amount") - F("amount_paid"), output_field=_DEC),
            Value(ZERO),
            output_field=_DEC,
        )
    )["total"]

    # --- Aging ---
    aging = _aging_buckets(outstanding_qs, today=today)

    # --- Por método de pago ---
    method_labels = dict(Payment.Method.choices)
    by_method = [
        {
            "method": row["method"],
            "label": method_labels.get(row["method"], row["method"]),
            "amount": row["amount"],
            "count": row["count"],
        }
        for row in payments_qs.values("method")
        .annotate(
            amount=Coalesce(Sum("amount"), Value(ZERO), output_field=_DEC),
            count=Count("id"),
        )
        .order_by("-amount")
    ]

    # --- Top servicios por producción (cargos del periodo) ---
    # Nota: usamos concept_id y description (snapshot).  Cuando concept es NULL
    # agrupamos por descripción tal como llega (snapshot del nombre al crear el cargo).
    by_service_raw = (
        charges_qs.values("concept_id", "description")
        .annotate(
            amount=Coalesce(Sum("amount"), Value(ZERO), output_field=_DEC),
            count=Count("id"),
        )
        .order_by("-amount")[:_TOP_SERVICES]
    )
    by_service = [
        {
            "concept_id": str(row["concept_id"]) if row["concept_id"] else None,
            "name": row["description"],
            "amount": row["amount"],
            "count": row["count"],
        }
        for row in by_service_raw
    ]

    # --- Por doctor (via appointment__doctor) ---
    # Solo aplica a cargos que tienen appointment seteado y cuyo appointment tiene doctor.
    # Cargos sin appointment (cobros manuales, cotizaciones) quedan en "sin doctor".
    by_doctor = _by_doctor(charges_qs)

    # --- Serie temporal ---
    trunc_fn = _GROUP_TRUNC[group]
    series_charges = list(
        charges_qs.annotate(period=trunc_fn("issued_at"))
        .values("period")
        .annotate(amount=Coalesce(Sum("amount"), Value(ZERO), output_field=_DEC))
        .order_by("period")
    )
    series_payments = list(
        payments_qs.annotate(period=trunc_fn("received_at"))
        .values("period")
        .annotate(amount=Coalesce(Sum("amount"), Value(ZERO), output_field=_DEC))
        .order_by("period")
    )
    # Unificar en un dict indexado por periodo (date-safe).
    series_map: dict[str, dict[str, Any]] = {}
    for row in series_charges:
        key = row["period"].isoformat() if row["period"] else ""
        if key:
            series_map.setdefault(key, {"period": key, "production": ZERO, "collection": ZERO})
            series_map[key]["production"] = row["amount"]
    for row in series_payments:
        key = row["period"].isoformat() if row["period"] else ""
        if key:
            series_map.setdefault(key, {"period": key, "production": ZERO, "collection": ZERO})
            series_map[key]["collection"] = row["amount"]
    series = sorted(series_map.values(), key=lambda x: x["period"])

    return {
        "range": {"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
        "prev_range": {
            "date_from": prev_date_from.isoformat(),
            "date_to": prev_date_to.isoformat(),
        },
        "group": group,
        # KPIs actuales
        "production": production,
        "collection": collection,
        "collection_pct": collection_pct,
        "ar_total": ar_total,
        "aging": aging,
        "average_ticket": average_ticket,
        "charges_count": charges_count,
        # Comparativa
        "prev_production": prev_production,
        "prev_collection": prev_collection,
        "prev_collection_pct": prev_collection_pct,
        "delta_production_pct": delta_production_pct,
        "delta_collection_pct": delta_collection_pct,
        "delta_collection_rate_ppt": delta_collection_rate_ppt,
        # Desglose
        "by_method": by_method,
        "by_service": by_service,
        "by_doctor": by_doctor,
        "series": series,
        # Nota sobre ajustes — no hay modelo Adjustment aún (plan §4 lo define como
        # trabajo futuro). Se reporta 0 con nota explicativa.
        "adjustments_total": ZERO,
        "adjustments_note": (
            "El modelo Adjustment no está implementado aún (plan §4 Fase 2). "
            "Se reporta 0. Cuando exista, se sumará aquí."
        ),
    }


def _by_doctor(charges_qs: QuerySet["Charge"]) -> list[dict[str, Any]]:
    """Agrega producción por doctor a partir de charges que tienen appointment.

    Usa appointment__doctor (FK transitiva limpia). Los cargos sin appointment
    se agrupan como 'sin_doctor'. La FK doctor→membership→user es necesaria
    solo para el nombre; la precargamos via annotation para evitar N+1.

    Returns:
        lista [{doctor_id, name, amount, count}], ordenada por amount desc.
    """
    from apps.agenda.models import Appointment  # noqa: PLC0415 — importación tardía para evitar circular

    # Cargos con doctor (tienen appointment_id seteado).
    with_doctor = (
        charges_qs.filter(appointment__isnull=False)
        .values(
            doctor_id=F("appointment__doctor__id"),
            first=F("appointment__doctor__membership__user__first_name"),
            last=F("appointment__doctor__membership__user__last_name"),
        )
        .annotate(
            amount=Coalesce(Sum("amount"), Value(ZERO), output_field=_DEC),
            count=Count("id"),
        )
        .order_by("-amount")
    )

    result: list[dict[str, Any]] = [
        {
            "doctor_id": str(row["doctor_id"]) if row["doctor_id"] else None,
            "name": f"{row['first']} {row['last']}".strip() or "Doctor sin nombre",
            "amount": row["amount"],
            "count": row["count"],
        }
        for row in with_doctor
    ]

    # Cargos sin appointment (cobros manuales) — agrupados como bloque.
    without_agg = charges_qs.filter(appointment__isnull=True).aggregate(
        amount=Coalesce(Sum("amount"), Value(ZERO), output_field=_DEC),
        count=Count("id"),
    )
    if without_agg["count"] > 0:
        result.append(
            {
                "doctor_id": None,
                "name": "Sin cita (cobro manual / cotización)",
                "amount": without_agg["amount"],
                "count": without_agg["count"],
            }
        )

    return result


# ---------------------------------------------------------------------------
# Fase 2 — Cierre diario (day sheet)
# ---------------------------------------------------------------------------


def finance_daily_sheet(*, date: datetime.date) -> dict[str, Any]:
    """Cierre diario de caja para una fecha concreta.

    Devuelve producción, cobranza y ajustes del día, desglose por método de pago,
    y la lista de movimientos (cargos + pagos) ordenados cronológicamente.

    El «cierre» es de solo lectura: el servicio no crea ningún registro ni bloquea
    la fecha. La lista de movimientos incluye todos los registros del día para que
    la recepción o el administrador impriman o revisen el resumen al cerrar.

    Nota: adjustments_total = 0 (no hay modelo Adjustment aún — plan §4 Fase 2).

    Args:
        date: Fecha del cierre (local; se filtra por __date__ contra el campo UTC).

    Returns:
        dict con:
          - date: ISO de la fecha del cierre.
          - production: suma de Charge.amount del día (sin CANCELLED).
          - collection: suma de Payment.amount del día.
          - adjustments_total: 0 (sin modelo Adjustment aún).
          - collection_pct: porcentaje de cobranza sobre producción.
          - by_method: [{method, label, amount, count}] del día.
          - movements: lista cronológica de movimientos {at, type, ref, amount}.
          - totals: resumen {charges_count, payments_count, production, collection}.
    """
    charges_qs = Charge.objects.filter(
        issued_at__date=date
    ).exclude(status=Charge.Status.CANCELLED)

    payments_qs = Payment.objects.filter(received_at__date=date)

    production = _sum(charges_qs, "amount")
    collection = _sum(payments_qs, "amount")
    collection_pct = (collection / production) if production > ZERO else ZERO

    # Desglose por método.
    method_labels = dict(Payment.Method.choices)
    by_method = [
        {
            "method": row["method"],
            "label": method_labels.get(row["method"], row["method"]),
            "amount": row["amount"],
            "count": row["count"],
        }
        for row in payments_qs.values("method")
        .annotate(
            amount=Coalesce(Sum("amount"), Value(ZERO), output_field=_DEC),
            count=Count("id"),
        )
        .order_by("-amount")
    ]

    # Lista de movimientos del día (cargos y pagos juntos, orden cronológico).
    movements: list[dict[str, Any]] = []
    for charge in charges_qs.select_related("patient").order_by("issued_at"):
        movements.append(
            {
                "at": charge.issued_at.isoformat(),
                "type": "charge",
                "description": charge.description,
                "patient_id": str(charge.patient_id),
                "amount": charge.amount,
                "status": charge.status,
            }
        )
    for payment in payments_qs.select_related("patient").order_by("received_at"):
        movements.append(
            {
                "at": payment.received_at.isoformat(),
                "type": "payment",
                "method": payment.method,
                "method_label": method_labels.get(payment.method, payment.method),
                "patient_id": str(payment.patient_id),
                "amount": payment.amount,
                "reference": payment.reference,
            }
        )
    movements.sort(key=lambda m: m["at"])

    return {
        "date": date.isoformat(),
        "production": production,
        "collection": collection,
        "adjustments_total": ZERO,
        "collection_pct": collection_pct,
        "by_method": by_method,
        "movements": movements,
        "totals": {
            "charges_count": charges_qs.count(),
            "payments_count": payments_qs.count(),
            "production": production,
            "collection": collection,
        },
    }
