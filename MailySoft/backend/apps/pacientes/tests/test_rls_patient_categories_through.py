"""
Tests de RLS para pacientes_patients_categories, la tabla through
AUTO-GENERADA del ManyToManyField Patient.categories (Cluster E — auditoría
de sucursales, 2026-07-15, extendida a "cualquier M2M de un TenantAwareModel",
docs/design/sucursales-hallazgos-seguridad.md).

Se cierra en apps/pacientes/migrations/0015_rls_patient_categories_through.py
con una policy que resuelve el tenant vía subconsulta al padre (Patient), ya
que la tabla through auto-generada no tiene columna tenant_id propia.

Ver el docstring de apps/personal/tests/test_rls_doctor_m2m_through.py para
la explicación completa de la limitación del entorno (rol de conexión
SUPERUSER, RLS no se puede probar "de verdad" con SELECT COUNT crudo) y de
la técnica usada aquí: leer la expresión `qual` real desde pg_policies y
evaluarla como SQL real con el GUC fijado por `apply_tenant_guc()`.
"""

from uuid import UUID

import pytest
from django.db import connection

from apps.core.tenant_context import apply_tenant_guc, clear_tenant_guc
from tests.factories import PatientCategoryFactory, PatientFactory, TenantFactory

_TABLE = "pacientes_patients_categories"
_POLICY = "pacientes_patients_categories_tenant_iso"


def _policy_qual() -> str:
    """Lee la expresión USING/qual tal como quedó instalada en pg_policies."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT qual FROM pg_policies
            WHERE schemaname = %s AND tablename = %s AND policyname = %s;
            """,
            ["public", _TABLE, _POLICY],
        )
        row = cursor.fetchone()
    assert row is not None, f"Policy '{_POLICY}' no encontrada en pg_policies para '{_TABLE}'."
    return str(row[0])


def _row_passes_policy(*, patient_id: UUID, category_id: UUID) -> bool:
    """Evalúa la expresión REAL de la policy contra una fila concreta del through."""
    predicate = _policy_qual()
    # noqa justificado: _TABLE es una constante de módulo (nombre de tabla
    # hardcodeado, nunca input de usuario) y `predicate` viene de pg_policies
    # (el catálogo de PostgreSQL, no de un request) — Postgres no permite
    # parametrizar identificadores con %s, solo valores (que sí van
    # parametrizados abajo).
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT EXISTS (
                SELECT 1 FROM {_TABLE}
                WHERE patient_id = %s AND patientcategory_id = %s AND ({predicate})
            );
            """,  # noqa: S608
            [patient_id, category_id],
        )
        row = cursor.fetchone()
    return bool(row[0]) if row else False


@pytest.mark.django_db
class TestPatientCategoriesThroughRls:
    """Aislamiento cross-tenant real de pacientes_patients_categories vía subconsulta."""

    def test_fila_pasa_la_policy_para_tenant_dueno_y_falla_para_otro_tenant(self) -> None:
        """Patient+PatientCategory en tenant1, asociados: la policy los deja
        pasar con el GUC de tenant1 y los bloquea con el GUC de tenant2.
        """
        tenant1 = TenantFactory()
        tenant2 = TenantFactory()
        patient1 = PatientFactory(tenant=tenant1)
        category1 = PatientCategoryFactory(tenant=tenant1)
        patient1.categories.add(category1)

        try:
            apply_tenant_guc(tenant1.id)
            visible_para_tenant1 = _row_passes_policy(
                patient_id=patient1.id, category_id=category1.id
            )
            assert visible_para_tenant1, (
                "La fila del through NO pasa la policy para tenant1 (su dueño "
                "real) — la subconsulta a pacientes_patients está mal escrita."
            )

            apply_tenant_guc(tenant2.id)
            visible_para_tenant2 = _row_passes_policy(
                patient_id=patient1.id, category_id=category1.id
            )
            assert not visible_para_tenant2, (
                "FUGA CROSS-TENANT: tenant2 puede ver una fila del through de un "
                "paciente de tenant1 en pacientes_patients_categories."
            )
        finally:
            clear_tenant_guc()

    def test_fila_pasa_la_policy_con_guc_vacio_fallback_sin_tenant(self) -> None:
        """Sin GUC en contexto, el fallback `current_tenant_id() IS NULL` deja
        pasar la fila (Celery, management commands, seeds)."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        category = PatientCategoryFactory(tenant=tenant)
        patient.categories.add(category)

        clear_tenant_guc()

        visible_sin_guc = _row_passes_policy(patient_id=patient.id, category_id=category.id)
        assert visible_sin_guc, (
            "Sin tenant en el GUC, la policy debería dejar pasar la fila "
            "(fallback current_tenant_id() IS NULL) para no romper Celery/seeds."
        )
