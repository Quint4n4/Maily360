"""
Migración manual: habilita Row Level Security en las tablas de finanzas.

Política de aislamiento por tenant usando current_tenant_id() (función
PostgreSQL definida en tenancy/0002_enable_rls.py), idéntica a pacientes/agenda.

OR current_tenant_id() IS NULL:
  Permite que Celery, management commands y migraciones accedan sin contexto.
  En un request HTTP el middleware siempre setea el tenant.

FORCE ROW LEVEL SECURITY:
  Aplica la política incluso al rol owner de la app para que no pueda
  bypassear accidentalmente en un path sin contexto.
"""

from django.db import migrations

# Tablas de finanzas con su política de aislamiento por tenant.
_TABLES = [
    "finanzas_service_concepts",
    "finanzas_fiscal_configs",
    "finanzas_quotes",
    "finanzas_quote_items",
    "finanzas_charges",
    "finanzas_payments",
    "finanzas_payment_allocations",
    "finanzas_cfdi_documents",
]


def _enable_sql(table: str) -> str:
    policy = f"{table}_tenant_isolation"
    return f"""
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
CREATE POLICY {policy} ON {table}
    USING (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL);
"""


def _disable_sql(table: str) -> str:
    policy = f"{table}_tenant_isolation"
    return f"""
DROP POLICY IF EXISTS {policy} ON {table};
ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    """Activa RLS en todas las tablas del dominio finanzas."""

    dependencies = [
        ("finanzas", "0001_initial"),
        # current_tenant_id() debe existir antes de crear las policies.
        ("tenancy", "0002_enable_rls"),
    ]

    operations = [
        migrations.RunSQL(sql=_enable_sql(table), reverse_sql=_disable_sql(table))
        for table in _TABLES
    ]
