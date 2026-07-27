"""
Aplica el empaquetado de roles a los planes que restringen (Básico y Solo).

El default `roles=[]` significa "sin restricción extra": el plan ofrece todos los
roles que sus módulos permitan. Por eso los planes existentes (pro, premium,
legacy-full…) NO se tocan — siguen ofreciendo todo, como antes. Solo se restringen
los tramos donde la decisión comercial (2026-07-24) recorta la lista:

  Básico → dueño, médico, enfermería, recepción (sin admin, finanzas ni solo-lectura).
  Solo   → solo dueño (plan de una persona).

Reversible: vaciar `roles` en esos dos planes los devuelve a "sin restricción".
"""

from django.db import migrations

_ROLES_POR_SLUG = {
    "basico": ["owner", "doctor", "nurse", "reception"],
    "solo": ["owner"],
}


def aplicar(apps, schema_editor):
    Plan = apps.get_model("tenancy", "Plan")
    for slug, roles in _ROLES_POR_SLUG.items():
        Plan.objects.filter(slug=slug).update(roles=roles)


def revertir(apps, schema_editor):
    Plan = apps.get_model("tenancy", "Plan")
    Plan.objects.filter(slug__in=_ROLES_POR_SLUG).update(roles=[])


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0008_plan_roles"),
    ]

    operations = [
        migrations.RunPython(aplicar, revertir),
    ]
