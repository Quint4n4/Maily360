"""
Migración de seguridad: habilita Row Level Security en recetas_prescription_formats (F3).

Política:
    USING:      tenant_id = current_tenant_id() OR current_tenant_id() IS NULL
    WITH CHECK: tenant_id = current_tenant_id() OR current_tenant_id() IS NULL

    La cláusula IS NULL permite que Celery, management commands y migraciones
    accedan sin contexto HTTP (donde current_tenant_id() devuelve NULL).

FORCE ROW LEVEL SECURITY:
    Aplica la política incluso al rol owner de PostgreSQL.

Reversibilidad: la migración inversa elimina las políticas y deshabilita RLS.
"""

from django.db import migrations

_TABLE: str = "recetas_prescription_formats"
_POLICY: str = "recetas_prescription_formats_tenant_isolation"
_CONDITION: str = "tenant_id = current_tenant_id() OR current_tenant_id() IS NULL"

_ENABLE_SQL: str = f"""
ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY {_POLICY} ON {_TABLE}
    USING ({_CONDITION})
    WITH CHECK ({_CONDITION});
"""

_DISABLE_SQL: str = f"""
DROP POLICY IF EXISTS {_POLICY} ON {_TABLE};
ALTER TABLE {_TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    """Activa RLS en recetas_prescription_formats."""

    dependencies = [
        ("recetas", "0006_f3_prescription_format"),
        # current_tenant_id() debe existir antes de crear la policy.
        ("tenancy", "0002_enable_rls"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_ENABLE_SQL,
            reverse_sql=_DISABLE_SQL,
        ),
    ]
