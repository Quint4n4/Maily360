"""
Factories compartidas para todos los tests de Maily Soft backend.

Usar estas factories en lugar de crear objetos directamente en los tests.
Factories específicas de un dominio pueden definirse en apps/<dominio>/tests/factories.py
e importarse aquí si son ampliamente reutilizadas.
"""

import datetime

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.agenda.models import AgendaBlock, AgendaItemNote, Appointment, AppointmentReminder, TenantAgendaConfig
from apps.audit.models import ActionType, AuditLog
from apps.authn.models import User
from apps.clinica.models import (
    ClinicSettings,
    ClinicTemplate,
    CredentialKind,
    DoctorCredential,
    DoctorUniversity,
    PatientCategory,
    TemplateKind,
)
from apps.expediente.models import (
    Addendum,
    Allergy,
    Diagnosis,
    DiagnosisKind,
    DiagnosisStatus,
    EvolutionNote,
    MedicalHistory,
    VitalSignsRecord,
)
from apps.notas.models import Note, NoteScope
from apps.recetas.models import (
    GlobalMedication,
    ItemKind,
    Medication,
    MedicationForm,
    Prescription,
    PrescriptionFormat,
    PrescriptionItem,
    PrescriptionStatus,
)
from apps.pacientes.models import Patient
from apps.personal.models import Consultorio, Doctor, DoctorSchedule
from apps.tenancy.models import Tenant, TenantMembership


class UserFactory(DjangoModelFactory):
    """Usuario base sin privilegios especiales."""

    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@maily.test")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    is_active = True
    is_staff = False
    is_platform_staff = False
    password = factory.PostGenerationMethodCall("set_password", "password-segura-123")


class PlatformStaffFactory(UserFactory):
    """Usuario del equipo interno de Maily Soft."""

    is_platform_staff = True
    is_staff = True
    platform_role = "engineering"


class TenantFactory(DjangoModelFactory):
    """Clínica (tenant) en estado activo por defecto."""

    class Meta:
        model = Tenant

    name = factory.Sequence(lambda n: f"Clínica {n}")
    slug = factory.Sequence(lambda n: f"clinica-{n}")
    status = "active"


class TenantMembershipFactory(DjangoModelFactory):
    """Membresía de un usuario en una clínica."""

    class Meta:
        model = TenantMembership

    user = factory.SubFactory(UserFactory)
    tenant = factory.SubFactory(TenantFactory)
    role = "doctor"
    is_active = True


class PatientFactory(DjangoModelFactory):
    """Paciente (expediente) en un tenant.

    El record_number se genera con un Sequence porque el servicio real usa
    PatientSequence (SELECT FOR UPDATE). En tests que ejercitan el service,
    llama directamente a patient_create() para generar el consecutivo real.
    Usa esta factory solo cuando necesitas un Patient ya persistido sin pasar
    por el service (p. ej., para tests de selectors o de aislamiento).
    """

    class Meta:
        model = Patient

    tenant = factory.SubFactory(TenantFactory)
    created_by = factory.SubFactory(UserFactory)
    first_name = factory.Faker("first_name", locale="es_MX")
    paternal_surname = factory.Faker("last_name", locale="es_MX")
    maternal_surname = factory.Faker("last_name", locale="es_MX")
    date_of_birth = factory.LazyFunction(lambda: datetime.date(1990, 1, 1))
    sex = "M"
    phone = factory.Sequence(lambda n: f"5512340{n:04d}")
    curp = ""
    email = ""
    record_number = factory.Sequence(lambda n: f"EXP-TEST-{n:05d}")
    notes = ""
    is_active = True


# ---------------------------------------------------------------------------
# Personal (Doctor, Consultorio, DoctorSchedule)
# ---------------------------------------------------------------------------


class DoctorFactory(DjangoModelFactory):
    """Perfil de médico dentro de un tenant.

    El tenant del Doctor y el de la TenantMembership DEBEN coincidir.
    Se usa LazyAttribute + post_generation para garantizar consistencia:
    - membership se crea primero apuntando a `tenant` del Doctor.
    - created_by se toma del usuario de la membership para evitar una
      query adicional.
    """

    class Meta:
        model = Doctor

    tenant = factory.SubFactory(TenantFactory)
    membership = factory.LazyAttribute(
        lambda obj: TenantMembershipFactory(tenant=obj.tenant, role="doctor")
    )
    created_by = factory.LazyAttribute(lambda obj: obj.membership.user)
    cedula_profesional = ""
    specialty = factory.Sequence(lambda n: f"Especialidad {n}")
    default_appointment_duration = 30
    bio_short = ""
    is_active = True


class ConsultorioFactory(DjangoModelFactory):
    """Consultorio (sala, box) dentro de un tenant."""

    class Meta:
        model = Consultorio

    tenant = factory.SubFactory(TenantFactory)
    created_by = factory.SubFactory(UserFactory)
    name = factory.Sequence(lambda n: f"Consultorio {n}")
    location = ""
    color_hex = ""
    is_active = True


class DoctorScheduleFactory(DjangoModelFactory):
    """Bloque de horario de un médico."""

    class Meta:
        model = DoctorSchedule

    tenant = factory.LazyAttribute(lambda obj: obj.doctor.tenant)
    created_by = factory.LazyAttribute(lambda obj: obj.doctor.created_by)
    doctor = factory.SubFactory(DoctorFactory)
    day_of_week = 0  # Lunes
    start_time = datetime.time(9, 0)
    end_time = datetime.time(13, 0)
    consultorio = None
    valid_from = None
    valid_until = None
    is_active = True


# ---------------------------------------------------------------------------
# Agenda (TenantAgendaConfig, Appointment)
# ---------------------------------------------------------------------------


class TenantAgendaConfigFactory(DjangoModelFactory):
    """Configuración de agenda de una clínica.

    Un único registro por tenant — la constraint UniqueConstraint lo garantiza.
    En la mayoría de los tests es más práctico obtener la config vía el selector
    agenda_config_get (get_or_create) que crear explícitamente con esta factory.
    Úsala cuando necesitas controlar los valores (p. ej. duración default distinta).
    """

    class Meta:
        model = TenantAgendaConfig

    tenant = factory.SubFactory(TenantFactory)
    created_by = None
    record_number_format = "EXP-{year}-{seq:05d}"
    record_number_reset_yearly = False
    default_appointment_duration = 30
    reminder_offsets_minutes = factory.LazyFunction(lambda: [1440])
    reminders_enabled = True


class AppointmentFactory(DjangoModelFactory):
    """Cita médica dentro de un tenant.

    RESTRICCIONES IMPORTANTES:
      - patient, doctor y consultorio deben pertenecer al MISMO tenant.
        Usa `tenant` explícito o deja que LazyAttribute lo resuelva a partir
        del doctor (que ya trae su propio tenant).
      - Por el exclusion constraint anti-empalme, cada AppointmentFactory que
        comparta el mismo doctor/consultorio DEBE tener horarios que NO se solapen.
        Usa starts_at distinto o un Sequence basado en horas.

    Estrategia de tenant:
      El doctor trae su propio tenant. Patient y Consultorio se crean apuntando
      a ese mismo tenant mediante LazyAttribute para garantizar consistencia.

    OJO: en tests que ejercitan appointment_create() directamente no se necesita
    esta factory; úsala cuando necesitas citas ya persistidas (selectors, APIs).
    """

    class Meta:
        model = Appointment

    # El doctor define el tenant raíz de la cita
    doctor = factory.SubFactory(DoctorFactory)
    tenant = factory.LazyAttribute(lambda obj: obj.doctor.tenant)
    created_by = factory.LazyAttribute(lambda obj: obj.doctor.created_by)

    # Paciente del MISMO tenant que el doctor
    patient = factory.LazyAttribute(
        lambda obj: PatientFactory(tenant=obj.doctor.tenant)
    )

    # Consultorio del MISMO tenant (opcional — None para telemedicina)
    consultorio = factory.LazyAttribute(
        lambda obj: ConsultorioFactory(tenant=obj.doctor.tenant)
    )

    # Horario: en el futuro, separado 1 hora por índice para evitar solapamiento
    # entre citas del mismo doctor creadas en el mismo test.
    # Si necesitas horarios distintos, pasa starts_at explícito.
    starts_at = factory.Sequence(
        lambda n: datetime.datetime(2030, 1, 1, 8, 0, 0, tzinfo=datetime.timezone.utc)
        + datetime.timedelta(hours=n)
    )
    ends_at = factory.LazyAttribute(
        lambda obj: obj.starts_at + datetime.timedelta(minutes=30)
    )
    status = Appointment.Status.SCHEDULED
    reason = factory.Sequence(lambda n: f"Consulta de seguimiento #{n}")
    specialty = ""
    notes = ""


class AppointmentReminderFactory(DjangoModelFactory):
    """Recordatorio de cita medica.

    tenant y created_by se heredan de la cita (appointment) para garantizar
    consistencia multi-tenant. El scheduled_at por defecto es 24h antes del
    starts_at de la cita (offset estandar de la plataforma).

    Restricciones:
      - El appointment ya debe existir en BD antes de llamar a esta factory.
      - El tenant del reminder DEBE coincidir con el del appointment.
    """

    class Meta:
        model = AppointmentReminder

    appointment = factory.SubFactory(AppointmentFactory)
    tenant = factory.LazyAttribute(lambda obj: obj.appointment.tenant)
    created_by = factory.LazyAttribute(lambda obj: obj.appointment.created_by)
    channel = AppointmentReminder.Channel.WHATSAPP
    scheduled_at = factory.LazyAttribute(
        lambda obj: obj.appointment.starts_at - datetime.timedelta(hours=24)
    )
    sent_at = None
    status = AppointmentReminder.ReminderStatus.PENDING
    message_preview = ""
    error_detail = ""
    external_message_id = ""


# ---------------------------------------------------------------------------
# Audit (AuditLog)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Notas (Note)
# ---------------------------------------------------------------------------


class NoteFactory(DjangoModelFactory):
    """Nota o tarea personal dentro de un tenant.

    Por defecto crea notas personales (scope=personal).
    Para notas globales pasa scope=NoteScope.ALL o scope=NoteScope.ROLE con
    target_role, y asegúrate de que el author sea OWNER del tenant.
    """

    class Meta:
        model = Note

    tenant = factory.SubFactory(TenantFactory)
    author = factory.SubFactory(UserFactory)
    created_by = factory.LazyAttribute(lambda obj: obj.author)
    title = factory.Sequence(lambda n: f"Nota {n}")
    body = ""
    scope = NoteScope.PERSONAL
    target_role = ""
    is_task = False
    done = False
    remind_at = None
    pinned = False


# ---------------------------------------------------------------------------
# Agenda — AgendaBlock y AgendaItemNote
# ---------------------------------------------------------------------------


class AgendaBlockFactory(DjangoModelFactory):
    """Evento de agenda (reunión o bloqueo) dentro de un tenant."""

    class Meta:
        model = AgendaBlock

    tenant = factory.SubFactory(TenantFactory)
    created_by = factory.SubFactory(UserFactory)
    kind = AgendaBlock.Kind.BLOCK
    title = factory.Sequence(lambda n: f"Bloqueo {n}")
    doctor = None
    consultorio = None
    starts_at = factory.Sequence(
        lambda n: datetime.datetime(2030, 6, 1, 8, 0, 0, tzinfo=datetime.timezone.utc)
        + datetime.timedelta(hours=n * 2)
    )
    ends_at = factory.LazyAttribute(
        lambda obj: obj.starts_at + datetime.timedelta(hours=1)
    )
    all_day = False
    notes = ""


class AgendaItemNoteFactory(DjangoModelFactory):
    """Nota colaborativa pegada a una cita o evento de agenda."""

    class Meta:
        model = AgendaItemNote

    tenant = factory.LazyAttribute(lambda obj: obj.appointment.tenant if obj.appointment else obj.agenda_block.tenant)
    created_by = factory.SubFactory(UserFactory)
    author = factory.LazyAttribute(lambda obj: obj.created_by)
    appointment = factory.SubFactory(AppointmentFactory)
    agenda_block = None
    body = factory.Sequence(lambda n: f"Nota colaborativa #{n}")


# ---------------------------------------------------------------------------
# Expediente (Allergy, MedicalHistory)
# ---------------------------------------------------------------------------


class AllergyFactory(DjangoModelFactory):
    """Alergia de un paciente.

    El tenant de la alergia DEBE coincidir con el del paciente.
    Por defecto crea alergias vigentes (is_active=True).
    """

    class Meta:
        model = Allergy

    tenant = factory.SubFactory(TenantFactory)
    patient = factory.LazyAttribute(lambda obj: PatientFactory(tenant=obj.tenant))
    created_by = factory.SubFactory(UserFactory)
    substance = factory.Sequence(lambda n: f"Sustancia {n}")
    reaction = ""
    severity = ""
    is_active = True


class MedicalHistoryFactory(DjangoModelFactory):
    """Historia clínica formal de un paciente.

    El tenant de la HC DEBE coincidir con el del paciente.
    Por defecto crea una HC con todos los bloques vacíos (HC incompleta válida).
    Úsala cuando necesitas una HC ya persistida sin pasar por el service
    (p. ej., para tests de selectors o de aislamiento).
    """

    class Meta:
        model = MedicalHistory

    tenant = factory.SubFactory(TenantFactory)
    patient = factory.LazyAttribute(lambda obj: PatientFactory(tenant=obj.tenant))
    created_by = factory.SubFactory(UserFactory)
    heredo_familiares = factory.LazyFunction(dict)
    personales_patologicos = factory.LazyFunction(dict)
    no_patologicos = factory.LazyFunction(dict)
    habitos_alimenticios = factory.LazyFunction(dict)
    gineco_obstetricos = factory.LazyFunction(dict)
    exploracion_fisica_basal = factory.LazyFunction(dict)
    antecedentes_importancia = ""
    padecimiento_actual = ""
    tratamientos_actuales = ""
    prioridad_analisis = ""


class VitalSignsRecordFactory(DjangoModelFactory):
    """Toma de signos vitales de un paciente (A3 — Append-only).

    El tenant de la toma DEBE coincidir con el del paciente.
    Por defecto crea una toma con measured_at en el pasado (hoy) y sin valores
    numéricos (toma vacía válida). Pasar los campos numéricos explícitamente
    cuando el test los necesite.

    Úsala cuando necesitas tomas ya persistidas sin pasar por el service
    (p. ej., para tests de selectors, series o de aislamiento).
    """

    class Meta:
        model = VitalSignsRecord

    tenant = factory.SubFactory(TenantFactory)
    patient = factory.LazyAttribute(lambda obj: PatientFactory(tenant=obj.tenant))
    created_by = factory.SubFactory(UserFactory)
    appointment = None
    measured_at = factory.LazyFunction(timezone.now)
    weight_kg = None
    height_m = None
    heart_rate = None
    resp_rate = None
    systolic = None
    diastolic = None
    temperature_c = None
    oxygen_saturation = None
    glucose = None
    extra_params = factory.LazyFunction(dict)
    notes = ""


class AuditLogFactory(DjangoModelFactory):
    """Registro inmutable de la bitácora (AuditLog).

    Usa all_objects.create() a través del método _create() para bypassar el
    TenantManager, que requiere tenant no-None. AuditLog puede tener tenant=None
    (eventos globales como LOGIN_FAILED), por lo que usamos all_objects igual
    que hace audit_record() en producción.

    Importante: no llames .save() sobre un AuditLog ya persistido — el modelo
    lanzará RuntimeError (diseño append-only). Esta factory solo crea, nunca edita.
    """

    class Meta:
        model = AuditLog
        # factory_boy necesita saber que queremos usar save() normal.
        # El override de save() en AuditLog verifica si el pk ya existe;
        # al crear uno nuevo el pk aún no está en BD → INSERT → OK.
        exclude: list[str] = []

    tenant = factory.SubFactory(TenantFactory)
    actor = factory.SubFactory(UserFactory)
    actor_role = "owner"
    action = ActionType.PATIENT_READ
    resource_type = "Patient"
    resource_id = factory.LazyFunction(
        lambda: __import__("uuid").uuid4()
    )
    resource_repr = factory.Sequence(lambda n: f"Paciente #{n}")
    description = ""
    ip_address = None
    user_agent = ""
    request_id = ""
    metadata = factory.LazyFunction(dict)


# ---------------------------------------------------------------------------
# Expediente A4 — EvolutionNote, Addendum, Diagnosis
# ---------------------------------------------------------------------------


class EvolutionNoteFactory(DjangoModelFactory):
    """Nota de evolución inmutable (A4).

    El tenant, patient, appointment y doctor DEBEN pertenecer al mismo tenant.
    Por defecto la cita se crea en estado ATTENDED para cumplir D-EC-2.

    IMPORTANTE: En tests que ejercitan evolution_note_create() directamente
    no se necesita esta factory. Úsala para notas ya persistidas (selectors, API).
    """

    class Meta:
        model = EvolutionNote

    # El doctor define el tenant raíz de la nota.
    doctor = factory.SubFactory(DoctorFactory)
    tenant = factory.LazyAttribute(lambda obj: obj.doctor.tenant)
    created_by = factory.LazyAttribute(lambda obj: obj.doctor.created_by)

    # Paciente del MISMO tenant que el doctor.
    patient = factory.LazyAttribute(
        lambda obj: PatientFactory(tenant=obj.doctor.tenant)
    )

    # Cita del mismo tenant, paciente y doctor, en estado ATTENDED (D-EC-2).
    appointment = factory.LazyAttribute(
        lambda obj: AppointmentFactory(
            tenant=obj.doctor.tenant,
            patient=obj.patient,
            doctor=obj.doctor,
            status=Appointment.Status.ATTENDED,
        )
    )
    vital_signs = None

    # Campos clínicos vacíos por defecto (válidos — todos opcionales).
    antecedentes = ""
    interrogatorio = ""
    estudios = ""
    diagnosticos_texto = ""
    tratamiento = ""
    plan_recomendaciones = ""
    indicaciones_enfermeria = ""
    exploracion_fisica = factory.LazyFunction(dict)
    is_locked = True


class AddendumFactory(DjangoModelFactory):
    """Addendum sobre una nota de evolución (A4 — Append-only)."""

    class Meta:
        model = Addendum

    evolution = factory.SubFactory(EvolutionNoteFactory)
    tenant = factory.LazyAttribute(lambda obj: obj.evolution.tenant)
    created_by = factory.LazyAttribute(lambda obj: obj.evolution.created_by)
    author = factory.LazyAttribute(lambda obj: obj.evolution.created_by)
    body = factory.Sequence(lambda n: f"Addendum de aclaración #{n}.")


class DiagnosisFactory(DjangoModelFactory):
    """Diagnóstico clínico de un paciente (A4).

    Por defecto crea un diagnóstico presuntivo activo sin vinculación a evolución.
    """

    class Meta:
        model = Diagnosis

    tenant = factory.SubFactory(TenantFactory)
    patient = factory.LazyAttribute(lambda obj: PatientFactory(tenant=obj.tenant))
    created_by = factory.SubFactory(UserFactory)
    evolution = None
    cie_code = ""
    description = factory.Sequence(lambda n: f"Diagnóstico de prueba #{n}")
    kind = DiagnosisKind.PRESUNTIVO
    status = DiagnosisStatus.ACTIVO


# ---------------------------------------------------------------------------
# Clinica (ClinicSettings, ClinicTemplate, PatientCategory, DoctorUniversity)
# ---------------------------------------------------------------------------


class ClinicSettingsFactory(DjangoModelFactory):
    """Configuración de clínica (ClinicSettings).

    Por defecto crea una config sin imágenes y sin datos de contacto.
    Pasar explícitamente los campos que el test necesite.
    """

    class Meta:
        model = ClinicSettings

    tenant = factory.SubFactory(TenantFactory)
    created_by = factory.SubFactory(UserFactory)
    address = ""
    address_2 = ""
    phone = ""
    mobile = ""
    email = ""
    website = ""
    facebook = ""
    instagram = ""
    youtube = ""
    letterhead_full_spaces = 0
    letterhead_half_spaces = 0


class ClinicTemplateFactory(DjangoModelFactory):
    """Plantilla clínica (ClinicTemplate).

    Por defecto crea una plantilla de tipo 'recipe' activa.
    """

    class Meta:
        model = ClinicTemplate

    tenant = factory.SubFactory(TenantFactory)
    created_by = factory.SubFactory(UserFactory)
    kind = TemplateKind.RECIPE
    name = factory.Sequence(lambda n: f"Plantilla {n}")
    body = factory.Sequence(lambda n: f"Cuerpo de plantilla {n}.")
    group = ""
    is_active = True


class PatientCategoryFactory(DjangoModelFactory):
    """Categoría de paciente (PatientCategory).

    Por defecto crea una categoría activa.
    """

    class Meta:
        model = PatientCategory

    tenant = factory.SubFactory(TenantFactory)
    created_by = factory.SubFactory(UserFactory)
    name = factory.Sequence(lambda n: f"Categoría {n}")
    is_active = True


# ---------------------------------------------------------------------------
# Recetas — GlobalMedication y Medication (B1.1)
# ---------------------------------------------------------------------------


class GlobalMedicationFactory(DjangoModelFactory):
    """Medicamento del catálogo global (sin tenant).

    Por defecto crea una tableta activa. COFEPRIS F2: kind=medicamento, controlled_group=none.
    """

    class Meta:
        model = GlobalMedication

    generic_name = factory.Sequence(lambda n: f"Medicamento Global {n}")
    commercial_name = ""
    form = MedicationForm.TABLETA
    concentration = factory.Sequence(lambda n: f"{n * 100 + 100} mg")
    presentation = ""
    is_active = True
    kind = ItemKind.MEDICAMENTO
    controlled_group = "none"


class MedicationFactory(DjangoModelFactory):
    """Medicamento custom de una clínica (con tenant).

    Por defecto crea una tableta activa. COFEPRIS F2: kind=medicamento, controlled_group=none.
    """

    class Meta:
        model = Medication

    tenant = factory.SubFactory(TenantFactory)
    created_by = factory.SubFactory(UserFactory)
    generic_name = factory.Sequence(lambda n: f"Medicamento Custom {n}")
    commercial_name = ""
    form = MedicationForm.TABLETA
    concentration = factory.Sequence(lambda n: f"{n * 50 + 50} mg")
    presentation = ""
    is_active = True
    kind = ItemKind.MEDICAMENTO
    controlled_group = "none"


class PrescriptionFactory(DjangoModelFactory):
    """Receta médica activa (con folio y doctor del tenant).

    NOTA: el folio no es consecutivo automáticamente aquí porque la factory
    no usa SELECT FOR UPDATE. Para tests que ejercitan el servicio real
    de folio consecutivo, usa directamente prescription_create().
    Esta factory es solo para tests de selectors, APIs y permisos donde
    el folio exacto no importa.
    """

    class Meta:
        model = Prescription

    tenant = factory.SubFactory(TenantFactory)
    created_by = factory.LazyAttribute(lambda obj: obj.doctor.membership.user)
    patient = factory.LazyAttribute(lambda obj: PatientFactory(tenant=obj.tenant))
    doctor = factory.LazyAttribute(
        lambda obj: DoctorFactory(tenant=obj.tenant)
    )
    folio = factory.Sequence(lambda n: n + 1)
    status = PrescriptionStatus.ACTIVE
    diagnosis = ""
    recommendations = ""
    vitals_snapshot = None
    cancelled_at = None
    cancellation_reason = ""
    # F6: medicamentos controlados (default: no controlada)
    controlled_folio = ""
    valid_until = None


class PrescriptionItemFactory(DjangoModelFactory):
    """Renglón de tratamiento de una receta.

    COFEPRIS F2: dose/frequency/route/duration son requeridos para kind=medicamento.
    La factory los rellena con valores válidos por defecto para no romper tests
    que no los pasaban explícitamente. Para suero/terapia pueden quedar vacíos.
    """

    class Meta:
        model = PrescriptionItem

    tenant = factory.LazyAttribute(lambda obj: obj.prescription.tenant)
    created_by = factory.LazyAttribute(lambda obj: obj.prescription.created_by)
    prescription = factory.SubFactory(PrescriptionFactory)
    order = factory.Sequence(lambda n: n + 1)
    kind = ItemKind.MEDICAMENTO
    medication_name = factory.Sequence(lambda n: f"Medicamento Test {n}")
    medication_presentation = ""
    medication_form = ""
    medication_concentration = ""
    # COFEPRIS F2: campos estructurados (rellenos con valores válidos por defecto)
    dose = "1 tableta"
    frequency = "cada 8 horas"
    route = "oral"
    duration = "7 días"
    # Nota adicional (antes campo obligatorio — ahora opcional)
    indication = ""
    quantity = ""
    # F6: snapshot del grupo COFEPRIS (default: no controlado)
    controlled_group = "none"


class PrescriptionFormatFactory(DjangoModelFactory):
    """Formato de receta configurable por clínica (F3).

    Por defecto crea un formato estándar activo (no default, no por médico).
    Pasar is_default=True para el formato default del tenant.
    Pasar doctor= y is_authorized=True para el formato personal del médico.
    """

    class Meta:
        model = PrescriptionFormat

    tenant = factory.SubFactory(TenantFactory)
    created_by = factory.SubFactory(UserFactory)
    name = factory.Sequence(lambda n: f"Formato Test {n}")
    base_layout = PrescriptionFormat.BaseLayout.DIGITAL
    accent_color = "#9A7B1E"
    font = PrescriptionFormat.FontChoice.HELVETICA
    sections = factory.LazyFunction(dict)
    letterhead_mode = PrescriptionFormat.LetterheadMode.DIGITAL
    is_default = False
    doctor = None
    is_authorized = False
    is_active = True


class DoctorUniversityFactory(DjangoModelFactory):
    """Logo de universidad de un médico (DoctorUniversity).

    NOTA: el campo logo es obligatorio (ImageField); en tests que no necesiten
    una imagen real, usa SimpleUploadedFile o pasa un mock. Esta factory
    no setea logo por defecto — pásalo explícitamente en el test.
    """

    class Meta:
        model = DoctorUniversity
        exclude = ["_doctor"]  # evitar que factory_boy lo trate como campo del modelo

    tenant = factory.SubFactory(TenantFactory)
    created_by = factory.SubFactory(UserFactory)
    doctor = factory.SubFactory(DoctorFactory)
    name = factory.Sequence(lambda n: f"Universidad {n}")


class DoctorCredentialFactory(DjangoModelFactory):
    """Credencial académica de un médico (DoctorCredential — COFEPRIS F2).

    Por defecto crea una cédula profesional activa con datos genéricos.
    Pasar `kind`, `title`, `institution` o `credential_number` explícitamente
    en el test si se necesitan valores específicos.
    """

    class Meta:
        model = DoctorCredential

    tenant = factory.SubFactory(TenantFactory)
    created_by = factory.SubFactory(UserFactory)
    doctor = factory.SubFactory(DoctorFactory)
    title = factory.Sequence(lambda n: f"Médico Cirujano {n}")
    institution = factory.Sequence(lambda n: f"Universidad Nacional {n}")
    credential_number = factory.Sequence(lambda n: f"{1000000 + n}")
    kind = CredentialKind.PROFESIONAL
    order = 0
    is_active = True
    # Por defecto validada (visible en la receta). Pasar validation_status="pendiente"
    # explícitamente para probar el flujo de validación.
    validation_status = "validada"
