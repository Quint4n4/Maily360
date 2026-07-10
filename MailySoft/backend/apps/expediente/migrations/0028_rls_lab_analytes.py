"""
Migración de seguridad: habilita RLS en expediente_lab_analytes.

Patrón idéntico al de 0026_rls_document_templates.py, con USING y WITH CHECK
desde el inicio (lección aprendida en 0003_rls_with_check.py — ALTO-2: una
policy creada solo con USING no restringe INSERT).

Reversible: la dirección inversa deshabilita RLS y elimina la política.
"""

from django.db import migrations

_TABLE = "expediente_lab_analytes"
_POLICY = "exp_lab_analytes_tenant_iso"
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
    """Habilita RLS con USING y WITH CHECK en expediente_lab_analytes."""

    dependencies = [
        ("expediente", "0027_labanalyte"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_FORWARD_SQL,
            reverse_sql=_REVERSE_SQL,
        ),
    ]
