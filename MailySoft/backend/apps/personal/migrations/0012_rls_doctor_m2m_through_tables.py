"""
Migración de seguridad: habilita RLS en las tablas through AUTO-GENERADAS de
los ManyToManyField de Doctor (Cluster E — hallazgo de la auditoría de
sucursales, docs/design/sucursales-hallazgos-seguridad.md).

Tablas cubiertas:
    personal_doctors_consultorios  (Doctor.consultorios  <-> Consultorio)
    personal_doctors_sucursales    (Doctor.sucursales    <-> clinica.Sucursal)

Por qué estas tablas quedaron sin RLS:
    Django genera automáticamente la tabla intermedia de un ManyToManyField
    cuando no se declara un `through` explícito. Esa tabla auto-generada NO
    hereda de TenantAwareModel (no tiene tenant_id, no pasa por TenantManager)
    y ninguna migración le agregó nunca ENABLE/FORCE ROW LEVEL SECURITY ni una
    policy — a diferencia de MembershipSucursal (clinica/0018), que SÍ es un
    through explícito tenant-aware con su propia columna tenant_id.

Por qué subconsulta al padre (Doctor) y no through explícito:
    Convertir el M2M a through explícito obligaría a una migración de datos y
    a tocar todos los call sites `.add()/.set()/.remove()` — mayor superficie
    de cambio para un hallazgo BAJO sin exploit activo. En su lugar, la tabla
    conserva su forma auto-generada (doctor_id, consultorio_id / sucursal_id,
    sin tenant_id propio) y la policy resuelve el tenant vía subconsulta a
    personal_doctors: una fila es visible/escribible solo si el Doctor
    referenciado por doctor_id pertenece al tenant activo.

Ambos extremos del M2M (Consultorio y Sucursal) también son tenant-aware y ya
tienen su propia RLS (personal_consultorios, clinica_sucursales) — esta policy
es una capa adicional específica de la tabla intermedia, no un reemplazo.

Patrón USING + WITH CHECK + fallback `OR current_tenant_id() IS NULL` idéntico
al resto de las migraciones RLS del proyecto (ver clinica/0017_rls_sucursal.py
y clinica/0018_rls_membership_sucursales.py para el estilo de referencia).
El fallback preserva el acceso de Celery, management commands, seeds y
migraciones que corren sin contexto de request (GUC vacío).

Reversible: la dirección inversa elimina la policy y deshabilita RLS.
"""

from django.db import migrations

# (tabla through, columna FK a Doctor, nombre de policy)
_THROUGH_TABLES: list[tuple[str, str, str]] = [
    ("personal_doctors_consultorios", "doctor_id", "personal_doctors_consultorios_tenant_iso"),
    ("personal_doctors_sucursales", "doctor_id", "personal_doctors_sucursales_tenant_iso"),
]


def _doctor_tenant_condition(through_table: str, doctor_fk_column: str) -> str:
    """Predicado: la fila es visible/escribible si su Doctor es del tenant activo.

    personal_doctors ya tiene su propia RLS (0002_enable_rls / 0007_rls_with_check),
    pero esa policy protege queries directas a personal_doctors, no lo que ve
    esta subconsulta desde la tabla through; por eso se repite explícitamente
    la condición `d.tenant_id = current_tenant_id() OR current_tenant_id() IS
    NULL` en vez de asumir que la RLS de personal_doctors ya la habrá aplicado.

    OJO: no se construye interpolando 'tenant_id' -> 'd.tenant_id' con
    str.replace sobre una condición genérica — 'current_tenant_id()' también
    contiene la subcadena 'tenant_id' y un replace ingenuo la corrompería
    (quedaría 'current_d.tenant_id()'). Se escribe explícita y completa.
    """
    # noqa justificado: {through_table}/{doctor_fk_column} son constantes de
    # módulo (nombres de tabla/columna de _THROUGH_TABLES), nunca input de
    # usuario — Postgres no permite parametrizar identificadores con %s, solo
    # valores. Ver skill django-clean-architecture, regla "cero SQL con datos
    # del usuario": esta regla es sobre datos de usuario, no sobre construir
    # DDL/policies con identificadores hardcodeados, patrón ya usado en todas
    # las migraciones RLS del proyecto (p.ej. clinica/0017_rls_sucursal.py).
    return (
        f"EXISTS (\n"  # noqa: S608
        f"        SELECT 1 FROM personal_doctors d\n"
        f"        WHERE d.id = {through_table}.{doctor_fk_column}\n"
        f"          AND (d.tenant_id = current_tenant_id() OR current_tenant_id() IS NULL)\n"
        f"    )"
    )


def _forward_sql(through_table: str, doctor_fk_column: str, policy: str) -> str:
    condition = _doctor_tenant_condition(through_table, doctor_fk_column)
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
    """Habilita RLS (vía subconsulta a personal_doctors) en las tablas through
    auto-generadas de Doctor.consultorios y Doctor.sucursales."""

    dependencies = [
        # 0011 es la última migración de personal en la cadena lineal; ya
        # incluye transitivamente 0007_rls_with_check (RLS de personal_doctors)
        # y depende de tenancy/0002_enable_rls (current_tenant_id()).
        ("personal", "0011_backfill_doctorschedule_sucursal"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_forward_sql(table, doctor_fk, policy),
            reverse_sql=_reverse_sql(table, policy),
        )
        for table, doctor_fk, policy in _THROUGH_TABLES
    ]
