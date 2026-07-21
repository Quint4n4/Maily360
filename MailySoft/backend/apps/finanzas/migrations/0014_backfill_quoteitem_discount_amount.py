"""
Data migration: backfill de `QuoteItem.discount_amount` (descuentos por
renglón/monto o porcentaje — decisión del dueño, 2026-07-21).

Antes de esta migración, `discount` en QuoteItem era SIEMPRE un monto en $
(no había `discount_type`); `line_total` ya reflejaba ese descuento
correctamente. La migración 0013 agrega `discount_type` (default 'amount') y
`discount_amount` (nuevo snapshot del descuento EFECTIVO en $, default 0.00)
sin tocar datos existentes — así que todo QuoteItem preexistente queda con
`discount_amount = 0.00` aunque `discount` (el monto histórico) sea > 0.

Esta migración corrige esa inconsistencia: para los renglones que quedaron
con `discount_type='amount'` (todos los preexistentes; ningún código anterior
a esta feature podía crear 'percent') y `discount_amount` sin backfillar,
copia `discount_amount = discount`. Es EXACTAMENTE el valor que ya estaba
descontado en `line_total` (el código anterior nunca dejaba que `discount`
superara la base), así que no cambia ningún total ya calculado — solo llena
el nuevo snapshot para que PDF/reportes lean el valor correcto sin tener que
reinterpretar `discount_type`.

Idempotente: solo toca filas con `discount_amount = 0` y `discount > 0`
(criterio "sin backfillar", mismo patrón que 0008/0010). Correrla dos veces
no sobreescribe nada.

Reverse: no-op documentado — no hay forma segura de distinguir "backfillado
por esta migración" de "un descuento capturado que legítimamente es 0.00
tras hacer efecto el clipping", y revertir sería destructivo.
"""

from django.db import migrations
from django.db.models import F


def backfill_discount_amount(apps, schema_editor):  # noqa: ANN001, ANN201
    QuoteItem = apps.get_model("finanzas", "QuoteItem")
    QuoteItem.objects.filter(
        discount_type="amount",
        discount_amount=0,
        discount__gt=0,
    ).update(discount_amount=F("discount"))


class Migration(migrations.Migration):

    dependencies = [
        ("finanzas", "0013_quote_global_discount_type_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_discount_amount, migrations.RunPython.noop),
    ]
