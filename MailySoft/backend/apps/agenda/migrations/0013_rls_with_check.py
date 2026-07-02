"""
Migración de seguridad: agrega WITH CHECK a las políticas RLS existentes de agenda.

Mismo defecto ALTO-2 corregido en expediente/0005_rls_with_check.py: las políticas
creadas solo con USING protegen SELECT/UPDATE/DELETE pero NO restringen INSERT,
por lo que un INSERT con tenant_id ajeno pasaba la barrera de base de datos.

Cubre las tablas de agenda cuyas políticas se crearon sin WITH CHECK:
    agenda_appointments          (0004_appointments_rls)
    agenda_appointment_reminders (0005_appointment_reminder_rls)
    agenda_tenant_config         (su migración enable_rls original)

Las tablas agenda_appointment_types, agenda_blocks y agenda_item_notes NO van
aquí: su política nace ya con WITH CHECK en 0012_rls_appointment_types_blocks_item_notes.

La condición es idéntica a la del USING (el OR IS NULL preserva Celery,
management commands y migraciones fuera de contexto de request).

Reversibilidad: ALTER POLICY con solo USING elimina el WITH CHECK.
"""

from django.db import migrations

# Constantes de tabla y política — nunca interpolar input del usuario en SQL.
# Nombres tomados literalmente de pg_policies.
_POLICIES: list[tuple[str, str]] = [
    ("agenda_appointments", "agenda_appointments_tenant_isolation"),
    ("agenda_appointment_reminders", "agenda_appointment_reminders_tenant_isolation"),
    ("agenda_tenant_config", "agenda_tenant_config_tenant_isolation"),
]

_TENANT_CONDITION: str = "tenant_id = current_tenant_id() OR current_tenant_id() IS NULL"


def _add_with_check(table: str, policy: str) -> str:
    return f"ALTER POLICY {policy} ON {table} WITH CHECK ({_TENANT_CONDITION});"


def _remove_with_check(table: str, policy: str) -> str:
    return f"ALTER POLICY {policy} ON {table} USING ({_TENANT_CONDITION});"


class Migration(migrations.Migration):
    """Añade WITH CHECK a las políticas RLS de agenda creadas solo con USING."""

    dependencies = [
        ("agenda", "0012_rls_appointment_types_blocks_item_notes"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_add_with_check(table, policy),
            reverse_sql=_remove_with_check(table, policy),
        )
        for table, policy in _POLICIES
    ]
