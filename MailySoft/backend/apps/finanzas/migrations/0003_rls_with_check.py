"""
Migración de seguridad: agrega WITH CHECK a las políticas RLS de finanzas.

Mismo defecto ALTO-2 corregido en expediente/0005_rls_with_check.py: las políticas
de 0002_enable_rls.py se crearon solo con USING, que protege SELECT/UPDATE/DELETE
pero NO restringe INSERT, por lo que un INSERT con tenant_id ajeno pasaba la
barrera de base de datos.

La condición es idéntica a la del USING (el OR IS NULL preserva Celery,
management commands y migraciones fuera de contexto de request).

Reversibilidad: ALTER POLICY con solo USING elimina el WITH CHECK.
"""

from django.db import migrations

# Constantes de tabla y política — nunca interpolar input del usuario en SQL.
# Nombres tomados literalmente de pg_policies.
_POLICIES: list[tuple[str, str]] = [
    ("finanzas_service_concepts", "finanzas_service_concepts_tenant_isolation"),
    ("finanzas_quotes", "finanzas_quotes_tenant_isolation"),
    ("finanzas_quote_items", "finanzas_quote_items_tenant_isolation"),
    ("finanzas_charges", "finanzas_charges_tenant_isolation"),
    ("finanzas_payments", "finanzas_payments_tenant_isolation"),
    ("finanzas_payment_allocations", "finanzas_payment_allocations_tenant_isolation"),
    ("finanzas_cfdi_documents", "finanzas_cfdi_documents_tenant_isolation"),
    ("finanzas_fiscal_configs", "finanzas_fiscal_configs_tenant_isolation"),
]

_TENANT_CONDITION: str = "tenant_id = current_tenant_id() OR current_tenant_id() IS NULL"


def _add_with_check(table: str, policy: str) -> str:
    return f"ALTER POLICY {policy} ON {table} WITH CHECK ({_TENANT_CONDITION});"


def _remove_with_check(table: str, policy: str) -> str:
    return f"ALTER POLICY {policy} ON {table} USING ({_TENANT_CONDITION});"


class Migration(migrations.Migration):
    """Añade WITH CHECK a las políticas RLS de finanzas creadas solo con USING."""

    dependencies = [
        ("finanzas", "0002_enable_rls"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_add_with_check(table, policy),
            reverse_sql=_remove_with_check(table, policy),
        )
        for table, policy in _POLICIES
    ]
