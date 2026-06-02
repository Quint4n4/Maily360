"""
Migración manual: corrige los exclusion constraints anti-empalme.

PROBLEMA (F2): la migración 0002 excluía solo ('cancelled', 'no_show') del
constraint WHERE, lo que significaba que una cita 'attended' (ya terminada)
seguía bloqueando el slot en la BD. Sin embargo la capa 1 (service) ya
excluye 'attended' de ACTIVE_STATUSES. Esta inconsistencia entre capas
provoca que la capa 2 rechace citas válidas.

SOLUCIÓN: recrear los dos constraints con el WHERE corregido:
    WHERE (deleted_at IS NULL AND status NOT IN ('cancelled','no_show','attended'))

El constraint de consultorio además mantiene AND consultorio_id IS NOT NULL.

El reverse_sql restaura exactamente los constraints de 0002 para que
`migrate --reverse` sea idempotente.
"""

from django.db import migrations

APPOINTMENTS_TABLE = "agenda_appointments"

# ---------------------------------------------------------------------------
# Nombres de constraints (idénticos a los de 0002 para hacer DROP correcto)
# ---------------------------------------------------------------------------

DOCTOR_CONSTRAINT = "appointment_no_overlap_doctor"
CONSULTORIO_CONSTRAINT = "appointment_no_overlap_consultorio"

# ---------------------------------------------------------------------------
# DROP (usados en forward y como reverse del reverse_sql)
# ---------------------------------------------------------------------------

DROP_DOCTOR = f"""
ALTER TABLE {APPOINTMENTS_TABLE}
DROP CONSTRAINT IF EXISTS {DOCTOR_CONSTRAINT};
"""

DROP_CONSULTORIO = f"""
ALTER TABLE {APPOINTMENTS_TABLE}
DROP CONSTRAINT IF EXISTS {CONSULTORIO_CONSTRAINT};
"""

# ---------------------------------------------------------------------------
# ADD — versión CORREGIDA (attended excluido del bloqueo)
# ACTIVE_STATUSES = {scheduled, confirmed, arrived, in_progress}
# ---------------------------------------------------------------------------

ADD_DOCTOR_CONSTRAINT_V2 = f"""
ALTER TABLE {APPOINTMENTS_TABLE}
ADD CONSTRAINT {DOCTOR_CONSTRAINT}
EXCLUDE USING gist (
    tenant_id WITH =,
    doctor_id WITH =,
    tstzrange(starts_at, ends_at, '[)') WITH &&
)
WHERE (
    deleted_at IS NULL
    AND status NOT IN ('cancelled', 'no_show', 'attended')
);
"""

ADD_CONSULTORIO_CONSTRAINT_V2 = f"""
ALTER TABLE {APPOINTMENTS_TABLE}
ADD CONSTRAINT {CONSULTORIO_CONSTRAINT}
EXCLUDE USING gist (
    tenant_id WITH =,
    consultorio_id WITH =,
    tstzrange(starts_at, ends_at, '[)') WITH &&
)
WHERE (
    deleted_at IS NULL
    AND status NOT IN ('cancelled', 'no_show', 'attended')
    AND consultorio_id IS NOT NULL
);
"""

# ---------------------------------------------------------------------------
# ADD — versión ORIGINAL de 0002 (para reverse_sql)
# ---------------------------------------------------------------------------

ADD_DOCTOR_CONSTRAINT_V1 = f"""
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

ADD_CONSULTORIO_CONSTRAINT_V1 = f"""
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


class Migration(migrations.Migration):
    """Recrea los exclusion constraints alineando capa 2 (BD) con ACTIVE_STATUSES."""

    dependencies = [
        ("agenda", "0002_enable_rls_and_constraints"),
    ]

    operations = [
        # 1. Recrear constraint de doctor con WHERE corregido
        migrations.RunSQL(
            sql=DROP_DOCTOR + ADD_DOCTOR_CONSTRAINT_V2,
            reverse_sql=DROP_DOCTOR + ADD_DOCTOR_CONSTRAINT_V1,
        ),
        # 2. Recrear constraint de consultorio con WHERE corregido
        migrations.RunSQL(
            sql=DROP_CONSULTORIO + ADD_CONSULTORIO_CONSTRAINT_V2,
            reverse_sql=DROP_CONSULTORIO + ADD_CONSULTORIO_CONSTRAINT_V1,
        ),
    ]
