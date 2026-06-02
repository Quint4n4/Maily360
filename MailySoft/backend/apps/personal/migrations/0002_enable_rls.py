"""
Migración manual: habilita Row Level Security en las tablas de personal.

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

Tablas cubiertas:
  - personal_doctors
  - personal_consultorios
  - personal_doctor_schedules
"""

from django.db import migrations

# ---------------------------------------------------------------------------
# personal_doctors
# ---------------------------------------------------------------------------

DOCTORS_TABLE = "personal_doctors"
DOCTORS_POLICY = "personal_doctors_tenant_isolation"

ENABLE_RLS_DOCTORS = f"""
ALTER TABLE {DOCTORS_TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {DOCTORS_TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY {DOCTORS_POLICY} ON {DOCTORS_TABLE}
    USING (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL);
"""

DISABLE_RLS_DOCTORS = f"""
DROP POLICY IF EXISTS {DOCTORS_POLICY} ON {DOCTORS_TABLE};
ALTER TABLE {DOCTORS_TABLE} DISABLE ROW LEVEL SECURITY;
"""

# ---------------------------------------------------------------------------
# personal_consultorios
# ---------------------------------------------------------------------------

CONSULTORIOS_TABLE = "personal_consultorios"
CONSULTORIOS_POLICY = "personal_consultorios_tenant_isolation"

ENABLE_RLS_CONSULTORIOS = f"""
ALTER TABLE {CONSULTORIOS_TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {CONSULTORIOS_TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY {CONSULTORIOS_POLICY} ON {CONSULTORIOS_TABLE}
    USING (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL);
"""

DISABLE_RLS_CONSULTORIOS = f"""
DROP POLICY IF EXISTS {CONSULTORIOS_POLICY} ON {CONSULTORIOS_TABLE};
ALTER TABLE {CONSULTORIOS_TABLE} DISABLE ROW LEVEL SECURITY;
"""

# ---------------------------------------------------------------------------
# personal_doctor_schedules
# ---------------------------------------------------------------------------

SCHEDULES_TABLE = "personal_doctor_schedules"
SCHEDULES_POLICY = "personal_doctor_schedules_tenant_isolation"

ENABLE_RLS_SCHEDULES = f"""
ALTER TABLE {SCHEDULES_TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {SCHEDULES_TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY {SCHEDULES_POLICY} ON {SCHEDULES_TABLE}
    USING (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL);
"""

DISABLE_RLS_SCHEDULES = f"""
DROP POLICY IF EXISTS {SCHEDULES_POLICY} ON {SCHEDULES_TABLE};
ALTER TABLE {SCHEDULES_TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    """Activa RLS en las tres tablas de la app personal."""

    dependencies = [
        ("personal", "0001_initial"),
        # Necesitamos que current_tenant_id() exista antes de crear las policies.
        ("tenancy", "0002_enable_rls"),
    ]

    operations = [
        migrations.RunSQL(
            sql=ENABLE_RLS_DOCTORS,
            reverse_sql=DISABLE_RLS_DOCTORS,
        ),
        migrations.RunSQL(
            sql=ENABLE_RLS_CONSULTORIOS,
            reverse_sql=DISABLE_RLS_CONSULTORIOS,
        ),
        migrations.RunSQL(
            sql=ENABLE_RLS_SCHEDULES,
            reverse_sql=DISABLE_RLS_SCHEDULES,
        ),
    ]
