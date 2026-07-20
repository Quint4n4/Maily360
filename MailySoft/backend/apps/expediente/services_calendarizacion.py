"""
Services de la Calendarización de tratamientos (esquema de protocolos por
sesiones) — Fases 1 y 4.

Vive en el expediente del paciente. El doctor arma una tabla de tratamientos
(tomados del catálogo `finanzas.ServiceConcept` o capturados a mano) con N
sesiones cada uno, fechas programadas y de aplicación, y descarga un PDF con
membrete de la clínica. Las firmas son FÍSICAS (columnas vacías del PDF) —
nunca se persisten.

Fase 4 (agendar sesiones como citas reales): cada TreatmentSession puede
ligarse a un `agenda.Appointment` real. TODA la disponibilidad (anti-empalme
de doctor/consultorio/eventos) se reutiliza de `apps.agenda.services` — este
módulo NUNCA reimplementa esa validación, solo arma el `reason`/paciente y
decide crear vs. reagendar vs. cancelar+crear (ver treatment_session_schedule).

API pública:
    treatment_plan_create     — crea el esquema + items + sesiones.
    treatment_plan_replace    — reemplaza el contenido del esquema,
                                 reconciliando items/sesiones por `id` (no
                                 borra y recrea: preserva `appointment` y
                                 `applied_date` de lo que sobrevive).
    treatment_plan_delete     — baja lógica del esquema.
    treatment_session_schedule   — agenda/reagenda una sesión como cita real.
    treatment_session_unschedule — quita una sesión de la agenda (cancela su cita).

Convención: keyword-only args, nombrado acción+entidad. Mismo patrón de
snapshot que `finanzas.services._create_quote_item` (description/unit_price
copiados del ServiceConcept al crear la línea).

REGLA DE PRIVACIDAD (NOM-024/LFPDPPP): resource_repr en AuditLog SIEMPRE es
el UUID del registro, NUNCA contenido clínico ni nombres de tratamientos.
"""

import datetime
import logging
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.clinica.sucursal_scope import allowed_sucursales
from apps.expediente.models import (
    DEFAULT_TREATMENT_PLAN_TITLE,
    TreatmentPlan,
    TreatmentPlanItem,
    TreatmentPlanStatus,
    TreatmentSession,
    TreatmentSessionStatus,
)
from apps.expediente.selectors import treatment_plan_get
from apps.finanzas.models import Quote, ServiceConcept, TreatmentPackage, TreatmentPackageItem
from apps.finanzas.selectors import concept_get
from apps.finanzas.services import quote_create
from apps.pacientes.models import Patient
from apps.personal.models import Consultorio, Doctor
from apps.tenancy.models import Tenant

logger = logging.getLogger("apps.expediente.services_calendarizacion")

# Roles clínicos que pueden armar/editar el esquema de tratamientos.
# Defensa en profundidad: TreatmentPlanPermission ya restringe el endpoint
# HTTP a este mismo conjunto, pero el service puede invocarse desde
# management commands/tests sin contexto HTTP.
_ALLOWED_ACTOR_ROLES: frozenset[str] = frozenset({"owner", "admin", "doctor"})


def _validate_actor_role(*, actor_role: str) -> None:
    """Valida que el rol activo del actor pueda operar el esquema.

    Cadena vacía ("" — no se proporcionó rol, p. ej. llamada directa desde un
    test o script interno) se permite pasar: la validación de rol HTTP ya
    corrió en TreatmentPlanPermission. Un rol NO vacío pero fuera del
    conjunto permitido sí se rechaza.

    Raises:
        ValidationError: si actor_role viene poblado con un rol no permitido.
    """
    if actor_role and actor_role not in _ALLOWED_ACTOR_ROLES:
        raise ValidationError(
            "Tu rol no tiene permiso para operar la calendarización de tratamientos."
        )


def _to_decimal(value: Any, *, default: Decimal) -> Decimal:
    """Convierte a Decimal de forma segura; usa `default` si viene vacío/None."""
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ValidationError("El precio unitario debe ser un número válido.") from exc


def _resolve_item_fields(*, raw: dict[str, Any]) -> tuple[ServiceConcept | None, str, Decimal, int]:
    """Resuelve concepto/descripción/precio/cantidad de una línea de tratamiento.

    Si `concept_id` viene, valida que el concepto exista en el tenant activo
    (concept_get, filtrado por TenantManager) y lo usa como default de
    `description`/`unit_price` cuando esos campos no llegan.

    Raises:
        ValidationError: si el concepto no existe, el concepto está
            desactivado, falta descripción, la cantidad es inválida o el
            precio no es numérico.
    """
    concept: ServiceConcept | None = None
    concept_id = raw.get("concept_id")
    if concept_id:
        try:
            concept = concept_get(concept_id=concept_id)
        except ServiceConcept.DoesNotExist as exc:
            raise ValidationError("Concepto no encontrado en esta clínica.") from exc
        if not concept.is_active:
            raise ValidationError(
                "El concepto está desactivado; no se puede usar en un tratamiento nuevo."
            )

    description = (raw.get("description") or "").strip()
    if not description:
        description = concept.name if concept is not None else ""
    if not description:
        raise ValidationError(
            "Cada tratamiento requiere una descripción o un concepto del catálogo."
        )

    default_price = concept.base_price if concept is not None else Decimal("0")
    unit_price = _to_decimal(raw.get("unit_price"), default=default_price)
    if unit_price < 0:
        raise ValidationError("El precio unitario no puede ser negativo.")

    quantity_raw = raw.get("quantity")
    try:
        quantity = int(quantity_raw) if quantity_raw not in (None, "") else 1
    except (TypeError, ValueError) as exc:
        raise ValidationError("La cantidad de sesiones debe ser un número entero.") from exc
    if quantity < 1:
        raise ValidationError("Cada tratamiento debe tener al menos una sesión.")

    return concept, description, unit_price, quantity


def _as_uuid(value: Any) -> uuid.UUID | None:
    """Normaliza un id de entrada (uuid.UUID o str) a uuid.UUID, o None.

    Los `id` de item/sesión llegan como `uuid.UUID` reales cuando el payload
    pasó por `TreatmentPlanItemInputSerializer`/`TreatmentSessionInputSerializer`
    (API), pero un caller directo del service (tests, scripts) puede pasar un
    `str`. Sin esta normalización, un lookup en un dict keyado por
    `item.id`/`session.id` (siempre `uuid.UUID`) fallaría silenciosamente
    para un `str` con el mismo valor — la reconciliación por `id` trataría
    la línea/sesión existente como "nueva" en vez de actualizarla en sitio.
    """
    if value is None or value == "":
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _cancel_session_appointment_if_any(
    *, actor: Any, session: TreatmentSession, reason: str, actor_role: str = ""
) -> None:
    """Cancela la cita ligada a una sesión (si tiene una) antes de borrarla/desligarla.

    Reutiliza `apps.agenda.services.appointment_change_status` — nunca toca
    la tabla de citas directamente. Import tardío (mismo patrón que
    `apps/expediente/services.py`) para evitar dependencias circulares entre
    expediente y agenda a nivel de módulo.

    SEGURIDAD: si `actor_role == "doctor"`, el actor solo puede cancelar la
    cita si es EL MÉDICO de esa cita. `TreatmentPlanPermission` permite el
    rol "doctor" en todos los endpoints de calendarización (crear/editar su
    propio esquema), pero eso no basta para impedir que un médico cancele o
    mueva la cita de OTRO médico (quitar de agenda, borrar una sesión en el
    PUT, o la cancelación implícita al reasignar a otro doctor en
    `treatment_session_schedule`). owner/admin/reception y `actor_role=""`
    (llamada interna sin contexto HTTP) no tienen esta restricción.

    Args:
        actor:      Usuario que ejecuta la acción (auditoría / dueño de la cita).
        session:    Sesión cuya cita (si existe) se cancela.
        reason:     Motivo de cancelación que queda en la cita.
        actor_role: Rol activo del actor, para el candado de propiedad.

    Raises:
        ValidationError: si `actor_role == "doctor"` y la cita pertenece a
            otro médico, o si la cita ya está en un estado terminal que no
            admite cancelación (p. ej. Atendida) — la máquina de estados de
            agenda no permite esa transición; se propaga tal cual.
    """
    appointment = session.appointment
    if appointment is None:
        return

    if actor_role == "doctor":
        from apps.personal.selectors import doctor_get_for_user  # noqa: PLC0415

        caller_doctor = doctor_get_for_user(user=actor, tenant_id=session.tenant_id)
        if caller_doctor is None or appointment.doctor_id != caller_doctor.id:
            raise ValidationError("Como médico, solo puedes cancelar o mover tus propias citas.")

    from apps.agenda.models import Appointment  # noqa: PLC0415
    from apps.agenda.services import appointment_change_status  # noqa: PLC0415

    appointment_change_status(
        appointment=appointment,
        user=actor,
        new_status=Appointment.Status.CANCELLED,
        reason=reason,
    )


def _reconcile_sessions_for_item(
    *,
    tenant: Tenant,
    actor: Any,
    item: TreatmentPlanItem,
    quantity: int,
    sessions_raw: list[dict[str, Any]] | None,
    actor_role: str = "",
) -> None:
    """Reconcilia las TreatmentSession de una línea contra `sessions_raw`, por `id`.

    - Sesión con `id` que ya existe en la línea -> se ACTUALIZA en sitio.
      `appointment` NUNCA se toca aquí (no es un campo del payload de PUT);
      `scheduled_date`/`scheduled_time`/`duration_minutes`/`applied_date`/
      `status` se preservan salvo que el payload los traiga explícitos (F4 —
      no perder la cita agendada, su horario capturado, ni el estado
      "aplicada" al reordenar/editar el esquema desde el frontend enviando
      solo `{id, number}`).
    - Sesión sin `id`, o con un `id` que no pertenece a esta línea -> se CREA.
    - Sesión que ya NO viene en `sessions_raw` -> se BORRA; si tenía una cita
      agendada, esa cita se CANCELA antes (nunca se deja un Appointment
      huérfano apuntando a una sesión borrada). `actor_role` viaja hasta esa
      cancelación para que un médico no pueda cancelar la cita de OTRO
      médico borrando la sesión desde el PUT (ver
      `_cancel_session_appointment_if_any`).
    - `sessions_raw` vacío/None -> genera `quantity` sesiones vacías (mismo
      comportamiento que crear una línea nueva); las sesiones previas de la
      línea se tratan como "ya no vienen" (se borran/cancelan) — el
      frontend es responsable de reenviar lo que ya existía si no quiere
      perderlo (mismo contrato que el resto de `treatment_plan_replace`).
    """
    # Consulta EN FRÍO (nunca `item.sessions.all()`): `item`/`plan` pueden venir
    # de un selector con `prefetch_related` (treatment_plan_get); reutilizar esa
    # caché aquí leería el estado de ANTES de agendar sesiones (appointment_id
    # obsoleto) y `_cancel_session_appointment_if_any` fallaría en silencio al
    # decidir si hay una cita que cancelar.
    existing_by_id: dict[uuid.UUID, TreatmentSession] = {
        s.id: s for s in TreatmentSession.objects.filter(item=item)
    }
    seen_ids: set[uuid.UUID] = set()

    if sessions_raw:
        for raw_session in sessions_raw:
            try:
                number = int(raw_session["number"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValidationError("Cada sesión requiere un número de sesión válido.") from exc
            if number < 1:
                raise ValidationError("El número de sesión debe ser mayor a cero.")

            status_value = raw_session.get("status")
            if status_value is not None and status_value not in TreatmentSessionStatus.values:
                raise ValidationError(f"Estado de sesión inválido: {status_value!r}.")

            session_id = _as_uuid(raw_session.get("id"))
            existing_session = existing_by_id.get(session_id) if session_id else None

            if existing_session is not None:
                seen_ids.add(existing_session.id)
                existing_session.number = number
                if "scheduled_date" in raw_session:
                    existing_session.scheduled_date = raw_session["scheduled_date"]
                if "scheduled_time" in raw_session:
                    existing_session.scheduled_time = raw_session["scheduled_time"]
                if "duration_minutes" in raw_session:
                    existing_session.duration_minutes = raw_session["duration_minutes"]
                if "applied_date" in raw_session:
                    existing_session.applied_date = raw_session["applied_date"]
                if status_value is not None:
                    existing_session.status = status_value
                existing_session.save(
                    update_fields=[
                        "number",
                        "scheduled_date",
                        "scheduled_time",
                        "duration_minutes",
                        "applied_date",
                        "status",
                        "updated_at",
                    ]
                )
            else:
                TreatmentSession.objects.create(
                    tenant=tenant,
                    created_by=actor,
                    item=item,
                    number=number,
                    scheduled_date=raw_session.get("scheduled_date"),
                    scheduled_time=raw_session.get("scheduled_time"),
                    duration_minutes=raw_session.get("duration_minutes"),
                    applied_date=raw_session.get("applied_date"),
                    status=status_value or TreatmentSessionStatus.PROGRAMADA,
                )
    else:
        for number in range(1, quantity + 1):
            TreatmentSession.objects.create(
                tenant=tenant,
                created_by=actor,
                item=item,
                number=number,
                status=TreatmentSessionStatus.PROGRAMADA,
            )

    for session_id, stale_session in existing_by_id.items():
        if session_id in seen_ids:
            continue
        _cancel_session_appointment_if_any(
            actor=actor,
            session=stale_session,
            reason="Sesión eliminada de la calendarización",
            actor_role=actor_role,
        )
        stale_session.delete()


def _upsert_item_with_sessions(
    *,
    tenant: Tenant,
    actor: Any,
    plan: TreatmentPlan,
    raw: dict[str, Any],
    order: int,
    existing_items_by_id: dict[uuid.UUID, TreatmentPlanItem],
    actor_role: str = "",
) -> TreatmentPlanItem:
    """Crea o actualiza (por `id`) una línea de tratamiento y reconcilia sus sesiones.

    `existing_items_by_id` vacío equivale al comportamiento de creación pura
    (treatment_plan_create): toda línea del payload se crea de cero.
    """
    concept, description, unit_price, quantity = _resolve_item_fields(raw=raw)

    item_id = _as_uuid(raw.get("id"))
    existing_item = existing_items_by_id.get(item_id) if item_id else None

    if existing_item is not None:
        existing_item.service_concept = concept
        existing_item.description = description
        existing_item.unit_price = unit_price
        existing_item.quantity = quantity
        existing_item.order = order
        existing_item.save(
            update_fields=[
                "service_concept",
                "description",
                "unit_price",
                "quantity",
                "order",
                "updated_at",
            ]
        )
        item = existing_item
    else:
        item = TreatmentPlanItem.objects.create(
            tenant=tenant,
            created_by=actor,
            plan=plan,
            service_concept=concept,
            description=description,
            unit_price=unit_price,
            quantity=quantity,
            order=order,
        )

    _reconcile_sessions_for_item(
        tenant=tenant,
        actor=actor,
        item=item,
        quantity=quantity,
        sessions_raw=raw.get("sessions"),
        actor_role=actor_role,
    )
    return item


def _plan_total(*, plan: TreatmentPlan) -> Decimal:
    """Suma(unit_price * quantity) de todos los items del esquema (para auditoría)."""
    total = Decimal("0")
    for item in plan.items.all():
        total += item.unit_price * item.quantity
    return total


def treatment_plan_create(
    *,
    patient: Patient,
    actor: Any,
    title: str = "",
    notes: str = "",
    status: str = TreatmentPlanStatus.ACTIVA,
    items: list[dict[str, Any]],
    doctor: Doctor | None = None,
    consultorio: Consultorio | None = None,
    actor_role: str = "",
) -> TreatmentPlan:
    """Crea un esquema de calendarización de tratamientos con sus items y sesiones.

    Cada item de `items`: {id? (ignorado al crear), concept_id?, description?,
    unit_price?, quantity?, order?, sessions?: [{id? (ignorado al crear),
    number, scheduled_date?, scheduled_time?, duration_minutes?, applied_date?,
    status?}]}. Si `concept_id` viene, se valida contra el catálogo del tenant
    activo y se usa su name/base_price como default de description/unit_price.
    Genera sesiones: si el item trae `sessions`, se usan tal cual (preservando
    fechas/estado); si no, se generan `quantity` sesiones vacías numeradas
    1..N en estado "programada".

    Args:
        patient:      Paciente al que pertenece el esquema (fija el tenant).
        actor:        Usuario que crea el esquema (auditoría).
        title:        Título del documento. Vacío -> DEFAULT_TREATMENT_PLAN_TITLE.
        notes:        Notas libres.
        status:       borrador | activa | completada.
        items:        Líneas de tratamiento (al menos una).
        doctor:       Médico responsable (opcional; debe ser del mismo tenant).
        consultorio:  Consultorio por defecto del esquema (opcional; debe ser
                      del mismo tenant) — Fase 4, sugerencia al agendar.
        actor_role:   Rol activo del actor, para defensa en profundidad
                      (el permiso HTTP ya filtra, este es un segundo candado).

    Returns:
        El TreatmentPlan recién creado, con items/sesiones precargados
        (vía treatment_plan_get).

    Raises:
        ValidationError: sin items, doctor/consultorio de otro tenant, o
            datos de línea inválidos (concepto inexistente, cantidad/precio
            inválidos).
    """
    _validate_actor_role(actor_role=actor_role)

    # El esquema puede crearse vacío (borrador): es un contenedor que el
    # médico va llenando después vía PUT. `items` puede ser [].
    tenant = patient.tenant
    if doctor is not None and doctor.tenant_id != tenant.id:
        raise ValidationError("El médico no pertenece a esta clínica.")
    if consultorio is not None and consultorio.tenant_id != tenant.id:
        raise ValidationError("El consultorio no pertenece a esta clínica.")

    resolved_title = title.strip() if title else ""

    with transaction.atomic():
        plan = TreatmentPlan.objects.create(
            tenant=tenant,
            created_by=actor,
            patient=patient,
            doctor=doctor,
            consultorio=consultorio,
            title=resolved_title or DEFAULT_TREATMENT_PLAN_TITLE,
            notes=notes,
            status=status,
        )
        for order, raw_item in enumerate(items):
            _upsert_item_with_sessions(
                tenant=tenant,
                actor=actor,
                plan=plan,
                raw=raw_item,
                order=order,
                existing_items_by_id={},
                actor_role=actor_role,
            )

    plan = treatment_plan_get(plan_id=plan.id)

    logger.info(
        "treatment_plan_create: esquema %s creado para paciente %s (tenant=%s)",
        plan.pk,
        patient.pk,
        tenant.pk,
    )

    audit_record(
        action=ActionType.TREATMENT_PLAN_SAVE,
        resource_type="TreatmentPlan",
        actor=actor,
        tenant=tenant,
        resource_id=plan.id,
        resource_repr=str(plan.id),
        metadata={"items": len(items), "total": str(_plan_total(plan=plan))},
    )
    return plan


def treatment_plan_replace(
    *,
    plan: TreatmentPlan,
    actor: Any,
    title: str = "",
    notes: str = "",
    status: str = TreatmentPlanStatus.ACTIVA,
    items: list[dict[str, Any]],
    doctor: Doctor | None = None,
    consultorio: Consultorio | None = None,
    actor_role: str = "",
) -> TreatmentPlan:
    """Reemplaza el contenido de un esquema (title/notes/status/doctor/consultorio/items).

    RECONCILIA por `id` en vez de borrar y recrear todo (F4 — Fase 4): un
    item/sesión que trae `id` existente se actualiza en sitio; sin `id` se
    crea; el que ya no viene en el payload se borra. Esto es indispensable
    para no perder `TreatmentSession.appointment` (la cita real ya agendada)
    ni `applied_date`/`status` cada vez que el médico reordena o edita el
    esquema. Si una sesión borrada tenía una cita ligada, esa cita se
    CANCELA antes de borrar la sesión (nunca se deja un Appointment
    huérfano). Ver `_reconcile_sessions_for_item` para el detalle exacto de
    qué se preserva vs. qué se sobreescribe.

    Si el cliente reenvía fechas/estado dentro de `sessions`, se preservan
    tal cual llegaron — quien arma el payload (frontend) es responsable de
    reenviar lo que ya existía (incluyendo el `id` de cada item/sesión) si
    no quiere perderlo.

    Args:
        plan:         Esquema a reemplazar (ya resuelto por selector — mismo
                      tenant garantizado por el TenantManager).
        actor:        Usuario que reemplaza el esquema (auditoría).
        title:        Título del documento. Vacío -> DEFAULT_TREATMENT_PLAN_TITLE.
        notes:        Notas libres.
        status:       borrador | activa | completada.
        items:        Líneas de tratamiento (al menos una).
        doctor:       Médico responsable (opcional; debe ser del mismo tenant).
        consultorio:  Consultorio por defecto del esquema (opcional; debe ser
                      del mismo tenant).
        actor_role:   Rol activo del actor (defensa en profundidad).

    Returns:
        El TreatmentPlan actualizado, con items/sesiones precargados.

    Raises:
        ValidationError: sin items, doctor/consultorio de otro tenant, datos
            de línea inválidos, o si una sesión/item que se elimina tenía una
            cita que ya no admite cancelación (estado terminal en agenda).
    """
    _validate_actor_role(actor_role=actor_role)

    # El esquema puede quedar vacío tras un reemplazo (borrador): `items` [].
    tenant = plan.tenant
    if doctor is not None and doctor.tenant_id != tenant.id:
        raise ValidationError("El médico no pertenece a esta clínica.")
    if consultorio is not None and consultorio.tenant_id != tenant.id:
        raise ValidationError("El consultorio no pertenece a esta clínica.")

    resolved_title = title.strip() if title else ""

    with transaction.atomic():
        # Consulta EN FRÍO (nunca `plan.items.all()`): `plan` viene de un
        # selector con `prefetch_related` (treatment_plan_get); reutilizar esa
        # caché leería items/sesiones desactualizados si algo los modificó
        # después de que `plan` se obtuvo (p. ej. una sesión agendada en una
        # llamada previa dentro del mismo proceso).
        existing_items_by_id: dict[uuid.UUID, TreatmentPlanItem] = {
            item.id: item for item in TreatmentPlanItem.objects.filter(plan=plan)
        }
        seen_item_ids: set[uuid.UUID] = set()

        plan.title = resolved_title or DEFAULT_TREATMENT_PLAN_TITLE
        plan.notes = notes
        plan.status = status
        plan.doctor = doctor
        plan.consultorio = consultorio
        plan.save(update_fields=["title", "notes", "status", "doctor", "consultorio", "updated_at"])

        for order, raw_item in enumerate(items):
            item = _upsert_item_with_sessions(
                tenant=tenant,
                actor=actor,
                plan=plan,
                raw=raw_item,
                order=order,
                existing_items_by_id=existing_items_by_id,
                actor_role=actor_role,
            )
            seen_item_ids.add(item.id)

        # Items que ya no vienen en el payload: cancela las citas de sus
        # sesiones (si tenían) y borra (CASCADE arrastra las sesiones).
        for item_id, stale_item in existing_items_by_id.items():
            if item_id in seen_item_ids:
                continue
            for stale_session in stale_item.sessions.all():
                _cancel_session_appointment_if_any(
                    actor=actor,
                    session=stale_session,
                    reason="Sesión eliminada de la calendarización",
                    actor_role=actor_role,
                )
            stale_item.delete()

    plan = treatment_plan_get(plan_id=plan.id)

    logger.info(
        "treatment_plan_replace: esquema %s reemplazado (tenant=%s)",
        plan.pk,
        tenant.pk,
    )

    audit_record(
        action=ActionType.TREATMENT_PLAN_SAVE,
        resource_type="TreatmentPlan",
        actor=actor,
        tenant=tenant,
        resource_id=plan.id,
        resource_repr=str(plan.id),
        metadata={"items": len(items), "total": str(_plan_total(plan=plan))},
    )
    return plan


def treatment_plan_delete(*, plan: TreatmentPlan, actor: Any, actor_role: str = "") -> None:
    """Baja lógica de un esquema de calendarización de tratamientos.

    Rellena `deleted_at` (heredado de BaseModel); el TenantManager lo excluye
    automáticamente de las lecturas siguientes. No se borra físicamente.

    Args:
        plan:       Esquema a dar de baja.
        actor:      Usuario que da de baja el esquema (auditoría).
        actor_role: Rol activo del actor (defensa en profundidad).
    """
    _validate_actor_role(actor_role=actor_role)

    plan.deleted_at = timezone.now()
    plan.save(update_fields=["deleted_at", "updated_at"])

    logger.info(
        "treatment_plan_delete: esquema %s dado de baja (tenant=%s)",
        plan.pk,
        plan.tenant_id,
    )

    audit_record(
        action=ActionType.TREATMENT_PLAN_SAVE,
        resource_type="TreatmentPlan",
        actor=actor,
        tenant=plan.tenant,
        resource_id=plan.id,
        resource_repr=str(plan.id),
        metadata={"deleted": True},
    )


# ---------------------------------------------------------------------------
# Fase 2 — generar una cotización a partir del esquema de calendarización
# ---------------------------------------------------------------------------


def quote_create_from_treatment_plan(
    *,
    plan: TreatmentPlan,
    user: Any,
    actor_role: str = "",
    sucursal: Any | None = None,
) -> Quote:
    """Genera una cotización (borrador) a partir de un esquema de calendarización.

    Copia cada `TreatmentPlanItem` a una línea de `Quote` (concept_id,
    description, unit_price, quantity = nº de sesiones del tratamiento) y
    delega la creación en `apps.finanzas.services.quote_create` — este
    service NUNCA reimplementa el cálculo de totales de la cotización.

    Cada llamada crea una cotización NUEVA y reapunta `plan.quote` a ella;
    si el plan ya tenía una cotización previa, esa cotización anterior NO se
    borra ni se cancela — queda intacta en el módulo de Cotizaciones, solo
    deja de ser "la" cotización vigente del esquema (decisión de producto:
    permite volver a cotizar tras cambios en el esquema sin perder historial).

    Args:
        plan:       Esquema de calendarización (ya resuelto por selector —
                    mismo tenant garantizado por el TenantManager).
        user:       Usuario que genera la cotización (auditoría).
        actor_role: Rol activo del actor (defensa en profundidad; el permiso
                    HTTP TreatmentPlanPermission ya filtra owner/admin/doctor).
        sucursal:   sede DONDE SE GENERA la cotización (multi-sede — Fase 3).
                    La vista la resuelve con `resolve_write_sucursal`. None =
                    tenant sin sucursales configuradas (compatibilidad retro).

    Returns:
        La Quote recién creada (DRAFT), con sus items.

    Raises:
        ValidationError: rol no permitido, el plan no tiene tratamientos
            que cotizar, o la sucursal es de otro tenant.
    """
    _validate_actor_role(actor_role=actor_role)

    items = list(TreatmentPlanItem.objects.filter(plan=plan))
    if not items:
        raise ValidationError("El plan no tiene tratamientos para cotizar.")

    quote_items: list[dict[str, Any]] = [
        {
            "concept_id": item.service_concept_id,
            "description": item.description,
            "unit_price": item.unit_price,
            "quantity": Decimal(item.quantity),
            "discount": Decimal("0.00"),
        }
        for item in items
    ]

    with transaction.atomic():
        quote = quote_create(
            tenant=plan.tenant,
            user=user,
            patient=plan.patient,
            items=quote_items,
            notes="Generada desde calendarización de tratamientos",
            sucursal=sucursal,
        )
        plan.quote = quote
        plan.save(update_fields=["quote", "updated_at"])

    logger.info(
        "quote_create_from_treatment_plan: cotización %s generada desde esquema %s (tenant=%s)",
        quote.pk,
        plan.pk,
        plan.tenant_id,
    )

    audit_record(
        action=ActionType.TREATMENT_PLAN_SAVE,
        resource_type="TreatmentPlan",
        actor=user,
        tenant=plan.tenant,
        resource_id=plan.id,
        resource_repr=str(plan.id),
        metadata={"quote_generated": True, "quote_id": str(quote.id)},
    )
    return quote


# ---------------------------------------------------------------------------
# Fase 3 — generar una calendarización NUEVA a partir de un paquete
# ---------------------------------------------------------------------------


def treatment_plan_create_from_package(
    *,
    patient: Patient,
    actor: Any,
    package: TreatmentPackage,
    actor_role: str = "",
) -> TreatmentPlan:
    """Crea un esquema de calendarización NUEVO a partir de un paquete del catálogo.

    Copia cada `TreatmentPackageItem` a una línea del esquema (concept_id,
    description = nombre vigente del concepto, unit_price = base_price
    vigente, quantity = nº de sesiones del paquete) y delega la creación en
    `treatment_plan_create` — mismo snapshot y generación de sesiones 1..N
    que crear un esquema a mano. El título del esquema es el nombre del
    paquete.

    Args:
        patient:    Paciente al que se le arma el esquema (fija el tenant).
        actor:      Usuario que genera el esquema (auditoría).
        package:    Paquete de tratamientos de origen (ya resuelto por
                    selector — mismo tenant garantizado por el TenantManager).
        actor_role: Rol activo del actor (defensa en profundidad).

    Returns:
        El TreatmentPlan recién creado, con items/sesiones precargados.

    Raises:
        ValidationError: rol no permitido, el paquete es de otro tenant, el
            paquete está desactivado, o el paquete no tiene tratamientos.
    """
    _validate_actor_role(actor_role=actor_role)

    if package.tenant_id != patient.tenant_id:
        raise ValidationError("El paquete no pertenece a esta clínica.")
    if not package.is_active:
        raise ValidationError(
            "El paquete está desactivado; no se puede usar para un esquema nuevo."
        )

    package_items = list(
        TreatmentPackageItem.objects.filter(package=package).select_related("service_concept")
    )
    if not package_items:
        raise ValidationError("El paquete no tiene tratamientos.")

    items: list[dict[str, Any]] = [
        {
            "concept_id": item.service_concept_id,
            "description": item.service_concept.name,
            "unit_price": item.service_concept.base_price,
            "quantity": item.sessions,
        }
        for item in package_items
    ]

    plan = treatment_plan_create(
        patient=patient,
        actor=actor,
        title=package.name,
        status=TreatmentPlanStatus.ACTIVA,
        items=items,
        actor_role=actor_role,
    )

    audit_record(
        action=ActionType.TREATMENT_PLAN_SAVE,
        resource_type="TreatmentPlan",
        actor=actor,
        tenant=plan.tenant,
        resource_id=plan.id,
        resource_repr=str(plan.id),
        metadata={"created_from_package": True, "package_id": str(package.id)},
    )
    return plan


# ---------------------------------------------------------------------------
# Fase 4 — agendar sesiones como citas reales de agenda
# ---------------------------------------------------------------------------


def treatment_session_schedule(
    *,
    session: TreatmentSession,
    actor: Any,
    actor_role: str,
    doctor_id: uuid.UUID | None,
    consultorio_id: uuid.UUID | None = None,
    starts_at: datetime.datetime,
    ends_at: datetime.datetime | None = None,
    scheduled_date: datetime.date,
    scheduled_time: datetime.time | None = None,
    duration_minutes: int | None = None,
    active_sucursal_id: uuid.UUID | None = None,
) -> TreatmentSession:
    """Agenda (o reagenda) una TreatmentSession como una cita real de agenda.

    Reutiliza `apps.agenda.services` por completo — este service NUNCA
    reimplementa el anti-empalme ni las reglas de disponibilidad:

      - Sesión SIN cita todavía -> `appointment_create` (valida tenant,
        doctor/consultorio activos, la regla "un doctor con rol 'doctor'
        solo agenda para sí mismo", y el anti-empalme de doctor/consultorio/
        eventos; lanza ValidationError si el horario choca).
      - Sesión CON cita y el MISMO doctor -> `appointment_reschedule`
        (cambia horario y/o consultorio sobre la MISMA cita, revalidando el
        anti-empalme y conservando su historial de recordatorios/reschedule_count).
      - Sesión CON cita pero OTRO doctor -> `appointment_reschedule` no
        soporta reasignar doctor (es un campo inmutable en
        `apps.agenda.services._APPOINTMENT_IMMUTABLE_FIELDS`, regla 1 del
        módulo). Se CANCELA la cita vieja (`_cancel_session_appointment_if_any`
        — mismo candado de propiedad que quitar de agenda: un doctor no
        puede reasignar la cita de OTRO médico) y se CREA una nueva con
        `appointment_create`.

    Las 3 ramas + el `session.save()` final corren dentro de
    `transaction.atomic()`: si la creación de la cita nueva falla (p. ej.
    empalme) en la rama "otro doctor", la cancelación de la cita vieja
    también se revierte — la sesión nunca queda huérfana apuntando a una
    cita CANCELLED sin haber logrado agendar la nueva.

    El `reason` de la cita es la descripción del tratamiento
    (`session.item.description`) — así la agenda muestra qué se va a hacer
    sin exponer datos clínicos adicionales.

    Args:
        session:           Sesión a agendar (ya resuelta por selector —
                            mismo tenant garantizado por el TenantManager).
        actor:              Usuario que agenda (auditoría; también queda
                            como `user`/creador de la cita en agenda).
        actor_role:         Rol activo del actor (defensa en profundidad).
        doctor_id:          Médico que atenderá la sesión (obligatorio).
        consultorio_id:     Consultorio (opcional).
        starts_at/ends_at:  Horario de la cita en UTC — el frontend ya
                            resuelve la conversión de zona horaria (mismo
                            patrón que el resto de la agenda); si `ends_at`
                            no viene, `appointment_create`/`appointment_reschedule`
                            lo calculan con la duración del doctor.
        scheduled_date/scheduled_time: Fecha/hora local que se guardan en la
                            sesión (para el detalle del esquema y el PDF).
        duration_minutes:   Duración capturada por el usuario; se persiste
                            tal cual en la sesión (informativo — el cálculo
                            real de `ends_at` ya lo hizo agenda).
        active_sucursal_id: Sucursal activa del request (header X-Sucursal-Id),
                            resuelta por la vista con `resolve_active_sucursal`.
                            Se reenvía a `appointment_create` (ramas "crear" y
                            "cancelar+crear") para que la sede resuelta respete
                            la sede activa del actor, igual que el resto de la
                            agenda — multi-sede Fase 2/3.

    Returns:
        La TreatmentSession actualizada con su `appointment` ligado.

    Raises:
        ValidationError: rol no permitido, falta `doctor_id`, un doctor
            intentando cancelar/reasignar la cita de OTRO médico, el actor no
            tiene acceso a la sede de la cita YA agendada de la sesión
            (multi-sede — cierre de A8, ver docs/design/sucursales-hallazgos-
            seguridad.md), o cualquier ValidationError que levanten
            `appointment_create`/`appointment_reschedule` (paciente/doctor/
            consultorio de otro tenant, inactivos, empalme de horario,
            bloqueo de agenda, etc.) — se propaga tal cual para que la vista
            la mapee a 400.
    """
    from apps.agenda.services import appointment_create, appointment_reschedule  # noqa: PLC0415

    _validate_actor_role(actor_role=actor_role)

    if not doctor_id:
        raise ValidationError("Selecciona un médico para agendar.")

    tenant = session.tenant
    plan = session.item.plan
    reason = session.item.description
    existing_appointment = session.appointment

    # Multi-sede — cierre de A8 (docs/design/sucursales-hallazgos-seguridad.md):
    # defensa en profundidad. `TreatmentSessionScheduleApi.post` YA valida la
    # sede DESTINO (con el consultorio elegido) antes de llamar a este
    # service, pero un caller directo (management command, test, futura
    # integración) podría saltarse esa vista. Aquí se valida la sede ORIGEN:
    # si la sesión YA tiene una cita agendada en una sede fuera del alcance
    # del actor, no se permite tocarla (ni reagendarla, ni reasignarla a otro
    # médico, ni crear una de reemplazo) — corre ANTES de decidir la rama
    # crear/reagendar/cancelar+crear, así protege las 3 por igual. Reutiliza
    # `allowed_sucursales` (mismo helper que usa el resto de la app); NUNCA
    # reimplementa el anti-empalme, que sigue siendo 100% de agenda.
    if existing_appointment is not None and existing_appointment.sucursal_id is not None:
        if (
            not allowed_sucursales(user=actor, tenant=tenant)
            .filter(id=existing_appointment.sucursal_id)
            .exists()
        ):
            raise ValidationError("No tienes acceso a la sede de la cita actual de esta sesión.")

    with transaction.atomic():
        if existing_appointment is None:
            appointment = appointment_create(
                tenant=tenant,
                user=actor,
                patient_id=plan.patient_id,
                doctor_id=doctor_id,
                starts_at=starts_at,
                ends_at=ends_at,
                consultorio_id=consultorio_id,
                reason=reason,
                active_sucursal_id=active_sucursal_id,
            )
        elif existing_appointment.doctor_id == doctor_id:
            appointment = appointment_reschedule(
                appointment=existing_appointment,
                user=actor,
                starts_at=starts_at,
                ends_at=ends_at,
                consultorio_id=consultorio_id,
            )
        else:
            _cancel_session_appointment_if_any(
                actor=actor,
                session=session,
                reason="Sesión reagendada a otro médico desde la calendarización de tratamientos.",
                actor_role=actor_role,
            )
            appointment = appointment_create(
                tenant=tenant,
                user=actor,
                patient_id=plan.patient_id,
                doctor_id=doctor_id,
                starts_at=starts_at,
                ends_at=ends_at,
                consultorio_id=consultorio_id,
                reason=reason,
                active_sucursal_id=active_sucursal_id,
            )

        session.scheduled_date = scheduled_date
        session.scheduled_time = scheduled_time
        session.duration_minutes = duration_minutes
        session.appointment = appointment
        session.save(
            update_fields=[
                "scheduled_date",
                "scheduled_time",
                "duration_minutes",
                "appointment",
                "updated_at",
            ]
        )

    logger.info(
        "treatment_session_schedule: sesión %s agendada -> cita %s (tenant=%s)",
        session.pk,
        appointment.pk,
        tenant.pk,
    )

    audit_record(
        action=ActionType.TREATMENT_SESSION_SCHEDULE,
        resource_type="TreatmentSession",
        actor=actor,
        tenant=tenant,
        resource_id=session.id,
        resource_repr=str(session.id),
        metadata={"appointment_id": str(appointment.id), "plan_id": str(plan.id)},
    )
    return session


def treatment_session_unschedule(
    *, session: TreatmentSession, actor: Any, actor_role: str = ""
) -> TreatmentSession:
    """Quita una sesión de la agenda: cancela su cita ligada (si tiene) y limpia el FK.

    Idempotente: si la sesión no tiene `appointment`, no hace nada (ni
    audita) y devuelve la sesión sin cambios.

    Args:
        session:    Sesión a desagendar.
        actor:      Usuario que ejecuta la acción (auditoría).
        actor_role: Rol activo del actor (defensa en profundidad; si es
                    "doctor", solo puede desagendar su PROPIA cita — ver
                    `_cancel_session_appointment_if_any`).

    Returns:
        La TreatmentSession con `appointment=None`.

    Raises:
        ValidationError: rol no permitido, un doctor intentando quitar de
            agenda la cita de OTRO médico, el actor no tiene acceso a la sede
            de la cita ligada (multi-sede — cierre de A8, ver docs/design/
            sucursales-hallazgos-seguridad.md), o si la cita ligada ya está
            en un estado terminal que no admite cancelación (p. ej.
            Atendida) — la máquina de estados de agenda no permite esa
            transición; se propaga tal cual.
    """
    _validate_actor_role(actor_role=actor_role)

    if session.appointment_id is None:
        return session

    # Multi-sede — cierre de A8: un actor acotado a una sede no puede quitar
    # de agenda (cancelar) una cita que vive en OTRA sede, aunque conozca el
    # id de la sesión (el estado de cuenta del paciente es compartido entre
    # sedes por diseño). Reutiliza `allowed_sucursales`, mismo patrón que
    # `treatment_session_schedule`.
    appointment = session.appointment
    if appointment is not None and appointment.sucursal_id is not None:
        if (
            not allowed_sucursales(user=actor, tenant=session.tenant)
            .filter(id=appointment.sucursal_id)
            .exists()
        ):
            raise ValidationError("No tienes acceso a la sede de la cita actual de esta sesión.")

    _cancel_session_appointment_if_any(
        actor=actor,
        session=session,
        reason="Quitada de la calendarización",
        actor_role=actor_role,
    )
    session.appointment = None
    session.save(update_fields=["appointment", "updated_at"])

    logger.info(
        "treatment_session_unschedule: sesión %s desagendada (tenant=%s)",
        session.pk,
        session.tenant_id,
    )

    audit_record(
        action=ActionType.TREATMENT_SESSION_SCHEDULE,
        resource_type="TreatmentSession",
        actor=actor,
        tenant=session.tenant,
        resource_id=session.id,
        resource_repr=str(session.id),
        metadata={"unscheduled": True},
    )
    return session
