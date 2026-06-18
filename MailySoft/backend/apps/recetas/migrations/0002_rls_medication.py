"""
Migración de seguridad: habilita Row Level Security en recetas_medications.

Decisión de RLS por tabla:
  recetas_medications (Medication — custom por tenant):
    Tabla con tenant_id: aplica política USING + WITH CHECK igual que las
    tablas de expediente. Solo el tenant activo puede ver y escribir sus
    medicamentos custom.

  recetas_global_medications (GlobalMedication — catálogo global):
    Tabla SIN tenant_id: no aplica política de aislamiento por tenant.
    La protección es de diseño en la capa de aplicación:
      - No existe endpoint de escritura para clientes sobre esta tabla.
      - El seed se ejecuta desde management command (sin contexto HTTP).
      - La política de PostgreSQL NO se aplica aquí para no bloquear
        el seed ni las migraciones que no tienen contexto de tenant.
    Si en el futuro se requiere mayor control a nivel BD, se puede añadir
    una política SELECT-only con USING (true) para cualquier rol de app.

Política de Medication:
    USING:      tenant_id = current_tenant_id() OR current_tenant_id() IS NULL
    WITH CHECK: tenant_id = current_tenant_id() OR current_tenant_id() IS NULL

    La cláusula IS NULL permite que Celery, management commands y migraciones
    accedan sin contexto HTTP (donde current_tenant_id() devuelve NULL).

FORCE ROW LEVEL SECURITY:
    Aplica la política incluso al rol owner de PostgreSQL para que no pueda
    bypassear accidentalmente en un path de código sin contexto.
    La cláusula OR IS NULL cubre los migrations.

Reversibilidad: la migración inversa elimina la política y deshabilita RLS,
dejando la tabla en su estado sin RLS.
"""

from django.db import migrations

# --- recetas_medications ---
TABLE: str = "recetas_medications"
POLICY: str = "recetas_medications_tenant_isolation"
_TENANT_CONDITION: str = "tenant_id = current_tenant_id() OR current_tenant_id() IS NULL"

ENABLE_RLS: str = f"""
ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY {POLICY} ON {TABLE}
    USING ({_TENANT_CONDITION})
    WITH CHECK ({_TENANT_CONDITION});
"""

DISABLE_RLS: str = f"""
DROP POLICY IF EXISTS {POLICY} ON {TABLE};
ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    """Activa RLS en recetas_medications (Medication custom por tenant).

    GlobalMedication (recetas_global_medications) se omite deliberadamente:
    tabla global sin tenant_id; la restricción de escritura es de aplicación,
    no de BD. Ver docstring del módulo.
    """

    dependencies = [
        ("recetas", "0001_initial"),
        # current_tenant_id() debe existir antes de crear la policy.
        ("tenancy", "0002_enable_rls"),
    ]

    operations = [
        migrations.RunSQL(
            sql=ENABLE_RLS,
            reverse_sql=DISABLE_RLS,
        ),
    ]
