"""
Selectors del dominio finanzas.

Lecturas/queries: NUNCA modifican datos. Las vistas que necesiten leer entidades
de finanzas deben pasar por aquí, nunca hacer queries directas.

El TenantManager (objects) filtra automáticamente por el tenant activo. Toda
agregación se hace con el ORM (Sum/Count/TruncDate) — cero N+1, sin SQL crudo.

Incluye los selectors analíticos:
  - account_statement_build: estado de cuenta de un paciente (movimientos + saldos).
  - finance_dashboard_metrics: KPIs + series para las gráficas interactivas.
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
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from apps.finanzas.models import (
    CfdiDocument,
    Charge,
    ClinicFiscalConfig,
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
) -> QuerySet[Charge]:
    """Lista cargos del tenant actual, con filtros opcionales."""
    qs: QuerySet[Charge] = Charge.objects.all()
    if patient_id is not None:
        qs = qs.filter(patient_id=patient_id)
    if status:
        qs = qs.filter(status=status)
    return qs.order_by("-issued_at")


def charges_outstanding(*, patient_id: uuid.UUID) -> QuerySet[Charge]:
    """Cargos con saldo pendiente de un paciente (pending o partial).

    Útil para que payment_register sepa qué liquidar por antigüedad.
    """
    return (
        Charge.objects.filter(
            patient_id=patient_id,
            status__in=[Charge.Status.PENDING, Charge.Status.PARTIAL],
        )
        .order_by("issued_at")
    )


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
# Config fiscal
# ---------------------------------------------------------------------------


def fiscal_config_get_or_none() -> Optional[ClinicFiscalConfig]:
    """Retorna la configuración fiscal del tenant actual, o None si no existe."""
    return ClinicFiscalConfig.objects.first()


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
    """
    today = timezone.now().date()
    if date_to is None:
        date_to = today
    if date_from is None:
        date_from = date_to - datetime.timedelta(days=30)

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
