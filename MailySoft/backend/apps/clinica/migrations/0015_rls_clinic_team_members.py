"""
Migración de seguridad: habilita RLS en clinica_team_members.

Patrón idéntico al de 0013_rls_with_check_null_fallback.py y el resto de las
migraciones enable_rls/rls_* del proyecto, con USING y WITH CHECK desde el
inicio (lección aprendida en finanzas/0003_rls_with_check.py — ALTO-2: una
policy creada solo con USING no restringe INSERT).

Reversible: la dirección inversa deshabilita RLS y elimina la política.
"""

from django.db import migrations

_TABLE = "clinica_team_members"
_POLICY = "clinica_team_members_tenant_iso"
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
    """Habilita RLS con USING y WITH CHECK en clinica_team_members."""

    dependencies = [
        ("clinica", "0014_clinicteammember"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_FORWARD_SQL,
            reverse_sql=_REVERSE_SQL,
        ),
    ]
