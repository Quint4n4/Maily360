"""
Selectors de la app pacientes.

Lecturas/queries: NUNCA modifican datos. Las vistas y servicios que necesiten
leer pacientes deben pasar por aquí, nunca hacer queries directas en views.

El TenantManager (objects) filtra automáticamente por el tenant activo en el
thread-local cuando context_active=True. En el contexto de un request HTTP, esto
garantiza que nunca se lean datos de otra clínica.
"""

import datetime
import uuid
from typing import Optional

from django.conf import settings
from django.db.models import Count, Exists, Max, OuterRef, Q, QuerySet
from django.utils import timezone

from apps.pacientes.models import Patient


# Valores de estado de citas (importados directamente desde el modelo para
# evitar dependencia circular en nivel de módulo; la app agenda puede importar
# pacientes, pero no al revés a nivel top-level).
_ATTENDED = "attended"
_CANCELLED = "cancelled"


def patient_get(*, patient_id: uuid.UUID) -> Patient:
    """Retorna un paciente por su UUID.

    Usa el TenantManager (filtra por tenant del contexto activo).
    Lanza Patient.DoesNotExist si no existe o no pertenece al tenant activo.
    Las vistas deben capturar DoesNotExist y devolver 404.

    Args:
        patient_id: UUID del paciente a recuperar.

    Returns:
        Instancia de Patient.

    Raises:
        Patient.DoesNotExist: si el paciente no existe en el tenant activo.
    """
    return Patient.objects.get(id=patient_id)


def patient_list(
    *,
    search: Optional[str] = "",
    segment: str = "all",
    date_from: Optional[datetime.date] = None,
    date_to: Optional[datetime.date] = None,
    category_id: Optional[uuid.UUID] = None,
) -> QuerySet[Patient]:
    """Retorna el QuerySet de pacientes activos del tenant actual con anotaciones estadísticas.

    Aplica filtros de búsqueda libre y segmento de clasificación. La paginación
    la aplica la vista.

    Anotaciones que agrega siempre (disponibles en cada objeto del QuerySet):
      - last_seen:         Max datetime de citas con status=attended del paciente.
      - attended_count:    Número de citas atendidas.
      - cancelled_count:   Número de citas canceladas.
      - rescheduled_count: Número de citas que fueron reagendadas al menos una vez.

    Segmentos disponibles:
      "all"       — todos los pacientes activos (orden -created_at).
      "recent"    — pacientes con al menos una cita atendida (orden -last_seen).
      "week"      — atendidos en la semana calendario actual (lunes–domingo, zona local).
      "month"     — atendidos en el mes calendario actual.
      "date"      — atendidos entre date_from y date_to inclusive (ambos requeridos).
      "potential" — nunca atendidos pero con citas canceladas o reagendadas.
      "favorites" — con la etiqueta de sistema Favorito (categories kind=favorite).
      "vip"       — con la etiqueta de sistema VIP (categories kind=vip).

    Args:
        search:    Término de búsqueda libre (icontains sobre nombre, apellidos,
                   teléfono, número de expediente). Vacío = sin filtro de búsqueda.
        segment:   Código del segmento (ver arriba). Desconocido → tratado como "all".
        date_from: Fecha de inicio del rango (solo para segment="date").
        date_to:   Fecha de fin del rango, inclusive (solo para segment="date").
        category_id: Si se provee, filtra los pacientes que tengan esa etiqueta
                   del catálogo asignada (combinable con el segmento).

    Returns:
        QuerySet[Patient] anotado, filtrado y ordenado. Sin paginar.
    """
    # Importación diferida para evitar dependencia circular en el módulo: agenda
    # importa pacientes, no al revés en top-level.
    from apps.agenda.models import Appointment  # noqa: PLC0415

    # Base: pacientes activos del tenant activo (TenantManager filtra por tenant).
    # prefetch_related("categories") evita N+1 al serializar las etiquetas.
    qs: QuerySet[Patient] = Patient.objects.filter(is_active=True).prefetch_related("categories")

    # Filtro de búsqueda libre (igual al selector original).
    if search:
        # TODO(perf): cuando el volumen de pacientes supere ~50k por tenant,
        # considerar índice pg_trgm (GIN) sobre first_name + paternal_surname
        # para búsqueda full-text eficiente. Ver: CREATE EXTENSION IF NOT EXISTS pg_trgm.
        qs = qs.filter(
            Q(first_name__icontains=search)
            | Q(paternal_surname__icontains=search)
            | Q(maternal_surname__icontains=search)
            | Q(phone__icontains=search)
            | Q(record_number__icontains=search)
        )

    # Anotaciones estadísticas: se calculan SIEMPRE para que los serializers
    # puedan leer los atributos con getattr sin fallar en el endpoint de detalle.
    qs = qs.annotate(
        last_seen=Max(
            "appointments__starts_at",
            filter=Q(appointments__status=_ATTENDED),
        ),
        attended_count=Count(
            "appointments",
            filter=Q(appointments__status=_ATTENDED),
            distinct=True,
        ),
        cancelled_count=Count(
            "appointments",
            filter=Q(appointments__status=_CANCELLED),
            distinct=True,
        ),
        rescheduled_count=Count(
            "appointments",
            filter=Q(appointments__reschedule_count__gt=0),
            distinct=True,
        ),
    )

    # Segmentos.
    if segment == "recent":
        qs = qs.filter(last_seen__isnull=False).order_by("-last_seen")

    elif segment == "week":
        ini_local, fin_local = _week_bounds()
        qs = qs.filter(
            Exists(
                Appointment.objects.filter(
                    patient=OuterRef("pk"),
                    status=_ATTENDED,
                    starts_at__gte=ini_local,
                    starts_at__lt=fin_local,
                )
            )
        ).order_by("-last_seen")

    elif segment == "month":
        ini_local, fin_local = _month_bounds()
        qs = qs.filter(
            Exists(
                Appointment.objects.filter(
                    patient=OuterRef("pk"),
                    status=_ATTENDED,
                    starts_at__gte=ini_local,
                    starts_at__lt=fin_local,
                )
            )
        ).order_by("-last_seen")

    elif segment == "date":
        # date_from y date_to son validados (ambos requeridos) en la vista antes
        # de llamar a este selector.
        ini_local, fin_local = _date_range_bounds(date_from=date_from, date_to=date_to)  # type: ignore[arg-type]
        qs = qs.filter(
            Exists(
                Appointment.objects.filter(
                    patient=OuterRef("pk"),
                    status=_ATTENDED,
                    starts_at__gte=ini_local,
                    starts_at__lt=fin_local,
                )
            )
        ).order_by("-last_seen")

    elif segment == "potential":
        qs = qs.filter(attended_count=0).filter(
            Q(cancelled_count__gt=0) | Q(rescheduled_count__gt=0)
        ).order_by("-created_at")

    elif segment == "favorites":
        qs = qs.filter(categories__kind="favorite").order_by("-created_at")

    elif segment == "vip":
        qs = qs.filter(categories__kind="vip").order_by("-created_at")

    else:
        # "all" y cualquier valor desconocido.
        qs = qs.order_by("-created_at")

    # Filtro adicional por etiqueta del catálogo (combinable con cualquier
    # segmento). Solo filtra por categorías del tenant activo: el join contra
    # PatientCategory ya está aislado, así que un id ajeno no devuelve nada.
    if category_id is not None:
        qs = qs.filter(categories__id=category_id)

    return qs


# ---------------------------------------------------------------------------
# Helpers privados: límites temporales en UTC a partir de zona local del proyecto
# ---------------------------------------------------------------------------


def _local_tz() -> datetime.tzinfo:
    """Devuelve el tzinfo de la zona horaria configurada en settings.TIME_ZONE."""
    import zoneinfo  # disponible en Python 3.9+

    return zoneinfo.ZoneInfo(settings.TIME_ZONE)


def _week_bounds() -> tuple[datetime.datetime, datetime.datetime]:
    """Retorna (inicio_semana_utc, inicio_semana_siguiente_utc) para la semana actual.

    La semana inicia el lunes 00:00 en la zona horaria del proyecto.
    """
    tz = _local_tz()
    now_local = timezone.now().astimezone(tz)
    # weekday(): lunes=0, domingo=6
    monday_local = (now_local - datetime.timedelta(days=now_local.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    next_monday_local = monday_local + datetime.timedelta(weeks=1)
    return monday_local.astimezone(datetime.timezone.utc), next_monday_local.astimezone(
        datetime.timezone.utc
    )


def _month_bounds() -> tuple[datetime.datetime, datetime.datetime]:
    """Retorna (inicio_mes_utc, inicio_mes_siguiente_utc) para el mes actual."""
    tz = _local_tz()
    now_local = timezone.now().astimezone(tz)
    first_day = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # Inicio del mes siguiente = día 1 del mes + 1.
    if now_local.month == 12:
        first_next = first_day.replace(year=now_local.year + 1, month=1, day=1)
    else:
        first_next = first_day.replace(month=now_local.month + 1, day=1)
    return first_day.astimezone(datetime.timezone.utc), first_next.astimezone(
        datetime.timezone.utc
    )


def _date_range_bounds(
    *,
    date_from: datetime.date,
    date_to: datetime.date,
) -> tuple[datetime.datetime, datetime.datetime]:
    """Convierte un rango de fechas locales a límites UTC para filtrar starts_at.

    date_to es inclusivo: el límite superior es el día siguiente a las 00:00 local.

    Args:
        date_from: Fecha de inicio (inclusive).
        date_to:   Fecha de fin (inclusive).

    Returns:
        Tupla (ini_utc, fin_utc) como datetimes aware en UTC.
    """
    tz = _local_tz()
    ini_local = datetime.datetime(
        date_from.year, date_from.month, date_from.day, 0, 0, 0, tzinfo=tz
    )
    # date_to inclusive → límite superior es el día siguiente a las 00:00.
    day_after = date_to + datetime.timedelta(days=1)
    fin_local = datetime.datetime(
        day_after.year, day_after.month, day_after.day, 0, 0, 0, tzinfo=tz
    )
    return ini_local.astimezone(datetime.timezone.utc), fin_local.astimezone(
        datetime.timezone.utc
    )
