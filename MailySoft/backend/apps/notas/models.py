"""
Modelos de la app notas.

Note(TenantAwareModel) — notas personales y avisos (globales/por rol) del tenant.

Visibilidad (resuelta por el selector, no por el modelo):
    personal → solo el autor (sin noción de sede).
    role     → usuarios del tenant cuyo rol == target_role, acotado a `sucursal`
               (null = todas las sedes) (+ el autor/dueño).
    all      → todos los usuarios del tenant, acotado a `sucursal`
               (null = todas las sedes).

Multi-sede (cierre de hueco — 2026-07-16): un aviso (scope role/all) puede
acotarse a UNA sucursal (`sucursal` != null) o a TODA la clínica
(`sucursal` = null). Las notas PERSONALES siempre tienen `sucursal` = null
(no aplica: son privadas del autor, no un aviso de sede).

Reglas de negocio (implementadas en services.py, NO en el modelo):
    - Al menos uno de title/body debe tener contenido.
    - scope=all lo pueden crear el owner (cualquier sede, o todas) o un
      admin (forzado a SU sede — ver sucursal_scope.py). scope=role lo
      puede crear cualquier ROLE_NOTE_SENDERS (mismo forzado de sede para
      no-owner).
    - target_role obligatorio cuando scope=role; vacío forzado en scope!=role.
    - is_important (aviso destacado) SOLO lo puede marcar el owner.
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
        sucursal    Sede a la que está acotado el aviso (scope=role|all).
                    Null = toda la clínica (todas las sedes). Siempre null
                    en notas personales (scope=personal).
        is_important Aviso destacado. Solo el owner puede marcarlo True.
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
    sucursal = models.ForeignKey(
        "clinica.Sucursal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_index=True,
        related_name="+",
        help_text=(
            "Sucursal (sede) a la que está acotado el aviso (scope=role|all). "
            "Null = aviso de TODA la clínica (todas las sedes). Siempre null "
            "en notas personales (scope=personal, que no tienen noción de "
            "sede). Un no-owner solo puede crear/editar avisos en SU propia "
            "sede (ver apps.clinica.sucursal_scope); solo el owner puede "
            "elegir 'todas las sedes' o una sede específica libremente."
        ),
    )
    is_important = models.BooleanField(
        default=False,
        help_text=(
            "Aviso destacado/importante. Solo el OWNER puede crearlo o "
            "editarlo con este valor en True; un no-owner nunca puede "
            "marcar ni mutar un aviso importante (services.py lo rechaza)."
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
