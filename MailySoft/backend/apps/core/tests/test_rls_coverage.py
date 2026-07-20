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

Extensión — Cluster E (auditoría de sucursales, 2026-07-15,
docs/design/sucursales-hallazgos-seguridad.md):
    Un ManyToManyField SIN `through` explícito (p.ej. Doctor.consultorios,
    Doctor.sucursales, Patient.categories) hace que Django genere su tabla
    intermedia automáticamente. Esa tabla NO es una subclase de
    TenantAwareModel — no tiene tenant_id propio, no pasa por TenantManager —
    así que el guardián de arriba, que solo enumera subclases de
    TenantAwareModel, nunca la ve. Tres tablas quedaron así sin RLS:
    personal_doctors_consultorios, personal_doctors_sucursales y
    pacientes_patients_categories.

    Se cierran con una migración RunSQL (subconsulta al padre: la fila es
    visible/escribible solo si su FK referencia a un registro tenant-aware
    del tenant activo — ver apps/personal/migrations/0012_rls_doctor_m2m_through_tables.py
    y apps/pacientes/migrations/0015_rls_patient_categories_through.py) y el
    guardián se extiende con `_auto_m2m_through_table_names()` para que
    cualquier M2M nuevo entre dos modelos tenant-aware sin `through` explícito
    y sin su migración RLS correspondiente rompa esta suite, igual que un
    TenantAwareModel nuevo sin RLS.
"""

import pytest
from django.apps import apps
from django.db import connection
from django.db import models as django_models

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


def _auto_m2m_through_table_names() -> list[str]:
    """Nombres de tabla de los through AUTO-GENERADOS de M2M en modelos tenant-aware.

    Se incluye una tabla through si, y solo si:
      1. El ManyToManyField está declarado en un modelo que hereda TenantAwareModel.
      2. El through es AUTO-GENERADO (`_meta.auto_created` es truthy: Django lo
         apunta a la clase del modelo dueño del campo). Un through EXPLÍCITO
         (p.ej. MembershipSucursal) es su propia subclase de TenantAwareModel
         con tenant_id real y ya lo cubre `_tenant_aware_table_names()` — no
         se duplica aquí.
      3. El OTRO extremo del M2M (`field.remote_field.model`) TAMBIÉN hereda
         TenantAwareModel — si no lo fuera, no habría tenant que resolver vía
         subconsulta al padre y el hallazgo no aplicaría.

    auto_created es un atributo de `Options`: Django lo deja en `False` para
    modelos declarados por el desarrollador (incluidos through explícitos) y
    lo apunta a la clase dueña del campo para tablas M2M generadas
    automáticamente — por eso `bool(...)` basta para distinguir los dos casos.
    """
    tables: set[str] = set()
    for model in apps.get_models():
        if model._meta.abstract or model._meta.proxy:
            continue
        if not issubclass(model, TenantAwareModel):
            continue
        for field in model._meta.get_fields():
            if not isinstance(field, django_models.ManyToManyField):
                continue
            through = field.remote_field.through
            if not through._meta.auto_created:
                continue
            related_model = field.remote_field.model
            if not issubclass(related_model, TenantAwareModel):
                continue
            tables.add(through._meta.db_table)
    return sorted(tables)


def _all_rls_required_table_names() -> list[str]:
    """Unión de tablas tenant-aware + tablas through auto de M2M tenant-aware.

    Todos los tests de este módulo que verifican el estado real de RLS
    (habilitado, forzado, con policy, con WITH CHECK, con fallback NULL)
    corren sobre esta unión — así un M2M nuevo sin RLS rompe el guardián
    exactamente igual que un TenantAwareModel nuevo sin RLS.
    """
    return sorted(set(_tenant_aware_table_names()) | set(_auto_m2m_through_table_names()))


@pytest.mark.django_db
class TestRlsCoverage:
    """Verifica que ninguna tabla tenant-aware quede sin RLS habilitado y forzado."""

    def test_hay_al_menos_una_tabla_tenant_aware(self) -> None:
        """Guarda de cordura: si esto da 0, la introspección está mal, no el sistema."""
        assert len(_tenant_aware_table_names()) > 0

    def test_hay_al_menos_una_tabla_through_auto_m2m(self) -> None:
        """Guarda de cordura del Cluster E: si esto da 0, la introspección de
        M2M está mal (hoy existen 3 tablas conocidas: ver
        test_las_tablas_through_m2m_del_cluster_e_tienen_rls), no el sistema.
        """
        assert len(_auto_m2m_through_table_names()) > 0

    def test_todas_las_tablas_tenant_aware_tienen_rls_habilitado_y_forzado(self) -> None:
        """Cada tabla tenant-aware (o through auto de M2M tenant-aware) tiene
        relrowsecurity=True y relforcerowsecurity=True.

        FORCE ROW LEVEL SECURITY es el mismo patrón usado en todas las
        migraciones enable_rls/rls_* existentes: la política aplica incluso
        al rol owner de la conexión de la app.
        """
        tables = _all_rls_required_table_names()

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
        assert not missing, f"Tablas tenant-aware sin fila en pg_class (¿falta migrar?): {missing}"

        not_enabled = [t for t in tables if not rows[t][0]]
        assert not not_enabled, (
            "Tablas tenant-aware (o through auto de M2M) SIN RLS habilitado "
            f"(ENABLE ROW LEVEL SECURITY): {not_enabled}. Si es un modelo "
            "TenantAwareModel, agrega una migración RunSQL siguiendo el patrón "
            "de apps/agenda/migrations/0005_appointment_reminder_rls.py. Si es "
            "una tabla through auto de un ManyToManyField, sigue el patrón de "
            "apps/personal/migrations/0012_rls_doctor_m2m_through_tables.py "
            "(RLS vía subconsulta al modelo padre, sin convertir a through explícito)."
        )

        not_forced = [t for t in tables if not rows[t][1]]
        assert not not_forced, (
            "Tablas tenant-aware (o through auto de M2M) con RLS habilitado "
            f"pero SIN FORCE ROW LEVEL SECURITY: {not_forced}. El rol owner de "
            "la app podría bypassear la política. Agrega FORCE ROW LEVEL "
            "SECURITY a la migración."
        )

    def test_todas_las_tablas_tenant_aware_tienen_al_menos_una_policy(self) -> None:
        """Cada tabla tenant-aware (o through auto de M2M tenant-aware) tiene
        al menos una fila en pg_policies."""
        tables = _all_rls_required_table_names()

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
            f"Tablas tenant-aware (o through auto de M2M) SIN ninguna policy "
            f"en pg_policies: {without_policy}. Si es un modelo TenantAwareModel "
            "con tenant_id propio, agrega una migración RunSQL con CREATE POLICY "
            "USING (tenant_id = current_tenant_id() OR current_tenant_id() IS "
            "NULL). Si es una tabla through sin tenant_id propio, usa la variante "
            "con subconsulta EXISTS al modelo padre, siguiendo el patrón de "
            "apps/personal/migrations/0012_rls_doctor_m2m_through_tables.py."
        )

    def test_todas_las_tablas_tenant_aware_restringen_insert_con_with_check(self) -> None:
        """Cada tabla tenant-aware (o through auto de M2M tenant-aware) tiene al
        menos una policy que restringe INSERT.

        Una policy creada solo con USING protege SELECT/UPDATE/DELETE pero NO
        valida INSERT: una fila con tenant_id ajeno entra sin error (defecto
        ALTO-2, corregido primero en expediente/0005_rls_with_check.py y luego
        en el resto de las apps). Para que INSERT quede cubierto debe existir
        una policy cmd IN ('ALL','INSERT') con with_check NO nulo.
        """
        tables = _all_rls_required_table_names()

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
            "Tablas tenant-aware (o through auto de M2M) cuya policy NO "
            f"restringe INSERT (falta WITH CHECK): {insert_unprotected}. Agrega "
            "una migración con ALTER POLICY ... WITH CHECK (tenant_id = "
            "current_tenant_id() OR current_tenant_id() IS NULL), siguiendo el "
            "patrón de apps/expediente/migrations/0005_rls_with_check.py."
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
        tables = _all_rls_required_table_names()

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

    def test_las_tablas_through_m2m_del_cluster_e_tienen_rls(self) -> None:
        """Regresión explícita del Cluster E (auditoría de sucursales, 2026-07-15,
        docs/design/sucursales-hallazgos-seguridad.md).

        No reemplaza los tests genéricos de arriba (que cubren cualquier M2M
        futuro entre modelos tenant-aware), pero deja constancia expresa de
        que estas 3 tablas through auto-generadas quedaron cubiertas:
          - personal_doctors_consultorios (Doctor.consultorios)
          - personal_doctors_sucursales   (Doctor.sucursales)
          - pacientes_patients_categories (Patient.categories)

        Las 3 usan RLS vía subconsulta al modelo padre (no tienen tenant_id
        propio): ver apps/personal/migrations/0012_rls_doctor_m2m_through_tables.py
        y apps/pacientes/migrations/0015_rls_patient_categories_through.py.
        """
        gap_tables = [
            "personal_doctors_consultorios",
            "personal_doctors_sucursales",
            "pacientes_patients_categories",
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
            assert enabled, f"{table}: RLS no habilitado (Cluster E reabierto)."
            assert forced, f"{table}: RLS no forzado (Cluster E reabierto)."

        # Confirma también que la introspección genérica los detecta como
        # requiriendo RLS (no solo que existan hardcodeados en esta lista).
        detected = set(_auto_m2m_through_table_names())
        assert set(gap_tables) <= detected, (
            "La introspección genérica _auto_m2m_through_table_names() no "
            f"detectó alguna de estas tablas: {set(gap_tables) - detected}. "
            "Revisa que el M2M siga declarado sin `through` explícito y que "
            "ambos extremos hereden TenantAwareModel."
        )
