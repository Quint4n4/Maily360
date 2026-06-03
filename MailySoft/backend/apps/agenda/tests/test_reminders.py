"""
Tests de los recordatorios de citas (WhatsApp) — Maily Soft agenda.

Cubre:
- schedule_reminders_for_appointment: offsets → reminders PENDING, skips pasado,
  reminders_enabled=False, deduplicacion, eta de apply_async.
- Integracion con appointment_create y appointment_reschedule (best-effort).
- cancel_reminders_for_appointment: pending→cancelled, sent intacto.
- Integracion con appointment_change_status (CANCELLED y NO_SHOW).
- send_appointment_reminder (tarea): pending+activa→sent, idempotencia,
  cita inactiva→skipped, adapter failure→failed, reminder inexistente.
- SimulatedWhatsAppAdapter: devuelve success + sim-<id>.
- reminder_list_for_appointment: orden por scheduled_at.
- AppointmentOutputSerializer: anida los reminders.

Patron: AAA. Todas tocan BD -> fixture db.
Para la tarea Celery se usa llamada directa (no apply_async) con el adapter
mockeado para controlar el resultado sin enviar nada real.
Para schedule_reminders_for_appointment se mockea apply_async para verificar
encola sin ejecutar la tarea.
"""

import datetime
import uuid
from contextlib import contextmanager
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from adapters.whatsapp import SimulatedWhatsAppAdapter, WhatsAppResult
from apps.agenda.models import Appointment, AppointmentReminder, TenantAgendaConfig
from apps.agenda.selectors import agenda_config_get, reminder_list_for_appointment
from apps.agenda.serializers import AppointmentOutputSerializer
from apps.agenda.services import (
    appointment_change_status,
    appointment_reschedule,
    cancel_reminders_for_appointment,
    schedule_reminders_for_appointment,
    appointment_create,
)
from apps.agenda.tasks import send_appointment_reminder
from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from tests.factories import (
    AppointmentFactory,
    DoctorFactory,
    PatientFactory,
    TenantAgendaConfigFactory,
    TenantFactory,
    UserFactory,
)

# ---------------------------------------------------------------------------
# Helpers comunes
# ---------------------------------------------------------------------------

# Fecha fija en el futuro lejano para starts_at de las citas en tests.
# Suficientemente en el futuro para que los offsets no caigan en el pasado.
_FUTURE = datetime.datetime(2035, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)


@contextmanager
def _tenant_context(tenant: object) -> Generator[None, None, None]:
    """Activa el contexto de tenant para que TenantManager filtre por el."""
    set_current_tenant(tenant)  # type: ignore[arg-type]
    set_tenant_context_active(True)
    try:
        yield
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)


def _make_appointment_via_service(
    tenant: object,
    doctor: object,
    patient: object,
    user: object,
    starts_at: datetime.datetime = _FUTURE,
    ends_at: datetime.datetime | None = None,
) -> Appointment:
    """Crea una cita via el service con contexto de tenant activo."""
    with _tenant_context(tenant):
        return appointment_create(
            tenant=tenant,  # type: ignore[arg-type]
            user=user,  # type: ignore[arg-type]
            patient_id=patient.id,  # type: ignore[union-attr]
            doctor_id=doctor.id,  # type: ignore[union-attr]
            starts_at=starts_at,
            ends_at=ends_at,
            reason="Consulta de prueba",
        )


def _config_for(tenant: object, **kwargs: object) -> TenantAgendaConfig:
    """Obtiene (o crea) la config del tenant y aplica kwargs."""
    config = agenda_config_get(tenant=tenant)  # type: ignore[arg-type]
    for k, v in kwargs.items():
        setattr(config, k, v)
    config.save()
    return config


# ---------------------------------------------------------------------------
# Factory de AppointmentReminder (auxiliar de tests)
# ---------------------------------------------------------------------------


def _make_reminder(
    appointment: Appointment,
    *,
    status: str = AppointmentReminder.ReminderStatus.PENDING,
    scheduled_at: datetime.datetime | None = None,
) -> AppointmentReminder:
    """Crea un AppointmentReminder directamente en BD (sin pasar por service/task)."""
    if scheduled_at is None:
        # 24h antes de la cita — siempre en el futuro si la cita es _FUTURE
        scheduled_at = appointment.starts_at - datetime.timedelta(hours=24)
    return AppointmentReminder.objects.create(
        tenant=appointment.tenant,
        created_by=appointment.created_by,
        appointment=appointment,
        channel=AppointmentReminder.Channel.WHATSAPP,
        scheduled_at=scheduled_at,
        status=status,
    )


# ===========================================================================
# schedule_reminders_for_appointment
# ===========================================================================


class TestScheduleRemindersForAppointment:
    """schedule_reminders_for_appointment: crea reminders PENDING segun config."""

    def test_schedule_creates_one_reminder_per_offset(self, db: None) -> None:
        """Con offset [1440] se crea exactamente 1 reminder PENDING."""
        # Arrange
        tenant = TenantFactory()
        _config_for(tenant, reminder_offsets_minutes=[1440], reminders_enabled=True)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            starts_at=_FUTURE,
        )

        # Act
        with patch("apps.agenda.tasks.send_appointment_reminder.apply_async"):
            created = schedule_reminders_for_appointment(appointment=appt)

        # Assert
        assert len(created) == 1
        assert created[0].status == AppointmentReminder.ReminderStatus.PENDING
        assert created[0].appointment_id == appt.id

    def test_schedule_creates_two_reminders_for_two_offsets(self, db: None) -> None:
        """Con offsets [1440, 120] se crean 2 reminders PENDING."""
        # Arrange
        tenant = TenantFactory()
        _config_for(tenant, reminder_offsets_minutes=[1440, 120], reminders_enabled=True)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            starts_at=_FUTURE,
        )

        # Act
        with patch("apps.agenda.tasks.send_appointment_reminder.apply_async"):
            created = schedule_reminders_for_appointment(appointment=appt)

        # Assert
        assert len(created) == 2
        statuses = {r.status for r in created}
        assert statuses == {AppointmentReminder.ReminderStatus.PENDING}

    def test_schedule_skips_offset_in_the_past(self, db: None) -> None:
        """Cita en 1h con offset 1440min (24h) -> scheduled_at en el pasado -> 0 reminders."""
        # Arrange
        tenant = TenantFactory()
        _config_for(tenant, reminder_offsets_minutes=[1440], reminders_enabled=True)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        # Cita en 1 hora desde ahora — offset 24h caeria 23h en el pasado
        starts_at = timezone.now() + datetime.timedelta(hours=1)
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            starts_at=starts_at,
        )

        # Act
        with patch("apps.agenda.tasks.send_appointment_reminder.apply_async"):
            created = schedule_reminders_for_appointment(appointment=appt)

        # Assert — el offset cae en el pasado, no se crea ningun reminder
        assert created == []
        assert AppointmentReminder.all_objects.filter(appointment=appt).count() == 0

    def test_schedule_returns_empty_when_reminders_disabled(self, db: None) -> None:
        """reminders_enabled=False -> schedule devuelve [] sin crear nada."""
        # Arrange
        tenant = TenantFactory()
        _config_for(tenant, reminder_offsets_minutes=[1440], reminders_enabled=False)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            starts_at=_FUTURE,
        )

        # Act
        with patch("apps.agenda.tasks.send_appointment_reminder.apply_async") as mock_enqueue:
            created = schedule_reminders_for_appointment(appointment=appt)

        # Assert
        assert created == []
        mock_enqueue.assert_not_called()
        assert AppointmentReminder.all_objects.filter(appointment=appt).count() == 0

    def test_schedule_avoids_duplicate_pending(self, db: None) -> None:
        """Llamar schedule dos veces no duplica reminders PENDING para el mismo scheduled_at."""
        # Arrange
        tenant = TenantFactory()
        _config_for(tenant, reminder_offsets_minutes=[1440], reminders_enabled=True)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            starts_at=_FUTURE,
        )

        # Act — llamar dos veces
        with patch("apps.agenda.tasks.send_appointment_reminder.apply_async"):
            first = schedule_reminders_for_appointment(appointment=appt)
            second = schedule_reminders_for_appointment(appointment=appt)

        # Assert — primera llamada crea 1, segunda crea 0 (ya existe PENDING)
        assert len(first) == 1
        assert len(second) == 0
        assert AppointmentReminder.all_objects.filter(
            appointment=appt,
            status=AppointmentReminder.ReminderStatus.PENDING,
        ).count() == 1

    def test_schedule_enqueues_task_with_correct_eta(self, db: None) -> None:
        """apply_async se llama con eta igual a scheduled_at del reminder."""
        # Arrange
        tenant = TenantFactory()
        offset = 1440  # 24 horas
        _config_for(tenant, reminder_offsets_minutes=[offset], reminders_enabled=True)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            starts_at=_FUTURE,
        )
        expected_eta = _FUTURE - datetime.timedelta(minutes=offset)

        # Act
        with patch("apps.agenda.tasks.send_appointment_reminder.apply_async") as mock_enqueue:
            created = schedule_reminders_for_appointment(appointment=appt)

        # Assert — apply_async llamado una vez con eta correcto
        assert len(created) == 1
        mock_enqueue.assert_called_once()
        call_kwargs = mock_enqueue.call_args
        # apply_async recibe args=[reminder_id_str] y eta=scheduled_at
        assert call_kwargs.kwargs["eta"] == expected_eta

    def test_appointment_create_schedules_reminders(self, db: None) -> None:
        """appointment_create con cita a 2 dias -> crea al menos 1 reminder PENDING."""
        # Arrange
        tenant = TenantFactory()
        _config_for(tenant, reminder_offsets_minutes=[1440], reminders_enabled=True)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        starts_at = timezone.now() + datetime.timedelta(days=2)

        # Act
        with patch("apps.agenda.tasks.send_appointment_reminder.apply_async"):
            appt = _make_appointment_via_service(
                tenant, doctor, patient, user, starts_at=starts_at
            )

        # Assert — al menos 1 reminder PENDING existe
        assert AppointmentReminder.all_objects.filter(
            appointment=appt,
            status=AppointmentReminder.ReminderStatus.PENDING,
        ).exists()

    def test_appointment_create_reminder_failure_does_not_break_creation(
        self, db: None
    ) -> None:
        """Si schedule_reminders lanza excepcion, la cita igual se crea (best-effort)."""
        # Arrange
        tenant = TenantFactory()
        _config_for(tenant, reminder_offsets_minutes=[1440], reminders_enabled=True)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        starts_at = timezone.now() + datetime.timedelta(days=2)

        # Act — schedule_reminders explota, la cita debe sobrevivir
        with patch(
            "apps.agenda.services.schedule_reminders_for_appointment",
            side_effect=RuntimeError("Fallo simulado en reminders"),
        ):
            with _tenant_context(tenant):
                appt = appointment_create(
                    tenant=tenant,  # type: ignore[arg-type]
                    user=user,
                    patient_id=patient.id,
                    doctor_id=doctor.id,
                    starts_at=starts_at,
                    reason="Test best-effort",
                )

        # Assert — la cita existe aunque los reminders fallaron
        assert appt.pk is not None
        assert Appointment.all_objects.filter(pk=appt.pk).exists()


# ===========================================================================
# cancel_reminders_for_appointment
# ===========================================================================


class TestCancelRemindersForAppointment:
    """cancel_reminders_for_appointment: marca PENDING como CANCELLED."""

    def test_cancel_marks_pending_as_cancelled(self, db: None) -> None:
        """Reminders PENDING se marcan CANCELLED; devuelve el count correcto."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            starts_at=_FUTURE,
        )
        r1 = _make_reminder(appt)
        r2 = _make_reminder(
            appt, scheduled_at=_FUTURE - datetime.timedelta(hours=2)
        )

        # Act
        count = cancel_reminders_for_appointment(appointment=appt)

        # Assert
        assert count == 2
        r1.refresh_from_db()
        r2.refresh_from_db()
        assert r1.status == AppointmentReminder.ReminderStatus.CANCELLED
        assert r2.status == AppointmentReminder.ReminderStatus.CANCELLED

    def test_cancel_ignores_already_sent_reminders(self, db: None) -> None:
        """Un reminder ya SENT no se toca al cancelar."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            starts_at=_FUTURE,
        )
        sent_reminder = _make_reminder(
            appt, status=AppointmentReminder.ReminderStatus.SENT
        )
        pending_reminder = _make_reminder(
            appt, scheduled_at=_FUTURE - datetime.timedelta(hours=2)
        )

        # Act
        count = cancel_reminders_for_appointment(appointment=appt)

        # Assert — solo el PENDING fue cancelado
        assert count == 1
        sent_reminder.refresh_from_db()
        pending_reminder.refresh_from_db()
        assert sent_reminder.status == AppointmentReminder.ReminderStatus.SENT
        assert pending_reminder.status == AppointmentReminder.ReminderStatus.CANCELLED

    def test_cancel_returns_zero_when_no_pending(self, db: None) -> None:
        """Si no hay reminders PENDING, devuelve 0."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            starts_at=_FUTURE,
        )

        # Act — sin reminders creados
        count = cancel_reminders_for_appointment(appointment=appt)

        # Assert
        assert count == 0

    def test_change_status_cancelled_cancels_reminders(self, db: None) -> None:
        """appointment_change_status a CANCELLED cancela los reminders PENDING."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=_FUTURE,
        )
        reminder = _make_reminder(appt)
        user = UserFactory()

        # Act
        appointment_change_status(
            appointment=appt, user=user, new_status=Appointment.Status.CANCELLED
        )

        # Assert
        reminder.refresh_from_db()
        assert reminder.status == AppointmentReminder.ReminderStatus.CANCELLED

    def test_change_status_no_show_cancels_reminders(self, db: None) -> None:
        """appointment_change_status a NO_SHOW cancela los reminders PENDING."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=_FUTURE,
        )
        reminder = _make_reminder(appt)
        user = UserFactory()

        # Act
        appointment_change_status(
            appointment=appt, user=user, new_status=Appointment.Status.NO_SHOW
        )

        # Assert
        reminder.refresh_from_db()
        assert reminder.status == AppointmentReminder.ReminderStatus.CANCELLED

    def test_change_status_attended_does_not_cancel_reminders(
        self, db: None
    ) -> None:
        """appointment_change_status a ATTENDED (desde IN_PROGRESS) NO cancela reminders.

        ATTENDED no esta en el bloque de cancelacion de services.py.
        """
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            status=Appointment.Status.IN_PROGRESS,
            starts_at=_FUTURE,
        )
        reminder = _make_reminder(appt)
        user = UserFactory()

        # Act
        appointment_change_status(
            appointment=appt, user=user, new_status=Appointment.Status.ATTENDED
        )

        # Assert — PENDING sigue PENDING (ATTENDED no cancela reminders)
        reminder.refresh_from_db()
        assert reminder.status == AppointmentReminder.ReminderStatus.PENDING


# ===========================================================================
# send_appointment_reminder (tarea Celery — llamada directa)
# ===========================================================================


class TestSendAppointmentReminderTask:
    """send_appointment_reminder: comportamiento con adapter mockeado."""

    def _call_task(self, reminder_id: str) -> str:
        """Llama la tarea directamente como funcion normal (sin Celery)."""
        return send_appointment_reminder(reminder_id=reminder_id)  # type: ignore[call-arg]

    def test_task_sends_when_pending_and_appointment_active(self, db: None) -> None:
        """Reminder PENDING + cita SCHEDULED -> adapter exitoso -> status SENT."""
        # Arrange — teléfono E.164 válido requerido por F4
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant, phone="+5214421112222")
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=_FUTURE,
        )
        reminder = _make_reminder(appt)
        fake_result = WhatsAppResult(success=True, external_message_id="ext-abc-123")

        # Act
        with patch("apps.agenda.tasks.get_whatsapp_adapter") as mock_factory:
            mock_adapter = MagicMock()
            mock_adapter.send_template.return_value = fake_result
            mock_factory.return_value = mock_adapter
            result = self._call_task(str(reminder.id))

        # Assert
        assert result == "sent:ext-abc-123"
        reminder.refresh_from_db()
        assert reminder.status == AppointmentReminder.ReminderStatus.SENT
        assert reminder.sent_at is not None
        assert reminder.external_message_id == "ext-abc-123"
        assert reminder.message_preview != ""

    def test_task_skips_when_reminder_already_sent(self, db: None) -> None:
        """Reminder ya SENT -> tarea retorna skipped sin reenviar."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            starts_at=_FUTURE,
        )
        reminder = _make_reminder(appt, status=AppointmentReminder.ReminderStatus.SENT)

        # Act
        with patch("apps.agenda.tasks.get_whatsapp_adapter") as mock_factory:
            result = self._call_task(str(reminder.id))

        # Assert — no llamo al adapter
        mock_factory.assert_not_called()
        assert result == "skipped:sent"
        reminder.refresh_from_db()
        assert reminder.status == AppointmentReminder.ReminderStatus.SENT

    def test_task_skips_when_reminder_already_cancelled(self, db: None) -> None:
        """Reminder CANCELLED -> tarea retorna skipped sin enviar."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            starts_at=_FUTURE,
        )
        reminder = _make_reminder(
            appt, status=AppointmentReminder.ReminderStatus.CANCELLED
        )

        # Act
        with patch("apps.agenda.tasks.get_whatsapp_adapter") as mock_factory:
            result = self._call_task(str(reminder.id))

        # Assert
        mock_factory.assert_not_called()
        assert result == "skipped:cancelled"

    def test_task_marks_skipped_when_appointment_is_cancelled(self, db: None) -> None:
        """Reminder PENDING pero cita CANCELLED -> reminder SKIPPED (no se envia)."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            status=Appointment.Status.CANCELLED,
            starts_at=_FUTURE,
        )
        # Creamos el reminder directamente con all_objects para saltarnos el TenantManager
        reminder = AppointmentReminder.all_objects.create(
            tenant=tenant,
            created_by=appt.created_by,
            appointment=appt,
            channel=AppointmentReminder.Channel.WHATSAPP,
            scheduled_at=_FUTURE - datetime.timedelta(hours=24),
            status=AppointmentReminder.ReminderStatus.PENDING,
        )

        # Act
        with patch("apps.agenda.tasks.get_whatsapp_adapter") as mock_factory:
            result = self._call_task(str(reminder.id))

        # Assert — no se envia; reminder marcado SKIPPED
        mock_factory.assert_not_called()
        assert result.startswith("skipped:appointment_")
        reminder.refresh_from_db()
        assert reminder.status == AppointmentReminder.ReminderStatus.SKIPPED
        # El error_detail usa get_status_display() -> "Cancelada" (label en espanol)
        assert reminder.error_detail != ""

    def test_task_marks_skipped_when_appointment_is_no_show(self, db: None) -> None:
        """Reminder PENDING + cita NO_SHOW -> reminder SKIPPED."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            status=Appointment.Status.NO_SHOW,
            starts_at=_FUTURE,
        )
        reminder = AppointmentReminder.all_objects.create(
            tenant=tenant,
            created_by=appt.created_by,
            appointment=appt,
            channel=AppointmentReminder.Channel.WHATSAPP,
            scheduled_at=_FUTURE - datetime.timedelta(hours=24),
            status=AppointmentReminder.ReminderStatus.PENDING,
        )

        # Act
        with patch("apps.agenda.tasks.get_whatsapp_adapter") as mock_factory:
            result = self._call_task(str(reminder.id))

        # Assert
        mock_factory.assert_not_called()
        reminder.refresh_from_db()
        assert reminder.status == AppointmentReminder.ReminderStatus.SKIPPED

    def test_task_marks_failed_when_adapter_returns_failure(self, db: None) -> None:
        """Adapter devuelve success=False -> reminder FAILED con error_detail."""
        # Arrange — teléfono E.164 válido para superar la validación F4
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant, phone="+5214421112222")
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=_FUTURE,
        )
        reminder = _make_reminder(appt)
        fail_result = WhatsAppResult(success=False, error="Rate limit exceeded")

        # Act
        with patch("apps.agenda.tasks.get_whatsapp_adapter") as mock_factory:
            mock_adapter = MagicMock()
            mock_adapter.send_template.return_value = fail_result
            mock_factory.return_value = mock_adapter
            result = self._call_task(str(reminder.id))

        # Assert — return value sanitized (F3: no raw external error in task result)
        assert result == "failed:adapter_error"
        reminder.refresh_from_db()
        assert reminder.status == AppointmentReminder.ReminderStatus.FAILED
        # error_detail is persisted in DB (protected by RLS) — still contains full info
        assert "Rate limit exceeded" in reminder.error_detail
        assert reminder.message_preview != ""

    def test_task_returns_not_found_for_missing_reminder(self, db: None) -> None:
        """UUID inexistente -> tarea retorna 'not_found' sin lanzar excepcion."""
        # Arrange — UUID que no existe en BD
        nonexistent_id = str(uuid.uuid4())

        # Act
        result = self._call_task(nonexistent_id)

        # Assert
        assert result == "not_found"

    def test_task_message_preview_stored_on_success(self, db: None) -> None:
        """Tras envio exitoso, message_preview contiene el nombre del paciente."""
        # Arrange — teléfono E.164 válido requerido por F4
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(
            tenant=tenant,
            first_name="Maria",
            paternal_surname="Lopez",
            phone="+5214421112222",
        )
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=_FUTURE,
        )
        reminder = _make_reminder(appt)
        ok_result = WhatsAppResult(success=True, external_message_id="ext-preview-001")

        # Act
        with patch("apps.agenda.tasks.get_whatsapp_adapter") as mock_factory:
            mock_adapter = MagicMock()
            mock_adapter.send_template.return_value = ok_result
            mock_factory.return_value = mock_adapter
            self._call_task(str(reminder.id))

        # Assert
        reminder.refresh_from_db()
        # El mensaje de preview debe contener datos del paciente
        assert len(reminder.message_preview) > 0
        assert "Maria" in reminder.message_preview or "Lopez" in reminder.message_preview

    def test_task_error_detail_empty_on_success(self, db: None) -> None:
        """Tras envio exitoso, error_detail queda vacio (limpiado por la tarea)."""
        # Arrange — teléfono E.164 válido requerido por F4
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant, phone="+5214421112222")
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=_FUTURE,
        )
        reminder = _make_reminder(appt)
        ok_result = WhatsAppResult(success=True, external_message_id="ext-clean")

        # Act
        with patch("apps.agenda.tasks.get_whatsapp_adapter") as mock_factory:
            mock_adapter = MagicMock()
            mock_adapter.send_template.return_value = ok_result
            mock_factory.return_value = mock_adapter
            self._call_task(str(reminder.id))

        # Assert
        reminder.refresh_from_db()
        assert reminder.error_detail == ""

    def test_task_falls_back_date_str_on_invalid_timezone(self, db: None) -> None:
        """Si el tenant tiene un timezone invalido, la fecha se formatea en UTC (fallback)."""
        # Arrange — teléfono E.164 válido; timezone inválido se fuerza con patch
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant, phone="+5214421112222")
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=_FUTURE,
        )
        reminder = _make_reminder(appt)
        ok_result = WhatsAppResult(success=True, external_message_id="ext-tz-fallback")

        # Act — hacemos que ZoneInfo falle para ejercitar la rama except
        with patch("apps.agenda.tasks.get_whatsapp_adapter") as mock_factory:
            mock_adapter = MagicMock()
            mock_adapter.send_template.return_value = ok_result
            mock_factory.return_value = mock_adapter
            with patch("zoneinfo.ZoneInfo", side_effect=Exception("bad tz")):
                result = self._call_task(str(reminder.id))

        # Assert — la tarea completo exitosamente con el fallback de formato
        assert result.startswith("sent:")
        reminder.refresh_from_db()
        assert reminder.status == AppointmentReminder.ReminderStatus.SENT
        # El message_preview debe contener el formato UTC fallback (YYYY-MM-DD)
        assert "UTC" in reminder.message_preview

    def test_task_skips_when_phone_missing(self, db: None) -> None:
        """F4: Paciente sin teléfono -> reminder SKIPPED, tarea retorna 'skipped:invalid_phone'."""
        # Arrange — phone vacío (por defecto la factory usa un número sin +, no E.164)
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant, phone="")
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=_FUTURE,
        )
        reminder = _make_reminder(appt)

        # Act — no se debe llamar al adapter
        with patch("apps.agenda.tasks.get_whatsapp_adapter") as mock_factory:
            result = self._call_task(str(reminder.id))

        # Assert
        mock_factory.assert_not_called()
        assert result == "skipped:invalid_phone"
        reminder.refresh_from_db()
        assert reminder.status == AppointmentReminder.ReminderStatus.SKIPPED
        assert reminder.error_detail == "Teléfono ausente o no E.164."

    def test_task_skips_when_phone_not_e164(self, db: None) -> None:
        """F4: Teléfono sin prefijo '+' -> reminder SKIPPED."""
        # Arrange — número sin '+' (formato México sin código de país)
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant, phone="4421112222")
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=_FUTURE,
        )
        reminder = _make_reminder(appt)

        # Act
        with patch("apps.agenda.tasks.get_whatsapp_adapter") as mock_factory:
            result = self._call_task(str(reminder.id))

        # Assert
        mock_factory.assert_not_called()
        assert result == "skipped:invalid_phone"
        reminder.refresh_from_db()
        assert reminder.status == AppointmentReminder.ReminderStatus.SKIPPED

    def test_task_marks_failed_on_max_retries_exceeded(self, db: None) -> None:
        """Adapter lanza excepcion + MaxRetriesExceededError -> reminder FAILED con detalle.

        Celery con bind=True: 'self' es la instancia Task inyectada por el framework.
        Para simular que self.retry() levante MaxRetriesExceededError, parcheamos
        el metodo retry directamente en la tarea registrada.
        """
        # Arrange — teléfono E.164 válido para superar la validación F4
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant, phone="+5214421112222")
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=_FUTURE,
        )
        reminder = _make_reminder(appt)

        from celery.exceptions import MaxRetriesExceededError
        from apps.agenda.tasks import send_appointment_reminder as task_proxy

        network_error = ConnectionError("Network unreachable")

        # Act — parchamos el metodo retry de la instancia Task para que levante
        # MaxRetriesExceededError inmediatamente (simulando reintentos agotados).
        with patch("apps.agenda.tasks.get_whatsapp_adapter") as mock_factory:
            mock_adapter = MagicMock()
            mock_adapter.send_template.side_effect = network_error
            mock_factory.return_value = mock_adapter
            with patch.object(
                task_proxy,
                "retry",
                side_effect=MaxRetriesExceededError("agotado"),
            ):
                result = self._call_task(str(reminder.id))

        # Assert — return value sanitized (F3: no raw exception in task result)
        assert result == "failed:max_retries"
        reminder.refresh_from_db()
        assert reminder.status == AppointmentReminder.ReminderStatus.FAILED
        # error_detail (DB/RLS-protected) still carries full exception message
        assert "reintentos" in reminder.error_detail


# ===========================================================================
# SimulatedWhatsAppAdapter
# ===========================================================================


class TestSimulatedWhatsAppAdapter:
    """SimulatedWhatsAppAdapter: contrato publico de la interfaz."""

    def test_send_template_returns_success(self) -> None:
        """SimulatedWhatsAppAdapter.send_template siempre devuelve success=True."""
        # Arrange
        adapter = SimulatedWhatsAppAdapter()

        # Act
        result = adapter.send_template(
            to="+5215512345678",
            template="recordatorio_cita",
            params={"nombre_paciente": "Juan Perez", "fecha_hora": "01/06/2035 12:00"},
        )

        # Assert
        assert result.success is True
        assert result.error == ""

    def test_send_template_returns_sim_prefixed_id(self) -> None:
        """El external_message_id del adapter simulado empieza con 'sim-'."""
        # Arrange
        adapter = SimulatedWhatsAppAdapter()

        # Act
        result = adapter.send_template(
            to="+5215512345678",
            template="recordatorio_cita",
            params={},
        )

        # Assert
        assert result.external_message_id.startswith("sim-")

    def test_send_template_returns_unique_ids(self) -> None:
        """Dos llamadas consecutivas producen external_message_id distintos."""
        # Arrange
        adapter = SimulatedWhatsAppAdapter()

        # Act
        result_a = adapter.send_template(to="+521", template="t", params={})
        result_b = adapter.send_template(to="+521", template="t", params={})

        # Assert
        assert result_a.external_message_id != result_b.external_message_id


# ===========================================================================
# reminder_list_for_appointment (selector)
# ===========================================================================


class TestReminderListForAppointment:
    """reminder_list_for_appointment: orden y filtrado correcto."""

    def test_reminder_list_ordered_by_scheduled_at(self, db: None) -> None:
        """Los reminders se devuelven ordenados por scheduled_at ASC."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            starts_at=_FUTURE,
        )
        # Crear en orden inverso para verificar el ordenamiento
        r_late = _make_reminder(appt, scheduled_at=_FUTURE - datetime.timedelta(hours=2))
        r_early = _make_reminder(appt, scheduled_at=_FUTURE - datetime.timedelta(hours=48))

        # Act
        with _tenant_context(tenant):
            qs = list(reminder_list_for_appointment(appointment=appt))

        # Assert — r_early primero (mas antiguo), r_late segundo
        assert qs[0].id == r_early.id
        assert qs[1].id == r_late.id

    def test_reminder_list_only_for_given_appointment(self, db: None) -> None:
        """Solo devuelve reminders de la cita especificada, no de otras citas."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt_a = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            starts_at=_FUTURE,
        )
        appt_b = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            starts_at=_FUTURE + datetime.timedelta(hours=2),
        )
        r_a = _make_reminder(appt_a)
        _make_reminder(appt_b)  # no debe aparecer

        # Act
        with _tenant_context(tenant):
            qs = list(reminder_list_for_appointment(appointment=appt_a))

        # Assert — solo el reminder de appt_a
        assert len(qs) == 1
        assert qs[0].id == r_a.id


# ===========================================================================
# AppointmentOutputSerializer — anida reminders
# ===========================================================================


class TestAppointmentOutputSerializerIncludesReminders:
    """El serializer de salida anida la lista de reminders correctamente."""

    def test_appointment_output_includes_reminders_field(self, db: None) -> None:
        """AppointmentOutputSerializer incluye la clave 'reminders' en la salida."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            starts_at=_FUTURE,
        )
        reminder = _make_reminder(appt)

        # Simular el prefetch que hace la vista real
        appt_with_prefetch = (
            Appointment.all_objects
            .prefetch_related("reminders")
            .get(pk=appt.pk)
        )

        # Act
        data = AppointmentOutputSerializer(appt_with_prefetch).data

        # Assert
        assert "reminders" in data
        assert len(data["reminders"]) == 1
        r_data = data["reminders"][0]
        assert str(r_data["id"]) == str(reminder.id)
        assert r_data["channel"] == "whatsapp"
        assert r_data["status"] == "pending"

    def test_appointment_output_reminders_empty_list_when_none(self, db: None) -> None:
        """Cita sin reminders devuelve reminders como lista vacia."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            starts_at=_FUTURE,
        )

        appt_with_prefetch = (
            Appointment.all_objects
            .prefetch_related("reminders")
            .get(pk=appt.pk)
        )

        # Act
        data = AppointmentOutputSerializer(appt_with_prefetch).data

        # Assert
        assert data["reminders"] == []

    def test_appointment_output_reminder_includes_channel_display(
        self, db: None
    ) -> None:
        """El reminder anidado incluye channel_display y status_display legibles."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            starts_at=_FUTURE,
        )
        _make_reminder(appt)

        appt_with_prefetch = (
            Appointment.all_objects
            .prefetch_related("reminders")
            .get(pk=appt.pk)
        )

        # Act
        data = AppointmentOutputSerializer(appt_with_prefetch).data

        # Assert — display fields presentes y no vacios
        r_data = data["reminders"][0]
        assert r_data["channel_display"] == "WhatsApp"
        assert r_data["status_display"] == "Pendiente"


# ===========================================================================
# appointment_reschedule — integration test (F5 reviewer recommendation)
# ===========================================================================


class TestAppointmentRescheduleReminders:
    """appointment_reschedule cancela reminders viejos y programa nuevos."""

    def test_reschedule_cancels_old_and_schedules_new_reminders(
        self, db: None
    ) -> None:
        """F5/REC: reagendar cancela los reminders del horario viejo y crea nuevos
        para el horario nuevo.

        Verifica:
          - Los reminders PENDING del horario original quedan CANCELLED.
          - Se crean nuevos reminders PENDING para el nuevo starts_at.
          - apply_async se llama para los nuevos reminders.
        """
        # Arrange
        tenant = TenantFactory()
        _config_for(tenant, reminder_offsets_minutes=[1440], reminders_enabled=True)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()

        original_starts = _FUTURE
        new_starts = _FUTURE + datetime.timedelta(days=1)

        # Crear la cita sin programar reminders automáticamente
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=original_starts,
            ends_at=original_starts + datetime.timedelta(hours=1),
        )
        # Crear manualmente un reminder PENDING para el horario original
        old_reminder = _make_reminder(appt, scheduled_at=original_starts - datetime.timedelta(hours=24))
        assert old_reminder.status == AppointmentReminder.ReminderStatus.PENDING

        # Act — reagendar con un nuevo horario
        with patch("apps.agenda.tasks.send_appointment_reminder.apply_async") as mock_enqueue:
            updated_appt = appointment_reschedule(
                appointment=appt,
                user=user,
                starts_at=new_starts,
                ends_at=new_starts + datetime.timedelta(hours=1),
            )

        # Assert 1: el reminder viejo quedó CANCELLED
        old_reminder.refresh_from_db()
        assert old_reminder.status == AppointmentReminder.ReminderStatus.CANCELLED

        # Assert 2: se crearon nuevos reminders PENDING para el horario nuevo
        new_reminders = list(
            AppointmentReminder.all_objects.filter(
                appointment=updated_appt,
                status=AppointmentReminder.ReminderStatus.PENDING,
            )
        )
        assert len(new_reminders) >= 1
        # El scheduled_at del nuevo reminder debe corresponder al nuevo horario
        expected_eta = new_starts - datetime.timedelta(minutes=1440)
        assert new_reminders[0].scheduled_at == expected_eta

        # Assert 3: apply_async fue llamado para los nuevos reminders
        mock_enqueue.assert_called_once()
        call_kwargs = mock_enqueue.call_args
        assert call_kwargs.kwargs["eta"] == expected_eta

    def test_reschedule_rollback_does_not_cancel_reminders(
        self, db: None
    ) -> None:
        """F5: si la transacción hace rollback (overlap constraint), los reminders
        del horario original NO quedan cancelados (están fuera del atomic()).
        """
        # Arrange
        tenant = TenantFactory()
        _config_for(tenant, reminder_offsets_minutes=[1440], reminders_enabled=True)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()

        original_starts = _FUTURE
        conflict_starts = _FUTURE + datetime.timedelta(hours=5)

        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=original_starts,
            ends_at=original_starts + datetime.timedelta(hours=1),
        )
        # Crear otra cita que bloqueará el reagendamiento por overlap
        AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=conflict_starts,
            ends_at=conflict_starts + datetime.timedelta(hours=1),
        )
        old_reminder = _make_reminder(appt)

        # Act — intentar reagendar al horario conflictivo
        from django.core.exceptions import ValidationError as DjangoValidationError
        with pytest.raises(DjangoValidationError):
            appointment_reschedule(
                appointment=appt,
                user=user,
                starts_at=conflict_starts,
                ends_at=conflict_starts + datetime.timedelta(hours=1),
            )

        # Assert — el reminder original sigue PENDING (no fue cancelado)
        old_reminder.refresh_from_db()
        assert old_reminder.status == AppointmentReminder.ReminderStatus.PENDING
