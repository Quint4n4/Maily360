"""
Test guardián: TODO modelo tenant-aware debe tener Row Level Security en PostgreSQL.

Contexto (auditoría de seguridad 2026-06-25 — Fase 0 de docs/design/plataforma-fases-plan.md):
se encontraron 4 tablas que heredan TenantAwareModel pero cuya migración de
creación nunca agregó la política RLS: notas_notes, agenda_item_notes,
agenda_blocks y agenda_appointment_types. El filtrado por tenant del
TenantManager (capa aplicación) las protegía, pero sin RLS (capa BD) un bug
en el manager, una query cruda o un acceso fuera del ORM habría expuesto
datos de otro tenant.

Este test recorre TODOS los modelos concretos registrados en Django que
heredan de TenantAwareModel y verifica, contra el catálogo de PostgreSQL
(pg_tables / pg_policies), que:
  1. La tabla tiene RLS habilitado (relrowsecurity).
  2. La tabla tiene RLS forzado (relforcerowsecurity) — aplica incluso al
     rol owner de la conexión, igual que el resto de las migraciones RLS.
  3. Existe al menos una política en pg_policies.

Si en el futuro se agrega un modelo tenant-aware nuevo y se olvida la
migración `enable_rls`/`rls_*`, este test falla en CI señalando exactamente
qué tabla falta — así la brecha de 2026-06-25 no se repite.
"""

import pytest
from django.apps import apps
from django.db import connection

from apps.core.models import TenantAwareModel


def _tenant_aware_table_names() -> list[str]:
    """Nombres de tabla de todos los modelos concretos que heredan TenantAwareModel.

    Excluye modelos abstractos y proxies (no tienen tabla propia).
    """
    tables: list[str] = []
    for model in apps.get_models():
        if model._meta.abstract or model._meta.proxy:
            continue
        if not issubclass(model, TenantAwareModel):
            continue
        tables.append(model._meta.db_table)
    return sorted(set(tables))


@pytest.mark.django_db
class TestRlsCoverage:
    """Verifica que ninguna tabla tenant-aware quede sin RLS habilitado y forzado."""

    def test_hay_al_menos_una_tabla_tenant_aware(self) -> None:
        """Guarda de cordura: si esto da 0, la introspección está mal, no el sistema."""
        assert len(_tenant_aware_table_names()) > 0

    def test_todas_las_tablas_tenant_aware_tienen_rls_habilitado_y_forzado(self) -> None:
        """Cada tabla tenant-aware tiene relrowsecurity=True y relforcerowsecurity=True.

        FORCE ROW LEVEL SECURITY es el mismo patrón usado en todas las
        migraciones enable_rls/rls_* existentes: la política aplica incluso
        al rol owner de la conexión de la app.
        """
        tables = _tenant_aware_table_names()

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relkind = 'r'
                  AND c.relname = ANY(%s);
                """,
                [tables],
            )
            rows: dict[str, tuple[bool, bool]] = {
                row[0]: (row[1], row[2]) for row in cursor.fetchall()
            }

        missing = [t for t in tables if t not in rows]
        assert not missing, (
            f"Tablas tenant-aware sin fila en pg_class (¿falta migrar?): {missing}"
        )

        not_enabled = [t for t in tables if not rows[t][0]]
        assert not not_enabled, (
            "Tablas tenant-aware SIN RLS habilitado (ENABLE ROW LEVEL SECURITY): "
            f"{not_enabled}. Agrega una migración RunSQL siguiendo el patrón de "
            "apps/agenda/migrations/0005_appointment_reminder_rls.py."
        )

        not_forced = [t for t in tables if not rows[t][1]]
        assert not not_forced, (
            "Tablas tenant-aware con RLS habilitado pero SIN FORCE ROW LEVEL "
            f"SECURITY: {not_forced}. El rol owner de la app podría bypassear "
            "la política. Agrega FORCE ROW LEVEL SECURITY a la migración."
        )

    def test_todas_las_tablas_tenant_aware_tienen_al_menos_una_policy(self) -> None:
        """Cada tabla tenant-aware tiene al menos una fila en pg_policies."""
        tables = _tenant_aware_table_names()

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT tablename, COUNT(*)
                FROM pg_policies
                WHERE schemaname = 'public'
                  AND tablename = ANY(%s)
                GROUP BY tablename;
                """,
                [tables],
            )
            counts: dict[str, int] = dict(cursor.fetchall())

        without_policy = [t for t in tables if counts.get(t, 0) == 0]
        assert not without_policy, (
            f"Tablas tenant-aware SIN ninguna policy en pg_policies: {without_policy}. "
            "Agrega una migración RunSQL con CREATE POLICY "
            "USING (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL), "
            "siguiendo el patrón de apps/agenda/migrations/0005_appointment_reminder_rls.py."
        )

    def test_todas_las_tablas_tenant_aware_restringen_insert_con_with_check(self) -> None:
        """Cada tabla tenant-aware tiene al menos una policy que restringe INSERT.

        Una policy creada solo con USING protege SELECT/UPDATE/DELETE pero NO
        valida INSERT: una fila con tenant_id ajeno entra sin error (defecto
        ALTO-2, corregido primero en expediente/0005_rls_with_check.py y luego
        en el resto de las apps). Para que INSERT quede cubierto debe existir
        una policy cmd IN ('ALL','INSERT') con with_check NO nulo.
        """
        tables = _tenant_aware_table_names()

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT tablename, COUNT(*)
                FROM pg_policies
                WHERE schemaname = 'public'
                  AND tablename = ANY(%s)
                  AND cmd IN ('ALL', 'INSERT')
                  AND with_check IS NOT NULL
                GROUP BY tablename;
                """,
                [tables],
            )
            covered: dict[str, int] = dict(cursor.fetchall())

        insert_unprotected = [t for t in tables if covered.get(t, 0) == 0]
        assert not insert_unprotected, (
            "Tablas tenant-aware cuya policy NO restringe INSERT (falta WITH "
            f"CHECK): {insert_unprotected}. Agrega una migración con ALTER "
            "POLICY ... WITH CHECK (tenant_id = current_tenant_id() OR "
            "current_tenant_id() IS NULL), siguiendo el patrón de "
            "apps/expediente/migrations/0005_rls_with_check.py."
        )

    def test_with_check_incluye_el_fallback_sin_tenant(self) -> None:
        """El WITH CHECK debe incluir `current_tenant_id() IS NULL`, igual que el USING.

        Un WITH CHECK ESTRICTO (`tenant_id = current_tenant_id()`, sin el
        `OR ... IS NULL`) rechaza los INSERT hechos SIN tenant en el GUC:
        alta de clínica (PlatformAPIView cross-tenant), tareas Celery, seeds y
        migraciones de datos. Con un rol superuser el defecto queda oculto (RLS
        no aplica); con el rol de aplicación NOSUPERUSER el INSERT explota con
        "new row violates row-level security policy" (bug 2026-07-03, alta de
        clínica en producción; corregido en clinica/0013_rls_with_check_null_fallback).

        Nota: no se puede validar funcionalmente aquí porque la suite corre con
        un rol superuser (exento de RLS); por eso se inspecciona la expresión de
        la policy en pg_policies.
        """
        tables = _tenant_aware_table_names()

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT tablename, with_check
                FROM pg_policies
                WHERE schemaname = 'public'
                  AND tablename = ANY(%s)
                  AND cmd IN ('ALL', 'INSERT')
                  AND with_check IS NOT NULL;
                """,
                [tables],
            )
            rows = cursor.fetchall()

        estrictas = sorted(
            {table for table, with_check in rows if "is null" not in (with_check or "").lower()}
        )
        assert not estrictas, (
            "Policies cuyo WITH CHECK es estricto y NO incluye el fallback "
            f"'current_tenant_id() IS NULL': {estrictas}. Rompen los INSERT sin "
            "tenant en el GUC (portal, Celery, seeds) con un rol NOSUPERUSER. "
            "Agrega `OR current_tenant_id() IS NULL` al WITH CHECK con ALTER "
            "POLICY, como clinica/0013_rls_with_check_null_fallback.py."
        )

    def test_las_4_tablas_de_la_brecha_2026_06_25_tienen_rls(self) -> None:
        """Regresión explícita de la brecha encontrada en la auditoría del 2026-06-25.

        No reemplaza los tests genéricos de arriba (que cubren cualquier
        modelo futuro), pero deja constancia expresa de que estas 4 tablas
        puntuales quedaron cubiertas.
        """
        gap_tables = [
            "notas_notes",
            "agenda_item_notes",
            "agenda_blocks",
            "agenda_appointment_types",
        ]

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relkind = 'r'
                  AND c.relname = ANY(%s);
                """,
                [gap_tables],
            )
            rows: dict[str, tuple[bool, bool]] = {
                row[0]: (row[1], row[2]) for row in cursor.fetchall()
            }

        for table in gap_tables:
            assert table in rows, f"{table}: no existe en pg_class."
            enabled, forced = rows[table]
            assert enabled, f"{table}: RLS no habilitado (brecha 2026-06-25 reabierta)."
            assert forced, f"{table}: RLS no forzado (brecha 2026-06-25 reabierta)."
