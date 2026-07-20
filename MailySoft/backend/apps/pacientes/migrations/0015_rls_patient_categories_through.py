"""
Migración de seguridad: habilita RLS en pacientes_patients_categories, la
tabla through AUTO-GENERADA del ManyToManyField Patient.categories (Cluster E
— hallazgo de la auditoría de sucursales, extendido durante ese análisis a
"cualquier M2M de un TenantAwareModel", docs/design/sucursales-hallazgos-seguridad.md).

Mismo defecto que personal_doctors_consultorios / personal_doctors_sucursales
(ver apps/personal/migrations/0012_rls_doctor_m2m_through_tables.py para el
razonamiento completo): Django generó la tabla intermedia automáticamente al
declarar `Patient.categories = ManyToManyField(PatientCategory)` sin `through`
explícito, así que la tabla no tiene tenant_id propio ni pasó nunca por una
migración enable_rls.

Se resuelve igual: subconsulta al padre (Patient, dueño del campo M2M) en vez
de convertir a through explícito. patient_id referencia a un Patient cuyo
tenant_id debe coincidir con el tenant activo (o GUC vacío, fallback estándar
para Celery/management commands/seeds).

pacientes_patients ya tiene su propia RLS con WITH CHECK (0002_enable_rls +
0014_rls_with_check); clinica_patient_categories también (0002_enable_rls de
clinica). Esta policy es una capa adicional para la tabla intermedia.

Reversible: la dirección inversa elimina la policy y deshabilita RLS.
"""

from django.db import migrations

_TABLE = "pacientes_patients_categories"
_POLICY = "pacientes_patients_categories_tenant_iso"

# noqa justificado: _TABLE es una constante de módulo (nombre de tabla
# hardcodeado), nunca input de usuario — Postgres no permite parametrizar
# identificadores con %s, solo valores. Mismo patrón que el resto de las
# migraciones RLS del proyecto (p.ej. clinica/0017_rls_sucursal.py).
_CONDITION = (
    "EXISTS (\n"  # noqa: S608
    "        SELECT 1 FROM pacientes_patients p\n"
    f"        WHERE p.id = {_TABLE}.patient_id\n"
    "          AND (p.tenant_id = current_tenant_id() OR current_tenant_id() IS NULL)\n"
    "    )"
)

_FORWARD_SQL: str = "\n".join(
    [
        f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY;",
        f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY;",
        (
            f"CREATE POLICY {_POLICY} ON {_TABLE}\n"
            f"    USING ({_CONDITION})\n"
            f"    WITH CHECK ({_CONDITION});"
        ),
    ]
)

_REVERSE_SQL: str = "\n".join(
    [
        f"DROP POLICY IF EXISTS {_POLICY} ON {_TABLE};",
        f"ALTER TABLE {_TABLE} DISABLE ROW LEVEL SECURITY;",
    ]
)


class Migration(migrations.Migration):
    """Habilita RLS (vía subconsulta a pacientes_patients) en la tabla through
    auto-generada de Patient.categories."""

    dependencies = [
        ("pacientes", "0014_rls_with_check"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_FORWARD_SQL,
            reverse_sql=_REVERSE_SQL,
        ),
    ]
