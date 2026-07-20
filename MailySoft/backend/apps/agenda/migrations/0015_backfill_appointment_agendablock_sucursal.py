"""
Data migration: backfill de `Appointment.sucursal` y `AgendaBlock.sucursal`
(multi-sede — Fase 2).

Por cada Tenant existente, para cada registro (Appointment / AgendaBlock) con
`sucursal_id` aún NULL:
  1. Si tiene `consultorio` y ese consultorio ya tiene `sucursal` asignada
     (backfill de la Fase 1, migración personal/0009), copia esa sucursal.
  2. Si no, asigna la "Sucursal Principal" (`is_default=True`) del tenant —
     que YA EXISTE para todo tenant tras el backfill de la Fase 1 (dependencia
     dura de esta migración sobre personal/0009_backfill_sucursal_principal).

Compatibilidad hacia atrás: tras correr esta migración, toda cita y todo
evento de agenda preexistente queda con una sucursal coherente con su
consultorio (si lo tenía) o con la sede única del tenant (clínicas de una
sola sede no notan ningún cambio funcional).

Idempotente: cada paso solo toca filas con `sucursal_id IS NULL`, así que
correrla dos veces no sobreescribe nada ya backfillado (ni datos asignados a
mano después del deploy).

Reverse: no-op documentado, mismo criterio que personal/0009 — no hay forma
segura de distinguir "asignado por este backfill" de "asignado manualmente
después", y revertir sería destructivo.
"""

from django.db import migrations


def backfill_sucursal(apps, schema_editor):  # noqa: ANN001, ANN201
    Tenant = apps.get_model("tenancy", "Tenant")
    Sucursal = apps.get_model("clinica", "Sucursal")
    Consultorio = apps.get_model("personal", "Consultorio")
    Appointment = apps.get_model("agenda", "Appointment")
    AgendaBlock = apps.get_model("agenda", "AgendaBlock")

    for tenant in Tenant.objects.all().iterator():
        principal = Sucursal.objects.filter(tenant_id=tenant.id, is_default=True).first()
        if principal is None:
            # Estado anómalo (no debería ocurrir tras el backfill de la Fase 1
            # — personal/0009 es dependencia dura de esta migración). Se
            # salta el tenant en vez de fallar el despliegue completo.
            continue

        consultorios_con_sede = Consultorio.objects.filter(
            tenant_id=tenant.id, sucursal_id__isnull=False
        )
        for consultorio in consultorios_con_sede.iterator():
            Appointment.objects.filter(
                tenant_id=tenant.id,
                consultorio_id=consultorio.id,
                sucursal_id__isnull=True,
            ).update(sucursal_id=consultorio.sucursal_id)
            AgendaBlock.objects.filter(
                tenant_id=tenant.id,
                consultorio_id=consultorio.id,
                sucursal_id__isnull=True,
            ).update(sucursal_id=consultorio.sucursal_id)

        # Lo que quedó sin sucursal (sin consultorio, o consultorio sin sede) → principal.
        Appointment.objects.filter(tenant_id=tenant.id, sucursal_id__isnull=True).update(
            sucursal_id=principal.id
        )
        AgendaBlock.objects.filter(tenant_id=tenant.id, sucursal_id__isnull=True).update(
            sucursal_id=principal.id
        )


class Migration(migrations.Migration):

    dependencies = [
        ("agenda", "0014_appointment_agendablock_doctorschedule_sucursal"),
        ("personal", "0009_backfill_sucursal_principal"),
        ("clinica", "0018_rls_membership_sucursales"),
        ("tenancy", "0005_seed_plans"),
    ]

    operations = [
        migrations.RunPython(backfill_sucursal, migrations.RunPython.noop),
    ]
