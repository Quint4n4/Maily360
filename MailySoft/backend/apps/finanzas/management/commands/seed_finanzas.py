"""
Management command: siembra datos demo del módulo finanzas para un tenant.

Crea conceptos, configuración fiscal, cotizaciones (con cargos generados),
cargos de distintas antigüedades (para poblar el aging) y pagos con varios
métodos, además de un CFDI timbrado con el PAC simulado.

Uso:
    python manage.py seed_finanzas --tenant <slug>
    python manage.py seed_finanzas            # usa el primer tenant existente

Idempotencia: usa nombres/expedientes con prefijo "DEMO-" para no chocar; si se
corre dos veces puede crear duplicados de pagos/cargos (datos demo, aceptable).
"""

import datetime
import random
from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.authn.models import User
from apps.core.tenant_context import (
    clear_current_tenant,
    set_current_tenant,
    set_tenant_context_active,
)
from apps.finanzas.services import (
    cfdi_issue,
    charge_create,
    clinic_fiscal_config_update,
    concept_create,
    payment_register,
    quote_accept,
    quote_create,
)
from apps.pacientes.models import Patient
from apps.pacientes.services import patient_create
from apps.tenancy.models import Tenant, TenantMembership

_DEMO_PASSWORD = "Demo1234!"
_DEMO_TENANT_SLUG = "demo"
_DEMO_USERS: list[tuple[str, str, str]] = [
    ("owner@demo.maily.mx", "Dueño", TenantMembership.Role.OWNER),
    ("finance@demo.maily.mx", "Finanzas", TenantMembership.Role.FINANCE),
    ("reception@demo.maily.mx", "Recepción", TenantMembership.Role.RECEPTION),
    ("readonly@demo.maily.mx", "Solo lectura", TenantMembership.Role.READONLY),
]

_CONCEPTS = [
    ("Consulta general", Decimal("600.00")),
    ("Consulta de especialidad", Decimal("950.00")),
    ("Radiografía", Decimal("450.00")),
    ("Terapia física", Decimal("520.00")),
    ("Laboratorio básico", Decimal("780.00")),
]


class Command(BaseCommand):
    help = "Siembra datos demo del módulo finanzas para un tenant."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--tenant",
            type=str,
            default=None,
            help="Slug del tenant. Si se omite, usa el primer tenant existente.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        tenant = self._resolve_tenant(options.get("tenant"))
        user = self._resolve_user(tenant)

        # Activar contexto de tenant para que el ORM/RLS opere sobre este tenant.
        set_current_tenant(tenant)
        set_tenant_context_active(True)
        try:
            self._seed(tenant=tenant, user=user)
        finally:
            clear_current_tenant()

    def _seed(self, *, tenant: Tenant, user: Any) -> None:
        self.stdout.write(f"Sembrando finanzas para: {tenant.name} ({tenant.slug})")

        # 1. Configuración fiscal del emisor.
        clinic_fiscal_config_update(
            tenant=tenant,
            user=user,
            rfc="DEMO010101AAA",
            legal_name=f"{tenant.name} SA de CV",
            tax_regime="601",
            postal_code="06000",
        )

        # 2. Catálogo de conceptos.
        concepts = []
        for name, price in _CONCEPTS:
            try:
                concepts.append(
                    concept_create(tenant=tenant, user=user, name=name, base_price=price)
                )
            except Exception:  # noqa: BLE001 — ya existe: lo reutilizamos
                from apps.finanzas.models import ServiceConcept

                existing = ServiceConcept.all_objects.filter(tenant=tenant, name=name).first()
                if existing:
                    concepts.append(existing)

        # 3. Pacientes demo (3).
        patients = self._ensure_patients(tenant, user, count=3)

        now = timezone.now()
        rng = random.Random(42)

        # 4. Cotizaciones (algunas aceptadas → generan cargos).
        for patient in patients:
            concept = rng.choice(concepts)
            quote = quote_create(
                tenant=tenant,
                user=user,
                patient=patient,
                items=[
                    {
                        "concept_id": str(concept.id),
                        "description": concept.name,
                        "quantity": "1",
                        "unit_price": str(concept.base_price),
                    }
                ],
            )
            if rng.random() < 0.6:
                quote_accept(quote=quote, user=user)

        # 5. Cargos de distintas antigüedades (aging) + pagos.
        ages = [5, 20, 45, 75, 120]
        methods = ["cash", "card", "transfer", "other"]
        for patient in patients:
            for age in ages:
                concept = rng.choice(concepts)
                issued = now - datetime.timedelta(days=age)
                charge = charge_create(
                    tenant=tenant,
                    user=user,
                    patient=patient,
                    amount=concept.base_price,
                    description=concept.name,
                    concept=concept,
                    issued_at=issued,
                )
                # Pagar (total o parcial) ~70% de los cargos.
                roll = rng.random()
                if roll < 0.45:
                    payment_register(
                        tenant=tenant,
                        user=user,
                        patient=patient,
                        amount=charge.amount,
                        method=rng.choice(methods),
                        received_at=issued + datetime.timedelta(days=1),
                        allocations=[{"charge_id": str(charge.id), "amount": str(charge.amount)}],
                    )
                elif roll < 0.7:
                    half = (charge.amount / 2).quantize(Decimal("0.01"))
                    payment_register(
                        tenant=tenant,
                        user=user,
                        patient=patient,
                        amount=half,
                        method=rng.choice(methods),
                        received_at=issued + datetime.timedelta(days=1),
                        allocations=[{"charge_id": str(charge.id), "amount": str(half)}],
                    )

        # 6. Un CFDI timbrado (PAC simulado) sobre el primer pago disponible.
        from apps.finanzas.models import Payment

        first_payment: Payment | None = Payment.objects.order_by("received_at").first()
        if first_payment is not None:
            cfdi_issue(
                tenant=tenant,
                user=user,
                payment=first_payment,
                receptor_rfc="XAXX010101000",
                receptor_name="Público en general",
            )

        self.stdout.write(self.style.SUCCESS("Datos demo de finanzas creados correctamente."))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_tenant(self, slug: str | None) -> Tenant:
        if slug:
            tenant = Tenant.objects.filter(slug=slug).first()
            if tenant is None:
                raise CommandError(f"No existe un tenant con slug '{slug}'.")
            return tenant
        tenant = Tenant.objects.order_by("created_at").first()
        if tenant is None:
            self.stdout.write("No hay tenants — creando entorno demo…")
            return self._bootstrap_demo()
        return tenant

    def _bootstrap_demo(self) -> Tenant:
        """Crea clínica demo + usuarios por rol (solo dev local)."""
        tenant, _ = Tenant.objects.get_or_create(
            slug=_DEMO_TENANT_SLUG,
            defaults={"name": "Clínica Demo Maily", "status": Tenant.Status.ACTIVE},
        )
        for email, label, role in _DEMO_USERS:
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "first_name": label,
                    "last_name": "Demo",
                    "is_active": True,
                    # Usuario de seed con contraseña conocida y documentada:
                    # NO debe forzar cambio de contraseña (rompería el demo/E2E).
                    "must_change_password": False,
                },
            )
            if created:
                user.set_password(_DEMO_PASSWORD)
                user.save(update_fields=["password"])
            TenantMembership.objects.get_or_create(
                user=user,
                tenant=tenant,
                defaults={"role": role, "is_active": True},
            )
        self.stdout.write(self.style.SUCCESS("Entorno demo creado. Credenciales (solo dev):"))
        for email, _, _ in _DEMO_USERS:
            self.stdout.write(f"  · {email} / {_DEMO_PASSWORD}")
        return tenant

    def _resolve_user(self, tenant: Tenant) -> Any:
        membership = (
            TenantMembership.objects.filter(tenant=tenant, is_active=True)
            .order_by("created_at")
            .first()
        )
        return membership.user if membership is not None else None

    def _ensure_patients(self, tenant: Tenant, user: Any, *, count: int) -> list[Patient]:
        """Reutiliza pacientes existentes del tenant o crea los necesarios."""
        existing = list(Patient.objects.all()[:count])
        if len(existing) >= count:
            return existing

        names = [
            ("Laura", "Hernández", "Gómez", "F"),
            ("Carlos", "Méndez", "Ruiz", "M"),
            ("Diana", "Torres", "Salas", "F"),
        ]
        created = list(existing)
        for i in range(count - len(existing)):
            first, pat, mat, sex = names[i % len(names)]
            created.append(
                patient_create(
                    tenant=tenant,
                    user=user,
                    first_name=first,
                    paternal_surname=pat,
                    maternal_surname=mat,
                    date_of_birth=datetime.date(1990, 1, 1),
                    sex=sex,
                    phone=f"55120000{i:02d}",
                )
            )
        return created
