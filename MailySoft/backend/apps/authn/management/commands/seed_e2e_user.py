"""Crea un usuario de pruebas E2E (Playwright) con contraseña conocida.

SOLO para desarrollo / E2E local. Idempotente. NO usar en producción.

Credenciales: e2e@maily.local / Demo1234!  (rol owner en el tenant clinica-demo).
Las pruebas de Playwright (web-soft/e2e/) usan estas credenciales para el flujo de
login. No toca usuarios reales: crea/actualiza solo este usuario dedicado.
"""

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.tenancy.models import Tenant, TenantMembership

E2E_EMAIL = "e2e@maily.local"
E2E_PASSWORD = "Demo1234!"  # noqa: S105 — credencial de prueba local, no es secreto real
E2E_TENANT_SLUG = "clinica-demo"


class Command(BaseCommand):
    help = "Crea el usuario E2E (Playwright) con contraseña conocida. Solo dev/local."

    def handle(self, *args: Any, **options: Any) -> None:
        user_model = get_user_model()

        tenant = Tenant.objects.filter(slug=E2E_TENANT_SLUG).first()
        if tenant is None:
            self.stderr.write(
                self.style.ERROR(
                    f"No existe el tenant '{E2E_TENANT_SLUG}'. "
                    "Corre antes: python manage.py seed_finanzas"
                )
            )
            return

        user, _created = user_model.objects.get_or_create(
            email=E2E_EMAIL,
            defaults={"first_name": "E2E", "last_name": "Test", "is_active": True},
        )
        user.is_active = True
        user.set_password(E2E_PASSWORD)  # siempre, para garantizar la contraseña conocida
        user.save()

        TenantMembership.objects.get_or_create(
            user=user,
            tenant=tenant,
            defaults={"role": TenantMembership.Role.OWNER, "is_active": True},
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Usuario E2E listo: {E2E_EMAIL} / {E2E_PASSWORD} "
                f"(owner en {E2E_TENANT_SLUG})."
            )
        )
