"""Crea usuarios de pruebas E2E (Playwright) con contraseña conocida.

SOLO para desarrollo / E2E local. Idempotente. NO usar en producción.

Modo por defecto (clínica):
    Credenciales: e2e@maily.local / Demo1234!  (rol owner en un tenant demo).
    Las pruebas de Playwright (web-soft/e2e/login.spec.ts) usan estas
    credenciales para el flujo de login de la app de clínica.

Modo --platform (staff de la plataforma):
    Credenciales: e2e-admin@maily.local / Demo1234!  (is_platform_staff=True,
    platform_role=super_admin). Usado por web-soft/e2e/plataforma.spec.ts para
    entrar al panel interno de Maily (/plataforma/*).

Uso:
    python manage.py seed_e2e_user              # usuario de clínica
    python manage.py seed_e2e_user --platform    # + usuario staff de plataforma

No toca usuarios reales: crea/actualiza solo los usuarios dedicados de E2E.

NOTA sobre el slug del tenant demo: el bootstrap de `seed_finanzas` (cuando la
BD está vacía) crea el slug "demo", pero entornos más antiguos pueden tener un
tenant demo sembrado a mano con el slug histórico "clinica-demo". Este comando
prueba ambos en orden y, si ninguno existe, usa el primer tenant disponible
para no bloquear el E2E por un desfase de nombre.
"""

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.authn.models import User
from apps.tenancy.models import Tenant, TenantMembership

E2E_EMAIL = "e2e@maily.local"
E2E_PASSWORD = "Demo1234!"  # noqa: S105 — credencial de prueba local, no es secreto real
E2E_TENANT_SLUG_CANDIDATES = ("clinica-demo", "demo")

E2E_PLATFORM_EMAIL = "e2e-admin@maily.local"
E2E_PLATFORM_PASSWORD = "Demo1234!"  # noqa: S105 — credencial de prueba local, no es secreto real


class Command(BaseCommand):
    help = "Crea los usuarios E2E (Playwright) con contraseña conocida. Solo dev/local."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--platform",
            action="store_true",
            default=False,
            help="Además del usuario de clínica, crea/actualiza el staff E2E de plataforma.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        self._seed_clinic_user()
        if options["platform"]:
            self._seed_platform_staff()

    def _seed_clinic_user(self) -> None:
        user_model = get_user_model()

        tenant = (
            Tenant.objects.filter(slug__in=E2E_TENANT_SLUG_CANDIDATES).first()
            or Tenant.objects.order_by("created_at").first()
        )
        if tenant is None:
            self.stderr.write(
                self.style.ERROR(
                    "No existe ningún tenant. Corre antes: python manage.py seed_finanzas"
                )
            )
            return

        user, _created = user_model.objects.get_or_create(
            email=E2E_EMAIL,
            defaults={
                "first_name": "E2E",
                "last_name": "Test",
                "is_active": True,
                "must_change_password": False,
            },
        )
        user.is_active = True
        # False explícito: si no, el flujo de login de Playwright chocaría con
        # el enforcement de "cambio de contraseña obligatorio" (ver apps/core/views.py).
        user.must_change_password = False
        user.set_password(E2E_PASSWORD)  # siempre, para garantizar la contraseña conocida
        user.save()

        TenantMembership.objects.get_or_create(
            user=user,
            tenant=tenant,
            defaults={"role": TenantMembership.Role.OWNER, "is_active": True},
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Usuario E2E listo: {E2E_EMAIL} / {E2E_PASSWORD} (owner en {tenant.slug})."
            )
        )

    def _seed_platform_staff(self) -> None:
        user_model = get_user_model()

        user, _created = user_model.objects.get_or_create(
            email=E2E_PLATFORM_EMAIL,
            defaults={
                "first_name": "E2E",
                "last_name": "Admin",
                "is_active": True,
                "is_staff": True,
                "is_platform_staff": True,
                "platform_role": User.PlatformRole.SUPER_ADMIN,
                "must_change_password": False,
            },
        )
        user.is_active = True
        user.is_staff = True
        user.is_platform_staff = True
        user.platform_role = User.PlatformRole.SUPER_ADMIN
        # False explícito y crítico: si no, el E2E de plataforma se bloquea en
        # /cambiar-contrasena en cuanto toca un endpoint de negocio (ver
        # apps/core/views.py — password_change_required).
        user.must_change_password = False
        user.set_password(E2E_PLATFORM_PASSWORD)
        user.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"Staff E2E de plataforma listo: {E2E_PLATFORM_EMAIL} / "
                f"{E2E_PLATFORM_PASSWORD} (super_admin)."
            )
        )
