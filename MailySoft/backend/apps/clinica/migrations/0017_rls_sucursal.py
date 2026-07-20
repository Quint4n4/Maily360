"""
Migración de seguridad: habilita RLS en clinica_sucursales.

Patrón idéntico al de 0015_rls_clinic_team_members.py y el resto de las
migraciones enable_rls/rls_* del proyecto, con USING y WITH CHECK desde el
inicio (lección aprendida en finanzas/0003_rls_with_check.py — ALTO-2: una
policy creada solo con USING no restringe INSERT) y el fallback
`OR current_tenant_id() IS NULL` (0013_rls_with_check_null_fallback.py —
necesario para INSERT sin GUC: alta de clínica, Celery, seeds, migraciones).

Nota (docs/design/sucursales-plan-implementacion.md, principio 2): esta RLS
sigue siendo por tenant_id, IGUAL que cualquier otra tabla tenant-aware. La
sucursal es una segunda dimensión de scoping OPERATIVO (ver
apps.clinica.sucursal_scope), NO una política RLS — dos sucursales del mismo
tenant NO están aisladas a nivel de base de datos por esta migración.

Reversible: la dirección inversa deshabilita RLS y elimina la política.
"""

from django.db import migrations

_TABLE = "clinica_sucursales"
_POLICY = "clinica_sucursales_tenant_iso"
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
    """Habilita RLS con USING y WITH CHECK en clinica_sucursales."""

    dependencies = [
        ("clinica", "0016_sucursal_membershipsucursal_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_FORWARD_SQL,
            reverse_sql=_REVERSE_SQL,
        ),
    ]
