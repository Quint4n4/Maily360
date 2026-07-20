"""
Selectors de la app agenda.

Lecturas/queries: NUNCA modifican datos.
El TenantManager (objects) filtra automáticamente por el tenant activo en el
thread-local cuando context_active=True.

Convención: keyword-only args, nombrado acción+entidad.

Regla (arquitectura): toda lectura de un objeto por id pasa por un selector.
NUNCA usar Appointment.objects.get() directo en vistas.
"""

import datetime
import uuid

from django.db.models import Q, QuerySet

from apps.agenda.models import (
    ACTIVE_STATUSES,
    AgendaBlock,
    AgendaItemNote,
    Appointment,
    AppointmentReminder,
    AppointmentType,
    TenantAgendaConfig,
)
from apps.tenancy.models import Tenant


def _agenda_block_scope_q(sucursal_ids: list[uuid.UUID]) -> Q:
    """Criterio de alcance por sucursal para AgendaBlock (listado Y detalle).

    Fuente única de verdad (hallazgo A3 — ver docs/design/sucursales-
    hallazgos-seguridad.md, REGLA de consistencia): `agenda_block_list` y
    `agenda_block_get` deben acotar EXACTAMENTE igual, para que "si no lo veo
    en el listado, no lo puedo tocar por id".

    - Un evento con `doctor` asignado SIEMPRE aplica (global, todas las
      sedes de ese médico — un médico no está en dos lados a la vez).
    - Un evento con `consultorio` asignado aplica solo si ese consultorio
      pertenece a una de las sedes permitidas (el consultorio ya "ancla"
      una sede).
    - Un evento sin doctor NI consultorio ("de toda la clínica" en v1, "de
      una sucursal" desde la Fase 2) aplica solo si su propio `sucursal_id`
      está entre las permitidas.
    """
    return (
        Q(doctor__isnull=False)
        | Q(consultorio__sucursal_id__in=sucursal_ids)
        | Q(doctor__isnull=True, consultorio__isnull=True, sucursal_id__in=sucursal_ids)
    )


def agenda_block_list(
    *,
    date_from: datetime.datetime | None = None,
    date_to: datetime.datetime | None = None,
    sucursal_id: uuid.UUID | None = None,
    sucursal_ids: list[uuid.UUID] | None = None,
) -> QuerySet[AgendaBlock]:
    """Eventos de agenda (reuniones/bloqueos) que solapan el rango dado.

    sucursal_id (multi-sede — Fase 2, opcional): filtra a los eventos que
    APLICAN a esa sede, con el mismo criterio de alcance que
    `apps.agenda.services._check_block_overlap` (ver `_agenda_block_scope_q`
    para la variante de VARIAS sedes).
    Sin sucursal_id ni sucursal_ids → sin filtro (compatibilidad retro).

    sucursal_ids (multi-sede — Fase 3, opcional): variante de `sucursal_id`
    para acotar a VARIAS sedes permitidas a la vez (ver
    `apps.clinica.sucursal_scope.sucursal_scope_ids`). Si se provee, tiene
    prioridad sobre `sucursal_id` (solo uno de los dos se usa en la práctica).
    """
    qs = AgendaBlock.objects.select_related("doctor", "consultorio", "sucursal").all()
    if date_to is not None:
        qs = qs.filter(starts_at__lt=date_to)
    if date_from is not None:
        qs = qs.filter(ends_at__gt=date_from)
    if sucursal_ids is not None:
        qs = qs.filter(_agenda_block_scope_q(sucursal_ids))
    elif sucursal_id is not None:
        qs = qs.filter(
            Q(doctor__isnull=False)
            | Q(consultorio__sucursal_id=sucursal_id)
            | Q(doctor__isnull=True, consultorio__isnull=True, sucursal_id=sucursal_id)
        )
    return qs.order_by("starts_at")


def agenda_block_get(
    *, block_id: uuid.UUID, sucursal_ids: list[uuid.UUID] | None = None
) -> AgendaBlock:
    """Retorna un evento de agenda por UUID (filtrado por tenant activo).

    sucursal_ids (multi-sede — Fase 3, seguridad, hallazgo A3, opcional):
    acota el lookup al MISMO alcance que `agenda_block_list` (ver
    `_agenda_block_scope_q`) — un evento fuera del alcance del actor no
    existe para él. None = sin filtro (compatibilidad retro / actor con
    alcance total, p. ej. owner). Las vistas de detalle/acción deben pasar
    `sucursal_scope_ids(request)` aquí, igual que ya lo hace el listado.

    Raises:
        AgendaBlock.DoesNotExist: si no existe, es de otro tenant, o cae
            fuera del alcance de sucursales indicado.
    """
    qs = AgendaBlock.objects.select_related("doctor", "consultorio", "sucursal")
    if sucursal_ids is not None:
        qs = qs.filter(_agenda_block_scope_q(sucursal_ids))
    return qs.get(id=block_id)


def appointment_type_list(*, only_active: bool = True) -> QuerySet[AppointmentType]:
    """Tipos de cita del tenant activo, ordenados por nombre."""
    qs = AppointmentType.objects.all()
    if only_active:
        qs = qs.filter(is_active=True)
    return qs.order_by("name")


def appointment_type_get(*, type_id: uuid.UUID) -> AppointmentType:
    """Retorna un tipo de cita por UUID (filtrado por tenant activo)."""
    return AppointmentType.objects.get(id=type_id)


def appointment_get(
    *, appointment_id: uuid.UUID, sucursal_ids: list[uuid.UUID] | None = None
) -> Appointment:
    """Retorna una cita por su UUID.

    Usa el TenantManager (filtra por tenant del contexto activo).
    Lanza Appointment.DoesNotExist si no existe o no pertenece al tenant activo.
    Las vistas deben capturar DoesNotExist y devolver 404 (nunca 403).

    Args:
        appointment_id: UUID de la cita a recuperar.
        sucursal_ids:   Lista de UUIDs de sucursal permitidas (multi-sede —
                        Fase 3, seguridad, hallazgo A2 — ver docs/design/
                        sucursales-hallazgos-seguridad.md). Mismo criterio
                        que `appointment_list`: si se provee, la cita debe
                        pertenecer a una de estas sedes o se comporta como
                        si no existiera. None = sin filtro (compatibilidad
                        retro / actor con alcance total, p. ej. owner). Las
                        vistas de detalle/acción deben pasar
                        `sucursal_scope_ids(request)` aquí, igual que ya lo
                        hace el listado — "si no la veo en la lista, no la
                        puedo tocar por id".

    Returns:
        Instancia de Appointment con relaciones pre-cargadas para evitar N+1.

    Raises:
        Appointment.DoesNotExist: si la cita no existe en el tenant activo,
            o cae fuera del alcance de sucursales indicado.
    """
    qs = Appointment.objects.select_related(
        "patient",
        "doctor__membership__user",
        "consultorio",
        "sucursal",
        "cancelled_by",
        "no_show_registered_by",
        "quote",  # C-3: resumen de cotización vinculada (sin N+1)
    ).prefetch_related("reminders")
    if sucursal_ids is not None:
        qs = qs.filter(sucursal_id__in=sucursal_ids)
    return qs.get(id=appointment_id)


def appointment_list(
    *,
    doctor_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    consultorio_id: uuid.UUID | None = None,
    status: str | None = None,
    date_from: datetime.datetime | None = None,
    date_to: datetime.datetime | None = None,
    sucursal_id: uuid.UUID | None = None,
    sucursal_ids: list[uuid.UUID] | None = None,
) -> QuerySet[Appointment]:
    """Retorna el QuerySet de citas del tenant actual con filtros opcionales.

    Todos los filtros son opcionales y se aplican acumulativamente (AND).
    El TenantManager ya filtra por tenant activo — no necesita argumento tenant.
    La paginación la aplica la vista.

    Filtros:
        doctor_id:      UUID del médico (calendar view por doctor).
        patient_id:     UUID del paciente (historial del paciente).
        consultorio_id: UUID del consultorio (calendar view por consultorio).
        status:         Valor del Status.choices (p.ej. "scheduled").
        date_from:      Citas que empiezan en o después de esta fecha/hora UTC.
        date_to:        Citas que empiezan antes de esta fecha/hora UTC.
        sucursal_id:    UUID de la sucursal activa (multi-sede — Fase 2). La
                        vista la resuelve con `resolve_active_sucursal(request)`.
                        None = sin filtro (compatibilidad retro, todas las sedes).
        sucursal_ids:   Lista de UUIDs de sucursal permitidas (multi-sede —
                        Fase 3, seguridad). Ver
                        `apps.clinica.sucursal_scope.sucursal_scope_ids`. Si
                        se provee, tiene prioridad sobre `sucursal_id`.

    Returns:
        QuerySet[Appointment] filtrado, con select_related para evitar N+1,
        ordenado por starts_at ASC (útil para calendarios).

    Performance: select_related cubre doctor→membership→user, patient, consultorio, sucursal.
    """
    qs: QuerySet[Appointment] = Appointment.objects.select_related(
        "patient",
        "doctor__membership__user",
        "consultorio",
        "sucursal",
        "quote",  # C-3: resumen de cotización vinculada (sin N+1)
    ).prefetch_related("reminders")

    if doctor_id is not None:
        qs = qs.filter(doctor_id=doctor_id)

    if patient_id is not None:
        qs = qs.filter(patient_id=patient_id)

    if consultorio_id is not None:
        qs = qs.filter(consultorio_id=consultorio_id)

    if status is not None:
        qs = qs.filter(status=status)

    if date_from is not None:
        qs = qs.filter(starts_at__gte=date_from)

    if date_to is not None:
        qs = qs.filter(starts_at__lt=date_to)

    if sucursal_ids is not None:
        qs = qs.filter(sucursal_id__in=sucursal_ids)
    elif sucursal_id is not None:
        qs = qs.filter(sucursal_id=sucursal_id)

    return qs.order_by("starts_at")


def agenda_config_get(*, tenant: Tenant) -> TenantAgendaConfig:
    """Retorna la configuración de agenda de un tenant, creándola con defaults si no existe.

    Se usa all_objects para que funcione fuera de contexto de request
    (Celery, management commands) sin depender del TenantManager.

    Args:
        tenant: Instancia del Tenant cuya config se busca/crea.

    Returns:
        Instancia TenantAgendaConfig del tenant. Siempre existe (get_or_create).
    """
    config, _ = TenantAgendaConfig.all_objects.get_or_create(
        tenant=tenant,
        defaults={
            "created_by": None,
            "record_number_format": "EXP-{year}-{seq:05d}",
            "record_number_reset_yearly": False,
            "default_appointment_duration": 30,
            "reminder_offsets_minutes": [1440],
            "reminders_enabled": True,
        },
    )
    return config


def agenda_item_note_list(
    *,
    appointment_id: uuid.UUID | None = None,
    block_id: uuid.UUID | None = None,
) -> QuerySet[AgendaItemNote]:
    """Retorna las notas del hilo de una cita o de un evento, ordenadas por created_at ASC.

    El TenantManager filtra por tenant activo automáticamente.
    Se espera que exactamente uno de appointment_id / block_id sea provisto.
    Si ninguno se provee, devuelve un QuerySet vacío (uso defensivo).

    Args:
        appointment_id: UUID de la cita. Excluyente con block_id.
        block_id:       UUID del evento. Excluyente con appointment_id.

    Returns:
        QuerySet[AgendaItemNote] con select_related("author"), ordenado por created_at ASC.
    """
    qs = AgendaItemNote.objects.select_related("author").order_by("created_at")
    if appointment_id is not None:
        return qs.filter(appointment_id=appointment_id)
    if block_id is not None:
        return qs.filter(agenda_block_id=block_id)
    # Ninguno provisto: devolver vacío (la vista ya valida que tenga uno u otro).
    return qs.none()


def agenda_item_note_get(*, note_id: uuid.UUID) -> AgendaItemNote:
    """Retorna una nota por su UUID (filtrado por tenant activo vía TenantManager).

    Raises:
        AgendaItemNote.DoesNotExist: si no existe o pertenece a otro tenant.
    """
    return AgendaItemNote.objects.select_related("author").get(id=note_id)


def reminder_list_for_appointment(*, appointment: Appointment) -> "QuerySet[AppointmentReminder]":
    """Retorna los recordatorios de una cita, ordenados por momento de envío.

    Args:
        appointment: Cita cuyos recordatorios se listan.

    Returns:
        QuerySet de AppointmentReminder de la cita (ascendente por scheduled_at).
    """
    # order_by omitted: Meta.ordering already sorts by scheduled_at ASC
    return AppointmentReminder.objects.filter(appointment=appointment)


def agenda_busy_intervals(
    *,
    doctor_id: uuid.UUID,
    consultorio_id: uuid.UUID | None,
    date_from: datetime.datetime,
    date_to: datetime.datetime,
    sucursal_id: uuid.UUID | None = None,
    sucursal_ids: list[uuid.UUID] | None = None,
) -> list[dict]:
    """Intervalos OCUPADOS de un médico/consultorio en un rango, para pintar
    disponibilidad en el frontend (qué horarios chocan al armar una serie).

    Incluye:
      - Citas ACTIVAS del médico (no canceladas / no-show) que solapan el rango.
        REGLA CRÍTICA (multi-sede — Fase 2): estas citas son SIEMPRE GLOBALES
        entre sedes — un médico no puede estar en dos sucursales a la vez. Por
        eso NO se filtran aquí por `sucursal_id`: una cita en Centro ocupa al
        médico también al consultar la disponibilidad de Norte.
      - Eventos de agenda (reuniones/bloqueos) aplicables: de ese médico (en
        TODAS sus sedes), de ese consultorio (si se da), o de la sucursal
        indicada (bloqueo "de toda la clínica" en v1, "de una sucursal" desde
        la Fase 2 — un cierre en Centro ya NO bloquea Norte). Sin
        `sucursal_id`, se conserva el comportamiento previo a la Fase 2 (el
        bloqueo sin doctor/consultorio aplica a cualquier sede) para no
        romper llamadores que aún no pasan la sede activa.

    El TenantManager (objects) filtra por el tenant activo. Solo lectura.

    Args:
        doctor_id:      médico de la serie.
        consultorio_id: consultorio de la cita (None en telemedicina/fuera).
        date_from/to:   rango UTC a inspeccionar (date_from inclusive, date_to exclusivo).
        sucursal_id:    sucursal activa del request (multi-sede — Fase 2).
                        None = compatibilidad retro (bloqueos "de clínica"
                        aplican a cualquier sede, como antes de la Fase 2).
        sucursal_ids:   lista de sucursales permitidas (multi-sede — Fase 3,
                        seguridad; ver `sucursal_scope_ids`). Si se provee,
                        tiene prioridad sobre `sucursal_id`.

    Returns:
        Lista de {"start": datetime, "end": datetime} (sin ordenar).
    """
    intervalos: list[dict] = []

    # Citas del médico: GLOBALES, nunca se filtran por sucursal (ver docstring).
    citas = Appointment.objects.filter(
        doctor_id=doctor_id,
        status__in=ACTIVE_STATUSES,
        starts_at__lt=date_to,
        ends_at__gt=date_from,
    ).values_list("starts_at", "ends_at")
    intervalos += [{"start": s, "end": e} for s, e in citas]

    alcance = Q(doctor_id=doctor_id)
    if consultorio_id is not None:
        alcance |= Q(consultorio_id=consultorio_id)
    if sucursal_ids is not None:
        alcance |= Q(doctor__isnull=True, consultorio__isnull=True, sucursal_id__in=sucursal_ids)
    elif sucursal_id is not None:
        alcance |= Q(doctor__isnull=True, consultorio__isnull=True, sucursal_id=sucursal_id)
    else:
        alcance |= Q(doctor__isnull=True, consultorio__isnull=True)
    bloques = AgendaBlock.objects.filter(
        alcance,
        starts_at__lt=date_to,
        ends_at__gt=date_from,
    ).values_list("starts_at", "ends_at")
    intervalos += [{"start": s, "end": e} for s, e in bloques]

    return intervalos
