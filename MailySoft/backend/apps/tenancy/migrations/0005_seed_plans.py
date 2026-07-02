"""
Data migration: siembra el catálogo inicial de 3 planes (Fase 3 — Suscripciones).

Idempotente: usa get_or_create por slug, así que correrla dos veces (o sobre
una BD que ya tenga los planes de una siembra manual anterior con el mismo
slug) no crea duplicados ni sobreescribe ediciones posteriores del equipo
comercial (precio/features editados a mano en el catálogo NO se pisan aquí).

Reverse: borra únicamente los 3 planes por slug (best-effort; si ya tienen
TenantSubscription asociadas el borrado falla por el PROTECT del FK — se deja
así a propósito: no queremos que un rollback de esquema borre en cascada
suscripciones reales de clínicas).
"""

from decimal import Decimal

from django.db import migrations

_PLANS = [
    {
        "slug": "basico",
        "name": "Básico",
        "price_monthly": Decimal("1500.00"),
        "is_featured": False,
        "features": [
            "1 consultorio",
            "Hasta 3 usuarios",
            "Agenda y pacientes",
            "Recordatorios WhatsApp",
        ],
        "order": 1,
    },
    {
        "slug": "pro",
        "name": "Pro",
        "price_monthly": Decimal("4500.00"),
        "is_featured": True,
        "features": [
            "Hasta 5 consultorios",
            "Usuarios ilimitados",
            "Expedientes completos",
            "Finanzas y reportes",
        ],
        "order": 2,
    },
    {
        "slug": "premium",
        "name": "Premium",
        "price_monthly": Decimal("8900.00"),
        "is_featured": False,
        "features": [
            "Consultorios ilimitados",
            "Multi-sucursal",
            "Soporte prioritario",
            "Integraciones a medida",
        ],
        "order": 3,
    },
]


def seed_plans(apps, schema_editor):
    Plan = apps.get_model("tenancy", "Plan")
    for data in _PLANS:
        Plan.objects.get_or_create(
            slug=data["slug"],
            defaults={
                "name": data["name"],
                "price_monthly": data["price_monthly"],
                "is_featured": data["is_featured"],
                "features": data["features"],
                "order": data["order"],
                "is_active": True,
            },
        )


def unseed_plans(apps, schema_editor):
    Plan = apps.get_model("tenancy", "Plan")
    slugs = [p["slug"] for p in _PLANS]
    Plan.objects.filter(slug__in=slugs).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0004_plan_tenant_trial_expired_notified_at_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_plans, unseed_plans),
    ]
