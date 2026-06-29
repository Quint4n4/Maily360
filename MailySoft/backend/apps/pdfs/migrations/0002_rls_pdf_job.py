"""
Migración de seguridad: habilita Row Level Security en pdfs_pdf_jobs.

Tabla:
  pdfs_pdf_jobs (PdfJob — por tenant):
    Trabajos genéricos de generación asíncrona de PDF. Misma política que el resto
    de tablas con tenant: solo el tenant activo ve/escribe sus jobs.

Política:
    USING:      tenant_id = current_tenant_id() OR current_tenant_id() IS NULL
    WITH CHECK: tenant_id = current_tenant_id() OR current_tenant_id() IS NULL

    La cláusula IS NULL permite que la tarea Celery (sin contexto HTTP) escriba el
    PDF; la propia tarea setea el contexto de tenant antes de operar (defensa extra).

FORCE ROW LEVEL SECURITY:
    Aplica la política incluso al rol owner de PostgreSQL.

Reversibilidad: la migración inversa elimina la policy y deshabilita RLS.
"""

from django.db import migrations

_TENANT_CONDITION: str = "tenant_id = current_tenant_id() OR current_tenant_id() IS NULL"

_TABLE: str = "pdfs_pdf_jobs"
_POLICY: str = "pdfs_pdf_jobs_tenant_isolation"

_ENABLE: str = f"""
ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY {_POLICY} ON {_TABLE}
    USING ({_TENANT_CONDITION})
    WITH CHECK ({_TENANT_CONDITION});
"""

_DISABLE: str = f"""
DROP POLICY IF EXISTS {_POLICY} ON {_TABLE};
ALTER TABLE {_TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    """Activa RLS en pdfs_pdf_jobs."""

    dependencies = [
        ("pdfs", "0001_initial"),
        # current_tenant_id() debe existir antes de crear la policy.
        ("tenancy", "0002_enable_rls"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_ENABLE,
            reverse_sql=_DISABLE,
        ),
    ]
