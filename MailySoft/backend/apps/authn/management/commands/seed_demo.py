"""Prepara un entorno DEMO listo para un piloto de clínica (idempotente).

Orquesta los seeds existentes y deja todo listo para que el personal de una
clínica entre a probar el sistema:

  - clínica demo (tenant "demo") + usuarios (owner / finance / reception / readonly),
  - pacientes de ejemplo + datos de finanzas,
  - catálogo de medicamentos (para recetas),
  - contraseña del dueño tomada de la variable de entorno DEMO_OWNER_PASSWORD
    (NUNCA hardcodeada), para no exponer una credencial en el código,
  - perfil de médico con cédula para el dueño (requisito para emitir recetas).

Uso (local o Railway):
    DEMO_OWNER_PASSWORD='UnaClaveFuerte123!' python manage.py seed_demo

Es idempotente: se puede correr varias veces sin duplicar datos.
"""

import os
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from apps.core.tenant_context import set_current_tenant
from apps.personal.models import Doctor
from apps.personal.services import doctor_create
from apps.tenancy.models import TenantMembership

_OWNER_EMAIL = "owner@demo.maily.mx"
_DOCTOR_EMAIL = "doctor@demo.maily.mx"


class Command(BaseCommand):
    help = "Prepara el entorno demo para un piloto de clínica (idempotente)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--cedula",
            default="1234567",
            help="Cédula profesional (demo) para el médico dueño.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        password = os.environ.get("DEMO_OWNER_PASSWORD", "").strip()
        if not password:
            raise CommandError(
                "Falta la variable DEMO_OWNER_PASSWORD. Ejemplo:\n"
                "  DEMO_OWNER_PASSWORD='ClaveFuerte123!' python manage.py seed_demo"
            )

        # 1) Clínica demo + usuarios + pacientes + finanzas.
        self.stdout.write("→ seed_finanzas (clínica demo + usuarios + pacientes)…")
        call_command("seed_finanzas")

        # 2) Catálogo de medicamentos (para poder emitir recetas).
        self.stdout.write("→ seed_medicamentos (catálogo de medicamentos)…")
        call_command("seed_medicamentos")

        user_model = get_user_model()
        owner = user_model.objects.filter(email=_OWNER_EMAIL).first()
        if owner is None:
            raise CommandError(
                f"No se encontró el usuario dueño '{_OWNER_EMAIL}' (¿corrió seed_finanzas?)."
            )

        # El tenant es el de la membresía del dueño. seed_finanzas puede REUSAR un
        # tenant existente en vez de crear el slug 'demo', así que no lo buscamos por slug.
        owner_membership = (
            TenantMembership.objects.filter(user=owner, is_active=True)
            .select_related("tenant")
            .first()
        )
        if owner_membership is None:
            raise CommandError("El dueño no tiene membresía activa en ninguna clínica.")
        tenant = owner_membership.tenant

        # 3) Contraseña del dueño desde el entorno (no hardcodeada).
        # must_change_password=False explícito: es un usuario demo/piloto con
        # contraseña conocida y documentada, NO una contraseña temporal generada
        # por plataforma — forzar el cambio rompería el demo de Railway.
        owner.set_password(password)
        owner.is_active = True
        owner.must_change_password = False
        owner.save(update_fields=["password", "is_active", "must_change_password"])
        self.stdout.write("  · contraseña del dueño actualizada desde DEMO_OWNER_PASSWORD.")

        # 4) Usuario MÉDICO dedicado con cédula (para emitir recetas). El dueño
        #    tiene rol "owner" y doctor_create exige rol "doctor", así que el
        #    médico es un usuario aparte con su propia membresía de rol doctor.
        doctor_user, _ = user_model.objects.get_or_create(
            email=_DOCTOR_EMAIL,
            defaults={
                "first_name": "Doctora",
                "last_name": "Demo",
                "is_active": True,
                "must_change_password": False,
            },
        )
        doctor_user.is_active = True
        doctor_user.must_change_password = False
        doctor_user.set_password(password)
        doctor_user.save(update_fields=["password", "is_active", "must_change_password"])

        doctor_membership, _ = TenantMembership.objects.get_or_create(
            user=doctor_user,
            tenant=tenant,
            defaults={"role": TenantMembership.Role.DOCTOR, "is_active": True},
        )
        if (
            doctor_membership.role != TenantMembership.Role.DOCTOR
            or not doctor_membership.is_active
        ):
            doctor_membership.role = TenantMembership.Role.DOCTOR
            doctor_membership.is_active = True
            doctor_membership.save(update_fields=["role", "is_active"])

        set_current_tenant(tenant)
        doctor = Doctor.objects.filter(tenant=tenant, membership=doctor_membership).first()
        if doctor is None:
            doctor_create(
                tenant=tenant,
                user=doctor_user,
                membership=doctor_membership,
                cedula_profesional=str(options["cedula"]),
                specialty="Medicina General",
            )
            self.stdout.write("  · usuario médico creado (con cédula).")
        elif not (doctor.cedula_profesional or "").strip():
            doctor.cedula_profesional = str(options["cedula"])
            doctor.save(update_fields=["cedula_profesional"])
            self.stdout.write("  · cédula asignada al médico.")

        self.stdout.write(
            self.style.SUCCESS(
                "\n✅ Entorno demo listo. Logins del personal (misma contraseña):\n"
                f"   Dueño / admin:  {_OWNER_EMAIL}\n"
                f"   Médico:         {_DOCTOR_EMAIL}\n"
                "   Password:       (la que pusiste en DEMO_OWNER_PASSWORD)\n"
                "   Otros (contraseña Demo1234! de seed_finanzas):\n"
                "     finance@demo.maily.mx · reception@demo.maily.mx · readonly@demo.maily.mx\n"
            )
        )
