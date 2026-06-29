"""
Generación de fechas para series de citas recurrentes (multi-cita).

Lógica pura de calendario para calcular las fechas de una serie según su
frecuencia (semanal/quincenal/mensual/personalizada). Sin acceso a BD ni a
modelos. Extraído de agenda/services.py; appointment_create_series consume
`_generate_series_starts` y `_SERIES_MAX_OCCURRENCES`.
"""

import calendar
import datetime
from typing import Optional

from django.core.exceptions import ValidationError

#: Frecuencias de repetición soportadas (mirror del frontend).
SERIES_WEEKLY = "weekly"
SERIES_BIWEEKLY = "biweekly"
SERIES_MONTHLY = "monthly"
SERIES_CUSTOM = "custom"
_SERIES_FREQUENCIES: frozenset[str] = frozenset(
    {SERIES_WEEKLY, SERIES_BIWEEKLY, SERIES_MONTHLY, SERIES_CUSTOM}
)

#: Tope de seguridad: nunca se generan más de estas citas en una serie.
_SERIES_MAX_OCCURRENCES = 52


def _add_one_month(d: datetime.datetime) -> datetime.datetime:
    """Suma un mes calendario, recortando el día al último válido (31 ene → 28 feb)."""
    month = d.month + 1
    year = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return d.replace(year=year, month=month, day=min(d.day, last_day))


def _series_step(
    d: datetime.datetime, *, frequency: str, interval_days: Optional[int]
) -> datetime.datetime:
    """Avanza una fecha al siguiente turno de la serie según la frecuencia."""
    if frequency == SERIES_WEEKLY:
        return d + datetime.timedelta(days=7)
    if frequency == SERIES_BIWEEKLY:
        return d + datetime.timedelta(days=14)
    if frequency == SERIES_MONTHLY:
        return _add_one_month(d)
    # custom
    return d + datetime.timedelta(days=interval_days or 0)


def _generate_series_starts(
    *,
    starts_at: datetime.datetime,
    frequency: str,
    interval_days: Optional[int],
    count: Optional[int],
    until: Optional[datetime.date],
) -> list[datetime.datetime]:
    """Genera las fechas de inicio de la serie (la primera es `starts_at`).

    Tope debe darse por `count` (número total de citas) O por `until` (fecha
    límite), exactamente uno. Limitado por _SERIES_MAX_OCCURRENCES.
    """
    if frequency not in _SERIES_FREQUENCIES:
        raise ValidationError(f"Frecuencia de repetición inválida: '{frequency}'.")
    if frequency == SERIES_CUSTOM and (not interval_days or interval_days < 1):
        raise ValidationError(
            "Para repetición personalizada indica cada cuántos días (≥ 1)."
        )
    if (count is None) == (until is None):
        raise ValidationError(
            "Indica exactamente uno: número de repeticiones o fecha límite."
        )
    if count is not None and count < 2:
        raise ValidationError("Una serie debe tener al menos 2 citas.")

    starts: list[datetime.datetime] = [starts_at]
    cur = starts_at
    while len(starts) < _SERIES_MAX_OCCURRENCES:
        if count is not None and len(starts) >= count:
            break
        cur = _series_step(cur, frequency=frequency, interval_days=interval_days)
        if until is not None and cur.date() > until:
            break
        starts.append(cur)
    return starts
