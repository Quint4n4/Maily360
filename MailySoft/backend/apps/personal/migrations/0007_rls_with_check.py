"""
Migración de seguridad: agrega WITH CHECK a las políticas RLS de personal.

Mismo defecto ALTO-2 corregido en expediente/0005_rls_with_check.py: las políticas
se crearon solo con USING, que protege SELECT/UPDATE/DELETE pero NO restringe
INSERT, por lo que un INSERT con tenant_id ajeno pasaba la barrera de base de datos.

La condición es idéntica a la del USING (el OR IS NULL preserva Celery,
management commands y migraciones fuera de contexto de request).

Reversibilidad: ALTER POLICY con solo USING elimina el WITH CHECK.
"""

from django.db import migrations

# Constantes de tabla y política — nunca interpolar input del usuario en SQL.
_POLICIES: list[tuple[str, str]] = [
    ("personal_doctors", "personal_doctors_tenant_isolation"),
    ("personal_doctor_schedules", "personal_doctor_schedules_tenant_isolation"),
    ("personal_consultorios", "personal_consultorios_tenant_isolation"),
]

_TENANT_CONDITION: str = "tenant_id = current_tenant_id() OR current_tenant_id() IS NULL"


def _add_with_check(table: str, policy: str) -> str:
    return f"ALTER POLICY {policy} ON {table} WITH CHECK ({_TENANT_CONDITION});"


def _remove_with_check(table: str, policy: str) -> str:
    return f"ALTER POLICY {policy} ON {table} USING ({_TENANT_CONDITION});"


class Migration(migrations.Migration):
    """Añade WITH CHECK a las políticas RLS de personal creadas solo con USING."""

    dependencies = [
        ("personal", "0006_alter_doctor_foto_alter_doctor_sello"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_add_with_check(table, policy),
            reverse_sql=_remove_with_check(table, policy),
        )
        for table, policy in _POLICIES
    ]
