"""
Migración de seguridad: habilita RLS en las tablas through AUTO-GENERADAS de
los nuevos ManyToManyField `sucursales` de ServiceConcept y TreatmentPackage
(multi-sede — decisión del dueño, 2026-07-16: el owner elige en qué
sucursales está disponible cada servicio/paquete; ver migración 0011).

Tablas cubiertas:
    finanzas_service_concepts_sucursales    (ServiceConcept.sucursales   <-> clinica.Sucursal)
    finanzas_treatment_packages_sucursales  (TreatmentPackage.sucursales <-> clinica.Sucursal)

Por qué estas tablas quedan sin RLS si no se agrega esta migración (mismo
defecto documentado en el Cluster E de la auditoría de sucursales, docs/
design/sucursales-hallazgos-seguridad.md): Django genera automáticamente la
tabla intermedia de un ManyToManyField cuando no se declara un `through`
explícito. Esa tabla auto-generada NO hereda de TenantAwareModel (no tiene
tenant_id, no pasa por TenantManager) y ninguna migración le agregaría nunca
ENABLE/FORCE ROW LEVEL SECURITY ni una policy — a diferencia de
ServiceConcept/TreatmentPackage mismos, que sí son TenantAwareModel y ya
tienen su RLS (finanzas/0002_enable_rls + 0003_rls_with_check).

Mismo patrón de subconsulta al padre que apps/personal/migrations/
0012_rls_doctor_m2m_through_tables.py y apps/pacientes/migrations/
0015_rls_patient_categories_through.py: la tabla through conserva su forma
auto-generada (sin tenant_id propio) y la policy resuelve el tenant vía
subconsulta a la tabla del modelo dueño del campo M2M (finanzas_service_concepts
/ finanzas_treatment_packages) — una fila es visible/escribible solo si el
concepto/paquete referenciado pertenece al tenant activo.

El otro extremo del M2M (clinica.Sucursal) también es tenant-aware y ya tiene
su propia RLS (clinica/0017_rls_sucursal.py) — esta policy es una capa
adicional específica de la tabla intermedia, no un reemplazo.

Patrón USING + WITH CHECK + fallback `OR current_tenant_id() IS NULL` idéntico
al resto de las migraciones RLS del proyecto. El fallback preserva el acceso
de Celery, management commands, seeds y migraciones que corren sin contexto
de request (GUC vacío).

Reversible: la dirección inversa elimina la policy y deshabilita RLS.
"""

from django.db import migrations

# (tabla through, columna FK al padre, tabla del padre, nombre de policy)
_THROUGH_TABLES: list[tuple[str, str, str, str]] = [
    (
        "finanzas_service_concepts_sucursales",
        "serviceconcept_id",
        "finanzas_service_concepts",
        "finanzas_service_concepts_sucursales_tenant_iso",
    ),
    (
        "finanzas_treatment_packages_sucursales",
        "treatmentpackage_id",
        "finanzas_treatment_packages",
        "finanzas_treatment_packages_sucursales_tenant_iso",
    ),
]


def _parent_tenant_condition(through_table: str, parent_fk_column: str, parent_table: str) -> str:
    """Predicado: la fila es visible/escribible si su padre (concepto/paquete)
    es del tenant activo.

    `finanzas_service_concepts`/`finanzas_treatment_packages` ya tienen su
    propia RLS (0002_enable_rls / 0003_rls_with_check), pero esa policy
    protege queries directas a esas tablas, no lo que ve esta subconsulta
    desde la tabla through; por eso se repite explícitamente la condición
    `p.tenant_id = current_tenant_id() OR current_tenant_id() IS NULL`.

    OJO: no se construye interpolando 'tenant_id' -> 'p.tenant_id' con
    str.replace sobre una condición genérica — 'current_tenant_id()' también
    contiene la subcadena 'tenant_id' y un replace ingenuo la corrompería.
    Se escribe explícita y completa (mismo cuidado que
    apps/personal/migrations/0012_rls_doctor_m2m_through_tables.py).
    """
    # noqa justificado: through_table/parent_fk_column/parent_table son
    # constantes de módulo (nombres de tabla/columna de _THROUGH_TABLES),
    # nunca input de usuario — Postgres no permite parametrizar identificadores
    # con %s, solo valores. Mismo patrón que el resto de las migraciones RLS
    # del proyecto (p. ej. apps/personal/migrations/0012_rls_doctor_m2m_through_tables.py).
    return (
        f"EXISTS (\n"  # noqa: S608
        f"        SELECT 1 FROM {parent_table} p\n"
        f"        WHERE p.id = {through_table}.{parent_fk_column}\n"
        f"          AND (p.tenant_id = current_tenant_id() OR current_tenant_id() IS NULL)\n"
        f"    )"
    )


def _forward_sql(through_table: str, parent_fk_column: str, parent_table: str, policy: str) -> str:
    condition = _parent_tenant_condition(through_table, parent_fk_column, parent_table)
    return "\n".join(
        [
            f"ALTER TABLE {through_table} ENABLE ROW LEVEL SECURITY;",
            f"ALTER TABLE {through_table} FORCE ROW LEVEL SECURITY;",
            (
                f"CREATE POLICY {policy} ON {through_table}\n"
                f"    USING ({condition})\n"
                f"    WITH CHECK ({condition});"
            ),
        ]
    )


def _reverse_sql(through_table: str, policy: str) -> str:
    return "\n".join(
        [
            f"DROP POLICY IF EXISTS {policy} ON {through_table};",
            f"ALTER TABLE {through_table} DISABLE ROW LEVEL SECURITY;",
        ]
    )


class Migration(migrations.Migration):
    """Habilita RLS (vía subconsulta al padre) en las tablas through
    auto-generadas de ServiceConcept.sucursales y TreatmentPackage.sucursales."""

    dependencies = [
        ("finanzas", "0011_serviceconcept_sucursales_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_forward_sql(table, parent_fk, parent_table, policy),
            reverse_sql=_reverse_sql(table, policy),
        )
        for table, parent_fk, parent_table, policy in _THROUGH_TABLES
    ]
