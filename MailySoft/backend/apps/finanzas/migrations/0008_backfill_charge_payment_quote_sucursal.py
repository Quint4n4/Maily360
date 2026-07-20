"""
Data migration: backfill de `Charge.sucursal`, `Quote.sucursal` y
`Payment.sucursal` (multi-sede — Fase 3).

Por cada Tenant existente:
  1. Charge: si tiene `appointment` y esa cita ya tiene `sucursal` asignada
     (backfill de la Fase 2, agenda/migrations/0015), copia esa sucursal. Si
     no, asigna la "Sucursal Principal" (`is_default=True`) del tenant.
  2. Quote: si tiene alguna cita ligada (`Appointment.quote`, reverse
     `appointments`) con `sucursal` asignada, copia la de la más antigua. Si
     no, asigna la Sucursal Principal.
  3. Payment: si tiene alguna aplicación (`PaymentAllocation`) a un Charge que
     YA quedó con sucursal (paso 1, misma migración), copia esa sucursal. Si
     no, asigna la Sucursal Principal.

Depende de agenda/0015 (backfill de Appointment.sucursal) para que el paso 1
y 2 puedan derivar de una cita ya backfillada.

Compatibilidad hacia atrás: tras correr esta migración, todo cargo/cotización/
pago preexistente queda con una sucursal coherente con su cita relacionada (si
la tenía) o con la sede única del tenant (clínicas de una sola sede no notan
ningún cambio funcional; el estado de cuenta del paciente sigue mostrando
TODOS sus movimientos sin importar la sede).

Idempotente: cada paso solo toca filas con `sucursal_id IS NULL`, así que
correrla dos veces no sobreescribe nada ya backfillado (ni datos asignados a
mano después del deploy).

Reverse: no-op documentado, mismo criterio que agenda/0015 — no hay forma
segura de distinguir "asignado por este backfill" de "asignado manualmente
después", y revertir sería destructivo.
"""

from django.db import migrations


def backfill_finanzas_sucursal(apps, schema_editor):  # noqa: ANN001, ANN201
    Tenant = apps.get_model("tenancy", "Tenant")
    Sucursal = apps.get_model("clinica", "Sucursal")
    Charge = apps.get_model("finanzas", "Charge")
    Payment = apps.get_model("finanzas", "Payment")
    Quote = apps.get_model("finanzas", "Quote")
    Appointment = apps.get_model("agenda", "Appointment")
    PaymentAllocation = apps.get_model("finanzas", "PaymentAllocation")

    for tenant in Tenant.objects.all().iterator():
        principal = Sucursal.objects.filter(tenant_id=tenant.id, is_default=True).first()
        if principal is None:
            # Estado anómalo (no debería ocurrir tras el backfill de la Fase 1
            # — personal/0009 es dependencia transitiva de esta migración).
            # Se salta el tenant en vez de fallar el despliegue completo.
            continue

        # -------------------------------------------------------------
        # 1. Charge: hereda de su Appointment (ya backfillada, agenda/0015).
        # -------------------------------------------------------------
        charges_con_cita = Charge.objects.filter(
            tenant_id=tenant.id,
            sucursal_id__isnull=True,
            appointment_id__isnull=False,
        )
        for charge in charges_con_cita.iterator():
            appt = Appointment.objects.filter(id=charge.appointment_id).only("sucursal_id").first()
            if appt is not None and appt.sucursal_id is not None:
                Charge.objects.filter(id=charge.id).update(sucursal_id=appt.sucursal_id)

        # Lo que quedó sin sucursal (sin cita, o cita sin sede) → principal.
        Charge.objects.filter(tenant_id=tenant.id, sucursal_id__isnull=True).update(
            sucursal_id=principal.id
        )

        # -------------------------------------------------------------
        # 2. Quote: hereda de la cita ligada más antigua (Appointment.quote)
        #    que ya tenga sucursal.
        # -------------------------------------------------------------
        quotes_sin_sucursal = Quote.objects.filter(tenant_id=tenant.id, sucursal_id__isnull=True)
        for quote in quotes_sin_sucursal.iterator():
            appt = (
                Appointment.objects.filter(quote_id=quote.id, sucursal_id__isnull=False)
                .order_by("created_at")
                .first()
            )
            sucursal_id = appt.sucursal_id if appt is not None else principal.id
            Quote.objects.filter(id=quote.id).update(sucursal_id=sucursal_id)

        # -------------------------------------------------------------
        # 3. Payment: hereda del primer Charge que liquida (vía
        #    PaymentAllocation), que YA quedó con sucursal en el paso 1.
        # -------------------------------------------------------------
        payments_sin_sucursal = Payment.objects.filter(
            tenant_id=tenant.id, sucursal_id__isnull=True
        )
        for payment in payments_sin_sucursal.iterator():
            alloc = (
                PaymentAllocation.objects.filter(payment_id=payment.id)
                .order_by("created_at")
                .first()
            )
            sucursal_id = principal.id
            if alloc is not None:
                charge = Charge.objects.filter(id=alloc.charge_id).only("sucursal_id").first()
                if charge is not None and charge.sucursal_id is not None:
                    sucursal_id = charge.sucursal_id
            Payment.objects.filter(id=payment.id).update(sucursal_id=sucursal_id)


class Migration(migrations.Migration):

    dependencies = [
        ("finanzas", "0007_charge_payment_quote_sucursal"),
        ("agenda", "0015_backfill_appointment_agendablock_sucursal"),
        ("clinica", "0018_rls_membership_sucursales"),
        ("tenancy", "0005_seed_plans"),
    ]

    operations = [
        migrations.RunPython(backfill_finanzas_sucursal, migrations.RunPython.noop),
    ]
