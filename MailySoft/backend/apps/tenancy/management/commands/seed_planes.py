"""
Siembra el catálogo de planes de Maily.

Idempotente y CONSERVADOR por defecto:
  - Plan que no existe        → se crea.
  - Plan existente SIN módulos → se completa (no le quita nada a nadie).
  - Plan existente CON módulos → NO se toca.

Cambiar los módulos de un plan vivo le quita funciones a las clínicas suscritas,
así que tiene que ser una decisión deliberada — se pide con `--actualizar`.

Uso:
    python manage.py seed_planes                # crea y completa
    python manage.py seed_planes --actualizar   # además reescribe los existentes
"""

from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand

from apps.core.modules import Module, expandir_dependencias, validar_modulos
from apps.tenancy.models import Plan, TenantMembership

# Lo clínico completo: la base de TODOS los planes. Un plan sin esto no sirve
# para dar consulta, y entonces no es un plan de un sistema clínico.
_CLINICO: list[str] = [
    Module.AGENDA,
    Module.RECORDATORIOS,
    Module.EXPEDIENTE,
    Module.RECETAS,
    Module.NOTAS,
]

# Lo comercial: el upgrade. Lo que se compra al subir de plan no es "poder
# trabajar", es "poder cobrar".
_COMERCIAL: list[str] = [
    Module.SERVICIOS,
    Module.PAQUETES,
    Module.COTIZACIONES,
    Module.COBRANZA,
]

_PERSONAL: list[str] = [Module.PERSONAL]

Role = TenantMembership.Role

# Roles por tramo (empaquetado aprobado 2026-07-24):
#   Básico → dueño, médico, enfermería, recepción.
#   Pro+   → además admin, finanzas y solo-lectura (finanzas solo con cobranza).
# `owner` siempre está: toda clínica tiene su dueño.
_ROLES_CLINICOS: list[str] = [Role.OWNER, Role.DOCTOR, Role.NURSE, Role.RECEPTION]
_ROLES_TODOS: list[str] = [
    Role.OWNER, Role.ADMIN, Role.DOCTOR, Role.NURSE,
    Role.RECEPTION, Role.FINANCE, Role.READONLY,
]


#: Catálogo. `None` en un límite = ilimitado.
PLANES: list[dict[str, Any]] = [
    {
        "slug": "solo",
        "name": "Solo",
        "description": "Para el médico que trabaja por su cuenta.",
        "price_monthly": Decimal("900.00"),
        "features": [
            "1 consultorio",
            "1 usuario",
            "Agenda y pacientes",
            "Expediente y recetas",
            "Recordatorios WhatsApp",
        ],
        "modules": _CLINICO,
        "roles": [Role.OWNER],
        "max_sucursales": 1,
        "max_consultorios": 1,
        "max_usuarios": 1,
        # Nace APAGADO a propósito: el tope de 1 usuario deja fuera a casi todo
        # médico que tenga quien le conteste el teléfono, y sostener un plan de
        # $900 cuesta lo mismo que uno de $4,500. Se enciende cuando haya casos
        # reales que digan el precio correcto. Mientras tanto, al médico solo se
        # le vende Básico con descuento.
        "is_active": False,
        "is_featured": False,
        "order": 1,
    },
    {
        "slug": "basico",
        "name": "Básico",
        "description": "Para consultorios pequeños.",
        "price_monthly": Decimal("1500.00"),
        "features": [
            "1 consultorio",
            "Hasta 3 usuarios",
            "Agenda y pacientes",
            "Expediente y recetas",
            "Recordatorios WhatsApp",
        ],
        "modules": _CLINICO + _PERSONAL,
        "roles": _ROLES_CLINICOS,
        "max_sucursales": 1,
        "max_consultorios": 1,
        "max_usuarios": 3,
        "is_active": True,
        "is_featured": False,
        "order": 2,
    },
    {
        "slug": "pro",
        "name": "Pro",
        "description": "Para clínicas en crecimiento.",
        "price_monthly": Decimal("4500.00"),
        "features": [
            "Hasta 5 consultorios",
            "Usuarios ilimitados",
            "Todo lo clínico",
            "Servicios, cotizaciones y paquetes",
            "Cobranza y estado de cuenta",
        ],
        "modules": _CLINICO + _COMERCIAL + _PERSONAL,
        "roles": _ROLES_TODOS,
        "max_sucursales": 1,
        "max_consultorios": 5,
        "max_usuarios": None,
        "is_active": True,
        "is_featured": True,
        "order": 3,
    },
    {
        "slug": "premium",
        "name": "Premium",
        "description": "Para clínicas con varias sedes.",
        "price_monthly": Decimal("8900.00"),
        "features": [
            "Consultorios ilimitados",
            "Multi-sucursal",
            "Facturación CFDI",
            "Todo lo de Pro",
            "Soporte prioritario",
        ],
        "modules": _CLINICO + _COMERCIAL + _PERSONAL + [Module.CFDI],
        "roles": _ROLES_TODOS,
        "max_sucursales": None,
        "max_consultorios": None,
        "max_usuarios": None,
        "is_active": True,
        "is_featured": False,
        "order": 4,
    },
    {
        "slug": "enterprise",
        "name": "Enterprise",
        "description": "Para cadenas y grupos médicos. Precio a cotizar.",
        "price_monthly": Decimal("0.00"),
        "features": [
            "Todo lo de Premium",
            "Integraciones a medida",
            "Branding propio",
            "Soporte dedicado",
        ],
        "modules": _CLINICO + _COMERCIAL + _PERSONAL + [Module.CFDI],
        "roles": _ROLES_TODOS,
        "max_sucursales": None,
        "max_consultorios": None,
        "max_usuarios": None,
        "is_active": True,
        "is_featured": False,
        "order": 5,
    },
]


class Command(BaseCommand):
    help = "Siembra el catálogo de planes (Solo, Básico, Pro, Premium, Enterprise)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--actualizar",
            action="store_true",
            help=(
                "Reescribe los planes que ya existen. CUIDADO: puede quitarle "
                "módulos a clínicas suscritas."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        actualizar: bool = options["actualizar"]
        creados = 0
        actualizados = 0
        omitidos = 0

        for datos in PLANES:
            campos = dict(datos)
            slug = campos.pop("slug")

            # Coherencia antes de guardar: un plan con dependencias sin cubrir
            # es un plan roto que el guard interpretaría de forma impredecible.
            campos["modules"] = sorted(expandir_dependencias(campos["modules"]))
            validar_modulos(campos["modules"])

            plan = Plan.objects.filter(slug=slug).first()
            if plan is None:
                Plan.objects.create(slug=slug, **campos)
                creados += 1
                self.stdout.write(self.style.SUCCESS(f"  + {campos['name']} creado."))
            elif not plan.modules:
                # Plan sin módulos = plan sin estrenar (lo dejó así 0005_seed_plans
                # o la migración de entitlements por no tener suscriptores).
                # Rellenarlo no le quita nada a nadie: es completarlo, no reescribirlo.
                for campo, valor in campos.items():
                    setattr(plan, campo, valor)
                plan.save()
                actualizados += 1
                self.stdout.write(f"  ~ {campos['name']} completado (estaba sin módulos).")
            elif actualizar:
                for campo, valor in campos.items():
                    setattr(plan, campo, valor)
                plan.save()
                actualizados += 1
                self.stdout.write(f"  ~ {campos['name']} actualizado.")
            else:
                omitidos += 1
                self.stdout.write(
                    f"  · {campos['name']} ya existe (usa --actualizar para reescribirlo)."
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Planes: {creados} creados, {actualizados} actualizados, "
                f"{omitidos} sin cambios."
            )
        )
