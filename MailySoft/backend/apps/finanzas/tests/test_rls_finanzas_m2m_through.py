"""
Tests de RLS para las tablas through AUTO-GENERADAS de los ManyToManyField
`sucursales` de ServiceConcept y TreatmentPackage (multi-sede — decisión del
dueño, 2026-07-16).

Tablas cubiertas:
    finanzas_service_concepts_sucursales    (ServiceConcept.sucursales)
    finanzas_treatment_packages_sucursales  (TreatmentPackage.sucursales)

Ambas se cierran en apps/finanzas/migrations/0012_rls_finanzas_m2m_through_tables.py
con una policy que resuelve el tenant vía subconsulta al padre (ServiceConcept
/ TreatmentPackage), ya que la tabla through auto-generada no tiene columna
tenant_id propia.

Ver el docstring de apps/personal/tests/test_rls_doctor_m2m_through.py (Cluster
E de la auditoría de sucursales) para la explicación completa de la
limitación del entorno (rol de conexión SUPERUSER, RLS no se puede probar
"de verdad" con SELECT COUNT crudo) y de la técnica usada aquí: leer la
expresión `qual` real desde pg_policies y evaluarla como SQL real con el GUC
fijado por `apply_tenant_guc()`.
"""

from uuid import UUID

import pytest
from django.db import connection

from apps.core.tenant_context import apply_tenant_guc, clear_tenant_guc
from tests.factories import (
    ServiceConceptFactory,
    SucursalFactory,
    TenantFactory,
    TreatmentPackageFactory,
)


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
    *, table: str, policy: str, parent_fk_column: str, parent_id: UUID, sucursal_id: UUID
) -> bool:
    """Evalúa la expresión REAL de la policy contra una fila concreta del through.

    Ejecuta `SELECT EXISTS(... WHERE <predicado real de pg_policies>)` sobre
    la fila (parent_id, sucursal_id). El GUC activo en ese momento (fijado
    con apply_tenant_guc) determina lo que current_tenant_id() devuelve
    dentro del predicado — igual que vería la policy si la aplicara un rol
    NOSUPERUSER.
    """
    predicate = _policy_qual(table=table, policy=policy)
    # noqa justificado: table/parent_fk_column son constantes de módulo
    # (nombres de tabla/columna hardcodeados en las llamadas de este archivo,
    # nunca input de usuario) y `predicate` viene de pg_policies (el catálogo
    # de PostgreSQL, no de un request) — Postgres no permite parametrizar
    # identificadores con %s, solo valores (que sí van parametrizados abajo).
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT EXISTS (
                SELECT 1 FROM {table}
                WHERE {parent_fk_column} = %s AND sucursal_id = %s AND ({predicate})
            );
            """,  # noqa: S608
            [parent_id, sucursal_id],
        )
        row = cursor.fetchone()
    return bool(row[0]) if row else False


@pytest.mark.django_db
class TestServiceConceptSucursalesThroughRls:
    """Aislamiento cross-tenant real de finanzas_service_concepts_sucursales."""

    def test_fila_pasa_la_policy_para_tenant_dueno_y_falla_para_otro_tenant(self) -> None:
        """Concepto+Sucursal en tenant1, asociados: la policy los deja pasar
        con el GUC de tenant1 y los bloquea con el GUC de tenant2 — sin
        exploit, sin fuga cross-tenant en la tabla through."""
        tenant1 = TenantFactory()
        tenant2 = TenantFactory()
        concept1 = ServiceConceptFactory(tenant=tenant1)
        sucursal1 = SucursalFactory(tenant=tenant1)
        concept1.sucursales.add(sucursal1)

        try:
            apply_tenant_guc(tenant1.id)
            visible_para_tenant1 = _row_passes_policy(
                table="finanzas_service_concepts_sucursales",
                policy="finanzas_service_concepts_sucursales_tenant_iso",
                parent_fk_column="serviceconcept_id",
                parent_id=concept1.id,
                sucursal_id=sucursal1.id,
            )
            assert visible_para_tenant1, (
                "La fila del through NO pasa la policy para tenant1 (su dueño "
                "real) — la subconsulta a finanzas_service_concepts está mal escrita."
            )

            apply_tenant_guc(tenant2.id)
            visible_para_tenant2 = _row_passes_policy(
                table="finanzas_service_concepts_sucursales",
                policy="finanzas_service_concepts_sucursales_tenant_iso",
                parent_fk_column="serviceconcept_id",
                parent_id=concept1.id,
                sucursal_id=sucursal1.id,
            )
            assert not visible_para_tenant2, (
                "FUGA CROSS-TENANT: tenant2 puede ver una fila del through de "
                "un concepto de tenant1. La subconsulta al padre no está "
                "aislando por tenant."
            )
        finally:
            clear_tenant_guc()

    def test_fila_pasa_la_policy_con_guc_vacio_fallback_sin_tenant(self) -> None:
        """Sin GUC en contexto (Celery, management commands, seeds), el
        fallback `current_tenant_id() IS NULL` deja pasar la fila."""
        tenant = TenantFactory()
        concept = ServiceConceptFactory(tenant=tenant)
        sucursal = SucursalFactory(tenant=tenant)
        concept.sucursales.add(sucursal)

        clear_tenant_guc()  # asegura GUC vacío (precondición explícita)

        visible_sin_guc = _row_passes_policy(
            table="finanzas_service_concepts_sucursales",
            policy="finanzas_service_concepts_sucursales_tenant_iso",
            parent_fk_column="serviceconcept_id",
            parent_id=concept.id,
            sucursal_id=sucursal.id,
        )
        assert visible_sin_guc, (
            "Sin tenant en el GUC, la policy debería dejar pasar la fila "
            "(fallback current_tenant_id() IS NULL) para no romper Celery/seeds."
        )


@pytest.mark.django_db
class TestTreatmentPackageSucursalesThroughRls:
    """Aislamiento cross-tenant real de finanzas_treatment_packages_sucursales."""

    def test_fila_pasa_la_policy_para_tenant_dueno_y_falla_para_otro_tenant(self) -> None:
        """Mismo escenario que ServiceConcept.sucursales, con TreatmentPackage."""
        tenant1 = TenantFactory()
        tenant2 = TenantFactory()
        package1 = TreatmentPackageFactory(tenant=tenant1)
        sucursal1 = SucursalFactory(tenant=tenant1)
        package1.sucursales.add(sucursal1)

        try:
            apply_tenant_guc(tenant1.id)
            visible_para_tenant1 = _row_passes_policy(
                table="finanzas_treatment_packages_sucursales",
                policy="finanzas_treatment_packages_sucursales_tenant_iso",
                parent_fk_column="treatmentpackage_id",
                parent_id=package1.id,
                sucursal_id=sucursal1.id,
            )
            assert (
                visible_para_tenant1
            ), "La fila del through NO pasa la policy para tenant1 (su dueño real)."

            apply_tenant_guc(tenant2.id)
            visible_para_tenant2 = _row_passes_policy(
                table="finanzas_treatment_packages_sucursales",
                policy="finanzas_treatment_packages_sucursales_tenant_iso",
                parent_fk_column="treatmentpackage_id",
                parent_id=package1.id,
                sucursal_id=sucursal1.id,
            )
            assert not visible_para_tenant2, (
                "FUGA CROSS-TENANT: tenant2 puede ver una fila del through de "
                "un paquete de tenant1 en finanzas_treatment_packages_sucursales."
            )
        finally:
            clear_tenant_guc()

    def test_fila_pasa_la_policy_con_guc_vacio_fallback_sin_tenant(self) -> None:
        tenant = TenantFactory()
        package = TreatmentPackageFactory(tenant=tenant)
        sucursal = SucursalFactory(tenant=tenant)
        package.sucursales.add(sucursal)

        clear_tenant_guc()

        visible_sin_guc = _row_passes_policy(
            table="finanzas_treatment_packages_sucursales",
            policy="finanzas_treatment_packages_sucursales_tenant_iso",
            parent_fk_column="treatmentpackage_id",
            parent_id=package.id,
            sucursal_id=sucursal.id,
        )
        assert visible_sin_guc, (
            "Sin tenant en el GUC, la policy debería dejar pasar la fila "
            "(fallback current_tenant_id() IS NULL) para no romper Celery/seeds."
        )
