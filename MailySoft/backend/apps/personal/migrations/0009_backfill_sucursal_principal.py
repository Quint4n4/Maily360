"""
Data migration: backfill de "Sucursal Principal" (multi-sede — Fase 1).

Por cada Tenant existente:
  1. Crea (si no existe ya) una Sucursal "Sucursal Principal" con
     is_default=True, is_active=True.
  2. Asigna TODOS los Consultorio del tenant que aún no tienen sucursal a la
     principal.
  3. Agrega la principal a Doctor.sucursales de cada doctor del tenant.
  4. Crea MembershipSucursal(membership, principal) para cada TenantMembership
     activa del tenant.

Compatibilidad hacia atrás (principio 1 del plan de sucursales): tras correr
esta migración, una clínica de una sola sede queda TODA bajo "Sucursal
Principal" — no nota ningún cambio visible (todos los FK `sucursal` nacieron
nullable, y ahora quedan apuntando a la misma sede única).

Idempotente: usa get_or_create / chequeos de existencia en cada paso, así
que correrla dos veces (o sobre datos ya backfillados manualmente) no
duplica sucursales, asignaciones ni membresías-sucursal. Puede además
recorrer un tenant que ya tenga varias sucursales creadas manualmente ANTES
de este backfill (nunca debería pasar en el flujo normal de despliegue, pero
por defensa se busca primero por is_default=True antes de crear una nueva).

Reverse: no-op documentado. Borrar sucursales/asignaciones en el rollback
sería destructivo y no hay forma segura de distinguir "creado por este
backfill" de "creado después por el usuario" (mismo criterio que
tenancy/0005_seed_plans.py para irreversibilidad de datos de negocio).
"""

from django.db import migrations

_SUCURSAL_PRINCIPAL_NAME = "Sucursal Principal"


def backfill_sucursal_principal(apps, schema_editor):  # noqa: ANN001, ANN201
    Tenant = apps.get_model("tenancy", "Tenant")
    TenantMembership = apps.get_model("tenancy", "TenantMembership")
    Sucursal = apps.get_model("clinica", "Sucursal")
    MembershipSucursal = apps.get_model("clinica", "MembershipSucursal")
    Consultorio = apps.get_model("personal", "Consultorio")
    Doctor = apps.get_model("personal", "Doctor")

    for tenant in Tenant.objects.all().iterator():
        principal = Sucursal.objects.filter(tenant_id=tenant.id, is_default=True).first()

        if principal is None:
            # Defensa: si ya existe una sucursal con el nombre esperado (pero
            # sin is_default, caso anómalo) la reutilizamos en vez de duplicar.
            principal = Sucursal.objects.filter(
                tenant_id=tenant.id, name=_SUCURSAL_PRINCIPAL_NAME
            ).first()

        if principal is None:
            principal = Sucursal.objects.create(
                tenant_id=tenant.id,
                name=_SUCURSAL_PRINCIPAL_NAME,
                address="",
                phone="",
                color_hex="",
                is_active=True,
                is_default=True,
            )
        elif not principal.is_default:
            principal.is_default = True
            principal.save(update_fields=["is_default"])

        # 2. Consultorios sin sucursal asignada → principal.
        Consultorio.objects.filter(tenant_id=tenant.id, sucursal__isnull=True).update(
            sucursal_id=principal.id
        )

        # 3. Doctor.sucursales (M2M) — agrega la principal si no la tiene ya.
        for doctor in Doctor.objects.filter(tenant_id=tenant.id).iterator():
            if not doctor.sucursales.filter(id=principal.id).exists():
                doctor.sucursales.add(principal)

        # 4. MembershipSucursal(membership, principal) por cada membresía activa.
        memberships = TenantMembership.objects.filter(
            tenant_id=tenant.id, is_active=True, deleted_at__isnull=True
        )
        for membership in memberships.iterator():
            already_assigned = MembershipSucursal.objects.filter(
                membership_id=membership.id, sucursal_id=principal.id
            ).exists()
            if not already_assigned:
                MembershipSucursal.objects.create(
                    tenant_id=tenant.id,
                    membership_id=membership.id,
                    sucursal_id=principal.id,
                )


class Migration(migrations.Migration):

    dependencies = [
        ("personal", "0008_consultorio_sucursal_doctor_sucursales"),
        ("clinica", "0018_rls_membership_sucursales"),
        ("tenancy", "0005_seed_plans"),
    ]

    operations = [
        migrations.RunPython(backfill_sucursal_principal, migrations.RunPython.noop),
    ]
