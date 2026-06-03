"""
Tareas Celery de la app agenda.

send_appointment_reminder — envía un recordatorio de cita al paciente.

IMPORTANTE — CONTEXTO DE TENANT EN CELERY:
    El worker Celery corre SIN request HTTP. No hay tenant en thread-local.
    Por eso se usan AppointmentReminder.all_objects y Appointment.all_objects
    (el Manager estándar, sin filtro de tenant). El aislamiento de datos lo
    proporciona el UUID directo del recordatorio + RLS en PostgreSQL.

    NUNCA llamar estas tareas desde una vista exponiendo el reminder_id
    directamente al usuario final (el id es interno, no público).

IDEMPOTENCIA:
    La tarea verifica el estado del recordatorio ANTES de enviar.
    Si ya está en SENT/FAILED/SKIPPED/CANCELLED, retorna sin hacer nada.
    Esto protege contra reenvíos si Celery re-encola la tarea (at-least-once).

REINTENTOS:
    max_retries=3, default_retry_delay=300 (5 min entre reintentos).
    Solo reintenta en excepciones transitorias (adapter falló). Si el
    adapter devuelve success=False, la tarea NO reintenta: marca FAILED.
"""

import logging

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from django.utils import timezone

from adapters.whatsapp import get_whatsapp_adapter
from apps.agenda.models import Appointment, AppointmentReminder

logger = logging.getLogger("apps.agenda.tasks")

#: Estados de cita que implican que el recordatorio NO debe enviarse.
#: Terminales = la cita ya no puede recibir atención activa.
_INACTIVE_APPOINTMENT_STATUSES: frozenset[str] = frozenset(
    {
        Appointment.Status.CANCELLED,
        Appointment.Status.NO_SHOW,
        Appointment.Status.ATTENDED,
    }
)

#: Longitud máxima del campo message_preview (truncar si supera).
_MESSAGE_PREVIEW_MAX_LENGTH: int = 500


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_appointment_reminder(self: "shared_task", reminder_id: str) -> str:  # type: ignore[name-defined]
    """Envía un recordatorio de cita al paciente vía WhatsApp (u otro canal).

    Flujo:
      1. Cargar el reminder con all_objects. Si no existe → "not_found".
      2. Si status != PENDING → "skipped:<status>" (idempotencia).
      3. Cargar la cita. Si está inactiva → marcar SKIPPED.
      4. Construir los parámetros del template.
      5. Llamar al adapter y actualizar status/sent_at/external_message_id.
      6. Si el adapter falla → marcar FAILED + guardar error_detail.
         (No se reintenta en fallo de adapter — es definitivo).
      7. Si ocurre una excepción inesperada → self.retry() si quedan reintentos.

    Args:
        reminder_id: UUID (str) del AppointmentReminder a procesar.

    Returns:
        String de resultado para trazabilidad:
        "sent:<external_id>", "skipped:<motivo>", "not_found", "failed:<error>".
    """
    # ------------------------------------------------------------------
    # 1. Cargar el reminder (all_objects: no hay tenant en contexto Celery)
    # ------------------------------------------------------------------
    try:
        reminder: AppointmentReminder = AppointmentReminder.all_objects.select_related(
            "appointment__patient",
            "appointment__doctor__membership__user",
            "appointment__tenant",
        ).get(id=reminder_id)
    except AppointmentReminder.DoesNotExist:
        logger.warning("send_appointment_reminder: reminder %s not found", reminder_id)
        return "not_found"

    # ------------------------------------------------------------------
    # 2. Idempotencia: si ya fue procesado, no hacer nada
    # ------------------------------------------------------------------
    if reminder.status != AppointmentReminder.ReminderStatus.PENDING:
        logger.info(
            "send_appointment_reminder: reminder %s ya tiene status=%s, omitiendo",
            reminder_id,
            reminder.status,
        )
        return f"skipped:{reminder.status}"

    appointment: Appointment = reminder.appointment

    # ------------------------------------------------------------------
    # 3. Verificar que la cita sigue activa
    # ------------------------------------------------------------------
    if appointment.status in _INACTIVE_APPOINTMENT_STATUSES:
        reminder.status = AppointmentReminder.ReminderStatus.SKIPPED
        reminder.error_detail = (
            f"Cita en estado '{appointment.get_status_display()}' "
            "al momento de intentar enviar el recordatorio."
        )
        reminder.save(update_fields=["status", "error_detail", "updated_at"])
        logger.info(
            "send_appointment_reminder: reminder %s omitido (cita %s en estado %s)",
            reminder_id,
            appointment.id,
            appointment.status,
        )
        return f"skipped:appointment_{appointment.status}"

    # ------------------------------------------------------------------
    # 4. Construir parámetros del template
    # ------------------------------------------------------------------
    patient = appointment.patient
    doctor = appointment.doctor

    # Nombre del paciente
    patient_full_name: str = getattr(patient, "full_name", str(patient_id := patient.id))  # type: ignore[assignment]

    # Nombre del médico (derivado de membership.user)
    doctor_full_name: str = ""
    try:
        doctor_full_name = doctor.membership.user.get_full_name() or str(doctor.id)
    except Exception:
        doctor_full_name = str(doctor.id)

    # Formatear fecha/hora en el timezone del tenant
    tenant = appointment.tenant
    tenant_timezone_name: str = getattr(tenant, "timezone", "America/Mexico_City") or "America/Mexico_City"
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(tenant_timezone_name)
        local_starts = appointment.starts_at.astimezone(tz)
        date_str = local_starts.strftime("%d/%m/%Y %H:%M")
    except Exception:
        date_str = appointment.starts_at.strftime("%Y-%m-%d %H:%M UTC")

    # Teléfono del paciente (para WhatsApp debe estar en E.164)
    patient_phone: str = getattr(patient, "phone", "") or ""

    template_params: dict[str, str] = {
        "nombre_paciente": patient_full_name,
        "fecha_hora": date_str,
        "nombre_doctor": doctor_full_name,
    }

    message_text = (
        f"Recordatorio: {patient_full_name}, tienes cita el {date_str} "
        f"con {doctor_full_name}."
    )

    # ------------------------------------------------------------------
    # 5. Llamar al adapter
    # ------------------------------------------------------------------
    try:
        adapter = get_whatsapp_adapter()
        result = adapter.send_template(
            to=patient_phone,
            template="recordatorio_cita",
            params=template_params,
        )
    except Exception as exc:
        # Excepción inesperada del adapter (red, SDK, etc.) → reintentar
        logger.error(
            "send_appointment_reminder: excepción en adapter para reminder %s: %s",
            reminder_id,
            exc,
            exc_info=True,
        )
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            # Agotamos reintentos — marcar como FAILED definitivo
            reminder.status = AppointmentReminder.ReminderStatus.FAILED
            reminder.error_detail = f"Excepción tras {self.max_retries} reintentos: {exc}"
            reminder.message_preview = message_text[:_MESSAGE_PREVIEW_MAX_LENGTH]
            reminder.save(update_fields=["status", "error_detail", "message_preview", "updated_at"])
            return f"failed:max_retries:{exc}"

    # ------------------------------------------------------------------
    # 6. Procesar resultado del adapter
    # ------------------------------------------------------------------
    if result.success:
        reminder.status = AppointmentReminder.ReminderStatus.SENT
        reminder.sent_at = timezone.now()
        reminder.external_message_id = result.external_message_id
        reminder.message_preview = message_text[:_MESSAGE_PREVIEW_MAX_LENGTH]
        reminder.error_detail = ""
        reminder.save(
            update_fields=[
                "status",
                "sent_at",
                "external_message_id",
                "message_preview",
                "error_detail",
                "updated_at",
            ]
        )
        logger.info(
            "send_appointment_reminder: reminder %s enviado OK ext_id=%s",
            reminder_id,
            result.external_message_id,
        )
        return f"sent:{result.external_message_id}"
    else:
        # El adapter devolvió fallo explícito — definitivo, no reintentar
        reminder.status = AppointmentReminder.ReminderStatus.FAILED
        reminder.error_detail = result.error or "El adapter reportó fallo sin detalle."
        reminder.message_preview = message_text[:_MESSAGE_PREVIEW_MAX_LENGTH]
        reminder.save(update_fields=["status", "error_detail", "message_preview", "updated_at"])
        logger.warning(
            "send_appointment_reminder: reminder %s FAILED: %s",
            reminder_id,
            result.error,
        )
        return f"failed:{result.error}"
