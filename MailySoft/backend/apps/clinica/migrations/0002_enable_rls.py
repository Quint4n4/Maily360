"""
Migración manual: habilita Row Level Security en las tablas de la app clinica.

Política de aislamiento por tenant usando current_tenant_id() (función
PostgreSQL definida en tenancy/0002_enable_rls.py).

OR current_tenant_id() IS NULL:
  Permite que Celery, management commands y migraciones accedan sin contexto.
  En un request HTTP el middleware siempre setea el tenant; la condición
  `= current_tenant_id()` es la que opera en producción.

WITH CHECK (tenant_id = current_tenant_id()):
  Previene que a través de RLS se inserte en un tenant diferente al contexto
  activo (defensa en profundidad sobre el filtro Django).

FORCE ROW LEVEL SECURITY:
  Aplica la política incluso al rol owner/superuser de la app.
  La cláusula `OR current_tenant_id() IS NULL` cubre las migraciones.

Tablas cubiertas:
  - clinica_settings
  - clinica_templates
  - clinica_patient_categories
  - clinica_doctor_universities
"""

from django.db import migrations

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALLOW_NULL = "OR current_tenant_id() IS NULL"


def _enable_sql(table: str, policy: str) -> str:
    return f"""
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
CREATE POLICY {policy} ON {table}
    USING (tenant_id = current_tenant_id() {ALLOW_NULL})
    WITH CHECK (tenant_id = current_tenant_id());
"""


def _disable_sql(table: str, policy: str) -> str:
    return f"""
DROP POLICY IF EXISTS {policy} ON {table};
ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
"""


# ---------------------------------------------------------------------------
# clinica_settings
# ---------------------------------------------------------------------------

_T1 = "clinica_settings"
_P1 = "clinica_settings_tenant_isolation"

# ---------------------------------------------------------------------------
# clinica_templates
# ---------------------------------------------------------------------------

_T2 = "clinica_templates"
_P2 = "clinica_templates_tenant_isolation"

# ---------------------------------------------------------------------------
# clinica_patient_categories
# ---------------------------------------------------------------------------

_T3 = "clinica_patient_categories"
_P3 = "clinica_patient_categories_tenant_isolation"

# ---------------------------------------------------------------------------
# clinica_doctor_universities
# ---------------------------------------------------------------------------

_T4 = "clinica_doctor_universities"
_P4 = "clinica_doctor_universities_tenant_isolation"


class Migration(migrations.Migration):
    """Activa RLS en las cuatro tablas de la app clinica."""

    dependencies = [
        ("clinica", "0001_initial"),
        # current_tenant_id() debe existir antes de crear las policies.
        ("tenancy", "0002_enable_rls"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_enable_sql(_T1, _P1),
            reverse_sql=_disable_sql(_T1, _P1),
        ),
        migrations.RunSQL(
            sql=_enable_sql(_T2, _P2),
            reverse_sql=_disable_sql(_T2, _P2),
        ),
        migrations.RunSQL(
            sql=_enable_sql(_T3, _P3),
            reverse_sql=_disable_sql(_T3, _P3),
        ),
        migrations.RunSQL(
            sql=_enable_sql(_T4, _P4),
            reverse_sql=_disable_sql(_T4, _P4),
        ),
    ]
