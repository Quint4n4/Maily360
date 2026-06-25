"""
Migración de seguridad Fase 2: habilita RLS en expediente_medical_history_questions.

Patrón idéntico al de 0007_rls_vital_signs.py y 0013_rls_evolution_images.py,
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

_TABLE: str = "expediente_medical_history_questions"
_POLICY: str = "exp_mhq_tenant_iso"

_TENANT_CONDITION: str = "tenant_id = current_tenant_id() OR current_tenant_id() IS NULL"

# ---------------------------------------------------------------------------
# SQL — dirección FORWARD
# ---------------------------------------------------------------------------

_ENABLE_RLS: str = f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY;"
_FORCE_RLS: str = f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY;"
_CREATE_POLICY: str = f"""
CREATE POLICY {_POLICY} ON {_TABLE}
    USING ({_TENANT_CONDITION})
    WITH CHECK ({_TENANT_CONDITION});
"""

# ---------------------------------------------------------------------------
# SQL — dirección REVERSE
# ---------------------------------------------------------------------------

_DROP_POLICY: str = f"DROP POLICY IF EXISTS {_POLICY} ON {_TABLE};"
_DISABLE_RLS: str = f"ALTER TABLE {_TABLE} DISABLE ROW LEVEL SECURITY;"


class Migration(migrations.Migration):
    """Habilita RLS con USING y WITH CHECK en expediente_medical_history_questions (ALTO-2)."""

    dependencies = [
        ("expediente", "0014_medicalhistory_custom_answers_medicalhistoryquestion"),
    ]

    operations = [
        migrations.RunSQL(
            sql="\n".join([_ENABLE_RLS, _FORCE_RLS, _CREATE_POLICY]),
            reverse_sql="\n".join([_DROP_POLICY, _DISABLE_RLS]),
        ),
    ]
