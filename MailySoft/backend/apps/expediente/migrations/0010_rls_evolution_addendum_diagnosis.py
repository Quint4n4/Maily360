"""
Migración de seguridad A4: habilita RLS en las tres tablas del expediente de evolución.

    expediente_evolution_notes — Notas de evolución (inmutables).
    expediente_addenda         — Addenda sobre notas de evolución.
    expediente_diagnoses       — Diagnósticos clínicos.

Patrón idéntico al de 0007_rls_vital_signs.py con USING y WITH CHECK desde el
inicio (lección aprendida en 0005_rls_with_check.py — ALTO-2).

Configuración por tabla:
    ENABLE ROW LEVEL SECURITY — activa RLS.
    FORCE ROW LEVEL SECURITY  — aplica RLS también al propietario de la tabla.
    POLICY USING + WITH CHECK — el tenant_id del row debe coincidir con el
                                 current_tenant_id() del contexto activo.
                                 La cláusula IS NULL preserva acceso de Celery,
                                 management commands y migraciones.

Reversible: la dirección inversa deshabilita RLS y elimina las políticas.
"""

from django.db import migrations

_TENANT_CONDITION: str = "tenant_id = current_tenant_id() OR current_tenant_id() IS NULL"

# ---------------------------------------------------------------------------
# Tablas y nombres de política
# ---------------------------------------------------------------------------

_TABLES = [
    ("expediente_evolution_notes", "exp_evolution_notes_tenant_iso"),
    ("expediente_addenda", "exp_addenda_tenant_iso"),
    ("expediente_diagnoses", "exp_diagnoses_tenant_iso"),
]

# ---------------------------------------------------------------------------
# Helpers para generar SQL por tabla
# ---------------------------------------------------------------------------


def _enable_sql(table: str, policy: str) -> str:
    return "\n".join(
        [
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
            (
                f"CREATE POLICY {policy} ON {table} "
                f"USING ({_TENANT_CONDITION}) "
                f"WITH CHECK ({_TENANT_CONDITION});"
            ),
        ]
    )


def _disable_sql(table: str, policy: str) -> str:
    return "\n".join(
        [
            f"DROP POLICY IF EXISTS {policy} ON {table};",
            f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;",
        ]
    )


# ---------------------------------------------------------------------------
# SQL consolidado — forward y reverse
# ---------------------------------------------------------------------------

_FORWARD_SQL: str = "\n\n".join(_enable_sql(t, p) for t, p in _TABLES)
_REVERSE_SQL: str = "\n\n".join(_disable_sql(t, p) for t, p in reversed(_TABLES))


class Migration(migrations.Migration):
    """Habilita RLS con USING y WITH CHECK en las 3 tablas de A4 (ALTO-2)."""

    dependencies = [
        ("expediente", "0009_add_evolution_addendum_diagnosis"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_FORWARD_SQL,
            reverse_sql=_REVERSE_SQL,
        ),
    ]
