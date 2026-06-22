"""
Modelo AuditLog — bitácora append-only de eventos clínicos (NOM-024).

Reglas de inmutabilidad (doble barrera):
  Python: save() prohíbe UPDATE; delete() siempre lanza RuntimeError.
  PostgreSQL: RLS FOR INSERT WITH CHECK + FORCE RLS + sin policy de UPDATE/DELETE
              (migración 0002_enable_rls). En prod: REVOKE UPDATE, DELETE al rol de app.

El campo tenant es nullable para cubrir eventos sin tenant (ej. login fallido).
Se hereda de TenantAwareModel para tener all_objects, objects con TenantManager
y los timestamps de BaseModel; el campo tenant se sobreescribe como nullable.
"""

import uuid

from django.conf import settings
from django.db import models

from apps.core.managers import TenantManager
from apps.core.models import TenantAwareModel


class AuditLogQuerySet(models.QuerySet):  # type: ignore[type-arg]
    """QuerySet append-only: bloquea update() y delete() a nivel masivo.

    El override de save()/delete() en el modelo solo protege operaciones de
    instancia. Las operaciones de QuerySet (`.filter(...).update()` /
    `.filter(...).delete()`) NO pasan por esos métodos, así que se bloquean
    aquí para que la inmutabilidad sea completa también a nivel Python
    (segunda barrera: RLS + REVOKE en PostgreSQL).
    """

    def update(self, **kwargs: object) -> int:
        raise RuntimeError("AuditLog es append-only: QuerySet.update() no permitido.")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise RuntimeError("AuditLog es append-only: QuerySet.delete() no permitido.")


class ActionType(models.TextChoices):
    """Tipos de acción auditables en la plataforma."""

    # Pacientes
    PATIENT_CREATE = "PATIENT_CREATE", "Crear paciente"
    PATIENT_READ = "PATIENT_READ", "Leer ficha de paciente"
    PATIENT_UPDATE = "PATIENT_UPDATE", "Actualizar paciente"
    PATIENT_DEACTIVATE = "PATIENT_DEACTIVATE", "Desactivar paciente"

    # Citas
    APPOINTMENT_CREATE = "APPOINTMENT_CREATE", "Crear cita"
    APPOINTMENT_UPDATE = "APPOINTMENT_UPDATE", "Actualizar cita"
    APPOINTMENT_STATUS = "APPOINTMENT_STATUS", "Cambiar estado de cita"
    APPOINTMENT_RESCHEDULE = "APPOINTMENT_RESCHEDULE", "Reagendar cita"
    APPOINTMENT_REACTIVATE = "APPOINTMENT_REACTIVATE", "Reactivar cita cancelada"
    APPOINTMENT_TYPE_CREATE = "APPOINTMENT_TYPE_CREATE", "Crear tipo de cita"
    APPOINTMENT_TYPE_UPDATE = "APPOINTMENT_TYPE_UPDATE", "Actualizar tipo de cita"
    APPOINTMENT_TYPE_DEACTIVATE = "APPOINTMENT_TYPE_DEACTIVATE", "Desactivar tipo de cita"
    AGENDA_EVENT_CREATE = "AGENDA_EVENT_CREATE", "Crear evento de agenda (reunión/bloqueo)"
    AGENDA_EVENT_UPDATE = "AGENDA_EVENT_UPDATE", "Actualizar evento de agenda"
    AGENDA_EVENT_DELETE = "AGENDA_EVENT_DELETE", "Eliminar evento de agenda"

    # Personal
    DOCTOR_CREATE = "DOCTOR_CREATE", "Crear médico"
    DOCTOR_UPDATE = "DOCTOR_UPDATE", "Actualizar médico"
    DOCTOR_DEACTIVATE = "DOCTOR_DEACTIVATE", "Desactivar médico"
    DOCTOR_CONSULTORIOS = "DOCTOR_CONSULTORIOS", "Asignar consultorios a médico"
    CONSULTORIO_CREATE = "CONSULTORIO_CREATE", "Crear consultorio"
    CONSULTORIO_UPDATE = "CONSULTORIO_UPDATE", "Actualizar consultorio"
    CONSULTORIO_DEACTIVATE = "CONSULTORIO_DEACTIVATE", "Desactivar consultorio"
    SCHEDULE_CREATE = "SCHEDULE_CREATE", "Crear horario"
    SCHEDULE_DEACTIVATE = "SCHEDULE_DEACTIVATE", "Desactivar horario"

    # Configuración
    CONFIG_UPDATE = "CONFIG_UPDATE", "Actualizar configuración de agenda"

    # Miembros de la clínica
    MEMBER_CREATE = "MEMBER_CREATE", "Alta de miembro"
    MEMBER_UPDATE = "MEMBER_UPDATE", "Actualizar miembro (nombre/rol)"
    MEMBER_BLOCK = "MEMBER_BLOCK", "Bloquear o reactivar cuenta de miembro"
    MEMBER_PASSWORD = "MEMBER_PASSWORD", "Restablecer contraseña de miembro"

    # Notas y Tareas
    NOTE_CREATE = "NOTE_CREATE", "Crear nota personal"
    NOTE_UPDATE = "NOTE_UPDATE", "Actualizar nota"
    NOTE_DELETE = "NOTE_DELETE", "Eliminar nota"
    NOTE_GLOBAL_SEND = "NOTE_GLOBAL_SEND", "Enviar nota global"
    AGENDA_NOTE_ADD = "AGENDA_NOTE_ADD", "Agregar nota a evento de agenda"
    AGENDA_NOTE_DELETE = "AGENDA_NOTE_DELETE", "Eliminar nota de evento de agenda"

    # Expediente clínico
    ALLERGY_CREATE = "ALLERGY_CREATE", "Registrar alergia"
    ALLERGY_RESOLVE = "ALLERGY_RESOLVE", "Resolver alergia"
    MEDICAL_HISTORY_READ = "MEDICAL_HISTORY_READ", "Leer historia clínica"
    MEDICAL_HISTORY_UPDATE = "MEDICAL_HISTORY_UPDATE", "Actualizar historia clínica"
    VITALSIGNS_CREATE = "VITALSIGNS_CREATE", "Registrar signos vitales"
    VITALSIGNS_READ = "VITALSIGNS_READ", "Consultar signos vitales"
    EVOLUTION_CREATE = "EVOLUTION_CREATE", "Crear nota de evolución"
    EVOLUTION_READ = "EVOLUTION_READ", "Consultar notas de evolución"
    ADDENDUM_CREATE = "ADDENDUM_CREATE", "Agregar addendum a nota de evolución"
    DIAGNOSIS_CREATE = "DIAGNOSIS_CREATE", "Registrar diagnóstico"
    DIAGNOSIS_RESOLVE = "DIAGNOSIS_RESOLVE", "Resolver diagnóstico"
    DIAGNOSIS_READ = "DIAGNOSIS_READ", "Consultar diagnósticos"
    EVOLUTION_IMAGE_ADD = "EVOLUTION_IMAGE_ADD", "Agregar imagen a evolución"
    EVOLUTION_IMAGE_REMOVE = "EVOLUTION_IMAGE_REMOVE", "Dar de baja imagen de evolución"

    # Recetas — catálogo de medicamentos (Fase B1.1)
    MEDICATION_CREATE = "MEDICATION_CREATE", "Crear medicamento custom"

    # Recetas — receta médica (Fase B1.2)
    PRESCRIPTION_CREATE = "PRESCRIPTION_CREATE", "Emitir receta médica"
    PRESCRIPTION_READ = "PRESCRIPTION_READ", "Consultar receta médica"
    PRESCRIPTION_CANCEL = "PRESCRIPTION_CANCEL", "Anular receta médica"

    # Recetas — PDF (Fase B1.3)
    PRESCRIPTION_PDF = "PRESCRIPTION_PDF", "Generar PDF de receta médica"

    # Plataforma (panel interno del equipo Maily — cross-tenant)
    TENANT_CREATE = "TENANT_CREATE", "Crear clínica nueva"
    TENANT_STATUS_CHANGE = "TENANT_STATUS_CHANGE", "Cambiar estado de clínica"

    # Autenticación
    LOGIN = "LOGIN", "Inicio de sesión"
    LOGOUT = "LOGOUT", "Cierre de sesión"
    LOGIN_FAILED = "LOGIN_FAILED", "Intento de sesión fallido"

    # Mi Consultorio — configuración de la clínica (Fase B base)
    CLINIC_SETTINGS_UPDATE = "CLINIC_SETTINGS_UPDATE", "Actualizar configuración de clínica"
    TEMPLATE_CREATE = "TEMPLATE_CREATE", "Crear plantilla clínica"
    TEMPLATE_UPDATE = "TEMPLATE_UPDATE", "Actualizar plantilla clínica"
    TEMPLATE_DELETE = "TEMPLATE_DELETE", "Desactivar plantilla clínica"
    PATIENT_CATEGORY_CREATE = "PATIENT_CATEGORY_CREATE", "Crear categoría de paciente"
    PATIENT_CATEGORY_DELETE = "PATIENT_CATEGORY_DELETE", "Desactivar categoría de paciente"

    # Recetas — cumplimiento COFEPRIS (Fase F2)
    CREDENTIAL_CREATE = "CREDENTIAL_CREATE", "Registrar credencial de médico"
    CREDENTIAL_UPDATE = "CREDENTIAL_UPDATE", "Actualizar credencial de médico"
    CREDENTIAL_DELETE = "CREDENTIAL_DELETE", "Eliminar credencial de médico"

    # Recetas — formatos configurables (Fase F3)
    FORMAT_CREATE = "FORMAT_CREATE", "Crear formato de receta"
    FORMAT_UPDATE = "FORMAT_UPDATE", "Actualizar formato de receta"
    FORMAT_DELETE = "FORMAT_DELETE", "Desactivar formato de receta"

    # Recetas — verificación pública de autenticidad (Fase F5)
    # Sin PII: solo folio + resultado (vigente/anulada). No registra IP ni sig.
    PRESCRIPTION_VERIFY = "PRESCRIPTION_VERIFY", "Verificar autenticidad de receta (público)"

    # Recetas — medicamentos controlados (Fase F6)
    # Auditoría reforzada para controladas: grupo más restrictivo y folio oficial incluidos.
    PRESCRIPTION_CONTROLLED_CREATE = (
        "PRESCRIPTION_CONTROLLED_CREATE",
        "Emitir receta con medicamento controlado",
    )


class AuditLog(TenantAwareModel):
    """Registro inmutable de un evento auditable en la plataforma.

    Tabla append-only: INSERT permitido, UPDATE y DELETE prohibidos tanto a
    nivel Python (override de save/delete) como a nivel PostgreSQL (RLS + REVOKE).

    El campo tenant es nullable para cubrir eventos globales (ej. LOGIN_FAILED
    donde el usuario no está resuelto aún).

    Nunca contiene PII clínica en metadata (ver política §3.4 del diseño).
    Las referencias a objetos de negocio son débiles (resource_type + resource_id)
    para durabilidad ante futuros borrados del modelo referenciado.
    """

    # --- Override: tenant nullable (hereda no-null de TenantAwareModel) ---
    tenant = models.ForeignKey(  # type: ignore[assignment]
        "tenancy.Tenant",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        help_text="Clínica del evento. Null para eventos globales (ej. login fallido sin tenant).",
    )

    # --- Actor ---
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Usuario que realizó la acción. Null si se borró el usuario o evento anónimo.",
    )
    actor_role = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Snapshot del rol del actor en el momento del evento.",
    )

    # --- Acción ---
    action = models.CharField(
        max_length=30,
        choices=ActionType.choices,
        db_index=True,
        help_text="Tipo de acción realizada (ActionType).",
    )

    # --- Recurso (referencia débil — durable ante borrados) ---
    resource_type = models.CharField(
        max_length=50,
        db_index=True,
        help_text='Nombre del modelo afectado: "Patient", "Appointment", etc.',
    )
    resource_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text="UUID del objeto afectado (nullable para eventos sin objeto específico).",
    )
    resource_repr = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Representación legible del recurso en el momento del evento (snapshot).",
    )

    # --- Descripción ---
    description = models.TextField(
        blank=True,
        default="",
        help_text="Descripción en lenguaje natural del evento.",
    )

    # --- Contexto HTTP ---
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        unpack_ipv4=True,
        help_text="IP de origen del request. Puede ser NAT; se registra igual (NOM-024).",
    )
    user_agent = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="User-Agent del cliente.",
    )
    request_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="ID de correlación del request (X-Request-ID o uuid4 hex generado).",
    )

    # --- Metadata sin PII ---
    metadata = models.JSONField(
        default=dict,
        help_text=(
            "Contexto adicional SIN PII clínica. "
            "Permitido: changed_fields, old/new_status, ids relacionados. "
            "Prohibido: diagnósticos, notas clínicas, CURP, teléfono, nombre."
        ),
    )

    # --- Managers (con AuditLogQuerySet: update/delete masivo bloqueado) ---
    objects = TenantManager.from_queryset(AuditLogQuerySet)()  # filtra por tenant + append-only
    all_objects = models.Manager.from_queryset(AuditLogQuerySet)()  # sin filtro + append-only

    class Meta:
        db_table = "audit_logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["tenant", "created_at"],
                name="audit_tenant_created_idx",
            ),
            models.Index(
                fields=["tenant", "actor"],
                name="audit_tenant_actor_idx",
            ),
            models.Index(
                fields=["tenant", "resource_type", "resource_id"],
                name="audit_tenant_resource_idx",
            ),
            models.Index(
                fields=["tenant", "action"],
                name="audit_tenant_action_idx",
            ),
        ]

    def save(self, *args: object, **kwargs: object) -> None:  # type: ignore[override]
        """Prohíbe UPDATE. AuditLog es append-only.

        Usa `self._state.adding` (True al construir, False tras el primer save)
        para distinguir INSERT de UPDATE sin un SELECT extra por cada escritura
        (la bitácora es de alto volumen).

        Raises:
            RuntimeError: si se intenta actualizar un registro existente.
        """
        if not self._state.adding:
            raise RuntimeError(
                "AuditLog es append-only: no se permite UPDATE. "
                f"pk={self.pk}"
            )
        super().save(*args, **kwargs)

    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict[str, int]]:  # type: ignore[override]
        """Prohíbe DELETE. AuditLog es append-only.

        Raises:
            RuntimeError: siempre.
        """
        raise RuntimeError(
            "AuditLog es append-only: no se permite DELETE. "
            f"pk={self.pk}"
        )

    def __str__(self) -> str:
        actor_str = str(self.actor_id) if self.actor_id else "anon"
        tenant_str = str(self.tenant_id) if self.tenant_id else "global"
        created = self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else "?"
        return (
            f"[{created}] {self.action} — {self.resource_type}:{self.resource_id} "
            f"by {actor_str} @ {tenant_str}"
        )
