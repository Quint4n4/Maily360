"""
Migración de datos — nadie pierde funciones al introducir los entitlements.

Antes de esta migración NADA se gateaba por plan: toda clínica veía toda la app.
Al empezar a gatear por `Plan.modules`, un plan con la lista vacía (el default
del campo nuevo) dejaría a su clínica sin absolutamente ningún módulo. Eso sería
una interrupción de servicio, no un cambio de producto.

Por eso:
  1. Los planes CON clínicas suscritas reciben el catálogo completo y límites
     ilimitados. Quien ya estaba en 'Básico' sigue viendo lo mismo que ayer.
  2. Se crea el plan 'Legacy full' (inactivo: no se ofrece a clientes nuevos)
     y se suscribe a él a las clínicas que hoy NO tienen plan — que sin esto
     se quedarían con cero módulos.

Los planes SIN suscriptores se dejan sin módulos a propósito: no hay nada que
proteger ahí, y son los que `seed_planes` va a rellenar con el empaquetado real.
Si se les diera todo aquí, el empaquetado nunca llegaría a aplicarse en una
instalación nueva (0005_seed_plans crea Básico/Pro/Premium vacíos de clientes).

El empaquetado real lo aplica el comando `seed_planes`, que rellena los planes
sin módulos pero NO reescribe los que ya los tienen: restringir a una clínica
viva es una decisión comercial deliberada (--actualizar), no un efecto colateral.

Reversible: la marcha atrás borra el plan Legacy full y sus suscripciones, y
vacía los campos nuevos.
"""

from datetime import timedelta

from django.db import migrations
from django.utils.timezone import now

# Copia literal de apps.core.modules.Module.values al momento de esta migración.
# NO se importa el módulo: una migración debe seguir corriendo igual aunque el
# catálogo cambie después (regla de oro de las migraciones de datos).
_MODULOS_AL_MIGRAR = [
    "agenda",
    "recordatorios",
    "expediente",
    "recetas",
    "notas",
    "servicios",
    "paquetes",
    "cotizaciones",
    "cobranza",
    "cfdi",
    "calendarizacion",
    "personal",
]

_LEGACY_SLUG = "legacy-full"


def aplicar(apps, schema_editor):
    """Da acceso completo a todo lo que ya existía."""
    Plan = apps.get_model("tenancy", "Plan")
    Tenant = apps.get_model("tenancy", "Tenant")
    TenantSubscription = apps.get_model("tenancy", "TenantSubscription")

    # 1) Los planes CON clínicas encima conservan TODO: nadie pierde funciones
    #    hoy. Los que nadie usa quedan vacíos para que `seed_planes` les ponga
    #    el empaquetado real — no hay nadie a quien proteger en ellos.
    Plan.objects.filter(subscriptions__isnull=False).distinct().update(
        modules=_MODULOS_AL_MIGRAR,
        max_sucursales=None,
        max_consultorios=None,
        max_usuarios=None,
    )

    # 2) Las clínicas sin plan necesitan uno o se quedarían sin módulos.
    sin_plan = Tenant.objects.filter(subscription__isnull=True)
    if not sin_plan.exists():
        return

    legacy, _ = Plan.objects.get_or_create(
        slug=_LEGACY_SLUG,
        defaults={
            "name": "Legacy full",
            "description": (
                "Plan histórico: acceso completo. Asignado automáticamente a las "
                "clínicas que ya operaban antes de que existieran los módulos por "
                "plan. No se ofrece a clientes nuevos."
            ),
            "price_monthly": 0,
            "features": ["Acceso completo (plan histórico)"],
            "modules": _MODULOS_AL_MIGRAR,
            "max_sucursales": None,
            "max_consultorios": None,
            "max_usuarios": None,
            "is_active": False,
            "is_featured": False,
            "order": 999,
        },
    )

    vence = (now() + timedelta(days=365)).date()
    TenantSubscription.objects.bulk_create(
        [
            TenantSubscription(
                tenant=tenant,
                plan=legacy,
                billing_cycle="monthly",
                current_period_end=vence,
            )
            for tenant in sin_plan
        ]
    )


def revertir(apps, schema_editor):
    """Deshace la asignación automática. Los campos nuevos los quita el esquema."""
    Plan = apps.get_model("tenancy", "Plan")
    TenantSubscription = apps.get_model("tenancy", "TenantSubscription")

    TenantSubscription.objects.filter(plan__slug=_LEGACY_SLUG).delete()
    Plan.objects.filter(slug=_LEGACY_SLUG).delete()
    Plan.objects.all().update(modules=[])


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0006_plan_max_consultorios_plan_max_sucursales_and_more"),
    ]

    operations = [
        migrations.RunPython(aplicar, revertir),
    ]
