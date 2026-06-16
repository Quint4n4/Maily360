"""
Migración de seguridad: agrega WITH CHECK a las políticas RLS existentes.

ALTO-2: las políticas creadas en 0002_enable_rls.py y 0004_enable_rls_medical_history.py
usaban solo la cláusula USING, que en PostgreSQL protege SELECT, UPDATE y DELETE
pero NO cubre INSERT. Cualquier INSERT pasaba sin filtro de tenant.

Esta migración usa ALTER POLICY para añadir WITH CHECK con la misma condición
que el USING, de modo que los INSERT también queden restringidos por tenant.

Condición aplicada a ambas tablas:
    tenant_id = current_tenant_id() OR current_tenant_id() IS NULL

La cláusula IS NULL preserva el acceso de Celery, management commands y migraciones
que se ejecutan fuera del contexto HTTP (donde current_tenant_id() devuelve NULL).

Reversibilidad: en la dirección inversa se elimina el WITH CHECK volviendo a una
política solo-USING (ALTER POLICY sin WITH CHECK lo elimina).

Nombres de política tomados literalmente de las migraciones que las crean:
    0002_enable_rls.py        → POLICY_ALLERGIES
    0004_enable_rls_medical_history.py → POLICY_HISTORIES
"""

from django.db import migrations

# Constantes de tabla y política — nunca interpolar input del usuario en SQL.
TABLE_ALLERGIES: str = "expediente_allergies"
POLICY_ALLERGIES: str = "expediente_allergies_tenant_isolation"

TABLE_HISTORIES: str = "expediente_medical_histories"
POLICY_HISTORIES: str = "expediente_medical_histories_tenant_isolation"

# Condición idéntica a la del USING ya existente.
_TENANT_CONDITION: str = "tenant_id = current_tenant_id() OR current_tenant_id() IS NULL"

# ---------------------------------------------------------------------------
# SQL — dirección FORWARD: añadir WITH CHECK a las dos políticas
# ---------------------------------------------------------------------------

ADD_WITH_CHECK_ALLERGIES: str = f"""
ALTER POLICY {POLICY_ALLERGIES} ON {TABLE_ALLERGIES}
    WITH CHECK ({_TENANT_CONDITION});
"""

ADD_WITH_CHECK_HISTORIES: str = f"""
ALTER POLICY {POLICY_HISTORIES} ON {TABLE_HISTORIES}
    WITH CHECK ({_TENANT_CONDITION});
"""

# ---------------------------------------------------------------------------
# SQL — dirección REVERSE: eliminar WITH CHECK dejando solo USING
# (ALTER POLICY sin WITH CHECK lo descarta; USING se conserva)
# ---------------------------------------------------------------------------

REMOVE_WITH_CHECK_ALLERGIES: str = f"""
ALTER POLICY {POLICY_ALLERGIES} ON {TABLE_ALLERGIES}
    USING ({_TENANT_CONDITION});
"""

REMOVE_WITH_CHECK_HISTORIES: str = f"""
ALTER POLICY {POLICY_HISTORIES} ON {TABLE_HISTORIES}
    USING ({_TENANT_CONDITION});
"""


class Migration(migrations.Migration):
    """Añade WITH CHECK a las políticas RLS de expediente (ALTO-2)."""

    dependencies = [
        ("expediente", "0004_enable_rls_medical_history"),
    ]

    operations = [
        migrations.RunSQL(
            sql=ADD_WITH_CHECK_ALLERGIES,
            reverse_sql=REMOVE_WITH_CHECK_ALLERGIES,
        ),
        migrations.RunSQL(
            sql=ADD_WITH_CHECK_HISTORIES,
            reverse_sql=REMOVE_WITH_CHECK_HISTORIES,
        ),
    ]
