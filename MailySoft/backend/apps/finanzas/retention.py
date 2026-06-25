"""
Analítica de retención de pacientes (Fase 3 — RFM).

Selector principal: ``retention_panel_build``.
Calcula en VIVO (sin tabla intermedia) métricas RFM por paciente del tenant activo.
No crea ni modifica ningún registro; es solo lectura.

Decisión D-3 (plan §3): mismo patrón que el ledger derivado; el cálculo vive aquí y
se ejecuta en BD con aggregate/annotate para evitar N+1 y cargas en memoria.
Decisión D-7 (plan §8): solo visualización — NO envía nada.

---
Definición de segmentos y umbrales (benchmark mercado dental/médico):
──────────────────────────────────────────────────────────────────────
• nuevo        : paciente cuya PRIMERA cita atendida fue en los últimos 3 meses
                 (< NEW_PATIENT_DAYS = 90 días desde la primera cita ATTENDED).
• vip          : gasto_12m en el top VIP_TOP_PCT % del tenant Y recencia < VIP_RECENCY_DAYS Y
                 frecuencia_12m ≥ VIP_MIN_VISITS.
• frecuente    : frecuencia_12m ≥ FREQUENT_MIN_VISITS Y recencia < FREQUENT_RECENCY_DAYS
                 (y no clasificado como vip ni nuevo).
• en_riesgo    : tenía ≥ AT_RISK_MIN_PAST_VISITS citas atendidas en los 12-24 meses anteriores
                 pero sin ninguna en los últimos AT_RISK_WINDOW_DAYS días.
• perdido      : sin ninguna cita ATTENDED en los últimos LOST_DAYS días (12 meses).
• ocasional    : el resto.

Constantes documentadas con su fuente:
  NEW_PATIENT_DAYS = 90      → benchmark Jane App / SimplePractice "new patient window".
  VIP_TOP_PCT      = 0.20    → top 20 % por gasto (Dentrix Magazine / Pearly).
  VIP_RECENCY_DAYS = 180     → <6 meses (RevenueWell / Clerri).
  VIP_MIN_VISITS   = 2       → ≥2 visitas/año.
  FREQUENT_MIN_VISITS  = 2   → ≥2 visitas/año (Cliniko benchmark).
  FREQUENT_RECENCY_DAYS = 180 → <6 meses.
  AT_RISK_WINDOW_DAYS  = 150  → ≥5 meses sin visita (promedio Tebra/Kareo 4-6 m).
  AT_RISK_MIN_PAST_VISITS = 2 → era regular (≥2 citas en el año previo).
  LOST_DAYS = 365             → sin visita en 12 meses (CleverTap / DoctorLogic).

Métrica de retención (tasa de retención):
  retención = (pacientes con ≥1 cita ATTENDED en los últimos 12m) /
              (pacientes con ≥1 cita ATTENDED en los últimos 13 a 24m)
  Fuente: Dentrix Magazine "patient retention = patients seen this year / patients
  seen last year". Solo se calcula si hay pacientes en el denominador.

Monetary: se usa ``Payment.amount`` (cobros reales recibidos) de los últimos 12 meses
  vinculados al paciente, como proxy del valor real cobrado.  Alternativa (Charge.amount)
  representaría producción facturada sin importar si se cobró — el plan menciona ambas,
  se elige Payment para medir ingresos reales (documentado aquí).

Paginación: las listas ``at_risk`` y ``lost`` están limitadas a ``MAX_ACTIONABLE = 500``
  registros (cap documentado). La respuesta incluye ``total_at_risk`` y ``total_lost``
  para que el frontend muestre cuántos hay en total aunque la lista esté truncada.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any, Optional

from django.db.models import (
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    FloatField,
    Max,
    Min,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce, Now
from django.utils import timezone

from apps.agenda.models import Appointment
from apps.finanzas.models import Payment

# ---------------------------------------------------------------------------
# Constantes / umbrales de segmentación
# ---------------------------------------------------------------------------

#: Ventana (días) para considerar a un paciente como NUEVO (desde su 1.ª cita atendida).
NEW_PATIENT_DAYS: int = 90

#: Top % por gasto (12 m) para calificar como VIP.
VIP_TOP_PCT: float = 0.20

#: Días máximos de recencia para VIP.
VIP_RECENCY_DAYS: int = 180

#: Mínimo de visitas en los últimos 12 meses para VIP.
VIP_MIN_VISITS: int = 2

#: Mínimo de visitas en los últimos 12 meses para FRECUENTE.
FREQUENT_MIN_VISITS: int = 2

#: Días máximos de recencia para FRECUENTE.
FREQUENT_RECENCY_DAYS: int = 180

#: Días sin visita para calificar como EN RIESGO (eje: >5 meses).
AT_RISK_WINDOW_DAYS: int = 150

#: Mínimo de citas atendidas en los 12-24 meses previos para ser "antes regular".
AT_RISK_MIN_PAST_VISITS: int = 2

#: Días sin visita para ser PERDIDO (12 meses).
LOST_DAYS: int = 365

#: Nº máximo de entradas en las listas accionables (at_risk + lost).
MAX_ACTIONABLE: int = 500

ZERO = Decimal("0.00")
_DEC = DecimalField(max_digits=14, decimal_places=2)


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _today() -> datetime.date:
    """Retorna la fecha actual (UTC)."""
    return timezone.now().date()


def _date_threshold(days: int) -> datetime.date:
    """Retorna `hoy - days` días."""
    return _today() - datetime.timedelta(days=days)


def _attended_qs(*, tenant_id: Any) -> QuerySet[Appointment]:
    """Queryset de citas ATTENDED del tenant (filtrado por tenant_id directo, no por TenantManager)."""
    return Appointment.objects.filter(
        tenant_id=tenant_id,
        status=Appointment.Status.ATTENDED,
        deleted_at__isnull=True,
    )


# ---------------------------------------------------------------------------
# Cálculo RFM por paciente — core de la analítica
# ---------------------------------------------------------------------------


def _rfm_rows(*, tenant_id: Any, today: datetime.date) -> list[dict[str, Any]]:
    """Devuelve un dict por paciente con recency/frequency/monetary calculados en BD.

    Usa una sola query que agrega Appointment (attended) y luego enriquece con
    Payment de los últimos 12 meses via subquery para evitar JOIN cartesiano.

    Estrategia:
      1. Aggregar citas ATTENDED por paciente → last_attended, first_attended, freq_12m.
      2. Anotar recency_days = (today - last_attended).days.
      3. Enriquecer con spent_12m via Subquery de Payment.

    NO usa TenantManager de Appointment (aislamiento garantizado por tenant_id explícito
    en el filtro, lo que también previene que el contexto del manager interfiera con
    las aggregaciones cross-manager en tests).
    """
    cutoff_12m = today - datetime.timedelta(days=365)

    attended_base = _attended_qs(tenant_id=tenant_id)

    # Sub-query de pagos de los últimos 12m por paciente.
    payment_sq = (
        Payment.objects.filter(
            tenant_id=tenant_id,
            patient_id=OuterRef("patient_id"),
            deleted_at__isnull=True,
            received_at__date__gte=cutoff_12m,
        )
        .values("patient_id")
        .annotate(total=Coalesce(Sum("amount"), Value(ZERO), output_field=_DEC))
        .values("total")
    )

    rows = (
        attended_base.values("patient_id")
        .annotate(
            last_attended=Max("starts_at"),
            first_attended=Min("starts_at"),
            freq_12m=Count(
                "id",
                filter=Q(starts_at__date__gte=cutoff_12m),
            ),
            spent_12m=Coalesce(
                Subquery(payment_sq[:1]),
                Value(ZERO),
                output_field=_DEC,
            ),
        )
        .values(
            "patient_id",
            "last_attended",
            "first_attended",
            "freq_12m",
            "spent_12m",
        )
    )

    today_dt = datetime.datetime.combine(today, datetime.time.min, tzinfo=datetime.timezone.utc)

    result: list[dict[str, Any]] = []
    for row in rows:
        last = row["last_attended"]
        first = row["first_attended"]
        recency_days: int = max(0, (today_dt - last).days) if last else LOST_DAYS + 1
        is_new_patient: bool = bool(first and (today_dt - first).days < NEW_PATIENT_DAYS)

        result.append(
            {
                "patient_id": row["patient_id"],
                "last_attended": last,
                "first_attended": first,
                "recency_days": recency_days,
                "freq_12m": row["freq_12m"],
                "spent_12m": row["spent_12m"],
                "is_new_patient": is_new_patient,
            }
        )

    return result


def _compute_vip_threshold(rows: list[dict[str, Any]]) -> Decimal:
    """Calcula el umbral mínimo de gasto para el top VIP_TOP_PCT %.

    Ordena los gastos de mayor a menor y retorna el valor del corte. Si no hay
    pacientes, retorna ZERO (nadie califica como VIP).
    """
    if not rows:
        return ZERO
    sorted_spent = sorted((r["spent_12m"] for r in rows), reverse=True)
    cutoff_idx = max(0, int(len(sorted_spent) * VIP_TOP_PCT) - 1)
    threshold = sorted_spent[cutoff_idx]
    # Si el threshold es ZERO nadie califica automáticamente (evitar falsos VIP sin gasto).
    return threshold


def _classify_segment(
    *,
    row: dict[str, Any],
    vip_threshold: Decimal,
    today: datetime.date,
) -> str:
    """Clasifica un paciente en su segmento RFM.

    El orden de evaluación importa (de más restrictivo a menos):
    nuevo > vip > frecuente > en_riesgo > perdido > ocasional.
    """
    recency = row["recency_days"]
    freq = row["freq_12m"]
    spent = row["spent_12m"]
    is_new = row["is_new_patient"]

    # --- NUEVO ---
    if is_new:
        return "nuevo"

    # --- PERDIDO ---
    if recency >= LOST_DAYS:
        return "perdido"

    # --- VIP ---
    if (
        spent > ZERO
        and spent >= vip_threshold
        and recency < VIP_RECENCY_DAYS
        and freq >= VIP_MIN_VISITS
    ):
        return "vip"

    # --- FRECUENTE ---
    if freq >= FREQUENT_MIN_VISITS and recency < FREQUENT_RECENCY_DAYS:
        return "frecuente"

    # --- EN RIESGO ---
    # "antes regular": ≥ AT_RISK_MIN_PAST_VISITS en los 12-24 meses previos;
    # ahora sin visita en los últimos AT_RISK_WINDOW_DAYS días.
    if recency >= AT_RISK_WINDOW_DAYS:
        # Verificar si tenía visitas en el año anterior (12-24m atrás).
        # Este dato no está en `row`; la función `retention_panel_build` lo precalcula
        # y lo inyecta como `past_visits_count`. Si no está disponible usamos una heurística:
        # si freq_12m == 0 pero last_attended existe (recency < LOST_DAYS), asumimos
        # que tenía historial previo. Para mayor precisión, la función principal
        # inyecta `past_visits` en el row antes de clasificar.
        past_visits: int = row.get("past_visits_count", 0)
        if past_visits >= AT_RISK_MIN_PAST_VISITS:
            return "en_riesgo"

    # --- OCASIONAL ---
    return "ocasional"


# ---------------------------------------------------------------------------
# Selector público
# ---------------------------------------------------------------------------


def retention_panel_build(*, tenant_id: Any) -> dict[str, Any]:
    """Construye el panel de retención RFM del tenant en vivo.

    Calcula RFM por paciente (solo lectura, sin modificar nada), clasifica en
    segmentos y devuelve distribución, listas accionables y métricas.

    Todas las queries importantes ocurren en BD. El único bucle Python itera
    el resultado agregado (tamaño = nº de pacientes activos, razonable para una clínica).

    Args:
        tenant_id: UUID del tenant activo (pasado explícito para evitar dependencia
                   del TenantManager en un contexto de selector).

    Returns:
        dict con:
          segments         — {nuevo, vip, frecuente, en_riesgo, perdido, ocasional}: conteo.
          at_risk_list     — lista de hasta MAX_ACTIONABLE pacientes en_riesgo con contacto.
          lost_list        — ídem para perdidos.
          total_at_risk    — conteo real de en_riesgo (puede superar MAX_ACTIONABLE).
          total_lost       — conteo real de perdidos.
          truncated        — True si alguna lista fue truncada.
          metrics          — {retention_rate, avg_ticket, no_show_rate, pct_with_future_appt}.
    """
    today = _today()
    cutoff_12m = today - datetime.timedelta(days=365)

    # -----------------------------------------------------------------------
    # 1. Datos RFM por paciente (attended_qs)
    # -----------------------------------------------------------------------
    rows = _rfm_rows(tenant_id=tenant_id, today=today)

    # -----------------------------------------------------------------------
    # 2. Precalcular visitas en el rango 12-24m atrás (para "en_riesgo")
    # -----------------------------------------------------------------------
    cutoff_24m = today - datetime.timedelta(days=730)

    past_visits_qs = (
        _attended_qs(tenant_id=tenant_id)
        .filter(
            starts_at__date__lt=cutoff_12m,
            starts_at__date__gte=cutoff_24m,
        )
        .values("patient_id")
        .annotate(past_count=Count("id"))
    )
    past_visits_map: dict[Any, int] = {
        r["patient_id"]: r["past_count"] for r in past_visits_qs
    }

    # Inyectar `past_visits_count` en cada row antes de clasificar.
    for row in rows:
        row["past_visits_count"] = past_visits_map.get(row["patient_id"], 0)

    # -----------------------------------------------------------------------
    # 3. Calcular umbral VIP y clasificar cada paciente
    # -----------------------------------------------------------------------
    vip_threshold = _compute_vip_threshold(rows)

    segments_count: dict[str, int] = {
        "nuevo": 0,
        "vip": 0,
        "frecuente": 0,
        "en_riesgo": 0,
        "perdido": 0,
        "ocasional": 0,
    }
    at_risk_ids: list[Any] = []
    lost_ids: list[Any] = []

    for row in rows:
        seg = _classify_segment(row=row, vip_threshold=vip_threshold, today=today)
        segments_count[seg] += 1
        if seg == "en_riesgo":
            at_risk_ids.append(row["patient_id"])
        elif seg == "perdido":
            lost_ids.append(row["patient_id"])

    # -----------------------------------------------------------------------
    # 4. Construir listas accionables (nombre + contacto + última visita + gasto_12m)
    #    Solo lee datos ya filtrados por patient_id — sin tocar pacientes/migrations.
    # -----------------------------------------------------------------------
    # Mapa rápido de patient_id → row para enriquecer las listas accionables.
    row_by_patient: dict[Any, dict[str, Any]] = {r["patient_id"]: r for r in rows}

    total_at_risk = len(at_risk_ids)
    total_lost = len(lost_ids)
    truncated = total_at_risk > MAX_ACTIONABLE or total_lost > MAX_ACTIONABLE

    at_risk_ids_capped = at_risk_ids[:MAX_ACTIONABLE]
    lost_ids_capped = lost_ids[:MAX_ACTIONABLE]

    def _build_actionable_list(patient_ids: list[Any]) -> list[dict[str, Any]]:
        """Carga nombre y contacto de los pacientes de la lista accionable.

        Importación tardía del modelo Patient para evitar importación circular
        y cumplir la restricción de no modificar apps/pacientes.
        """
        if not patient_ids:
            return []

        from apps.pacientes.models import Patient  # noqa: PLC0415

        # Un único SELECT con solo los campos necesarios (sin N+1).
        patients = Patient.objects.filter(
            id__in=patient_ids,
            tenant_id=tenant_id,
            deleted_at__isnull=True,
        ).values("id", "first_name", "paternal_surname", "maternal_surname", "phone", "email")

        result: list[dict[str, Any]] = []
        for p in patients:
            pid = p["id"]
            rfm = row_by_patient.get(pid, {})
            last_dt = rfm.get("last_attended")
            result.append(
                {
                    "patient_id": str(pid),
                    "full_name": f"{p['first_name']} {p['paternal_surname']} {p['maternal_surname']}".strip(),
                    "phone": p["phone"] or "",
                    "email": p["email"] or "",
                    "last_visited": last_dt.date().isoformat() if last_dt else None,
                    "recency_days": rfm.get("recency_days"),
                    "spent_12m": rfm.get("spent_12m", ZERO),
                    "freq_12m": rfm.get("freq_12m", 0),
                }
            )
        return result

    at_risk_list = _build_actionable_list(at_risk_ids_capped)
    lost_list = _build_actionable_list(lost_ids_capped)

    # -----------------------------------------------------------------------
    # 5. Métricas globales (todas en BD)
    # -----------------------------------------------------------------------
    metrics = _compute_metrics(tenant_id=tenant_id, today=today)

    return {
        "segments": segments_count,
        "at_risk_list": at_risk_list,
        "lost_list": lost_list,
        "total_at_risk": total_at_risk,
        "total_lost": total_lost,
        "truncated": truncated,
        "metrics": metrics,
    }


def _compute_metrics(*, tenant_id: Any, today: datetime.date) -> dict[str, Any]:
    """Calcula métricas de retención, ticket, no-show y % con próxima cita.

    Todas las queries son en BD — sin bucles Python sobre filas individuales.

    Métricas:
      retention_rate       — pacientes vistos en los últimos 12m /
                             pacientes vistos en los 12-24m anteriores.
                             None si el denominador es 0.
      avg_ticket           — Payment.amount promedio de los últimos 12m (por pago).
      no_show_rate         — citas NO_SHOW / (NO_SHOW + ATTENDED) de los últimos 12m.
                             None si no hay citas en ese rango.
      pct_with_future_appt — % de pacientes activos (vistos en 12m) que tienen
                             al menos 1 cita futura SCHEDULED o CONFIRMED.
    """
    cutoff_12m = today - datetime.timedelta(days=365)
    cutoff_24m = today - datetime.timedelta(days=730)

    appts_12m = Appointment.objects.filter(
        tenant_id=tenant_id,
        deleted_at__isnull=True,
        starts_at__date__gte=cutoff_12m,
        starts_at__date__lte=today,
    )

    appts_prev_12m = Appointment.objects.filter(
        tenant_id=tenant_id,
        deleted_at__isnull=True,
        starts_at__date__gte=cutoff_24m,
        starts_at__date__lt=cutoff_12m,
    )

    # --- Tasa de retención ---
    patients_this_year: int = (
        appts_12m.filter(status=Appointment.Status.ATTENDED)
        .values("patient_id")
        .distinct()
        .count()
    )
    patients_prev_year: int = (
        appts_prev_12m.filter(status=Appointment.Status.ATTENDED)
        .values("patient_id")
        .distinct()
        .count()
    )
    retention_rate: Optional[float] = (
        round(patients_this_year / patients_prev_year, 4)
        if patients_prev_year > 0
        else None
    )

    # --- Ticket promedio (payment promedio de los últimos 12m) ---
    payments_12m = Payment.objects.filter(
        tenant_id=tenant_id,
        deleted_at__isnull=True,
        received_at__date__gte=cutoff_12m,
    )
    pay_agg = payments_12m.aggregate(
        total=Coalesce(Sum("amount"), Value(ZERO), output_field=_DEC),
        count=Count("id"),
    )
    avg_ticket: Decimal = (
        round(pay_agg["total"] / pay_agg["count"], 2)
        if pay_agg["count"] > 0
        else ZERO
    )

    # --- No-show rate (citas del último año) ---
    no_show_agg = appts_12m.filter(
        status__in=[Appointment.Status.NO_SHOW, Appointment.Status.ATTENDED]
    ).aggregate(
        no_show=Count("id", filter=Q(status=Appointment.Status.NO_SHOW)),
        total=Count("id"),
    )
    no_show_rate: Optional[float] = (
        round(no_show_agg["no_show"] / no_show_agg["total"], 4)
        if no_show_agg["total"] > 0
        else None
    )

    # --- % pacientes activos con próxima cita futura ---
    # "Activos" = al menos 1 cita ATTENDED en los últimos 12m.
    active_patient_ids = set(
        appts_12m.filter(status=Appointment.Status.ATTENDED)
        .values_list("patient_id", flat=True)
        .distinct()
    )
    total_active = len(active_patient_ids)

    with_future: int = 0
    if active_patient_ids:
        with_future = (
            Appointment.objects.filter(
                tenant_id=tenant_id,
                deleted_at__isnull=True,
                patient_id__in=active_patient_ids,
                starts_at__date__gt=today,
                status__in=[
                    Appointment.Status.SCHEDULED,
                    Appointment.Status.CONFIRMED,
                ],
            )
            .values("patient_id")
            .distinct()
            .count()
        )

    pct_with_future_appt: Optional[float] = (
        round(with_future / total_active, 4) if total_active > 0 else None
    )

    return {
        "retention_rate": retention_rate,
        "avg_ticket": avg_ticket,
        "no_show_rate": no_show_rate,
        "pct_with_future_appt": pct_with_future_appt,
        "patients_seen_12m": patients_this_year,
        "patients_seen_prev_12m": patients_prev_year,
    }
