"""
Factories compartidas para todos los tests de Maily Soft backend.

Usar estas factories en lugar de crear objetos directamente en los tests.
Factories específicas de un dominio pueden definirse en apps/<dominio>/tests/factories.py
e importarse aquí si son ampliamente reutilizadas.
"""

import datetime

import factory
from factory.django import DjangoModelFactory

from apps.authn.models import User
from apps.pacientes.models import Patient
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
