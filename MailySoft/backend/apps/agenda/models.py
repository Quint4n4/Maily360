"""
Modelos de la app agenda.

TenantAgendaConfig    — configuración de agenda por clínica (1 registro por tenant).
Appointment           — cita médica con máquina de estados explícita.
AppointmentReminder   — recordatorio de cita (WhatsApp/SMS/Email, programado vía Celery).

Todos heredan de TenantAwareModel (id UUID, timestamps, soft-delete, tenant FK,
created_by, TenantManager con filtro por tenant activo).

Máquina de estados (ver VALID_TRANSITIONS al final del módulo):
    SCHEDULED → CONFIRMED, CANCELLED, NO_SHOW
    CONFIRMED → ARRIVED, CANCELLED, NO_SHOW
    ARRIVED   → IN_PROGRESS, CANCELLED, NO_SHOW
    IN_PROGRESS → ATTENDED
    ATTENDED / CANCELLED / NO_SHOW → (terminal)

Anti-empalme:
  - Capa 1 (service): verificación antes de INSERT.
  - Capa 2 (BD): exclusion constraints btree_gist en migración 0002_*.
                 NO se modelan en Meta de Django (requieren btree_gist + sintaxis raw).
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import TenantAwareModel

# ---------------------------------------------------------------------------
# Helpers de default para JSONField
# ---------------------------------------------------------------------------


def _default_reminder_offsets() -> list[int]:
    """Default para reminder_offsets_minutes: [1440] (24 horas antes)."""
    return [1440]


# ---------------------------------------------------------------------------
# TenantAgendaConfig
# ---------------------------------------------------------------------------


class TenantAgendaConfig(TenantAwareModel):
    """Configuración de agenda de una clínica.

    Un único registro por tenant. Se obtiene (o crea con defaults) a través del
    selector `agenda_config_get(tenant=...)` que llama get_or_create internamente.

    Campos:
        record_number_format:       Plantilla para número de expediente.
                                    Placeholders: {year}, {seq}.
                                    Solo se almacena; la generación la hace
                                    `_next_record_number` en pacientes/services.py.
                                    TODO(3c): leer desde aquí en ese service.
        record_number_reset_yearly: Si el consecutivo se reinicia cada año.
        default_appointment_duration: Duración default de cita en minutos (nivel clínica).
                                    Doctor.default_appointment_duration tiene precedencia.
        reminder_offsets_minutes:   Lista de minutos antes de la cita para recordatorios.
                                    Default [1440] = 24 horas. Ejemplo [1440, 120] = 24h y 2h.
        reminders_enabled:          Interruptor global de recordatorios de la clínica.
        agenda_start_hour:          Hora (0-23) a la que ABRE la rejilla de la agenda.
                                    Default 9 (9:00 am).
        agenda_end_hour:            Hora (1-24) a la que CIERRA la rejilla, EXCLUSIVA:
                                    la última franja mostrada termina a esta hora.
                                    Default 18 (la agenda cierra a las 18:00).
                                    Debe ser mayor que agenda_start_hour.
        slot_interval_minutes:      Granularidad de la rejilla en minutos (cada cuánto
                                    hay una línea). Default 30. Solo acepta
                                    SLOT_INTERVAL_CHOICES.
    """

    #: Granularidades válidas para la rejilla de la agenda.
    SLOT_INTERVAL_CHOICES = [
        (5, "5 minutos"),
        (10, "10 minutos"),
        (15, "15 minutos"),
        (20, "20 minutos"),
        (30, "30 minutos"),
        (60, "60 minutos"),
    ]

    record_number_format = models.CharField(
        max_length=50,
        default="EXP-{year}-{seq:05d}",
        help_text=(
            "Plantilla del número de expediente. "
            "Placeholders: {year} (año) y {seq} (consecutivo). "
            "Ejemplo: EXP-{year}-{seq:05d}"
        ),
    )
    record_number_reset_yearly = models.BooleanField(
        default=False,
        help_text="Si True, el consecutivo de expediente se reinicia cada año.",
    )
    default_appointment_duration = models.PositiveSmallIntegerField(
        default=30,
        help_text=(
            "Duración default de cita en minutos a nivel clínica. "
            "Doctor.default_appointment_duration tiene precedencia sobre este valor."
        ),
    )
    reminder_offsets_minutes = models.JSONField(
        default=_default_reminder_offsets,
        help_text=(
            "Lista de enteros: minutos antes de la cita para cada recordatorio. "
            "Ejemplo: [1440] = 24h, [1440, 120] = 24h y 2h."
        ),
    )
    reminders_enabled = models.BooleanField(
        default=True,
        help_text="Interruptor global de recordatorios de la clínica.",
    )
    agenda_start_hour = models.PositiveSmallIntegerField(
        default=9,
        help_text="Hora (0-23) a la que abre la rejilla de la agenda. Ejemplo: 9 = 9:00 am.",
    )
    agenda_end_hour = models.PositiveSmallIntegerField(
        default=18,
        help_text=(
            "Hora (1-24) a la que cierra la rejilla de la agenda. EXCLUSIVA: la "
            "última franja mostrada termina a esta hora. Ejemplo: 18 = cierra a "
            "las 18:00. Debe ser mayor que agenda_start_hour."
        ),
    )
    slot_interval_minutes = models.PositiveSmallIntegerField(
        default=30,
        choices=SLOT_INTERVAL_CHOICES,
        help_text="Cada cuántos minutos hay una línea en la rejilla de la agenda.",
    )

    class Meta:
        db_table = "agenda_tenant_config"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant"],
                name="agenda_config_tenant_uniq",
            ),
            # Defensa en profundidad — la validación de negocio vive en
            # agenda_config_update (services.py); esta constraint solo protege
            # contra escrituras que no pasen por ahí (ej. fixtures, SQL directo).
            models.CheckConstraint(
                condition=Q(agenda_start_hour__gte=0) & Q(agenda_start_hour__lte=23),
                name="agenda_config_start_hour_range",
            ),
            models.CheckConstraint(
                condition=Q(agenda_end_hour__gte=1) & Q(agenda_end_hour__lte=24),
                name="agenda_config_end_hour_range",
            ),
            models.CheckConstraint(
                condition=Q(agenda_end_hour__gt=models.F("agenda_start_hour")),
                name="agenda_config_end_after_start",
            ),
            models.CheckConstraint(
                condition=Q(slot_interval_minutes__in=[5, 10, 15, 20, 30, 60]),
                name="agenda_config_slot_interval_choices",
            ),
        ]

    def __str__(self) -> str:
        tenant_name = getattr(self.tenant, "name", str(self.tenant_id))
        dur = self.default_appointment_duration
        return f"Config agenda — {tenant_name} (dur. default: {dur} min)"


# ---------------------------------------------------------------------------
# Appointment
# ---------------------------------------------------------------------------


class AppointmentType(TenantAwareModel):
    """Tipo de cita configurable por clínica (Primera vez, Seguimiento, Urgente…).

    Cada tipo tiene un color para diferenciar las citas en el tablero de la agenda.
    Se administra (crear/editar/desactivar) igual que los consultorios.
    """

    name = models.CharField(
        max_length=80,
        help_text="Nombre del tipo de cita (ej. 'Primera vez', 'Seguimiento').",
    )
    color_hex = models.CharField(
        max_length=7,
        blank=True,
        default="",
        help_text="Color #RRGGBB para distinguir el tipo en la agenda.",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="False = tipo desactivado (no aparece al agendar).",
    )

    class Meta:
        db_table = "agenda_appointment_types"
        ordering = ["name"]
        constraints = [
            # Nombre único por clínica entre los tipos no borrados.
            models.UniqueConstraint(
                fields=["tenant", "name"],
                condition=Q(deleted_at__isnull=True),
                name="appointment_type_name_uniq",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class AgendaBlock(TenantAwareModel):
    """Evento de agenda SIN paciente: reunión o bloqueo de horario.

    - MEETING (reunión): evento con título (ej. 'Junta de equipo').
    - BLOCK (bloqueo): marca un horario como NO disponible.

    Alcance (a qué afecta para el anti-empalme de citas):
      - doctor y consultorio en null → toda la clínica (día festivo, etc.).
      - doctor seteado               → ese médico está ocupado.
      - consultorio seteado          → ese consultorio está ocupado.
    Una cita de paciente NO puede agendarse sobre un evento que le aplique
    (ver _check_block_overlap en services.py).
    """

    class Kind(models.TextChoices):
        MEETING = "meeting", "Reunión"
        BLOCK = "block", "Bloqueo"

    kind = models.CharField(
        max_length=10,
        choices=Kind.choices,
        default=Kind.BLOCK,
        db_index=True,
    )
    title = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="Título del evento (ej. 'Junta', 'Día festivo'). Opcional.",
    )
    doctor = models.ForeignKey(
        "personal.Doctor",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="agenda_blocks",
        help_text="Médico al que aplica. Null = no atado a un médico.",
    )
    consultorio = models.ForeignKey(
        "personal.Consultorio",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="agenda_blocks",
        help_text="Consultorio al que aplica. Null = no atado a un consultorio.",
    )
    sucursal = models.ForeignKey(
        "clinica.Sucursal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agenda_blocks",
        help_text=(
            "Sucursal (sede) del evento (multi-sede — Fase 2). Determina el "
            "alcance de un bloqueo SIN doctor ni consultorio ('de toda la "
            "clínica' pasó a ser 'de una sucursal': un cierre en Centro ya NO "
            "bloquea Norte). Un bloqueo con doctor sigue aplicando en TODAS "
            "las sedes de ese médico; uno con consultorio, solo a ese cuarto. "
            "Se resuelve automáticamente si no se indica explícitamente."
        ),
    )
    starts_at = models.DateTimeField(db_index=True, help_text="Inicio en UTC.")
    ends_at = models.DateTimeField(help_text="Fin en UTC. Debe ser posterior a starts_at.")
    all_day = models.BooleanField(default=False, help_text="True = ocupa el día completo.")
    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "agenda_blocks"
        ordering = ["starts_at"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.title or self.starts_at}"  # type: ignore[attr-defined]


class Appointment(TenantAwareModel):
    """Cita médica dentro de un tenant.

    ZONA HORARIA: starts_at y ends_at se almacenan en UTC (USE_TZ=True).
    La presentación en hora local es responsabilidad del frontend usando
    Tenant.timezone.

    MÁQUINA DE ESTADOS: los cambios de estado SOLO ocurren a través del
    service `appointment_change_status`. NUNCA actualizar `status` directamente
    desde un PATCH genérico.

    ANTI-EMPALME: la validación de solapamiento (capa 1) ocurre en services.py.
    La capa 2 (exclusion constraints PostgreSQL) está en la migración 0002.

    GANCHO v2: series_id es un UUID nullable para futura funcionalidad de
    citas recurrentes/series. En v1 siempre es None. NO modelar Series aún.
    """

    class Status(models.TextChoices):
        """Estados posibles de una cita médica."""

        SCHEDULED = "scheduled", "Agendada"
        CONFIRMED = "confirmed", "Confirmada"
        ARRIVED = "arrived", "En sala"
        IN_PROGRESS = "in_progress", "En consulta"
        ATTENDED = "attended", "Atendida"
        CANCELLED = "cancelled", "Cancelada"
        NO_SHOW = "no_show", "No se presentó"

    class Modality(models.TextChoices):
        """Modalidad de la cita (dónde/cómo se realiza)."""

        OFFICE = "office", "Consultorio u Oficina"
        PHONE = "phone", "Telefónica"
        VIDEO = "video", "Video Llamada"
        OFFSITE = "offsite", "Fuera de la Instalación"

    # ---- Relaciones principales ----

    patient = models.ForeignKey(
        "pacientes.Patient",
        on_delete=models.PROTECT,
        related_name="appointments",
        help_text="Paciente al que corresponde la cita.",
    )
    doctor = models.ForeignKey(
        "personal.Doctor",
        on_delete=models.PROTECT,
        related_name="appointments",
        help_text="Médico que atenderá la cita.",
    )
    consultorio = models.ForeignKey(
        "personal.Consultorio",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="appointments",
        help_text=(
            "Consultorio donde se realizará la cita. "
            "Opcional (puede ser telemedicina o domicilio)."
        ),
    )
    sucursal = models.ForeignKey(
        "clinica.Sucursal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_index=True,
        related_name="appointments",
        help_text=(
            "Sucursal (sede) donde se agenda la cita (multi-sede — Fase 2). "
            "Se resuelve automáticamente en appointment_create si no se "
            "indica explícitamente (consultorio.sucursal → sede activa del "
            "request → sede predeterminada del tenant). Null = dato legado "
            "sin backfillar. La disponibilidad del MÉDICO sigue siendo "
            "GLOBAL entre sedes (ver _check_doctor_overlap); solo los "
            "bloqueos 'de toda la clínica' quedan acotados por sucursal."
        ),
    )
    modality = models.CharField(
        max_length=12,
        choices=Modality.choices,
        default=Modality.OFFICE,
        db_index=True,
        help_text="Modalidad: consultorio, telefónica, video o fuera de la instalación.",
    )

    # ---- Horario ----

    starts_at = models.DateTimeField(
        db_index=True,
        help_text="Inicio de la cita en UTC.",
    )
    ends_at = models.DateTimeField(
        help_text="Fin de la cita en UTC. Debe ser posterior a starts_at.",
    )

    # ---- Estado ----

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SCHEDULED,
        db_index=True,
        help_text=(
            "Estado actual de la cita. "
            "SOLO modificar a través de appointment_change_status en services.py."
        ),
    )

    # ---- Información clínica ----

    reason = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Motivo de la cita (texto libre, opcional).",
    )
    appointment_type = models.ForeignKey(
        "agenda.AppointmentType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
        help_text="Tipo de cita (categoría con color). Opcional.",
    )
    specialty = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Especialidad de la cita. Texto libre en v1; catálogo en v2.",
    )
    notes = models.TextField(
        blank=True,
        default="",
        help_text="Notas internas de la cita.",
    )

    # ---- Campos de cancelación ----

    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Usuario que canceló la cita.",
    )
    cancellation_reason = models.TextField(
        blank=True,
        default="",
        help_text="Motivo de cancelación (se registra al cancelar).",
    )

    # ---- No Show ----

    no_show_registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Usuario que registró la inasistencia.",
    )

    # ---- Contador de reagendamientos ----

    reschedule_count = models.PositiveSmallIntegerField(
        default=0,
        help_text="Cuántas veces se ha reagendado esta cita.",
    )

    # ---- Vínculo con cotización (C-3) ----

    quote = models.ForeignKey(
        "finanzas.Quote",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
        help_text=(
            "Cotización aceptada que originó esta cita (opcional). "
            "Solo se puede vincular una Quote en estado ACCEPTED. "
            "Si la cotización se elimina, la FK queda en null (SET_NULL)."
        ),
    )

    # ---- Gancho v2 series ----

    series_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        default=None,
        help_text=(
            "UUID de la serie de citas recurrentes. "
            "GANCHO v2 — siempre None en v1. "
            "No crear tabla AppointmentSeries hasta v2."
        ),
    )

    class Meta:
        db_table = "agenda_appointments"
        ordering = ["-starts_at"]
        indexes = [
            # Calendario del médico
            models.Index(
                fields=["tenant", "doctor", "starts_at", "ends_at"],
                name="appt_doctor_range_idx",
            ),
            # Calendario del consultorio
            models.Index(
                fields=["tenant", "consultorio", "starts_at", "ends_at"],
                name="appt_consultorio_range_idx",
            ),
            # Historial del paciente (DESC en starts_at)
            models.Index(
                fields=["tenant", "patient", "-starts_at"],
                name="appt_patient_hist_idx",
            ),
            # Sala de espera / listado por estado
            models.Index(
                fields=["tenant", "status", "starts_at"],
                name="appt_status_idx",
            ),
            # Calendario por sede (multi-sede — Fase 2)
            models.Index(
                fields=["tenant", "sucursal", "starts_at"],
                name="appt_sucursal_range_idx",
            ),
        ]
        # NOTA: Los exclusion constraints anti-empalme (btree_gist) NO se modelan aquí.
        # Se crean en la migración 0002_enable_rls_and_constraints.py con RunSQL.
        # Razón: Django ORM no tiene soporte nativo para EXCLUDE USING GIST.

    def clean(self) -> None:
        """Valida que ends_at sea posterior a starts_at."""
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError(
                {"ends_at": "La hora de fin debe ser posterior a la hora de inicio."}
            )

    def __str__(self) -> str:
        patient_name = getattr(self.patient, "full_name", str(self.patient_id))
        starts = self.starts_at.strftime("%Y-%m-%d %H:%M") if self.starts_at else "?"
        status_label = self.get_status_display()
        return f"{patient_name} — {starts} UTC [{status_label}]"


# ---------------------------------------------------------------------------
# Transiciones válidas de la máquina de estados
# ---------------------------------------------------------------------------

#: Mapa de transiciones permitidas: estado_origen → conjunto de estados_destino.
#: Usar en services.py para validar antes de cambiar status.
#: Estados terminales (ATTENDED, CANCELLED, NO_SHOW) tienen set vacío.
VALID_TRANSITIONS: dict[str, set[str]] = {
    Appointment.Status.SCHEDULED: {
        Appointment.Status.CONFIRMED,
        # El paciente puede LLEGAR sin confirmación previa (walk-in / no se confirmó):
        # se permite Agendada → En sala directamente.
        Appointment.Status.ARRIVED,
        Appointment.Status.CANCELLED,
        Appointment.Status.NO_SHOW,
    },
    Appointment.Status.CONFIRMED: {
        Appointment.Status.ARRIVED,
        Appointment.Status.CANCELLED,
        Appointment.Status.NO_SHOW,
    },
    Appointment.Status.ARRIVED: {
        Appointment.Status.IN_PROGRESS,
        Appointment.Status.CANCELLED,
        Appointment.Status.NO_SHOW,
    },
    Appointment.Status.IN_PROGRESS: {
        Appointment.Status.ATTENDED,
    },
    Appointment.Status.ATTENDED: set(),
    Appointment.Status.CANCELLED: set(),
    Appointment.Status.NO_SHOW: set(),
}

# ---------------------------------------------------------------------------
# AgendaItemNote
# ---------------------------------------------------------------------------


class AgendaItemNote(TenantAwareModel):
    """Nota colaborativa pegada a una cita o a un evento de agenda (hilo de comentarios).

    Visible para todos los roles con acceso a la agenda.
    Solo se setea UNA de las dos FKs (appointment XOR agenda_block).
    El constraint "agenda_item_note_exactly_one_target" lo refuerza a nivel BD.

    Ciclo de vida:
        - Cualquier miembro con acceso a la agenda puede crear notas.
        - El autor, el owner y el admin pueden eliminarlas (soft-delete via deleted_at).
        - NO se editan (append-only por diseño; corrige agregando una nota nueva).

    Relaciones:
        author       → User que creó la nota.
        appointment  → Cita a la que pertenece (null si es de un evento).
        agenda_block → Evento al que pertenece (null si es de una cita).
    """

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agenda_item_notes",
        help_text="Usuario que agregó la nota.",
    )
    appointment = models.ForeignKey(
        "agenda.Appointment",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="item_notes",
        help_text="Cita a la que pertenece esta nota. Null si pertenece a un evento.",
    )
    agenda_block = models.ForeignKey(
        "agenda.AgendaBlock",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="item_notes",
        help_text="Evento al que pertenece esta nota. Null si pertenece a una cita.",
    )
    body = models.TextField(
        help_text="Contenido de la nota. Requerido, no puede estar vacío.",
    )

    class Meta:
        db_table = "agenda_item_notes"
        ordering = ["created_at"]
        constraints = [
            # Exactamente uno de appointment / agenda_block debe estar seteado.
            # (A XOR B) = (A AND NOT B) OR (NOT A AND B)
            models.CheckConstraint(
                check=(
                    models.Q(appointment__isnull=False, agenda_block__isnull=True)
                    | models.Q(appointment__isnull=True, agenda_block__isnull=False)
                ),
                name="agenda_item_note_exactly_one_target",
            ),
        ]

    def __str__(self) -> str:
        author_str = getattr(self.author, "email", str(self.author_id))
        target = (
            f"cita={self.appointment_id}"
            if self.appointment_id
            else f"evento={self.agenda_block_id}"
        )
        return f"Nota de {author_str} en {target}"


#: Estados que se consideran "activos" para el anti-empalme.
#: Una cita en cualquiera de estos estados ocupa el slot del médico/consultorio.
ACTIVE_STATUSES: frozenset[str] = frozenset(
    {
        Appointment.Status.SCHEDULED,
        Appointment.Status.CONFIRMED,
        Appointment.Status.ARRIVED,
        Appointment.Status.IN_PROGRESS,
    }
)


# ---------------------------------------------------------------------------
# AppointmentReminder
# ---------------------------------------------------------------------------


class AppointmentReminder(TenantAwareModel):
    """Recordatorio programado para una cita médica.

    Cada instancia representa un intento de enviar un aviso al paciente
    por el canal elegido (WhatsApp, SMS, Email) en la fecha scheduled_at UTC.

    La tarea Celery `send_appointment_reminder` carga el recordatorio por id,
    verifica que siga PENDING y que la cita esté activa, luego llama al adapter
    y actualiza status/sent_at/error_detail.

    CICLO DE VIDA:
        PENDING  →  SENT    (adapter respondió éxito)
        PENDING  →  FAILED  (adapter falló; se reintenta hasta max_retries)
        PENDING  →  SKIPPED (cita cancelada/no-show/atendida antes de enviarse)
        PENDING  →  CANCELLED (cancel_reminders_for_appointment fue llamado)
        FAILED   →  (la tarea ya agotó reintentos — queda en FAILED)

    AISLAMIENTO MULTI-TENANT:
        La tarea Celery carga con all_objects (no hay tenant en el worker).
        El aislamiento lo garantiza el id directo de UUID + RLS en BD.
        NUNCA exponer el endpoint de creación manual de recordatorios al usuario.

    INMUTABILIDAD:
        scheduled_at, channel y appointment no cambian tras la creación.
        Solo status, sent_at, error_detail y external_message_id mutan
        (escritura exclusiva desde la tarea Celery o cancel_reminders_for_appointment).
    """

    class Channel(models.TextChoices):
        """Canal de envío del recordatorio."""

        WHATSAPP = "whatsapp", "WhatsApp"
        SMS = "sms", "SMS"
        EMAIL = "email", "Email"

    class ReminderStatus(models.TextChoices):
        """Estado del recordatorio."""

        PENDING = "pending", "Pendiente"
        SENT = "sent", "Enviado"
        FAILED = "failed", "Fallido"
        SKIPPED = "skipped", "Omitido"
        CANCELLED = "cancelled", "Cancelado"

    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.CASCADE,
        related_name="reminders",
        help_text="Cita a la que corresponde este recordatorio.",
    )
    channel = models.CharField(
        max_length=20,
        choices=Channel.choices,
        default=Channel.WHATSAPP,
        help_text="Canal de envío del recordatorio.",
    )
    scheduled_at = models.DateTimeField(
        db_index=True,
        help_text="Momento UTC en que debe enviarse el recordatorio.",
    )
    sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Momento UTC en que se envió efectivamente. Null si aún no se envió.",
    )
    status = models.CharField(
        max_length=20,
        choices=ReminderStatus.choices,
        default=ReminderStatus.PENDING,
        db_index=True,
        help_text="Estado del recordatorio.",
    )
    message_preview = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Primeros ~500 caracteres del mensaje enviado (para trazabilidad). "
            "LFPDPPP: este campo puede contener datos personales del paciente "
            "(nombre, fecha de cita). Está protegido por Row Level Security (RLS) "
            "en PostgreSQL; nunca exponerlo en listados públicos ni logs. "
            "Solo consultable por usuarios del mismo tenant."
        ),
    )
    error_detail = models.TextField(
        blank=True,
        default="",
        help_text="Detalle del error si el envío falló.",
    )
    external_message_id = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text=(
            "ID del mensaje asignado por el proveedor externo (Meta, Twilio, etc.). "
            "Útil para reconciliación y webhooks de entrega."
        ),
    )

    class Meta:
        db_table = "agenda_appointment_reminders"
        ordering = ["scheduled_at"]
        indexes = [
            # Worker query: buscar los PENDING próximos a enviarse
            models.Index(
                fields=["scheduled_at", "status"],
                name="reminder_scheduled_status_idx",
            ),
            # Consultas por tenant + cita (selectors)
            models.Index(
                fields=["tenant", "appointment"],
                name="reminder_tenant_appt_idx",
            ),
        ]

    def __str__(self) -> str:
        channel_label = self.get_channel_display()  # type: ignore[attr-defined]
        status_label = self.get_status_display()  # type: ignore[attr-defined]
        scheduled = self.scheduled_at.strftime("%Y-%m-%d %H:%M") if self.scheduled_at else "?"
        return (
            f"Recordatorio [{channel_label}] cita={self.appointment_id} "
            f"scheduled={scheduled} UTC [{status_label}]"
        )
