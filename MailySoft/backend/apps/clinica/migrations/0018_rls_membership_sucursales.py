"""
Migración de seguridad: habilita RLS en tenancy_membership_sucursales.

Mismo patrón que 0017_rls_sucursal.py (USING + WITH CHECK + fallback NULL).
Ver ese módulo para el razonamiento completo.

Reversible: la dirección inversa deshabilita RLS y elimina la política.
"""

from django.db import migrations

_TABLE = "tenancy_membership_sucursales"
_POLICY = "tenancy_membership_sucursales_tenant_iso"
_TENANT_CONDITION: str = "tenant_id = current_tenant_id() OR current_tenant_id() IS NULL"

_FORWARD_SQL: str = "\n".join(
    [
        f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY;",
        f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY;",
        (
            f"CREATE POLICY {_POLICY} ON {_TABLE} "
            f"USING ({_TENANT_CONDITION}) "
            f"WITH CHECK ({_TENANT_CONDITION});"
        ),
    ]
)

_REVERSE_SQL: str = "\n".join(
    [
        f"DROP POLICY IF EXISTS {_POLICY} ON {_TABLE};",
        f"ALTER TABLE {_TABLE} DISABLE ROW LEVEL SECURITY;",
    ]
)


class Migration(migrations.Migration):
    """Habilita RLS con USING y WITH CHECK en tenancy_membership_sucursales."""

    dependencies = [
        ("clinica", "0017_rls_sucursal"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_FORWARD_SQL,
            reverse_sql=_REVERSE_SQL,
        ),
    ]
