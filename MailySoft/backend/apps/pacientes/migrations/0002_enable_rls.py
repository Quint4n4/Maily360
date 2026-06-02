"""
Migración manual: habilita Row Level Security en las tablas de pacientes.

Política de aislamiento por tenant usando current_tenant_id() (función
PostgreSQL definida en tenancy/0002_enable_rls.py).

OR current_tenant_id() IS NULL:
  Permite que Celery, management commands y migraciones accedan sin contexto.
  En un request HTTP el middleware siempre setea el tenant, así que la
  condición `= current_tenant_id()` es la que opera en producción.

FORCE ROW LEVEL SECURITY:
  Aplica la política incluso al rol owner/superuser de la app para que
  no pueda bypassear accidentalmente en un path de código sin contexto.
  La cláusula `OR current_tenant_id() IS NULL` cubre las migraciones.
"""

from django.db import migrations

# ---------------------------------------------------------------------------
# pacientes_patients
# ---------------------------------------------------------------------------

PATIENTS_TABLE = "pacientes_patients"
PATIENTS_POLICY = "pacientes_patients_tenant_isolation"

ENABLE_RLS_PATIENTS = f"""
ALTER TABLE {PATIENTS_TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {PATIENTS_TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY {PATIENTS_POLICY} ON {PATIENTS_TABLE}
    USING (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL);
"""

DISABLE_RLS_PATIENTS = f"""
DROP POLICY IF EXISTS {PATIENTS_POLICY} ON {PATIENTS_TABLE};
ALTER TABLE {PATIENTS_TABLE} DISABLE ROW LEVEL SECURITY;
"""

# ---------------------------------------------------------------------------
# pacientes_patient_sequences
# ---------------------------------------------------------------------------

SEQUENCES_TABLE = "pacientes_patient_sequences"
SEQUENCES_POLICY = "pacientes_patient_sequences_tenant_isolation"

ENABLE_RLS_SEQUENCES = f"""
ALTER TABLE {SEQUENCES_TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {SEQUENCES_TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY {SEQUENCES_POLICY} ON {SEQUENCES_TABLE}
    USING (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL);
"""

DISABLE_RLS_SEQUENCES = f"""
DROP POLICY IF EXISTS {SEQUENCES_POLICY} ON {SEQUENCES_TABLE};
ALTER TABLE {SEQUENCES_TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    """Activa RLS en pacientes_patients y pacientes_patient_sequences."""

    dependencies = [
        ("pacientes", "0001_initial"),
        # Necesitamos que current_tenant_id() exista antes de crear las policies.
        ("tenancy", "0002_enable_rls"),
    ]

    operations = [
        migrations.RunSQL(
            sql=ENABLE_RLS_PATIENTS,
            reverse_sql=DISABLE_RLS_PATIENTS,
        ),
        migrations.RunSQL(
            sql=ENABLE_RLS_SEQUENCES,
            reverse_sql=DISABLE_RLS_SEQUENCES,
        ),
    ]
