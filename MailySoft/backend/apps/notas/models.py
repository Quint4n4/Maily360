"""
Modelos de la app notas.

Note(TenantAwareModel) — notas personales y globales del tenant.

Visibilidad (resuelta por el selector, no por el modelo):
    personal → solo el autor.
    role     → usuarios del tenant cuyo rol == target_role (+ el autor/dueño).
    all      → todos los usuarios del tenant.

Reglas de negocio (implementadas en services.py, NO en el modelo):
    - Al menos uno de title/body debe tener contenido.
    - scope role/all solo lo puede crear el owner.
    - target_role obligatorio cuando scope=role; vacío forzado en scope!=role.
    - done/toggle solo aplica cuando is_task=True.
    - Borrado: soft-delete (deleted_at = now), nunca DELETE real.
"""

from django.conf import settings
from django.db import models

from apps.core.models import TenantAwareModel


class NoteScope(models.TextChoices):
    """Audiencia de la nota dentro del tenant."""

    PERSONAL = "personal", "Personal"
    ROLE = "role", "Rol específico"
    ALL = "all", "Todos"


class Note(TenantAwareModel):
    """Nota o tarea de un usuario dentro de un tenant (clínica).

    Campos:
        author      FK al usuario que creó la nota.
        title       Título breve (opcional, max 120).
        body        Cuerpo de la nota (opcional).
                    REGLA: al menos uno de title/body debe estar relleno
                    (validado en note_create / note_update de services.py).
        scope       Audiencia: personal / role / all.
        target_role Rol destinatario cuando scope=role. Vacío en otros casos.
        is_task     Si True, la nota es una tarea con checkbox.
        done        Estado de la tarea. Solo relevante cuando is_task=True.
        remind_at   Recordatorio opcional (para el widget de agenda).
        pinned      Fijada al tope del listado.

    Timestamps y soft-delete heredados de TenantAwareModel (BaseModel):
        id, created_at, updated_at, deleted_at, tenant, created_by.
    """

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notes",
        help_text="Usuario que creó la nota.",
    )
    title = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="Título breve de la nota (opcional).",
    )
    body = models.TextField(
        blank=True,
        default="",
        help_text="Cuerpo de la nota (opcional). Al menos title o body deben tener contenido.",
    )
    scope = models.CharField(
        max_length=10,
        choices=NoteScope.choices,
        default=NoteScope.PERSONAL,
        db_index=True,
        help_text="Audiencia de la nota: personal / role / all.",
    )
    target_role = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text=(
            "Rol destinatario cuando scope=role. "
            "Vacío en scope=personal o scope=all. "
            "Valores válidos: owner, admin, doctor, nurse, reception, finance, readonly."
        ),
    )
    is_task = models.BooleanField(
        default=False,
        help_text="Si True, la nota es una tarea (muestra checkbox de done/pendiente).",
    )
    done = models.BooleanField(
        default=False,
        help_text="Estado de la tarea. Solo relevante cuando is_task=True.",
    )
    remind_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Fecha/hora UTC del recordatorio. Null = sin recordatorio.",
    )
    pinned = models.BooleanField(
        default=False,
        help_text="Fijada al tope del listado.",
    )

    class Meta:
        db_table = "notas_notes"
        ordering = ["-pinned", "-created_at"]

    def __str__(self) -> str:
        author_str = getattr(self.author, "email", str(self.author_id))
        scope_str = self.get_scope_display()  # type: ignore[attr-defined]
        title_str = self.title or self.body[:40] or "(sin contenido)"
        return f"[{scope_str}] {title_str} — {author_str}"
