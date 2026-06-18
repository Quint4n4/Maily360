"""
Factories compartidas para todos los tests de Maily Soft backend.

Usar estas factories en lugar de crear objetos directamente en los tests.
Factories específicas de un dominio pueden definirse en apps/<dominio>/tests/factories.py
e importarse aquí si son ampliamente reutilizadas.
"""

import datetime
from decimal import Decimal

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.agenda.models import AgendaBlock, AgendaItemNote, Appointment, AppointmentReminder, TenantAgendaConfig
from apps.audit.models import ActionType, AuditLog
from apps.authn.models import User
<<<<<<< Updated upstream
from apps.notas.models import Note, NoteScope
=======
<<<<<<< HEAD
from apps.finanzas.models import (
    CfdiDocument,
    Charge,
    ClinicFiscalConfig,
    Payment,
    Quote,
    QuoteItem,
    ServiceConcept,
)
=======
from apps.notas.models import Note, NoteScope
>>>>>>> 9f3cd4149619be4d5c604a117d939f7904aad547
>>>>>>> Stashed changes
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
# Finanzas (ServiceConcept, Quote, Charge, Payment, ClinicFiscalConfig, CFDI)
# ---------------------------------------------------------------------------


class ServiceConceptFactory(DjangoModelFactory):
    """Concepto cobrable del catálogo de un tenant."""

    class Meta:
        model = ServiceConcept

    tenant = factory.SubFactory(TenantFactory)
    created_by = factory.SubFactory(UserFactory)
    name = factory.Sequence(lambda n: f"Consulta {n}")
    description = ""
    base_price = factory.LazyFunction(lambda: Decimal("500.00"))
    sat_product_key = "85121600"
    sat_unit_key = "E48"
    is_active = True


class ClinicFiscalConfigFactory(DjangoModelFactory):
    """Configuración fiscal del emisor (uno por tenant)."""

    class Meta:
        model = ClinicFiscalConfig

    tenant = factory.SubFactory(TenantFactory)
    created_by = None
    rfc = "XAXX010101000"
    legal_name = "Clínica Demo SA de CV"
    tax_regime = "601"
    postal_code = "06000"
    series = "A"
    next_folio = 1


class QuoteFactory(DjangoModelFactory):
    """Cotización (en borrador por defecto). El paciente comparte tenant."""

    class Meta:
        model = Quote

    tenant = factory.SubFactory(TenantFactory)
    created_by = factory.LazyAttribute(lambda obj: None)
    patient = factory.LazyAttribute(lambda obj: PatientFactory(tenant=obj.tenant))
    status = Quote.Status.DRAFT
    valid_until = None
    notes = ""
    subtotal = factory.LazyFunction(lambda: Decimal("0.00"))
    discount_total = factory.LazyFunction(lambda: Decimal("0.00"))
    total = factory.LazyFunction(lambda: Decimal("0.00"))


class QuoteItemFactory(DjangoModelFactory):
    """Línea de cotización. Hereda tenant de la cotización."""

    class Meta:
        model = QuoteItem

    quote = factory.SubFactory(QuoteFactory)
    tenant = factory.LazyAttribute(lambda obj: obj.quote.tenant)
    created_by = None
    concept = None
    description = factory.Sequence(lambda n: f"Servicio {n}")
    quantity = factory.LazyFunction(lambda: Decimal("1.00"))
    unit_price = factory.LazyFunction(lambda: Decimal("500.00"))
    discount = factory.LazyFunction(lambda: Decimal("0.00"))
    line_total = factory.LazyFunction(lambda: Decimal("500.00"))


class ChargeFactory(DjangoModelFactory):
    """Cargo / cuenta por cobrar. El paciente comparte tenant."""

    class Meta:
        model = Charge

    tenant = factory.SubFactory(TenantFactory)
    created_by = None
    patient = factory.LazyAttribute(lambda obj: PatientFactory(tenant=obj.tenant))
    concept = None
    description = factory.Sequence(lambda n: f"Cargo {n}")
    appointment = None
    quote = None
    amount = factory.LazyFunction(lambda: Decimal("500.00"))
    amount_paid = factory.LazyFunction(lambda: Decimal("0.00"))
    status = Charge.Status.PENDING
    issued_at = factory.LazyFunction(timezone.now)


class PaymentFactory(DjangoModelFactory):
    """Pago recibido de un paciente. El paciente comparte tenant."""

    class Meta:
        model = Payment

    tenant = factory.SubFactory(TenantFactory)
    created_by = None
    patient = factory.LazyAttribute(lambda obj: PatientFactory(tenant=obj.tenant))
    amount = factory.LazyFunction(lambda: Decimal("500.00"))
    method = Payment.Method.CASH
    reference = ""
    received_at = factory.LazyFunction(timezone.now)
    notes = ""


class CfdiDocumentFactory(DjangoModelFactory):
    """Comprobante CFDI (en borrador por defecto). El paciente comparte tenant."""

    class Meta:
        model = CfdiDocument

    tenant = factory.SubFactory(TenantFactory)
    created_by = None
    payment = None
    patient = factory.LazyAttribute(lambda obj: PatientFactory(tenant=obj.tenant))
    status = CfdiDocument.Status.DRAFT
    series = "A"
    folio = 1
    uuid_sat = ""
    receptor_rfc = "XAXX010101000"
    receptor_name = "Público en general"
    receptor_tax_regime = "616"
    receptor_postal_code = "06000"
    cfdi_use = "G03"
    payment_form = "01"
    payment_method = "PUE"
    subtotal = factory.LazyFunction(lambda: Decimal("500.00"))
    total = factory.LazyFunction(lambda: Decimal("500.00"))
