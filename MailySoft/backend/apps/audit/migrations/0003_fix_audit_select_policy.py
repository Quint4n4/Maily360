"""
Migración: corrige la policy SELECT de audit_logs (FIX-1 de la auditoría).

Problema: la policy SELECT de 0002 incluía `OR tenant_id IS NULL`, lo que hacía
que CUALQUIER tenant autenticado viera los eventos globales (LOGIN_FAILED, con
email_hint) de TODA la plataforma — fuga cross-tenant y de PII (LFPDPPP).

Corrección: la policy SELECT solo permite ver:
  - los registros del tenant activo (tenant_id = current_tenant_id()), y
  - todo cuando NO hay contexto de tenant (current_tenant_id() IS NULL) →
    esto es para Celery/migraciones/Django Admin (platform staff con all_objects).

Los eventos globales (tenant=NULL) ya NO son visibles para un owner/admin que
consulta el endpoint dentro de su contexto de tenant. Solo el platform staff
los ve vía Django Admin (que opera sin contexto de tenant).
"""

from django.db import migrations

TABLE = "audit_logs"
SELECT_POLICY = "audit_logs_tenant_select"

# Policy SELECT corregida: SIN `OR tenant_id IS NULL`.
CREATE_SELECT_POLICY_FIXED = f"""
DROP POLICY IF EXISTS {SELECT_POLICY} ON {TABLE};
CREATE POLICY {SELECT_POLICY} ON {TABLE}
    FOR SELECT
    USING (
        tenant_id = current_tenant_id()
        OR current_tenant_id() IS NULL
    );
"""

# Reverse: restaura la versión anterior (con OR tenant_id IS NULL).
CREATE_SELECT_POLICY_OLD = f"""
DROP POLICY IF EXISTS {SELECT_POLICY} ON {TABLE};
CREATE POLICY {SELECT_POLICY} ON {TABLE}
    FOR SELECT
    USING (
        tenant_id = current_tenant_id()
        OR tenant_id IS NULL
        OR current_tenant_id() IS NULL
    );
"""


class Migration(migrations.Migration):
    """Quita `OR tenant_id IS NULL` de la policy SELECT (fuga cross-tenant)."""

    dependencies = [
        ("audit", "0002_enable_rls"),
    ]

    operations = [
        migrations.RunSQL(
            sql=CREATE_SELECT_POLICY_FIXED,
            reverse_sql=CREATE_SELECT_POLICY_OLD,
        ),
    ]
