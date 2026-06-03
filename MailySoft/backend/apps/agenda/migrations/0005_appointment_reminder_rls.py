"""
Migración manual: habilita Row Level Security en agenda_appointment_reminders.

Replica el patrón de aislamiento por tenant de las demás tablas:
  - ENABLE + FORCE ROW LEVEL SECURITY.
  - Política USING (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL).

OR current_tenant_id() IS NULL:
    Permite que la tarea Celery `send_appointment_reminder` (que corre sin
    contexto de request) cargue el recordatorio por id. El aislamiento real en
    ese flujo lo da el UUID directo; la política protege las queries con contexto.
"""

from django.db import migrations

REMINDERS_TABLE = "agenda_appointment_reminders"
REMINDERS_POLICY = "agenda_appointment_reminders_tenant_isolation"

ENABLE_RLS_REMINDERS = f"""
ALTER TABLE {REMINDERS_TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {REMINDERS_TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY {REMINDERS_POLICY} ON {REMINDERS_TABLE}
    USING (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL);
"""

DISABLE_RLS_REMINDERS = f"""
DROP POLICY IF EXISTS {REMINDERS_POLICY} ON {REMINDERS_TABLE};
ALTER TABLE {REMINDERS_TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    """Activa RLS en agenda_appointment_reminders."""

    dependencies = [
        ("agenda", "0004_appointmentreminder"),
        # current_tenant_id() debe existir antes de crear la policy.
        ("tenancy", "0002_enable_rls"),
    ]

    operations = [
        migrations.RunSQL(
            sql=ENABLE_RLS_REMINDERS,
            reverse_sql=DISABLE_RLS_REMINDERS,
        ),
    ]
