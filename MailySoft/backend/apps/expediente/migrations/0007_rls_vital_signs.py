"""
Migración de seguridad A3: habilita RLS en expediente_vital_signs.

Patrón idéntico al de 0002_enable_rls.py y 0004_enable_rls_medical_history.py,
con WITH CHECK desde el inicio (lección aprendida en 0005_rls_with_check.py).

Configuración:
    ENABLE ROW LEVEL SECURITY — activa RLS en la tabla.
    FORCE ROW LEVEL SECURITY  — aplica RLS también al propietario de la tabla
                                (rol de app, no superusuario).
    POLICY USING + WITH CHECK — el tenant_id del row debe coincidir con el
                                 current_tenant_id() del contexto activo.
                                 La cláusula IS NULL preserva acceso de Celery,
                                 management commands y migraciones que corren
                                 fuera de contexto HTTP.

Reversible: la dirección inversa deshabilita RLS y elimina la política.

ALTO-2: incluir WITH CHECK en la política original (no en una migración posterior)
para proteger INSERT desde el primer momento.
"""

from django.db import migrations

TABLE: str = "expediente_vital_signs"
POLICY: str = "expediente_vital_signs_tenant_isolation"

_TENANT_CONDITION: str = "tenant_id = current_tenant_id() OR current_tenant_id() IS NULL"

# ---------------------------------------------------------------------------
# SQL — dirección FORWARD
# ---------------------------------------------------------------------------

ENABLE_RLS: str = f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY;"
FORCE_RLS: str = f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY;"
CREATE_POLICY: str = f"""
CREATE POLICY {POLICY} ON {TABLE}
    USING ({_TENANT_CONDITION})
    WITH CHECK ({_TENANT_CONDITION});
"""

# ---------------------------------------------------------------------------
# SQL — dirección REVERSE
# ---------------------------------------------------------------------------

DROP_POLICY: str = f"DROP POLICY IF EXISTS {POLICY} ON {TABLE};"
DISABLE_RLS: str = f"ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY;"


class Migration(migrations.Migration):
    """Habilita RLS con USING y WITH CHECK en expediente_vital_signs (ALTO-2)."""

    dependencies = [
        ("expediente", "0006_add_vital_signs"),
    ]

    operations = [
        migrations.RunSQL(
            sql="\n".join([ENABLE_RLS, FORCE_RLS, CREATE_POLICY]),
            reverse_sql="\n".join([DROP_POLICY, DISABLE_RLS]),
        ),
    ]
