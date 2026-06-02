"""
Migración manual: habilita Row Level Security y exclusion constraints anti-empalme.

1. RLS en agenda_appointments y agenda_tenant_config (aislamiento por tenant).
2. CREATE EXTENSION btree_gist (necesario para EXCLUDE USING GIST con rangos).
3. Dos exclusion constraints anti-empalme:
   - appointment_no_overlap_doctor:      un médico no puede tener dos citas activas
     que se solapen en el mismo tenant.
   - appointment_no_overlap_consultorio: un consultorio no puede tener dos citas
     activas que se solapen en el mismo tenant. Solo aplica cuando consultorio_id IS NOT NULL.

Rango [starts_at, ends_at): citas consecutivas (10:00-11:00 y 11:00-12:00) no chocan.
El WHERE excluye citas terminales (cancelled, no_show) y soft-deleted (deleted_at IS NULL).

OR current_tenant_id() IS NULL:
    Permite que Celery, management commands y migraciones accedan sin contexto.

FORCE ROW LEVEL SECURITY:
    Aplica la política incluso al rol owner/superuser de la app para que
    no pueda bypassear accidentalmente en un path de código sin contexto.
    La cláusula OR ... IS NULL cubre las migraciones.
"""

from django.db import migrations

# ---------------------------------------------------------------------------
# agenda_appointments — RLS
# ---------------------------------------------------------------------------

APPOINTMENTS_TABLE = "agenda_appointments"
APPOINTMENTS_POLICY = "agenda_appointments_tenant_isolation"

ENABLE_RLS_APPOINTMENTS = f"""
ALTER TABLE {APPOINTMENTS_TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {APPOINTMENTS_TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY {APPOINTMENTS_POLICY} ON {APPOINTMENTS_TABLE}
    USING (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL);
"""

DISABLE_RLS_APPOINTMENTS = f"""
DROP POLICY IF EXISTS {APPOINTMENTS_POLICY} ON {APPOINTMENTS_TABLE};
ALTER TABLE {APPOINTMENTS_TABLE} DISABLE ROW LEVEL SECURITY;
"""

# ---------------------------------------------------------------------------
# agenda_tenant_config — RLS
# ---------------------------------------------------------------------------

CONFIG_TABLE = "agenda_tenant_config"
CONFIG_POLICY = "agenda_tenant_config_tenant_isolation"

ENABLE_RLS_CONFIG = f"""
ALTER TABLE {CONFIG_TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {CONFIG_TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY {CONFIG_POLICY} ON {CONFIG_TABLE}
    USING (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL);
"""

DISABLE_RLS_CONFIG = f"""
DROP POLICY IF EXISTS {CONFIG_POLICY} ON {CONFIG_TABLE};
ALTER TABLE {CONFIG_TABLE} DISABLE ROW LEVEL SECURITY;
"""

# ---------------------------------------------------------------------------
# btree_gist extension
# ---------------------------------------------------------------------------

ENABLE_BTREE_GIST = "CREATE EXTENSION IF NOT EXISTS btree_gist;"

# No se dropea la extensión en reverse (puede usarse por otros objetos).
DISABLE_BTREE_GIST = "-- btree_gist no se elimina en reverse (puede usarse por otras tablas)."

# ---------------------------------------------------------------------------
# Exclusion constraint: doctor no overlap
# ---------------------------------------------------------------------------
# Garantiza que un médico (dentro de un tenant) no tenga dos citas activas
# cuyo rango de tiempo [starts_at, ends_at) se solape.
# tenant_id WITH = : no bloquea médicos en 2 clínicas distintas.
# deleted_at IS NULL: ignora soft-deleted.
# status NOT IN (...): ignora citas terminales (canceladas, no-show).
# ---------------------------------------------------------------------------

DOCTOR_CONSTRAINT = "appointment_no_overlap_doctor"

ADD_DOCTOR_CONSTRAINT = f"""
ALTER TABLE {APPOINTMENTS_TABLE}
ADD CONSTRAINT {DOCTOR_CONSTRAINT}
EXCLUDE USING gist (
    tenant_id WITH =,
    doctor_id WITH =,
    tstzrange(starts_at, ends_at, '[)') WITH &&
)
WHERE (
    deleted_at IS NULL
    AND status NOT IN ('cancelled', 'no_show')
);
"""

DROP_DOCTOR_CONSTRAINT = f"""
ALTER TABLE {APPOINTMENTS_TABLE}
DROP CONSTRAINT IF EXISTS {DOCTOR_CONSTRAINT};
"""

# ---------------------------------------------------------------------------
# Exclusion constraint: consultorio no overlap
# ---------------------------------------------------------------------------
# Idéntico al de doctor pero para consultorio_id.
# Solo aplica cuando consultorio_id IS NOT NULL (consultorio es OPCIONAL).
# El AND consultorio_id IS NOT NULL en el WHERE evita que la restricción
# bloquee citas sin consultorio asignado (telemedicina, domicilio, etc.).
# ---------------------------------------------------------------------------

CONSULTORIO_CONSTRAINT = "appointment_no_overlap_consultorio"

ADD_CONSULTORIO_CONSTRAINT = f"""
ALTER TABLE {APPOINTMENTS_TABLE}
ADD CONSTRAINT {CONSULTORIO_CONSTRAINT}
EXCLUDE USING gist (
    tenant_id WITH =,
    consultorio_id WITH =,
    tstzrange(starts_at, ends_at, '[)') WITH &&
)
WHERE (
    deleted_at IS NULL
    AND status NOT IN ('cancelled', 'no_show')
    AND consultorio_id IS NOT NULL
);
"""

DROP_CONSULTORIO_CONSTRAINT = f"""
ALTER TABLE {APPOINTMENTS_TABLE}
DROP CONSTRAINT IF EXISTS {CONSULTORIO_CONSTRAINT};
"""


class Migration(migrations.Migration):
    """Activa RLS en las tablas de agenda y añade exclusion constraints anti-empalme."""

    dependencies = [
        ("agenda", "0001_initial"),
        # current_tenant_id() debe existir antes de crear las policies.
        ("tenancy", "0002_enable_rls"),
    ]

    operations = [
        # 1. Extension btree_gist (necesaria para EXCLUDE USING GIST con tstzrange)
        migrations.RunSQL(
            sql=ENABLE_BTREE_GIST,
            reverse_sql=DISABLE_BTREE_GIST,
        ),
        # 2. RLS en citas
        migrations.RunSQL(
            sql=ENABLE_RLS_APPOINTMENTS,
            reverse_sql=DISABLE_RLS_APPOINTMENTS,
        ),
        # 3. RLS en config de agenda
        migrations.RunSQL(
            sql=ENABLE_RLS_CONFIG,
            reverse_sql=DISABLE_RLS_CONFIG,
        ),
        # 4. Exclusion constraint: doctor no overlap
        migrations.RunSQL(
            sql=ADD_DOCTOR_CONSTRAINT,
            reverse_sql=DROP_DOCTOR_CONSTRAINT,
        ),
        # 5. Exclusion constraint: consultorio no overlap (solo cuando no es null)
        migrations.RunSQL(
            sql=ADD_CONSULTORIO_CONSTRAINT,
            reverse_sql=DROP_CONSULTORIO_CONSTRAINT,
        ),
    ]
