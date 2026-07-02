"""
Migración manual: habilita Row Level Security en agenda_appointment_types,
agenda_blocks y agenda_item_notes.

Replica el patrón de aislamiento por tenant de las demás tablas:
  - ENABLE + FORCE ROW LEVEL SECURITY.
  - Política USING (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL)
    + WITH CHECK con la misma condición (sin WITH CHECK los INSERT no quedan
    restringidos por tenant — mismo defecto ALTO-2 corregido en
    expediente/0005_rls_with_check.py).

OR current_tenant_id() IS NULL:
    Permite que Celery, management commands y migraciones accedan sin
    contexto de request. El aislamiento real en request context lo da la
    política.

FORCE ROW LEVEL SECURITY:
    Aplica la política incluso al rol owner/superuser de la app para que
    no pueda bypassear accidentalmente en un path de código sin contexto.

Fase 0 (auditoría de seguridad 2026-06-25): estas tres tablas son
tenant-aware (heredan TenantAwareModel) pero se crearon sin migración de
RLS (0006_alter_appointment_reason_and_more.py, 0007_agendablock.py y
0008_agendaitemnote.py no incluyeron la política). Esta migración cierra
esa brecha.
"""

from django.db import migrations

APPOINTMENT_TYPES_TABLE = "agenda_appointment_types"
APPOINTMENT_TYPES_POLICY = "agenda_appointment_types_tenant_isolation"

ENABLE_RLS_APPOINTMENT_TYPES = f"""
ALTER TABLE {APPOINTMENT_TYPES_TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {APPOINTMENT_TYPES_TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY {APPOINTMENT_TYPES_POLICY} ON {APPOINTMENT_TYPES_TABLE}
    USING (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL)
    WITH CHECK (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL);
"""

DISABLE_RLS_APPOINTMENT_TYPES = f"""
DROP POLICY IF EXISTS {APPOINTMENT_TYPES_POLICY} ON {APPOINTMENT_TYPES_TABLE};
ALTER TABLE {APPOINTMENT_TYPES_TABLE} DISABLE ROW LEVEL SECURITY;
"""

BLOCKS_TABLE = "agenda_blocks"
BLOCKS_POLICY = "agenda_blocks_tenant_isolation"

ENABLE_RLS_BLOCKS = f"""
ALTER TABLE {BLOCKS_TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {BLOCKS_TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY {BLOCKS_POLICY} ON {BLOCKS_TABLE}
    USING (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL)
    WITH CHECK (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL);
"""

DISABLE_RLS_BLOCKS = f"""
DROP POLICY IF EXISTS {BLOCKS_POLICY} ON {BLOCKS_TABLE};
ALTER TABLE {BLOCKS_TABLE} DISABLE ROW LEVEL SECURITY;
"""

ITEM_NOTES_TABLE = "agenda_item_notes"
ITEM_NOTES_POLICY = "agenda_item_notes_tenant_isolation"

ENABLE_RLS_ITEM_NOTES = f"""
ALTER TABLE {ITEM_NOTES_TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {ITEM_NOTES_TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY {ITEM_NOTES_POLICY} ON {ITEM_NOTES_TABLE}
    USING (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL)
    WITH CHECK (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL);
"""

DISABLE_RLS_ITEM_NOTES = f"""
DROP POLICY IF EXISTS {ITEM_NOTES_POLICY} ON {ITEM_NOTES_TABLE};
ALTER TABLE {ITEM_NOTES_TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    """Activa RLS en agenda_appointment_types, agenda_blocks y agenda_item_notes."""

    dependencies = [
        ("agenda", "0011_appointment_quote"),
        # current_tenant_id() debe existir antes de crear las policies.
        ("tenancy", "0002_enable_rls"),
    ]

    operations = [
        migrations.RunSQL(
            sql=ENABLE_RLS_APPOINTMENT_TYPES,
            reverse_sql=DISABLE_RLS_APPOINTMENT_TYPES,
        ),
        migrations.RunSQL(
            sql=ENABLE_RLS_BLOCKS,
            reverse_sql=DISABLE_RLS_BLOCKS,
        ),
        migrations.RunSQL(
            sql=ENABLE_RLS_ITEM_NOTES,
            reverse_sql=DISABLE_RLS_ITEM_NOTES,
        ),
    ]
