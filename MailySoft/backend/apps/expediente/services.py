"""
Services de la app expediente (sub-fases A1, A2, A3 y A4).

Toda escritura del expediente pasa por aquí. Las vistas son delgadas.

Convención: keyword-only args, nombrado acción+entidad.

Decisiones del plan respetadas:
  D-EC-1 — evolución inmutable + addendum: evolution_note_create crea y bloquea;
            addendum_create es append-only.
  D-EC-2 — evolución nace de cita ATTENDED: validado en evolution_note_create.
  D-EC-5 — sin borrado físico: allergy_resolve→is_active=False;
            diagnosis_resolve→status=resuelto. NUNCA .delete().
  D-EC-7 — validación estricta de choices: en serializer; service defiende en prof.
  D-EC-4 — HC flexible por bloque: los bloques JSON se reciben ya validados.

API pública:
    allergy_create         — registra una alergia nueva para un paciente.
    allergy_resolve        — da de baja clínica (is_active=False). Sin borrado físico.
    medical_history_upsert — crea o actualiza la HC de un paciente (upsert).
    vital_signs_create     — registra una toma de signos vitales (append-only).
    evolution_note_create  — crea una nota de evolución (inmutable).
    addendum_create        — agrega un addendum a una nota (append-only).
    diagnosis_create       — registra un diagnóstico para un paciente.
    diagnosis_resolve      — marca un diagnóstico como resuelto (baja lógica).
    evolution_image_add    — adjunta una imagen a una nota de evolución.
    evolution_image_remove — baja lógica de una imagen de evolución.

REGLA DE PRIVACIDAD — NUNCA incluir PII clínica en logs ni en la bitácora:
  Los campos `substance`, `reaction`, y cualquier dato del expediente clínico
  son información de salud sensible protegida por la LFPDPPP y NOM-024.
  La bitácora de auditoría (AuditLog) es append-only e inmutable; una vez
  escrita NO se puede purgar. Por ello:
    - `resource_repr` del AuditLog SIEMPRE es un identificador (UUID/número),
      NUNCA contenido de texto del expediente (sustancia, diagnóstico, anamnesis...).
    - Los `logger.*` de diagnóstico usan EXCLUSIVAMENTE IDs (pk) de entidades,
      NUNCA sus valores de texto (substance, reaction, diagnosis, etc.).
  Violación de esta regla = bug crítico de privacidad.
"""

import logging
from typing import Any

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

import datetime
from decimal import Decimal

from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.core.files import validate_evolution_image
from apps.expediente.models import (
    Addendum,
    Allergy,
    Diagnosis,
    DiagnosisKind,
    DiagnosisStatus,
    EvolutionImage,
    EvolutionNote,
    MedicalHistory,
    MedicalHistoryQuestion,
    QuestionFieldType,
    Severity,
    VitalSignsRecord,
)
from apps.notificaciones.models import NotificationKind, NotificationTarget
from apps.notificaciones.recipients import Role, users_with_role
from apps.notificaciones.services import notification_fanout
from apps.pacientes.models import Patient
from apps.tenancy.models import Tenant

logger = logging.getLogger("apps.expediente.services")


# ---------------------------------------------------------------------------
# allergy_create
# ---------------------------------------------------------------------------


@transaction.atomic
def allergy_create(
    *,
    tenant: Tenant,
    user: Any,
    patient: Patient,
    substance: str,
    reaction: str = "",
    severity: str = "",
) -> Allergy:
    """Registra una alergia nueva para el paciente indicado.

    Valida:
    - Que tenant no sea None (defensa para llamadas desde Celery sin contexto HTTP).
    - Que el paciente pertenezca al mismo tenant (defensa en profundidad).
    - Que severity, si se provee, sea uno de los choices válidos (D-EC-7).
    - Que substance no esté vacía.

    La alergia se crea con is_active=True (vigente por defecto).

    Args:
        tenant:    Clínica del contexto activo. No puede ser None.
        user:      Usuario que registra la alergia (para created_by/auditoría).
        patient:   Paciente al que pertenece la alergia (debe ser del mismo tenant).
        substance: Sustancia o medicamento alergénico.
        reaction:  Reacción observada (opcional).
        severity:  Severidad: 'leve', 'moderada', 'severa' o '' (sin especificar).

    Returns:
        La instancia Allergy recién creada.

    Raises:
        ValidationError: si tenant es None, si el paciente no pertenece al tenant,
                         si la sustancia está vacía, o si severity es un valor no
                         permitido.
    """
    # Guardia: el service puede invocarse desde Celery/management commands donde
    # no hay contexto HTTP y tenant podría llegar como None.
    if tenant is None:
        raise ValidationError(
            "Se requiere un tenant activo para registrar una alergia."
        )

    # Defensa en profundidad: el paciente debe ser del mismo tenant.
    # Aunque la view resuelve el paciente por TenantManager, el service puede
    # llamarse desde Celery o comandos sin contexto de request.
    if patient.tenant_id != tenant.id:
        raise ValidationError(
            "El paciente no pertenece a esta clínica."
        )

    # Validar sustancia.
    substance = substance.strip()
    if not substance:
        raise ValidationError("La sustancia no puede estar vacía.")

    # Validar severity (whitelist — D-EC-7).
    if severity:
        valid_severities = [choice[0] for choice in Severity.choices]
        if severity not in valid_severities:
            raise ValidationError(
                f"Severidad inválida '{severity}'. "
                f"Debe ser una de: {', '.join(valid_severities)}."
            )

    allergy = Allergy.objects.create(
        tenant=tenant,
        created_by=user,
        patient=patient,
        substance=substance,
        reaction=reaction,
        severity=severity,
        is_active=True,
    )

    logger.info(
        "allergy_create: alergia %s creada para paciente %s (tenant=%s)",
        allergy.pk,
        patient.pk,
        tenant.pk,
    )

    # ALTO-1: resource_repr usa el UUID del registro, NUNCA la sustancia (PII clínica).
    # La bitácora es append-only e inmutable (NOM-024); no se puede purgar.
    audit_record(
        action=ActionType.ALLERGY_CREATE,
        resource_type="Allergy",
        actor=user,
        tenant=tenant,
        resource_id=allergy.id,
        resource_repr=str(allergy.id),
        metadata={"patient_id": str(patient.id), "severity": severity or ""},
    )
    return allergy


# ---------------------------------------------------------------------------
# allergy_resolve — baja lógica (D-EC-5: sin borrado físico)
# ---------------------------------------------------------------------------


@transaction.atomic
def allergy_resolve(
    *,
    allergy: Allergy,
    user: Any,
) -> Allergy:
    """Marca una alergia como resuelta (baja lógica clínica).

    NUNCA borra el registro físicamente (D-EC-5). Solo pone is_active=False.
    Si ya estaba resuelta, la operación es idempotente (no error).

    Valida que el tenant de la alergia no sea None (defensa para llamadas desde
    Celery/management commands sin contexto HTTP).

    Args:
        allergy: Instancia de Allergy a resolver (ya obtenida por el selector).
        user:    Usuario que realiza la acción (para futura auditoría).

    Returns:
        La instancia Allergy con is_active=False.

    Raises:
        ValidationError: si el tenant de la alergia es None.
    """
    # Guardia: la alergia debe tener un tenant asociado.
    if allergy.tenant is None:
        raise ValidationError(
            "La alergia no tiene un tenant asociado. No se puede resolver."
        )

    if allergy.is_active:
        allergy.is_active = False
        allergy.save(update_fields=["is_active", "updated_at"])

        logger.info(
            "allergy_resolve: alergia %s resuelta por usuario %s",
            allergy.pk,
            getattr(user, "pk", None),
        )

        # ALTO-1: resource_repr usa el UUID del registro, NUNCA la sustancia (PII clínica).
        # La bitácora es append-only e inmutable (NOM-024); no se puede purgar.
        audit_record(
            action=ActionType.ALLERGY_RESOLVE,
            resource_type="Allergy",
            actor=user,
            tenant=allergy.tenant,
            resource_id=allergy.id,
            resource_repr=str(allergy.id),
            metadata={"patient_id": str(allergy.patient_id)},
        )

    return allergy


# ---------------------------------------------------------------------------
# medical_history_upsert — crea o actualiza la HC (D-EC-4, D-EC-5)
# ---------------------------------------------------------------------------


@transaction.atomic
def medical_history_upsert(
    *,
    tenant: Tenant,
    user: Any,
    patient: Patient,
    heredo_familiares: dict[str, Any] | None = None,
    personales_patologicos: dict[str, Any] | None = None,
    no_patologicos: dict[str, Any] | None = None,
    habitos_alimenticios: dict[str, Any] | None = None,
    gineco_obstetricos: dict[str, Any] | None = None,
    exploracion_fisica_basal: dict[str, Any] | None = None,
    antecedentes_importancia: str = "",
    padecimiento_actual: str = "",
    tratamientos_actuales: str = "",
    prioridad_analisis: str = "",
    custom_answers: dict[str, Any] | None = None,
) -> MedicalHistory:
    """Crea o actualiza la historia clínica formal del paciente (upsert).

    Si el paciente ya tiene una HC activa, la actualiza aplicando SOLO los bloques
    provistos (los bloques None se omiten para no borrar datos existentes).
    Si no existe, crea una nueva HC con los bloques provistos.

    Valida:
    - Que tenant no sea None (defensa para llamadas desde Celery sin contexto HTTP).
    - Que el paciente pertenezca al mismo tenant (defensa en profundidad).

    La validación de schema de los bloques JSON y la validación condicional por
    sexo del bloque gineco_obstetricos se hacen en el serializer ANTES de llamar
    a este service. El service confía en que los datos ya llegan limpios y validados.

    Registra MEDICAL_HISTORY_UPDATE en AuditLog (NOM-024).

    MEDIO-4 — Registro de acceso en el upsert:
    El evento MEDICAL_HISTORY_UPDATE implica que el médico leyó la HC para editarla
    (el PUT devuelve el estado resultante, que incluye datos previos). Por ello NO se
    emite MEDICAL_HISTORY_READ adicional en el PUT; emitirlo sería doble registro que
    contamina los reportes NOM-024 sin añadir valor de auditoría real. El GET tiene
    su propio MEDICAL_HISTORY_READ separado.

    REGLA DE PRIVACIDAD: resource_repr = str(history.id), NUNCA contenido clínico.

    Args:
        tenant:                   Clínica del contexto activo. No puede ser None.
        user:                     Usuario que realiza la actualización.
        patient:                  Paciente al que pertenece la HC (mismo tenant).
        heredo_familiares:        Bloque AHF (None = no tocar).
        personales_patologicos:   Bloque APP (None = no tocar).
        no_patologicos:           Bloque APNP (None = no tocar).
        habitos_alimenticios:     Bloque hábitos cortos (None = no tocar).
        gineco_obstetricos:       Bloque AGO (None = no tocar).
        exploracion_fisica_basal: Bloque exploración (None = no tocar).
        antecedentes_importancia: Texto libre (string vacío = no tocar si ya existe).
        padecimiento_actual:      Texto libre.
        tratamientos_actuales:    Texto libre.
        prioridad_analisis:       Texto libre.
        custom_answers:           Respuestas a preguntas extra (Fase 2).
                                  None = no tocar. Dict = reemplaza completamente.
                                  Las claves que no correspondan a UUIDs de preguntas
                                  activas del tenant se ignoran silenciosamente.

    Returns:
        La instancia MedicalHistory creada o actualizada.

    Raises:
        ValidationError: si tenant es None, o si el paciente no pertenece al tenant.
    """
    # Guardia: el service puede invocarse desde Celery/management commands donde
    # no hay contexto HTTP y tenant podría llegar como None.
    if tenant is None:
        raise ValidationError(
            "Se requiere un tenant activo para actualizar la historia clínica."
        )

    # Defensa en profundidad: el paciente debe ser del mismo tenant.
    if patient.tenant_id != tenant.id:
        raise ValidationError(
            "El paciente no pertenece a esta clínica."
        )

    # MEDIO-1 — Protección contra condición de carrera en upsert.
    #
    # Problema: dos PUT simultáneos pueden ambos ver history=None y ambos intentar
    # INSERT, lo que viola el UniqueConstraint (patient, deleted_at IS NULL) y
    # genera IntegrityError → 500 en el segundo request.
    #
    # Solución: dentro de la transacción atómica usamos select_for_update() para
    # adquirir un bloqueo de fila al leer la HC existente. El segundo request
    # espera (NOWAIT no está activado) hasta que el primero haga commit/rollback.
    # Así solo uno llega a la rama is_new=True; el segundo encontrará la fila ya
    # creada al adquirir el lock.
    #
    # Fallback: si de todos modos se produce IntegrityError (p. ej. al llamar desde
    # fuera de transacción atómica o con un engine sin soporte), se captura,
    # se carga la fila existente y se aplica la actualización. Esto garantiza que
    # dos PUT concurrentes siempre resulten en una sola fila sin 500.
    history: MedicalHistory | None = (
        MedicalHistory.objects.select_for_update().filter(patient=patient).first()
    )

    is_new = history is None

    def _apply_fields(h: MedicalHistory) -> MedicalHistory:
        """Aplica solo los bloques provistos y los campos de texto al objeto HC."""
        if heredo_familiares is not None:
            h.heredo_familiares = heredo_familiares
        if personales_patologicos is not None:
            h.personales_patologicos = personales_patologicos
        if no_patologicos is not None:
            h.no_patologicos = no_patologicos
        if habitos_alimenticios is not None:
            h.habitos_alimenticios = habitos_alimenticios
        if gineco_obstetricos is not None:
            h.gineco_obstetricos = gineco_obstetricos
        if exploracion_fisica_basal is not None:
            h.exploracion_fisica_basal = exploracion_fisica_basal
        # Campos de texto: el serializer garantiza default="" si no se envían.
        h.antecedentes_importancia = antecedentes_importancia
        h.padecimiento_actual = padecimiento_actual
        h.tratamientos_actuales = tratamientos_actuales
        h.prioridad_analisis = prioridad_analisis

        # Fase 2: custom_answers — filtrar claves para quedarse solo con las que
        # corresponden a preguntas activas del tenant (ignora claves desconocidas).
        if custom_answers is not None:
            valid_ids: set[str] = set(
                str(pk)
                for pk in MedicalHistoryQuestion.objects.filter(
                    tenant=tenant, is_active=True
                ).values_list("id", flat=True)
            )
            h.custom_answers = {
                k: v for k, v in custom_answers.items() if k in valid_ids
            }

        return h

    if is_new:
        history = MedicalHistory(
            tenant=tenant,
            created_by=user,
            patient=patient,
        )
        _apply_fields(history)
        try:
            # MEDIO-3: CREATE usa save() sin update_fields (todos los campos son nuevos).
            history.save()
        except IntegrityError:
            # Fallback de carrera: otro worker creó la fila en el instante entre el
            # select_for_update (que encontró None) y este save(). Cargamos la fila
            # ganadora y aplicamos la actualización encima.
            logger.warning(
                "medical_history_upsert: IntegrityError en CREATE, reintentando "
                "como UPDATE (race condition). paciente=%s tenant=%s",
                patient.pk,
                tenant.pk,
            )
            history = MedicalHistory.objects.select_for_update().get(patient=patient)
            is_new = False
            _apply_fields(history)
            # MEDIO-3: UPDATE con update_fields — solo los bloques y textos modificables.
            history.save(
                update_fields=[
                    "heredo_familiares",
                    "personales_patologicos",
                    "no_patologicos",
                    "habitos_alimenticios",
                    "gineco_obstetricos",
                    "exploracion_fisica_basal",
                    "antecedentes_importancia",
                    "padecimiento_actual",
                    "tratamientos_actuales",
                    "prioridad_analisis",
                    "custom_answers",
                    "updated_at",
                ]
            )
    else:
        _apply_fields(history)
        # MEDIO-3: UPDATE usa update_fields para evitar sobreescribir tenant/patient/
        # created_by/created_at accidentalmente (son campos de identidad inmutables).
        history.save(
            update_fields=[
                "heredo_familiares",
                "personales_patologicos",
                "no_patologicos",
                "habitos_alimenticios",
                "gineco_obstetricos",
                "exploracion_fisica_basal",
                "antecedentes_importancia",
                "padecimiento_actual",
                "tratamientos_actuales",
                "prioridad_analisis",
                "custom_answers",
                "updated_at",
            ]
        )

    logger.info(
        "medical_history_upsert: HC %s %s para paciente %s (tenant=%s)",
        history.pk,
        "creada" if is_new else "actualizada",
        patient.pk,
        tenant.pk,
    )

    # ALTO-1: resource_repr usa el UUID del registro, NUNCA contenido clínico (PII).
    # La bitácora es append-only e inmutable (NOM-024); no se puede purgar.
    audit_record(
        action=ActionType.MEDICAL_HISTORY_UPDATE,
        resource_type="MedicalHistory",
        actor=user,
        tenant=tenant,
        resource_id=history.id,
        resource_repr=str(history.id),
        metadata={
            "patient_id": str(patient.id),
            "is_new": is_new,
        },
    )

    return history


# ---------------------------------------------------------------------------
# vital_signs_create — Signos Vitales (A3) — Append-only (D-EC-1/D-EC-5)
# ---------------------------------------------------------------------------


@transaction.atomic
def vital_signs_create(
    *,
    tenant: Tenant,
    user: Any,
    patient: Patient,
    measured_at: datetime.datetime,
    weight_kg: Decimal | None = None,
    height_m: Decimal | None = None,
    heart_rate: int | None = None,
    resp_rate: int | None = None,
    systolic: int | None = None,
    diastolic: int | None = None,
    temperature_c: Decimal | None = None,
    oxygen_saturation: int | None = None,
    glucose: int | None = None,
    extra_params: dict[str, Any] | None = None,
    notes: str = "",
    appointment: Any = None,
) -> VitalSignsRecord:
    """Registra una toma de signos vitales para el paciente indicado.

    Las tomas son **inmutables** (append-only — D-EC-1/D-EC-5). Solo se crean;
    no existen endpoints de edición ni borrado. Si hubo un error en el registro,
    se crea una nueva toma con los valores correctos.

    Valida:
    - Que tenant no sea None (defensa para llamadas desde Celery sin contexto HTTP).
    - Que el paciente pertenezca al mismo tenant (IDOR / defensa en profundidad).
    - Que measured_at no sea futuro (validación también en el serializer, aquí es
      defensa en profundidad para llamadas directas al service).
    - Si se provee appointment, que pertenezca al mismo paciente y tenant.

    La validación de rangos fisiológicos se realiza en el serializer ANTES de
    llamar a este service. El service confía en que los valores de los campos
    numéricos ya vienen dentro de rangos válidos.

    Registra VITALSIGNS_CREATE en AuditLog (NOM-024).
    resource_repr = str(record.id) — NUNCA PII ni valores clínicos.

    Args:
        tenant:            Clínica del contexto activo. No puede ser None.
        user:              Usuario que registra la toma (responsable).
        patient:           Paciente de la toma (debe ser del mismo tenant).
        measured_at:       Momento de la toma. No puede ser futuro.
        weight_kg:         Peso en kg (opcional).
        height_m:          Talla en metros (opcional).
        heart_rate:        Frecuencia cardíaca en lpm (opcional).
        resp_rate:         Frecuencia respiratoria en rpm (opcional).
        systolic:          Presión sistólica en mmHg (opcional).
        diastolic:         Presión diastólica en mmHg (opcional).
        temperature_c:     Temperatura en °C (opcional).
        oxygen_saturation: Saturación de oxígeno en % (opcional).
        glucose:           Glucosa en mg/dL (opcional).
        extra_params:      Parámetros del legacy (whitelist estricta, validados en serializer).
        notes:             Observaciones breves (máx 255 chars).
        appointment:       Cita asociada (opcional). Debe ser del mismo paciente y tenant.

    Returns:
        La instancia VitalSignsRecord recién creada.

    Raises:
        ValidationError: si tenant es None, el paciente no pertenece al tenant,
                         measured_at es futuro, o el appointment no coincide.
    """
    from django.utils import timezone

    # Guardia: el service puede invocarse desde Celery/management commands donde
    # no hay contexto HTTP y tenant podría llegar como None.
    if tenant is None:
        raise ValidationError(
            "Se requiere un tenant activo para registrar signos vitales."
        )

    # Defensa en profundidad: el paciente debe ser del mismo tenant.
    if patient.tenant_id != tenant.id:
        raise ValidationError(
            "El paciente no pertenece a esta clínica."
        )

    # Validar que measured_at no sea futuro (también validado en serializer).
    now = timezone.now()
    if measured_at > now:
        raise ValidationError(
            "La fecha de la toma no puede ser futura."
        )

    # Validar appointment si se provee.
    if appointment is not None:
        if appointment.patient_id != patient.id:
            raise ValidationError(
                "La cita no corresponde al paciente indicado."
            )
        if appointment.tenant_id != tenant.id:
            raise ValidationError(
                "La cita no pertenece a esta clínica."
            )

    record = VitalSignsRecord.objects.create(
        tenant=tenant,
        created_by=user,
        patient=patient,
        appointment=appointment,
        measured_at=measured_at,
        weight_kg=weight_kg,
        height_m=height_m,
        heart_rate=heart_rate,
        resp_rate=resp_rate,
        systolic=systolic,
        diastolic=diastolic,
        temperature_c=temperature_c,
        oxygen_saturation=oxygen_saturation,
        glucose=glucose,
        extra_params=extra_params or {},
        notes=notes,
    )

    logger.info(
        "vital_signs_create: toma %s creada para paciente %s (tenant=%s)",
        record.pk,
        patient.pk,
        tenant.pk,
    )

    # ALTO-1: resource_repr = UUID del registro, NUNCA valores clínicos (PII).
    # La bitácora es append-only e inmutable (NOM-024); no se puede purgar.
    audit_record(
        action=ActionType.VITALSIGNS_CREATE,
        resource_type="VitalSignsRecord",
        actor=user,
        tenant=tenant,
        resource_id=record.id,
        resource_repr=str(record.id),
        metadata={
            "patient_id": str(patient.id),
            "appointment_id": str(appointment.id) if appointment is not None else None,
        },
    )

    return record


# ---------------------------------------------------------------------------
# evolution_note_create — Nota de Evolución (A4) — Inmutable (D-EC-1)
# ---------------------------------------------------------------------------


@transaction.atomic
def evolution_note_create(
    *,
    tenant: Tenant,
    user: Any,
    patient: Patient,
    appointment: Any,
    doctor: Any,
    actor_role: str = "",
    antecedentes: str = "",
    interrogatorio: str = "",
    estudios: str = "",
    diagnosticos_texto: str = "",
    tratamiento: str = "",
    plan_recomendaciones: str = "",
    indicaciones_enfermeria: str = "",
    exploracion_fisica: dict[str, Any] | None = None,
    vital_signs: Any = None,
) -> EvolutionNote:
    """Crea una nota de evolución clínica inmutable (D-EC-1, D-EC-2).

    La nota se firma al crear (is_locked=True) y no admite modificación.
    Solo existe el endpoint POST; PATCH/PUT/DELETE devuelven 405.

    Valida (D-EC-2 y defensa en profundidad):
    - Que tenant no sea None.
    - Que el paciente pertenezca al mismo tenant.
    - Que la cita (appointment) pertenezca al mismo tenant y paciente.
    - Que la cita esté en estado ATTENDED.
    - Que el doctor sea el doctor de la cita.
    - Regla del médico (ALTO-1): si actor_role == 'doctor', debe ser el autor
      de la cita (appointment.doctor.membership.user == user). Owner/admin
      pueden crear evoluciones para cualquier médico. actor_role es un argumento
      explícito (no leído de atributos efímeros del usuario) para que la regla
      funcione correctamente en llamadas desde Celery/commands/tests.
    - Que vital_signs, si se provee, pertenezca al mismo paciente y tenant.

    MEDIO-4: si appointment.doctor.membership no existe (datos corruptos),
    lanza ValidationError en lugar de RelatedObjectDoesNotExist → 500.

    Registra EVOLUTION_CREATE en AuditLog (NOM-024).
    resource_repr = str(note.id) — NUNCA PII.

    Args:
        tenant:                  Clínica del contexto activo. No puede ser None.
        user:                    Usuario que crea la nota (para created_by/auditoría).
        patient:                 Paciente de la nota (mismo tenant).
        appointment:             Cita médica (ATTENDED, mismo paciente y tenant).
        doctor:                  Médico autor clínico (debe ser el doctor de la cita).
        actor_role:              Rol activo del usuario ('doctor', 'owner', 'admin', ...).
                                 La view lo extrae de request.active_role y lo pasa
                                 explícitamente. Default '' = sin restricción de médico.
        antecedentes:            Antecedentes del episodio.
        interrogatorio:          Interrogatorio por aparatos y sistemas.
        estudios:                Estudios solicitados o reportados.
        diagnosticos_texto:      Diagnósticos en texto libre.
        tratamiento:             Tratamiento prescrito.
        plan_recomendaciones:    Plan y recomendaciones.
        indicaciones_enfermeria: Indicaciones para enfermería.
        exploracion_fisica:      Dict de exploración por sistemas (validado en serializer).
        vital_signs:             Toma de signos asociada (opcional, mismo paciente/tenant).

    Returns:
        La instancia EvolutionNote recién creada con is_locked=True.

    Raises:
        ValidationError: si cualquiera de las validaciones falla.
    """
    from apps.agenda.models import Appointment  # noqa: PLC0415

    if tenant is None:
        raise ValidationError(
            "Se requiere un tenant activo para crear una nota de evolución."
        )

    # Defensa en profundidad: el paciente debe ser del mismo tenant.
    if patient.tenant_id != tenant.id:
        raise ValidationError("El paciente no pertenece a esta clínica.")

    # Validar appointment: mismo tenant, mismo paciente, estado ATTENDED (D-EC-2).
    if appointment.tenant_id != tenant.id:
        raise ValidationError("La cita no pertenece a esta clínica.")
    if appointment.patient_id != patient.id:
        raise ValidationError("La cita no corresponde al paciente indicado.")
    if appointment.status != Appointment.Status.ATTENDED:
        raise ValidationError(
            "La nota de evolución solo puede crearse sobre una cita con "
            "estado ATTENDED (atendida)."
        )

    # Validar que el doctor sea el de la cita.
    if appointment.doctor_id != doctor.id:
        raise ValidationError(
            "El médico de la nota debe ser el médico de la cita."
        )

    # Defensa: el doctor debe pertenecer al mismo tenant.
    if doctor.tenant_id != tenant.id:
        raise ValidationError("El médico no pertenece a esta clínica.")

    # Regla del médico (D-EC-2, ALTO-1): actor_role es argumento explícito.
    # Si el actor tiene rol 'doctor', solo puede crear evoluciones sobre sus
    # propias citas. Owner/admin no tienen restricción.
    if actor_role == "doctor":
        # MEDIO-4: appointment.doctor.membership puede no existir (datos corruptos).
        # Capturamos RelatedObjectDoesNotExist para devolver 400 en lugar de 500.
        try:
            membership_user_id = appointment.doctor.membership.user_id
        except Exception:
            raise ValidationError(
                "El médico de la cita no tiene perfil de membresía válido."
            )
        if membership_user_id != user.pk:
            raise ValidationError(
                "Un médico solo puede crear notas de evolución sobre sus propias citas."
            )

    # Validar vital_signs si se provee.
    if vital_signs is not None:
        if vital_signs.patient_id != patient.id:
            raise ValidationError(
                "Los signos vitales no corresponden al paciente indicado."
            )
        if vital_signs.tenant_id != tenant.id:
            raise ValidationError(
                "Los signos vitales no pertenecen a esta clínica."
            )

    # MEDIO-2: capturar IntegrityError de UniqueConstraint(appointment) para dar
    # error 400 claro en lugar de 500. Se valida antes con un SELECT para dar el
    # mensaje de error en ValidationError antes del INSERT; el IntegrityError es
    # la segunda barrera (race condition o llamada directa al service).
    if EvolutionNote.objects.filter(
        appointment=appointment, deleted_at__isnull=True
    ).exists():
        raise ValidationError(
            "Ya existe una nota de evolución para esta cita."
        )

    try:
        note = EvolutionNote.objects.create(
            tenant=tenant,
            created_by=user,
            patient=patient,
            appointment=appointment,
            doctor=doctor,
            vital_signs=vital_signs,
            antecedentes=antecedentes,
            interrogatorio=interrogatorio,
            estudios=estudios,
            diagnosticos_texto=diagnosticos_texto,
            tratamiento=tratamiento,
            plan_recomendaciones=plan_recomendaciones,
            indicaciones_enfermeria=indicaciones_enfermeria,
            exploracion_fisica=exploracion_fisica or {},
            is_locked=True,
        )
    except IntegrityError as exc:
        # Segunda barrera: race condition entre el SELECT de arriba y el INSERT.
        if "evolution_note_appointment_uniq" in str(exc) or "unique" in str(exc).lower():
            raise ValidationError(
                "Ya existe una nota de evolución para esta cita."
            ) from exc
        raise

    logger.info(
        "evolution_note_create: nota %s creada para paciente %s cita %s (tenant=%s)",
        note.pk,
        patient.pk,
        appointment.pk,
        tenant.pk,
    )

    # ALTO-1: resource_repr = UUID del registro, NUNCA PII clínica.
    audit_record(
        action=ActionType.EVOLUTION_CREATE,
        resource_type="EvolutionNote",
        actor=user,
        tenant=tenant,
        resource_id=note.id,
        resource_repr=str(note.id),
        metadata={
            "patient_id": str(patient.id),
            "appointment_id": str(appointment.id),
            "doctor_id": str(doctor.id),
        },
    )

    # Best-effort: notificar a enfermería si hay indicaciones.
    # El try/except garantiza que un fallo en el fanout NO tumba la creación
    # de la evolución (disponibilidad clínica > entrega garantizada de avisos).
    # Notificación sin PII: el título y cuerpo son genéricos; la navegación
    # usa target_type=PATIENT + target_id (UUID del paciente).
    if indicaciones_enfermeria.strip():
        try:
            nurses = users_with_role(tenant=tenant, role=Role.NURSE)
            notification_fanout(
                tenant=tenant,
                recipients=nurses,
                kind=NotificationKind.NURSING_INSTRUCTION,
                title="Indicaciones de enfermería pendientes",
                body="Hay nuevas indicaciones en el expediente del paciente.",
                actor=user,
                target_type=NotificationTarget.PATIENT,
                target_id=patient.id,
            )
        except Exception:
            logger.warning(
                "evolution_note_create: no se pudo notificar a enfermería "
                "(best-effort). note_id=%s patient_id=%s tenant_id=%s",
                note.pk,
                patient.pk,
                tenant.pk,
            )

    return note


# ---------------------------------------------------------------------------
# addendum_create — Addendum sobre EvolutionNote (A4) — Append-only
# ---------------------------------------------------------------------------


@transaction.atomic
def addendum_create(
    *,
    tenant: Tenant,
    user: Any,
    evolution: EvolutionNote,
    body: str,
) -> Addendum:
    """Agrega un addendum a una nota de evolución (D-EC-1, append-only).

    El addendum NO modifica la nota original: la extiende con una anotación
    adicional preservando la trazabilidad clínica.

    Valida:
    - Que tenant no sea None.
    - Que la nota de evolución pertenezca al mismo tenant.
    - Que el body no esté vacío.

    Registra ADDENDUM_CREATE en AuditLog (NOM-024).
    resource_repr = str(addendum.id) — NUNCA PII.

    Args:
        tenant:    Clínica del contexto activo. No puede ser None.
        user:      Usuario que agrega el addendum.
        evolution: Nota de evolución a la que se agrega el addendum.
        body:      Texto del addendum (requerido, no vacío).

    Returns:
        La instancia Addendum recién creada.

    Raises:
        ValidationError: si tenant es None, la nota no pertenece al tenant, o
                         el body está vacío.
    """
    if tenant is None:
        raise ValidationError(
            "Se requiere un tenant activo para agregar un addendum."
        )

    if evolution.tenant_id != tenant.id:
        raise ValidationError(
            "La nota de evolución no pertenece a esta clínica."
        )

    body = body.strip()
    if not body:
        raise ValidationError("El texto del addendum no puede estar vacío.")

    addendum = Addendum.objects.create(
        tenant=tenant,
        created_by=user,
        evolution=evolution,
        author=user,
        body=body,
    )

    logger.info(
        "addendum_create: addendum %s creado sobre evolución %s (tenant=%s)",
        addendum.pk,
        evolution.pk,
        tenant.pk,
    )

    # ALTO-1: resource_repr = UUID del registro, NUNCA PII.
    audit_record(
        action=ActionType.ADDENDUM_CREATE,
        resource_type="Addendum",
        actor=user,
        tenant=tenant,
        resource_id=addendum.id,
        resource_repr=str(addendum.id),
        metadata={
            "evolution_id": str(evolution.id),
            "patient_id": str(evolution.patient_id),
        },
    )

    return addendum


# ---------------------------------------------------------------------------
# diagnosis_create — Diagnóstico Clínico (A4)
# ---------------------------------------------------------------------------


@transaction.atomic
def diagnosis_create(
    *,
    tenant: Tenant,
    user: Any,
    patient: Patient,
    description: str,
    cie_code: str = "",
    kind: str = DiagnosisKind.PRESUNTIVO,
    evolution: EvolutionNote | None = None,
) -> Diagnosis:
    """Registra un diagnóstico clínico para el paciente indicado.

    Valida:
    - Que tenant no sea None.
    - Que el paciente pertenezca al mismo tenant.
    - Que description no esté vacía.
    - Que kind sea un valor válido de DiagnosisKind.
    - Que evolution, si se provee, pertenezca al mismo paciente y tenant.

    El diagnóstico nace con status=activo (D-EC-5: resolución vía
    diagnosis_resolve, nunca borrado físico).
    Registra DIAGNOSIS_CREATE en AuditLog (NOM-024).
    resource_repr = str(diagnosis.id) — NUNCA PII.

    Args:
        tenant:      Clínica del contexto activo. No puede ser None.
        user:        Usuario que registra el diagnóstico.
        patient:     Paciente al que pertenece.
        description: Descripción del diagnóstico (requerida).
        cie_code:    Código CIE-10 (texto libre en v1).
        kind:        Tipo: 'presuntivo' (default) o 'definitivo'.
        evolution:   Nota de evolución vinculada (opcional).

    Returns:
        La instancia Diagnosis recién creada.

    Raises:
        ValidationError: si las validaciones fallan.
    """
    if tenant is None:
        raise ValidationError(
            "Se requiere un tenant activo para registrar un diagnóstico."
        )

    if patient.tenant_id != tenant.id:
        raise ValidationError("El paciente no pertenece a esta clínica.")

    description = description.strip()
    if not description:
        raise ValidationError("La descripción del diagnóstico no puede estar vacía.")

    # Validar kind (whitelist — D-EC-7).
    valid_kinds = [choice[0] for choice in DiagnosisKind.choices]
    if kind not in valid_kinds:
        raise ValidationError(
            f"Tipo de diagnóstico inválido '{kind}'. "
            f"Debe ser uno de: {', '.join(valid_kinds)}."
        )

    # Validar evolution si se provee.
    if evolution is not None:
        if evolution.tenant_id != tenant.id:
            raise ValidationError(
                "La nota de evolución no pertenece a esta clínica."
            )
        if evolution.patient_id != patient.id:
            raise ValidationError(
                "La nota de evolución no corresponde al paciente indicado."
            )

    diagnosis = Diagnosis.objects.create(
        tenant=tenant,
        created_by=user,
        patient=patient,
        evolution=evolution,
        cie_code=cie_code,
        description=description,
        kind=kind,
        status=DiagnosisStatus.ACTIVO,
    )

    logger.info(
        "diagnosis_create: diagnóstico %s creado para paciente %s (tenant=%s)",
        diagnosis.pk,
        patient.pk,
        tenant.pk,
    )

    # ALTO-1: resource_repr = UUID, NUNCA descripción del diagnóstico (PII clínica).
    audit_record(
        action=ActionType.DIAGNOSIS_CREATE,
        resource_type="Diagnosis",
        actor=user,
        tenant=tenant,
        resource_id=diagnosis.id,
        resource_repr=str(diagnosis.id),
        metadata={
            "patient_id": str(patient.id),
            "kind": kind,
            "evolution_id": str(evolution.id) if evolution is not None else None,
        },
    )

    return diagnosis


# ---------------------------------------------------------------------------
# diagnosis_resolve — Baja lógica del diagnóstico (D-EC-5)
# ---------------------------------------------------------------------------


@transaction.atomic
def diagnosis_resolve(
    *,
    diagnosis: Diagnosis,
    user: Any,
) -> Diagnosis:
    """Marca un diagnóstico como resuelto (baja lógica — D-EC-5).

    NUNCA borra el registro físicamente. Solo cambia status de 'activo' a
    'resuelto'. Si ya estaba resuelto, la operación es idempotente (no error).

    description, cie_code y kind son inmutables tras el CREATE; no se tocan aquí.

    Registra DIAGNOSIS_RESOLVE en AuditLog (NOM-024).
    resource_repr = str(diagnosis.id) — NUNCA PII.

    Args:
        diagnosis: Instancia de Diagnosis a resolver.
        user:      Usuario que ejecuta la acción.

    Returns:
        La instancia Diagnosis con status=resuelto.

    Raises:
        ValidationError: si el tenant de la instancia es None.
    """
    if diagnosis.tenant is None:
        raise ValidationError(
            "El diagnóstico no tiene un tenant asociado. No se puede resolver."
        )

    if diagnosis.status == DiagnosisStatus.ACTIVO:
        diagnosis.status = DiagnosisStatus.RESUELTO
        diagnosis.save(update_fields=["status", "updated_at"])

        logger.info(
            "diagnosis_resolve: diagnóstico %s resuelto por usuario %s",
            diagnosis.pk,
            getattr(user, "pk", None),
        )

        # ALTO-1: resource_repr = UUID, NUNCA descripción (PII clínica).
        audit_record(
            action=ActionType.DIAGNOSIS_RESOLVE,
            resource_type="Diagnosis",
            actor=user,
            tenant=diagnosis.tenant,
            resource_id=diagnosis.id,
            resource_repr=str(diagnosis.id),
            metadata={"patient_id": str(diagnosis.patient_id)},
        )

    return diagnosis


# ---------------------------------------------------------------------------
# evolution_image_add / evolution_image_remove — Imágenes de Evolución
# ---------------------------------------------------------------------------


#: MEDIO-2 — Límite de imágenes activas por nota de evolución.
#: Protege contra DoS por acumulación de archivos en una sola nota clínica.
MAX_IMAGES_PER_EVOLUTION: int = 20


@transaction.atomic
def evolution_image_add(
    *,
    tenant: Tenant,
    user: Any,
    evolution: EvolutionNote,
    image: Any,
    caption: str = "",
) -> EvolutionImage:
    """Agrega una imagen fotográfica a una nota de evolución.

    Valida:
    - Que tenant no sea None.
    - Que la nota de evolución pertenezca al mismo tenant (defensa en profundidad).
    - Que la nota no supere MAX_IMAGES_PER_EVOLUTION imágenes activas (MEDIO-2).
    - Que `image` sea una imagen real y segura (Pillow, whitelist de formatos,
      rechazo de SVG, límite de 10 MB, sin bombas de descompresión). Esta es
      la barrera principal de seguridad.

    El nombre del archivo se aleatoriza en `evolution_image_path` (ya en el modelo).
    El almacenamiento es local en MEDIA_ROOT/evoluciones/. En producción solo
    hay que cambiar DEFAULT_FILE_STORAGE / STORAGES a S3; el código no cambia.

    D-EC-5: las imágenes nunca se borran físicamente. Usar evolution_image_remove
    para la baja lógica (pone deleted_at).

    Registra EVOLUTION_IMAGE_ADD en AuditLog (NOM-024 — MEDIO-3).
    resource_repr = str(evo_image.id) — NUNCA PII ni nombre de archivo.

    Args:
        tenant:    Clínica del contexto activo. No puede ser None.
        user:      Usuario que sube la imagen (para created_by/auditoría).
        evolution: Nota de evolución a la que se agrega la imagen (mismo tenant).
        image:     Archivo subido (UploadedFile). DEBE pasar validación Pillow.
        caption:   Descripción breve opcional (ej. "Herida día 3").

    Returns:
        La instancia EvolutionImage recién creada.

    Raises:
        ValidationError: si tenant es None, la nota no pertenece al tenant,
                         se superó el límite de imágenes, o la imagen no pasa
                         la validación de seguridad.
    """
    if tenant is None:
        raise ValidationError(
            "Se requiere un tenant activo para subir imágenes de evolución."
        )

    # Defensa en profundidad: la nota de evolución debe ser del mismo tenant.
    if evolution.tenant_id != tenant.id:
        raise ValidationError(
            "La nota de evolución no pertenece a esta clínica."
        )

    # Límite de imágenes activas por nota.
    # Usamos el manager por defecto (objects) que ya excluye soft-deleted y
    # filtra por tenant (validado arriba). No es necesario all_objects ni
    # filtrar deleted_at manualmente.
    active_count = EvolutionImage.objects.filter(
        evolution=evolution,
    ).count()
    if active_count >= MAX_IMAGES_PER_EVOLUTION:
        raise ValidationError(
            f"La nota ya tiene el máximo de imágenes ({MAX_IMAGES_PER_EVOLUTION})."
        )

    # Barrera principal de seguridad: validar que el archivo SEA una imagen real.
    # Pillow verifica el contenido binario (no la extensión ni el Content-Type).
    # Rechaza SVG, bytes basura con extensión .jpg, archivos corruptos, y bombas
    # de descompresión (MEDIO-1).
    validate_evolution_image(image)

    evo_image = EvolutionImage.objects.create(
        tenant=tenant,
        created_by=user,
        evolution=evolution,
        image=image,
        caption=caption.strip(),
    )

    logger.info(
        "evolution_image_add: imagen %s agregada a evolución %s (tenant=%s)",
        evo_image.pk,
        evolution.pk,
        tenant.pk,
    )

    # MEDIO-3 — Bitácora NOM-024: registrar la subida de imagen.
    # resource_repr = UUID del registro, NUNCA el nombre del archivo (PII de ruta).
    # metadata incluye evolution_id y patient_id para correlación de auditoría,
    # SIN datos clínicos ni rutas de almacenamiento.
    audit_record(
        action=ActionType.EVOLUTION_IMAGE_ADD,
        resource_type="EvolutionImage",
        actor=user,
        tenant=tenant,
        resource_id=evo_image.id,
        resource_repr=str(evo_image.id),
        metadata={
            "evolution_id": str(evolution.id),
            "patient_id": str(evolution.patient_id),
        },
    )

    return evo_image


# ---------------------------------------------------------------------------
# MedicalHistoryQuestion CRUD (Fase 2)
# ---------------------------------------------------------------------------

#: Campos que no se pueden modificar mediante el service de update.
_MHQ_IMMUTABLE_FIELDS: frozenset[str] = frozenset(
    {"id", "tenant", "tenant_id", "created_at", "updated_at", "deleted_at", "is_active"}
)


@transaction.atomic
def medical_history_question_create(
    *,
    tenant: Tenant,
    user: Any,
    label: str,
    field_type: str,
    options: list[Any] | None = None,
    section: str = "",
    order: int = 0,
    is_required: bool = False,
) -> MedicalHistoryQuestion:
    """Crea una pregunta extra para la HC de la clínica.

    Valida:
    - Que tenant no sea None (defensa para llamadas desde Celery sin contexto HTTP).
    - Que field_type sea un valor válido de QuestionFieldType.
    - Que si field_type == 'select', options sea lista no vacía de strings.
    - Que si field_type != 'select', options sea [] (o None → se fuerza a []).

    Registra MEDICAL_HISTORY_QUESTION_CREATE en AuditLog.
    resource_repr = str(question.id) — NUNCA label (podría contener PII).

    Args:
        tenant:      Clínica del contexto activo. No puede ser None.
        user:        Usuario que crea la pregunta (para created_by/auditoría).
        label:       Texto de la pregunta (requerido, no vacío).
        field_type:  Tipo de campo (text|textarea|boolean|select|number|date).
        options:     Lista de opciones para type=select. None → [] para otros tipos.
        section:     Agrupador opcional.
        order:       Posición en el formulario (default=0).
        is_required: Si True, el frontend exige respuesta.

    Returns:
        La instancia MedicalHistoryQuestion recién creada.

    Raises:
        ValidationError: si tenant es None, label está vacío, field_type es inválido,
                         o las opciones no son coherentes con el tipo de campo.
    """
    if tenant is None:
        raise ValidationError(
            "Se requiere un tenant activo para crear una pregunta de HC."
        )

    label = label.strip()
    if not label:
        raise ValidationError("El texto de la pregunta no puede estar vacío.")

    # Validar field_type en whitelist.
    valid_types = [choice[0] for choice in QuestionFieldType.choices]
    if field_type not in valid_types:
        raise ValidationError(
            f"Tipo de campo inválido '{field_type}'. "
            f"Debe ser uno de: {', '.join(valid_types)}."
        )

    options_clean: list[Any] = options or []

    # Si field_type == 'select', options no puede ser vacío.
    if field_type == QuestionFieldType.SELECT and not options_clean:
        raise ValidationError(
            "Las opciones son requeridas para tipo 'select'."
        )

    # Si field_type != 'select', options debe ser vacío.
    if field_type != QuestionFieldType.SELECT and options_clean:
        raise ValidationError(
            "Las opciones solo aplican para tipo 'select'."
        )

    question = MedicalHistoryQuestion.objects.create(
        tenant=tenant,
        created_by=user,
        label=label,
        field_type=field_type,
        options=options_clean,
        section=section,
        order=order,
        is_required=is_required,
        is_active=True,
    )

    logger.info(
        "medical_history_question_create: pregunta %s creada (tenant=%s)",
        question.pk,
        tenant.pk,
    )

    audit_record(
        action=ActionType.MEDICAL_HISTORY_QUESTION_CREATE,
        resource_type="MedicalHistoryQuestion",
        actor=user,
        tenant=tenant,
        resource_id=question.id,
        resource_repr=str(question.id),
        metadata={"field_type": field_type, "order": order},
    )

    return question


@transaction.atomic
def medical_history_question_update(
    *,
    question: MedicalHistoryQuestion,
    user: Any,
    **fields: Any,
) -> MedicalHistoryQuestion:
    """Actualiza campos mutables de la pregunta extra de HC.

    Campos mutables: label, field_type, options, section, order, is_required.
    Campos inmutables (_MHQ_IMMUTABLE_FIELDS): id, tenant, tenant_id, created_at,
    updated_at, deleted_at, is_active.

    Para desactivar la pregunta usar medical_history_question_deactivate.

    Valida:
    - Que ningún campo de _MHQ_IMMUTABLE_FIELDS esté en `fields`.
    - Que field_type, si se actualiza, sea un valor válido.
    - Coherencia options/field_type si alguno de los dos cambia.

    Registra MEDICAL_HISTORY_QUESTION_UPDATE en AuditLog.

    Args:
        question: Instancia de MedicalHistoryQuestion a actualizar.
        user:     Usuario que realiza la actualización (para auditoría).
        **fields: Campos a actualizar (solo mutables).

    Returns:
        La instancia MedicalHistoryQuestion actualizada.

    Raises:
        ValidationError: si se intenta modificar campos inmutables o los datos
                         no son coherentes.
    """
    if question.tenant is None:
        raise ValidationError(
            "La pregunta no tiene un tenant asociado."
        )

    # Bloquear campos inmutables.
    bad = set(fields) & _MHQ_IMMUTABLE_FIELDS
    if bad:
        raise ValidationError(
            f"No se pueden modificar los campos: {', '.join(sorted(bad))}."
        )

    # Determinar el field_type resultante (el nuevo o el actual).
    new_field_type: str = fields.get("field_type", question.field_type)

    # Validar field_type si se cambia.
    if "field_type" in fields:
        valid_types = [choice[0] for choice in QuestionFieldType.choices]
        if new_field_type not in valid_types:
            raise ValidationError(
                f"Tipo de campo inválido '{new_field_type}'."
            )

    # Determinar options resultantes.
    new_options: list[Any] = fields.get("options", question.options)

    # Validar coherencia options/field_type.
    if new_field_type == QuestionFieldType.SELECT and not new_options:
        raise ValidationError(
            "Las opciones son requeridas para tipo 'select'."
        )
    if new_field_type != QuestionFieldType.SELECT and new_options:
        raise ValidationError(
            "Las opciones solo aplican para tipo 'select'."
        )

    # Normalizar label si se provee.
    if "label" in fields:
        fields["label"] = fields["label"].strip()
        if not fields["label"]:
            raise ValidationError("El texto de la pregunta no puede estar vacío.")

    for attr, value in fields.items():
        setattr(question, attr, value)

    question.save(
        update_fields=list(fields.keys()) + ["updated_at"],
    )

    logger.info(
        "medical_history_question_update: pregunta %s actualizada (tenant=%s)",
        question.pk,
        question.tenant_id,
    )

    audit_record(
        action=ActionType.MEDICAL_HISTORY_QUESTION_UPDATE,
        resource_type="MedicalHistoryQuestion",
        actor=user,
        tenant=question.tenant,
        resource_id=question.id,
        resource_repr=str(question.id),
        metadata={"updated_fields": sorted(fields.keys())},
    )

    return question


@transaction.atomic
def medical_history_question_deactivate(
    *,
    question: MedicalHistoryQuestion,
    user: Any,
) -> MedicalHistoryQuestion:
    """Baja lógica de una pregunta extra de HC (D-EC-5).

    NUNCA borra el registro físicamente. Pone is_active=False.
    Si ya estaba inactiva, la operación es idempotente (no error).

    Las respuestas históricas en custom_answers permanecen intactas.

    Registra MEDICAL_HISTORY_QUESTION_DEACTIVATE en AuditLog.

    Args:
        question: Instancia de MedicalHistoryQuestion a desactivar.
        user:     Usuario que ejecuta la acción (para auditoría).

    Returns:
        La instancia MedicalHistoryQuestion con is_active=False.

    Raises:
        ValidationError: si el tenant de la instancia es None.
    """
    if question.tenant is None:
        raise ValidationError(
            "La pregunta no tiene un tenant asociado. No se puede desactivar."
        )

    if question.is_active:
        question.is_active = False
        question.save(update_fields=["is_active", "updated_at"])

        logger.info(
            "medical_history_question_deactivate: pregunta %s desactivada por usuario %s",
            question.pk,
            getattr(user, "pk", None),
        )

        audit_record(
            action=ActionType.MEDICAL_HISTORY_QUESTION_DEACTIVATE,
            resource_type="MedicalHistoryQuestion",
            actor=user,
            tenant=question.tenant,
            resource_id=question.id,
            resource_repr=str(question.id),
            metadata={},
        )

    return question


@transaction.atomic
def evolution_image_remove(
    *,
    image: EvolutionImage,
    user: Any,
) -> EvolutionImage:
    """Baja lógica de una imagen de evolución (D-EC-5).

    NUNCA borra el registro físicamente. Pone deleted_at = ahora.
    Si ya estaba con deleted_at (ya dada de baja), la operación es idempotente.

    Registra EVOLUTION_IMAGE_REMOVE en AuditLog (NOM-024 — MEDIO-3).
    resource_repr = str(image.id) — NUNCA PII ni nombre de archivo.

    Args:
        image: Instancia de EvolutionImage a dar de baja.
        user:  Usuario que ejecuta la acción (para auditoría).

    Returns:
        La instancia EvolutionImage con deleted_at rellenado.

    Raises:
        ValidationError: si el tenant de la imagen es None.
    """
    from django.utils import timezone  # noqa: PLC0415

    if image.tenant is None:
        raise ValidationError(
            "La imagen no tiene un tenant asociado. No se puede dar de baja."
        )

    if image.deleted_at is None:
        image.deleted_at = timezone.now()
        image.save(update_fields=["deleted_at", "updated_at"])

        logger.info(
            "evolution_image_remove: imagen %s dada de baja por usuario %s",
            image.pk,
            getattr(user, "pk", None),
        )

        # MEDIO-3 — Bitácora NOM-024: registrar la baja lógica de imagen.
        # resource_repr = UUID del registro, NUNCA nombre de archivo ni ruta.
        # metadata incluye evolution_id y patient_id para correlación de auditoría.
        audit_record(
            action=ActionType.EVOLUTION_IMAGE_REMOVE,
            resource_type="EvolutionImage",
            actor=user,
            tenant=image.tenant,
            resource_id=image.id,
            resource_repr=str(image.id),
            metadata={
                "evolution_id": str(image.evolution_id),
                "patient_id": str(image.evolution.patient_id),
            },
        )

    return image
