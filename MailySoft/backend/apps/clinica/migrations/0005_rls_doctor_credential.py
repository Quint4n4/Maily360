"""
Migración manual: habilita Row Level Security en clinica_doctor_credentials.

Política de aislamiento por tenant usando current_tenant_id() (función
PostgreSQL definida en tenancy/0002_enable_rls.py).

Misma estructura que clinica/0002_enable_rls.py.

USING  (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL)
WITH CHECK (tenant_id = current_tenant_id())

El OR IS NULL cubre migraciones, management commands y Celery sin contexto HTTP.
"""

from django.db import migrations

_TABLE = "clinica_doctor_credentials"
_POLICY = "clinica_doctor_credentials_tenant_isolation"
_ALLOW_NULL = "OR current_tenant_id() IS NULL"

_ENABLE_SQL = f"""
ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY {_POLICY} ON {_TABLE}
    USING (tenant_id = current_tenant_id() {_ALLOW_NULL})
    WITH CHECK (tenant_id = current_tenant_id());
"""

_DISABLE_SQL = f"""
DROP POLICY IF EXISTS {_POLICY} ON {_TABLE};
ALTER TABLE {_TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    """Activa RLS en la tabla clinica_doctor_credentials."""

    dependencies = [
        ("clinica", "0004_f2_commercial_name_doctor_credential"),
        # current_tenant_id() debe existir antes de crear las policies.
        ("tenancy", "0002_enable_rls"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_ENABLE_SQL,
            reverse_sql=_DISABLE_SQL,
        ),
    ]
