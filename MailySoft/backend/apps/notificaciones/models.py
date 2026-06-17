"""
Modelos de la app notificaciones.

Notification(TenantAwareModel) — aviso dirigido a UN usuario dentro de un tenant.

Una notificación es un registro denormalizado: guarda su propio título/cuerpo de
texto en el momento en que se dispara, para no depender del objeto origen (que
podría cambiar o borrarse). El destino de clic se modela con (target_type,
target_id) y lo resuelve el frontend a una ruta.

Las notificaciones se generan por "reparto en escritura" (fan-out on write):
cuando ocurre un evento de dominio (se crea una reunión, se agrega una nota de
equipo, se dirige una nota a un rol), el service de ESE dominio llama a
`notification_fanout` de esta app y crea una notificación por destinatario.

Visibilidad:
    Cada usuario solo ve sus propias notificaciones (recipient == request.user),
    siempre dentro del tenant activo. El selector lo garantiza; el modelo no.

Reglas de negocio (en services.py, NO en el modelo):
    - Nunca te notificas a ti mismo: el actor se excluye del reparto.
    - read_at NULL = no leída; rellenado = leída. Marcar leída es idempotente.
    - Borrado: soft-delete heredado (deleted_at), nunca DELETE real.
"""

from django.conf import settings
from django.db import models

from apps.core.models import TenantAwareModel


class NotificationKind(models.TextChoices):
    """Tipo de evento que originó la notificación."""

    MEETING = "meeting", "Reunión"
    TEAM_NOTE = "team_note", "Nota de equipo"
    ROLE_NOTE = "role_note", "Nota dirigida a un rol"
    BROADCAST = "broadcast", "Aviso a toda la clínica"
    NURSING_INSTRUCTION = "nursing_instruction", "Indicación de enfermería"


class NotificationTarget(models.TextChoices):
    """Tipo de objeto al que apunta la notificación (para construir el enlace).

    El valor vacío ("") significa que la notificación no lleva a ningún objeto.
    """

    APPOINTMENT = "appointment", "Cita"
    AGENDA_BLOCK = "agenda_block", "Evento de agenda"
    NOTE = "note", "Nota"
    PATIENT = "patient", "Paciente"


class Notification(TenantAwareModel):
    """Aviso dirigido a un usuario dentro de un tenant (clínica).

    Campos:
        recipient    Usuario que recibe el aviso (dueño de la notificación).
        actor        Usuario que disparó el evento (quién la "envía"). Null si
                     el origen fue el sistema o el actor fue borrado.
        kind         Tipo de evento (meeting / team_note / role_note / broadcast).
        title        Texto principal, ya armado para mostrar (denormalizado).
        body         Texto secundario opcional (denormalizado).
        target_type  Tipo de objeto destino para el clic (appointment / agenda_block
                     / note / "" si no hay destino).
        target_id    UUID del objeto destino. Null si target_type está vacío.
        read_at      Fecha/hora UTC en que se marcó como leída. Null = no leída.

    Timestamps y soft-delete heredados de TenantAwareModel (BaseModel):
        id, created_at, updated_at, deleted_at, tenant, created_by.
    """

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        db_index=True,
        help_text="Usuario que recibe la notificación.",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
        help_text="Usuario que disparó el evento. Null si fue el sistema o fue borrado.",
    )
    kind = models.CharField(
        max_length=20,
        choices=NotificationKind.choices,
        db_index=True,
        help_text="Tipo de evento que originó la notificación.",
    )
    title = models.CharField(
        max_length=160,
        help_text="Texto principal de la notificación (ya armado para mostrar).",
    )
    body = models.TextField(
        blank=True,
        default="",
        help_text="Texto secundario opcional.",
    )
    target_type = models.CharField(
        max_length=20,
        choices=NotificationTarget.choices,
        blank=True,
        default="",
        help_text="Tipo de objeto destino para el enlace. Vacío = sin destino.",
    )
    target_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="UUID del objeto destino. Null si target_type está vacío.",
    )
    read_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Fecha/hora UTC en que se marcó como leída. Null = no leída.",
    )

    class Meta:
        db_table = "notificaciones_notifications"
        ordering = ["-created_at"]
        indexes = [
            # Conteo de no leídas y filtro "solo no leídas" por usuario.
            models.Index(fields=["recipient", "read_at"], name="notif_recip_read_idx"),
            # Listado por usuario ordenado por fecha (más reciente primero).
            models.Index(fields=["recipient", "-created_at"], name="notif_recip_created_idx"),
        ]

    def __str__(self) -> str:
        recipient_str = getattr(self.recipient, "email", str(self.recipient_id))
        estado = "leída" if self.read_at is not None else "no leída"
        return f"[{self.get_kind_display()}] {self.title} → {recipient_str} ({estado})"  # type: ignore[attr-defined]

    @property
    def is_read(self) -> bool:
        """True si la notificación ya fue marcada como leída."""
        return self.read_at is not None
