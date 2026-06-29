"""
Programación y cancelación de recordatorios de cita (WhatsApp).

Crea/cancela AppointmentReminder y encola la tarea Celery de envío. Extraído de
agenda/services.py; lo consume el ciclo de vida de la cita (appointment_create /
appointment_reschedule / appointment_change_status / appointment_reactivate).

Best-effort: una falla aquí NO debe tumbar la cita (quien llama lo envuelve en
try/except). La tarea Celery revalida el estado antes de enviar (idempotencia).
"""

import datetime

from django.utils import timezone

from apps.agenda.models import Appointment, AppointmentReminder
from apps.agenda.selectors import agenda_config_get


def schedule_reminders_for_appointment(
    *,
    appointment: Appointment,
) -> list[AppointmentReminder]:
    """Programa los recordatorios de una cita según la config de la clínica.

    Lee ``reminder_offsets_minutes`` de la config del tenant y crea un
    ``AppointmentReminder`` PENDING por cada offset cuyo ``scheduled_at`` esté en
    el futuro, encolando la tarea Celery ``send_appointment_reminder`` con ``eta``.

    Decisiones de diseño:
      - Si ``reminders_enabled`` es False → no crea nada (devuelve ``[]``).
      - Offsets cuyo ``scheduled_at`` ya pasó (<= ahora) se OMITEN: un recordatorio
        en el pasado no aporta valor (no se crea como SKIPPED, simplemente no se crea).
      - Evita duplicados: no crea otro PENDING para el mismo (cita, scheduled_at).

    NOTA: esta función es best-effort respecto a la creación de la cita —
    quien la llama (appointment_create / appointment_reschedule) la envuelve en
    try/except para que una falla aquí NO tumbe la cita.

    Args:
        appointment: Cita ya persistida (recién creada o reagendada).

    Returns:
        Lista de ``AppointmentReminder`` creados (puede ser vacía).
    """
    config = agenda_config_get(tenant=appointment.tenant)
    if not config.reminders_enabled:
        return []

    # Import local para evitar import circular (tasks importa services indirectamente).
    from apps.agenda.tasks import send_appointment_reminder

    now = timezone.now()
    created: list[AppointmentReminder] = []

    for offset_minutes in config.reminder_offsets_minutes or []:
        scheduled_at = appointment.starts_at - datetime.timedelta(
            minutes=int(offset_minutes)
        )
        if scheduled_at <= now:
            # Recordatorio caería en el pasado: omitir.
            continue

        # Evitar duplicados para el mismo momento de envío.
        duplicate_exists = AppointmentReminder.all_objects.filter(
            appointment=appointment,
            scheduled_at=scheduled_at,
            status=AppointmentReminder.ReminderStatus.PENDING,
        ).exists()
        if duplicate_exists:
            continue

        reminder = AppointmentReminder.objects.create(
            tenant=appointment.tenant,
            created_by=appointment.created_by,
            appointment=appointment,
            channel=AppointmentReminder.Channel.WHATSAPP,
            scheduled_at=scheduled_at,
            status=AppointmentReminder.ReminderStatus.PENDING,
        )
        # Encola el envío para el momento programado. La tarea revalida el estado.
        send_appointment_reminder.apply_async(
            args=[str(reminder.id)],
            eta=scheduled_at,
        )
        created.append(reminder)

    return created


def cancel_reminders_for_appointment(
    *,
    appointment: Appointment,
) -> int:
    """Marca como CANCELLED todos los recordatorios PENDING de una cita.

    Se invoca al cancelar / marcar no-show una cita, o al reagendarla (antes de
    reprogramar con el nuevo horario).

    Usa ``all_objects`` porque puede ejecutarse sin contexto de tenant, pero filtra
    por la cita concreta (que ya está acotada a su tenant). La revocación de las
    tareas Celery encoladas es best-effort: la tarea ``send_appointment_reminder``
    revalida ``status == PENDING`` antes de enviar, por lo que un recordatorio
    CANCELLED nunca se envía aunque su tarea llegue a ejecutarse.

    Args:
        appointment: Cita cuyos recordatorios pendientes se cancelan.

    Returns:
        Número de recordatorios cancelados.
    """
    return AppointmentReminder.all_objects.filter(
        appointment=appointment,
        status=AppointmentReminder.ReminderStatus.PENDING,
    ).update(status=AppointmentReminder.ReminderStatus.CANCELLED)
