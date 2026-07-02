"""
Migración de seguridad: agrega WITH CHECK a la política RLS de notificaciones.

Mismo defecto ALTO-2 corregido en expediente/0005_rls_with_check.py: la política
se creó solo con USING, que protege SELECT/UPDATE/DELETE pero NO restringe
INSERT, por lo que un INSERT con tenant_id ajeno pasaba la barrera de base de datos.

La condición es idéntica a la del USING (el OR IS NULL preserva Celery,
management commands y migraciones fuera de contexto de request).

Reversibilidad: ALTER POLICY con solo USING elimina el WITH CHECK.
"""

from django.db import migrations

# Constantes de tabla y política — nunca interpolar input del usuario en SQL.
_TABLE: str = "notificaciones_notifications"
_POLICY: str = "notificaciones_notifications_tenant_isolation"

_TENANT_CONDITION: str = "tenant_id = current_tenant_id() OR current_tenant_id() IS NULL"

ADD_WITH_CHECK: str = f"ALTER POLICY {_POLICY} ON {_TABLE} WITH CHECK ({_TENANT_CONDITION});"
REMOVE_WITH_CHECK: str = f"ALTER POLICY {_POLICY} ON {_TABLE} USING ({_TENANT_CONDITION});"


class Migration(migrations.Migration):
    """Añade WITH CHECK a la política RLS de notificaciones creada solo con USING."""

    dependencies = [
        ("notificaciones", "0004_alter_notification_kind_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql=ADD_WITH_CHECK,
            reverse_sql=REMOVE_WITH_CHECK,
        ),
    ]
