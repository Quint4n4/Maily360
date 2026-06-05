"""
Migración manual: habilita Row Level Security en audit_logs.

Doble barrera de inmutabilidad (§4 del diseño):
  1. Python: AuditLog.save() lanza RuntimeError si el pk ya existe.
  2. PostgreSQL (esta migración):
     - ENABLE + FORCE ROW LEVEL SECURITY.
     - POLICY FOR SELECT: cada tenant solo ve sus propios registros
       (o los globales con tenant IS NULL, que son eventos sin tenant como LOGIN_FAILED).
     - POLICY FOR INSERT WITH CHECK: solo se puede insertar para el tenant activo.
     - Sin policy de UPDATE ni DELETE → operaciones bloqueadas silenciosamente
       (FORCE RLS sin policy = denegación por defecto para esas operaciones).

REVOKE UPDATE, DELETE:
    En desarrollo el rol de la app es el mismo superuser que creó la BD
    (típicamente 'mailysoft' o 'postgres'), y FORCE RLS + ausencia de policy
    ya bloquea esas operaciones. El REVOKE explícito se añade en hardening de
    producción cuando el rol de aplicación es distinto del superuser.
    En esta migración se documenta el intento: si el role aplicable existe y
    no es superuser, el REVOKE se aplica; si no, se omite sin error.

OR tenant_id IS NULL:
    Permite que eventos globales (LOGIN_FAILED con tenant=None) sean visibles
    para el platform staff que conecta con all_objects desde el admin de Django.

OR current_tenant_id() IS NULL:
    Permite que Celery, management commands y migraciones lean sin contexto.

FORCE ROW LEVEL SECURITY:
    Aplica la política incluso al dueño de la tabla (owner/superuser de la app)
    para evitar bypassear accidentalmente en un path de código sin contexto.
    La cláusula OR current_tenant_id() IS NULL cubre las migraciones.
"""

from django.db import migrations

TABLE = "audit_logs"
SELECT_POLICY = "audit_logs_tenant_select"
INSERT_POLICY = "audit_logs_tenant_insert"

# ---------------------------------------------------------------------------
# ENABLE + FORCE RLS
# ---------------------------------------------------------------------------

ENABLE_RLS = f"""
ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY;
"""

DISABLE_RLS = f"""
ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY;
"""

# ---------------------------------------------------------------------------
# Policy FOR SELECT
# Un tenant ve sus propios registros + los globales (tenant IS NULL) + sin contexto
# ---------------------------------------------------------------------------

CREATE_SELECT_POLICY = f"""
CREATE POLICY {SELECT_POLICY} ON {TABLE}
    FOR SELECT
    USING (
        tenant_id = current_tenant_id()
        OR tenant_id IS NULL
        OR current_tenant_id() IS NULL
    );
"""

DROP_SELECT_POLICY = f"""
DROP POLICY IF EXISTS {SELECT_POLICY} ON {TABLE};
"""

# ---------------------------------------------------------------------------
# Policy FOR INSERT WITH CHECK
# Solo se puede insertar para el tenant activo, o sin tenant (eventos globales)
# ---------------------------------------------------------------------------

CREATE_INSERT_POLICY = f"""
CREATE POLICY {INSERT_POLICY} ON {TABLE}
    FOR INSERT
    WITH CHECK (
        tenant_id = current_tenant_id()
        OR tenant_id IS NULL
        OR current_tenant_id() IS NULL
    );
"""

DROP_INSERT_POLICY = f"""
DROP POLICY IF EXISTS {INSERT_POLICY} ON {TABLE};
"""

# ---------------------------------------------------------------------------
# REVOKE UPDATE, DELETE — hardening para producción
# En dev el owner de la BD es superuser y FORCE RLS ya bloquea.
# El DO block captura el error si el rol no existe o es superuser,
# y continúa sin error (la protección real ya la provee FORCE RLS).
# ---------------------------------------------------------------------------

REVOKE_MUTATING = """
DO $$
BEGIN
    -- Intentar REVOKE al rol de la aplicación si existe y no es superuser.
    -- En dev el owner es superuser, el REVOKE no aplica pero tampoco hace falta.
    IF EXISTS (
        SELECT 1 FROM pg_roles
        WHERE rolname = current_user
          AND NOT rolsuper
    ) THEN
        EXECUTE 'REVOKE UPDATE, DELETE ON TABLE audit_logs FROM ' || quote_ident(current_user);
    END IF;
EXCEPTION
    WHEN insufficient_privilege THEN
        NULL;  -- silencioso: la protección real es FORCE RLS sin policy de UPDATE/DELETE
    WHEN undefined_object THEN
        NULL;
END;
$$;
"""

# No hay reverse sensato para REVOKE (no queremos re-conceder en producción).
GRANT_MUTATING_NOOP = "-- REVOKE aplicado en forward no se revierte en reverse."


class Migration(migrations.Migration):
    """Activa RLS en audit_logs para inmutabilidad y aislamiento por tenant."""

    dependencies = [
        ("audit", "0001_initial"),
        # current_tenant_id() debe existir antes de crear las policies.
        ("tenancy", "0002_enable_rls"),
    ]

    operations = [
        migrations.RunSQL(
            sql=ENABLE_RLS,
            reverse_sql=DISABLE_RLS,
        ),
        migrations.RunSQL(
            sql=CREATE_SELECT_POLICY,
            reverse_sql=DROP_SELECT_POLICY,
        ),
        migrations.RunSQL(
            sql=CREATE_INSERT_POLICY,
            reverse_sql=DROP_INSERT_POLICY,
        ),
        migrations.RunSQL(
            sql=REVOKE_MUTATING,
            reverse_sql=GRANT_MUTATING_NOOP,
        ),
    ]
