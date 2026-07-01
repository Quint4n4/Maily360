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
from apps.tenancy.models import Tenant, TenantMembership

_DEMO_TENANT_SLUG = "demo"
_OWNER_EMAIL = "owner@demo.maily.mx"


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

        tenant = Tenant.objects.filter(slug=_DEMO_TENANT_SLUG).first()
        if tenant is None:
            raise CommandError(f"No se encontró el tenant demo '{_DEMO_TENANT_SLUG}'.")

        user_model = get_user_model()
        owner = user_model.objects.filter(email=_OWNER_EMAIL).first()
        if owner is None:
            raise CommandError(f"No se encontró el usuario dueño '{_OWNER_EMAIL}'.")

        # 3) Contraseña del dueño desde el entorno (no hardcodeada).
        owner.set_password(password)
        owner.is_active = True
        owner.save(update_fields=["password", "is_active"])
        self.stdout.write("  · contraseña del dueño actualizada desde DEMO_OWNER_PASSWORD.")

        membership = TenantMembership.objects.filter(
            tenant=tenant, user=owner, is_active=True
        ).first()
        if membership is None:
            raise CommandError("El dueño no tiene membresía activa en la clínica demo.")

        # 4) Perfil de médico con cédula (para emitir recetas — NOM-004 / Art. 83 LGS).
        set_current_tenant(tenant)
        doctor = Doctor.objects.filter(tenant=tenant, membership=membership).first()
        if doctor is None:
            doctor_create(
                tenant=tenant,
                user=owner,
                membership=membership,
                cedula_profesional=str(options["cedula"]),
                specialty="Medicina General",
            )
            self.stdout.write("  · perfil de médico creado (con cédula).")
        elif not (doctor.cedula_profesional or "").strip():
            doctor.cedula_profesional = str(options["cedula"])
            doctor.save(update_fields=["cedula_profesional"])
            self.stdout.write("  · cédula asignada al médico dueño.")

        self.stdout.write(
            self.style.SUCCESS(
                "\n✅ Entorno demo listo. Login del personal de la clínica:\n"
                f"   Usuario:  {_OWNER_EMAIL}\n"
                "   Password: (la que pusiste en DEMO_OWNER_PASSWORD)\n"
                "   Rol:      dueño (owner) + médico con cédula\n"
                "   Otros usuarios (misma contraseña de demo, ver seed_finanzas):\n"
                "     finance@demo.maily.mx · reception@demo.maily.mx · readonly@demo.maily.mx\n"
            )
        )
