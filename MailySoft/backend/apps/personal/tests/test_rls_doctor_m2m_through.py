"""
Tests de RLS para las tablas through AUTO-GENERADAS de los ManyToManyField de
Doctor (Cluster E — auditoría de sucursales, 2026-07-15,
docs/design/sucursales-hallazgos-seguridad.md).

Tablas cubiertas:
    personal_doctors_sucursales    (Doctor.sucursales)
    personal_doctors_consultorios  (Doctor.consultorios)

Ambas se cierran en apps/personal/migrations/0012_rls_doctor_m2m_through_tables.py
con una policy que resuelve el tenant vía subconsulta al padre (Doctor), ya
que la tabla through auto-generada no tiene columna tenant_id propia.

LIMITACIÓN DEL ENTORNO (misma que apps/core/tests/test_tenant_guc_modes.py,
sección "RLS real end-to-end"): el rol de conexión de dev/test (`mailysoft`)
es SUPERUSER de PostgreSQL. Postgres exime a los superusers de RLS incluso
con FORCE ROW LEVEL SECURITY — no es algo que un test pueda evitar sin
cambiar el rol de conexión. Por eso "SELECT * FROM personal_doctors_sucursales"
con este rol siempre devuelve todas las filas sin importar el GUC, y no sirve
para probar el enforcement real de la barrera de base de datos aquí.

Lo que SÍ es determinista y prueba la barrera real: en vez de copiar a mano
la condición de la policy (que podría divergir en silencio de la migración
real si alguien la edita), estos tests LEEN la expresión `qual` tal como
quedó instalada en `pg_policies` para esta tabla y la EVALÚAN como una
consulta SQL real, con `current_tenant_id()` real y el GUC fijado con
`apply_tenant_guc()` — el mismo mecanismo que usa TenantAPIView/TenantMiddleware
en producción. Si esa expresión (la que Postgres aplicaría con un rol
NOSUPERUSER) no aísla correctamente por tenant, estos tests lo detectan.
"""

from uuid import UUID

import pytest
from django.db import connection

from apps.core.tenant_context import apply_tenant_guc, clear_tenant_guc
from tests.factories import ConsultorioFactory, DoctorFactory, SucursalFactory, TenantFactory


def _policy_qual(*, table: str, policy: str) -> str:
    """Lee la expresión USING/qual tal como quedó instalada en pg_policies.

    No se copia a mano la condición de la migración: se lee la que Postgres
    tiene realmente guardada, para que el test falle si alguien la cambia sin
    querer (drift entre migración y comportamiento real).
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT qual FROM pg_policies
            WHERE schemaname = %s AND tablename = %s AND policyname = %s;
            """,
            ["public", table, policy],
        )
        row = cursor.fetchone()
    assert row is not None, f"Policy '{policy}' no encontrada en pg_policies para '{table}'."
    return str(row[0])


def _row_passes_policy(
    *, table: str, policy: str, fk_column: str, doctor_id: UUID, other_id: UUID, other_column: str
) -> bool:
    """Evalúa la expresión REAL de la policy contra una fila concreta del through.

    Ejecuta `SELECT EXISTS(... WHERE <predicado real de pg_policies>)` sobre
    la fila (doctor_id, other_id). El GUC activo en ese momento (fijado con
    apply_tenant_guc) determina lo que current_tenant_id() devuelve dentro
    del predicado — igual que vería la policy si la aplicara un rol NOSUPERUSER.
    """
    predicate = _policy_qual(table=table, policy=policy)
    # noqa justificado: table/fk_column/other_column son constantes de módulo
    # (nombres de tabla/columna hardcodeados en las llamadas de este archivo,
    # nunca input de usuario) y `predicate` viene de pg_policies (el catálogo
    # de PostgreSQL, no de un request) — Postgres no permite parametrizar
    # identificadores con %s, solo valores (que sí van parametrizados abajo).
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT EXISTS (
                SELECT 1 FROM {table}
                WHERE {fk_column} = %s AND {other_column} = %s AND ({predicate})
            );
            """,  # noqa: S608
            [doctor_id, other_id],
        )
        row = cursor.fetchone()
    return bool(row[0]) if row else False


@pytest.mark.django_db
class TestDoctorSucursalesThroughRls:
    """Aislamiento cross-tenant real de personal_doctors_sucursales vía subconsulta."""

    def test_fila_pasa_la_policy_para_tenant_dueno_y_falla_para_otro_tenant(self) -> None:
        """Doctor+Sucursal en tenant1, asociados: la policy los deja pasar con el
        GUC de tenant1 y los bloquea con el GUC de tenant2 — sin exploit, sin
        fuga cross-tenant en la tabla through.
        """
        tenant1 = TenantFactory()
        tenant2 = TenantFactory()
        doctor1 = DoctorFactory(tenant=tenant1)
        sucursal1 = SucursalFactory(tenant=tenant1)
        doctor1.sucursales.add(sucursal1)

        try:
            apply_tenant_guc(tenant1.id)
            visible_para_tenant1 = _row_passes_policy(
                table="personal_doctors_sucursales",
                policy="personal_doctors_sucursales_tenant_iso",
                fk_column="doctor_id",
                doctor_id=doctor1.id,
                other_id=sucursal1.id,
                other_column="sucursal_id",
            )
            assert visible_para_tenant1, (
                "La fila del through NO pasa la policy para tenant1 (su dueño "
                "real) — la subconsulta a personal_doctors está mal escrita."
            )

            apply_tenant_guc(tenant2.id)
            visible_para_tenant2 = _row_passes_policy(
                table="personal_doctors_sucursales",
                policy="personal_doctors_sucursales_tenant_iso",
                fk_column="doctor_id",
                doctor_id=doctor1.id,
                other_id=sucursal1.id,
                other_column="sucursal_id",
            )
            assert not visible_para_tenant2, (
                "FUGA CROSS-TENANT: tenant2 puede ver una fila del through de un "
                "doctor de tenant1. La subconsulta al padre no está aislando por tenant."
            )
        finally:
            clear_tenant_guc()

    def test_fila_pasa_la_policy_con_guc_vacio_fallback_sin_tenant(self) -> None:
        """Sin GUC en contexto (Celery, management commands, seeds), el fallback
        `current_tenant_id() IS NULL` deja pasar la fila — igual que el resto
        de las políticas RLS del proyecto.
        """
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        sucursal = SucursalFactory(tenant=tenant)
        doctor.sucursales.add(sucursal)

        clear_tenant_guc()  # asegura GUC vacío (precondición explícita)

        visible_sin_guc = _row_passes_policy(
            table="personal_doctors_sucursales",
            policy="personal_doctors_sucursales_tenant_iso",
            fk_column="doctor_id",
            doctor_id=doctor.id,
            other_id=sucursal.id,
            other_column="sucursal_id",
        )
        assert visible_sin_guc, (
            "Sin tenant en el GUC, la policy debería dejar pasar la fila "
            "(fallback current_tenant_id() IS NULL) para no romper Celery/seeds."
        )


@pytest.mark.django_db
class TestDoctorConsultoriosThroughRls:
    """Aislamiento cross-tenant real de personal_doctors_consultorios vía subconsulta."""

    def test_fila_pasa_la_policy_para_tenant_dueno_y_falla_para_otro_tenant(self) -> None:
        """Mismo escenario que Doctor.sucursales, con Doctor.consultorios."""
        tenant1 = TenantFactory()
        tenant2 = TenantFactory()
        doctor1 = DoctorFactory(tenant=tenant1)
        consultorio1 = ConsultorioFactory(tenant=tenant1)
        doctor1.consultorios.add(consultorio1)

        try:
            apply_tenant_guc(tenant1.id)
            visible_para_tenant1 = _row_passes_policy(
                table="personal_doctors_consultorios",
                policy="personal_doctors_consultorios_tenant_iso",
                fk_column="doctor_id",
                doctor_id=doctor1.id,
                other_id=consultorio1.id,
                other_column="consultorio_id",
            )
            assert (
                visible_para_tenant1
            ), "La fila del through NO pasa la policy para tenant1 (su dueño real)."

            apply_tenant_guc(tenant2.id)
            visible_para_tenant2 = _row_passes_policy(
                table="personal_doctors_consultorios",
                policy="personal_doctors_consultorios_tenant_iso",
                fk_column="doctor_id",
                doctor_id=doctor1.id,
                other_id=consultorio1.id,
                other_column="consultorio_id",
            )
            assert not visible_para_tenant2, (
                "FUGA CROSS-TENANT: tenant2 puede ver una fila del through de un "
                "doctor de tenant1 en personal_doctors_consultorios."
            )
        finally:
            clear_tenant_guc()
