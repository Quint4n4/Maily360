"""
Migración de seguridad: habilita Row Level Security en las tablas de recetas (B1.2).

Tablas:
  recetas_prescriptions (Prescription — por tenant):
    RLS USING + WITH CHECK igual que expediente y Medication.
    Garantiza que solo el tenant activo puede ver y escribir sus recetas.

  recetas_prescription_items (PrescriptionItem — por tenant):
    Misma política que Prescription.

Política:
    USING:      tenant_id = current_tenant_id() OR current_tenant_id() IS NULL
    WITH CHECK: tenant_id = current_tenant_id() OR current_tenant_id() IS NULL

    La cláusula IS NULL permite que Celery, management commands y migraciones
    accedan sin contexto HTTP (donde current_tenant_id() devuelve NULL).

FORCE ROW LEVEL SECURITY:
    Aplica la política incluso al rol owner de PostgreSQL.
    La cláusula OR IS NULL cubre las migraciones.

Reversibilidad: la migración inversa elimina las políticas y deshabilita RLS.
"""

from django.db import migrations

_TENANT_CONDITION: str = "tenant_id = current_tenant_id() OR current_tenant_id() IS NULL"

# --- recetas_prescriptions ---
_PRESCRIPTIONS_TABLE: str = "recetas_prescriptions"
_PRESCRIPTIONS_POLICY: str = "recetas_prescriptions_tenant_isolation"

_PRESCRIPTIONS_ENABLE: str = f"""
ALTER TABLE {_PRESCRIPTIONS_TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {_PRESCRIPTIONS_TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY {_PRESCRIPTIONS_POLICY} ON {_PRESCRIPTIONS_TABLE}
    USING ({_TENANT_CONDITION})
    WITH CHECK ({_TENANT_CONDITION});
"""

_PRESCRIPTIONS_DISABLE: str = f"""
DROP POLICY IF EXISTS {_PRESCRIPTIONS_POLICY} ON {_PRESCRIPTIONS_TABLE};
ALTER TABLE {_PRESCRIPTIONS_TABLE} DISABLE ROW LEVEL SECURITY;
"""

# --- recetas_prescription_items ---
_ITEMS_TABLE: str = "recetas_prescription_items"
_ITEMS_POLICY: str = "recetas_prescription_items_tenant_isolation"

_ITEMS_ENABLE: str = f"""
ALTER TABLE {_ITEMS_TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {_ITEMS_TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY {_ITEMS_POLICY} ON {_ITEMS_TABLE}
    USING ({_TENANT_CONDITION})
    WITH CHECK ({_TENANT_CONDITION});
"""

_ITEMS_DISABLE: str = f"""
DROP POLICY IF EXISTS {_ITEMS_POLICY} ON {_ITEMS_TABLE};
ALTER TABLE {_ITEMS_TABLE} DISABLE ROW LEVEL SECURITY;
"""

_ENABLE_ALL: str = _PRESCRIPTIONS_ENABLE + _ITEMS_ENABLE
_DISABLE_ALL: str = _PRESCRIPTIONS_DISABLE + _ITEMS_DISABLE


class Migration(migrations.Migration):
    """Activa RLS en recetas_prescriptions y recetas_prescription_items."""

    dependencies = [
        ("recetas", "0003_prescription"),
        # current_tenant_id() debe existir antes de crear la policy.
        ("tenancy", "0002_enable_rls"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_ENABLE_ALL,
            reverse_sql=_DISABLE_ALL,
        ),
    ]
