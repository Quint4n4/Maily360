"""
Migración manual: habilita Row Level Security en la tabla de expediente.

Política de aislamiento por tenant usando current_tenant_id() (función
PostgreSQL definida en tenancy/0002_enable_rls.py).

OR current_tenant_id() IS NULL:
  Permite que Celery, management commands y migraciones accedan sin contexto.
  En un request HTTP el middleware siempre setea el tenant, así que la
  condición `= current_tenant_id()` es la que opera en producción.

FORCE ROW LEVEL SECURITY:
  Aplica la política incluso al rol owner/superuser de la app para que no pueda
  bypassear accidentalmente en un path de código sin contexto. La cláusula
  `OR current_tenant_id() IS NULL` cubre las migraciones.
"""

from django.db import migrations

TABLE = "expediente_allergies"
POLICY = "expediente_allergies_tenant_isolation"

ENABLE_RLS = f"""
ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY {POLICY} ON {TABLE}
    USING (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL);
"""

DISABLE_RLS = f"""
DROP POLICY IF EXISTS {POLICY} ON {TABLE};
ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    """Activa RLS en expediente_allergies."""

    dependencies = [
        ("expediente", "0001_initial"),
        # Necesitamos que current_tenant_id() exista antes de crear la policy.
        ("tenancy", "0002_enable_rls"),
    ]

    operations = [
        migrations.RunSQL(
            sql=ENABLE_RLS,
            reverse_sql=DISABLE_RLS,
        ),
    ]
