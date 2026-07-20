"""
Data migration: backfill de `CfdiDocument.sucursal` (multi-sede — Fase 3,
clúster D — docs/design/sucursales-hallazgos-seguridad.md).

Por cada Tenant existente, para cada CfdiDocument sin sucursal:
  1. Si tiene `payment` y ese pago YA tiene `sucursal` asignada (backfill de
     la Fase 3, finanzas/migrations/0008), copia esa sucursal.
  2. Si no (CFDI sin pago ligado, o pago sin sucursal), asigna la "Sucursal
     Principal" (`is_default=True`) del tenant.

Depende de finanzas/0008 (backfill de Payment.sucursal) para que el paso 1
pueda derivar de un pago ya backfillado.

Compatibilidad hacia atrás: tras correr esta migración, todo CFDI preexistente
queda con una sucursal coherente con su pago relacionado (si lo tenía) o con
la sede única del tenant (clínicas de una sola sede no notan ningún cambio
funcional).

Idempotente: solo toca filas con `sucursal_id IS NULL`, así que correrla dos
veces no sobreescribe nada ya backfillado (ni datos asignados a mano después
del deploy).

Reverse: no-op documentado, mismo criterio que finanzas/0008 — no hay forma
segura de distinguir "asignado por este backfill" de "asignado manualmente
después", y revertir sería destructivo.
"""

from django.db import migrations


def backfill_cfdi_sucursal(apps, schema_editor):  # noqa: ANN001, ANN201
    Tenant = apps.get_model("tenancy", "Tenant")
    Sucursal = apps.get_model("clinica", "Sucursal")
    CfdiDocument = apps.get_model("finanzas", "CfdiDocument")
    Payment = apps.get_model("finanzas", "Payment")

    for tenant in Tenant.objects.all().iterator():
        principal = Sucursal.objects.filter(tenant_id=tenant.id, is_default=True).first()
        if principal is None:
            # Estado anómalo (no debería ocurrir tras el backfill de la Fase 1
            # — personal/0009 es dependencia transitiva de esta migración).
            # Se salta el tenant en vez de fallar el despliegue completo.
            continue

        # -------------------------------------------------------------
        # CfdiDocument hereda de su Payment (ya backfillado, finanzas/0008).
        # -------------------------------------------------------------
        cfdi_con_pago = CfdiDocument.objects.filter(
            tenant_id=tenant.id,
            sucursal_id__isnull=True,
            payment_id__isnull=False,
        )
        for cfdi in cfdi_con_pago.iterator():
            payment = Payment.objects.filter(id=cfdi.payment_id).only("sucursal_id").first()
            if payment is not None and payment.sucursal_id is not None:
                CfdiDocument.objects.filter(id=cfdi.id).update(sucursal_id=payment.sucursal_id)

        # Lo que quedó sin sucursal (sin pago, o pago sin sede) → principal.
        CfdiDocument.objects.filter(tenant_id=tenant.id, sucursal_id__isnull=True).update(
            sucursal_id=principal.id
        )


class Migration(migrations.Migration):

    dependencies = [
        ("finanzas", "0009_cfdidocument_sucursal"),
        ("finanzas", "0008_backfill_charge_payment_quote_sucursal"),
        ("clinica", "0018_rls_membership_sucursales"),
        ("tenancy", "0005_seed_plans"),
    ]

    operations = [
        migrations.RunPython(backfill_cfdi_sucursal, migrations.RunPython.noop),
    ]
