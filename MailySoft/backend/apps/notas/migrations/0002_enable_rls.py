"""
Migración manual: habilita Row Level Security en notas_notes.

Replica el patrón de aislamiento por tenant de las demás tablas:
  - ENABLE + FORCE ROW LEVEL SECURITY.
  - Política USING (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL)
    + WITH CHECK con la misma condición (sin WITH CHECK los INSERT no quedan
    restringidos por tenant — mismo defecto ALTO-2 corregido en
    expediente/0005_rls_with_check.py).

OR current_tenant_id() IS NULL:
    Permite que management commands, seeds y migraciones accedan sin contexto
    de request. El aislamiento real en request context lo da la política.

FORCE ROW LEVEL SECURITY:
    Aplica la política incluso al rol owner/superuser de la app para que
    no pueda bypassear accidentalmente en un path de código sin contexto.

Fase 0 (auditoría de seguridad 2026-06-25): notas_notes es tenant-aware
(hereda TenantAwareModel) pero se creó sin migración de RLS. Esta migración
cierra esa brecha.
"""

from django.db import migrations

NOTES_TABLE = "notas_notes"
NOTES_POLICY = "notas_notes_tenant_isolation"

ENABLE_RLS_NOTES = f"""
ALTER TABLE {NOTES_TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {NOTES_TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY {NOTES_POLICY} ON {NOTES_TABLE}
    USING (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL)
    WITH CHECK (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL);
"""

DISABLE_RLS_NOTES = f"""
DROP POLICY IF EXISTS {NOTES_POLICY} ON {NOTES_TABLE};
ALTER TABLE {NOTES_TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    """Activa RLS en notas_notes."""

    dependencies = [
        ("notas", "0001_initial"),
        # current_tenant_id() debe existir antes de crear la policy.
        ("tenancy", "0002_enable_rls"),
    ]

    operations = [
        migrations.RunSQL(
            sql=ENABLE_RLS_NOTES,
            reverse_sql=DISABLE_RLS_NOTES,
        ),
    ]
