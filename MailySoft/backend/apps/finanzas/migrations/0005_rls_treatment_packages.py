"""
Migración de seguridad: habilita RLS en las 2 tablas de Paquetes de
Tratamientos (finanzas_treatment_packages, finanzas_treatment_package_items).

Patrón idéntico al de expediente/0020_rls_treatment_plans.py, con USING y
WITH CHECK desde el inicio (lección aprendida en 0003_rls_with_check.py —
ALTO-2: una policy creada solo con USING no restringe INSERT).

Configuración por tabla:
    ENABLE ROW LEVEL SECURITY — activa RLS en la tabla.
    FORCE ROW LEVEL SECURITY  — aplica RLS también al propietario de la tabla
                                 (el usuario de Django con el que corre la app).
    POLICY USING + WITH CHECK — el tenant_id del row debe coincidir con el
                                 current_tenant_id() del contexto activo.
                                 La cláusula IS NULL preserva acceso de Celery,
                                 management commands y migraciones (sin tenant activo).

Reversible: la dirección inversa deshabilita RLS y elimina la política de
cada tabla.
"""

from django.db import migrations

_TENANT_CONDITION: str = "tenant_id = current_tenant_id() OR current_tenant_id() IS NULL"

_TABLES_AND_POLICIES: tuple[tuple[str, str], ...] = (
    ("finanzas_treatment_packages", "finanzas_treatment_packages_tenant_iso"),
    ("finanzas_treatment_package_items", "finanzas_treatment_package_items_tenant_iso"),
)


def _forward_sql() -> str:
    statements: list[str] = []
    for table, policy in _TABLES_AND_POLICIES:
        statements.append(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        statements.append(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        statements.append(
            f"CREATE POLICY {policy} ON {table} "
            f"USING ({_TENANT_CONDITION}) "
            f"WITH CHECK ({_TENANT_CONDITION});"
        )
    return "\n".join(statements)


def _reverse_sql() -> str:
    statements: list[str] = []
    for table, policy in _TABLES_AND_POLICIES:
        statements.append(f"DROP POLICY IF EXISTS {policy} ON {table};")
        statements.append(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
    return "\n".join(statements)


class Migration(migrations.Migration):
    """Habilita RLS con USING y WITH CHECK en las 2 tablas de Paquetes de Tratamientos."""

    dependencies = [
        ("finanzas", "0004_treatmentpackage_treatmentpackageitem_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_forward_sql(),
            reverse_sql=_reverse_sql(),
        ),
    ]
