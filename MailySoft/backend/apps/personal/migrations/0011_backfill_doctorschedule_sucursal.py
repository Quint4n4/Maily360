"""
Data migration: backfill de `DoctorSchedule.sucursal` (multi-sede — Fase 2).

Por cada Tenant existente, para cada `DoctorSchedule` con `sucursal_id` NULL:
  1. Si tiene `consultorio` y ese consultorio ya tiene `sucursal` asignada
     (backfill de la Fase 1, migración 0009), copia esa sucursal.
  2. Si no, asigna la "Sucursal Principal" (`is_default=True`) del tenant —
     que YA EXISTE para todo tenant tras 0009_backfill_sucursal_principal
     (dependencia dura de esta migración).

Mismo patrón que agenda/0015_backfill_appointment_agendablock_sucursal.py
(horarios laborales son al Consultorio/Doctor lo que las citas son a la
agenda). Idempotente: solo toca filas con `sucursal_id IS NULL`.

Reverse: no-op documentado (mismo criterio que 0009 y agenda/0015).
"""

from django.db import migrations


def backfill_sucursal(apps, schema_editor):  # noqa: ANN001, ANN201
    Tenant = apps.get_model("tenancy", "Tenant")
    Sucursal = apps.get_model("clinica", "Sucursal")
    Consultorio = apps.get_model("personal", "Consultorio")
    DoctorSchedule = apps.get_model("personal", "DoctorSchedule")

    for tenant in Tenant.objects.all().iterator():
        principal = Sucursal.objects.filter(tenant_id=tenant.id, is_default=True).first()
        if principal is None:
            # Estado anómalo (no debería ocurrir tras el backfill de la Fase 1).
            continue

        consultorios_con_sede = Consultorio.objects.filter(
            tenant_id=tenant.id, sucursal_id__isnull=False
        )
        for consultorio in consultorios_con_sede.iterator():
            DoctorSchedule.objects.filter(
                tenant_id=tenant.id,
                consultorio_id=consultorio.id,
                sucursal_id__isnull=True,
            ).update(sucursal_id=consultorio.sucursal_id)

        DoctorSchedule.objects.filter(tenant_id=tenant.id, sucursal_id__isnull=True).update(
            sucursal_id=principal.id
        )


class Migration(migrations.Migration):

    dependencies = [
        ("personal", "0010_appointment_agendablock_doctorschedule_sucursal"),
        ("personal", "0009_backfill_sucursal_principal"),
        ("clinica", "0018_rls_membership_sucursales"),
        ("tenancy", "0005_seed_plans"),
    ]

    operations = [
        migrations.RunPython(backfill_sucursal, migrations.RunPython.noop),
    ]
