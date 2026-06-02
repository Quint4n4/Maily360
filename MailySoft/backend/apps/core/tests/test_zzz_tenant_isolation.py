"""
Tests de aislamiento del TenantManager (la regla más importante del sistema).

Estrategia de tabla temporal:
- El modelo de test `TenantAwareNoFKModel` replica la estructura de TenantAwareModel
  pero con `tenant_id` como UUIDField (no ForeignKey) para evitar que Django
  registre un ManyToOneRel en Tenant._meta que cause problemas en otros tests.
- El TenantManager funciona igual porque filtra por `tenant_id`, no por la FK.
- El fixture `isolated_tenant_table` tiene scope="module" y crea/destruye la tabla
  con autocommit DDL, fuera de las transacciones de pytest.

IMPORTANTE: estos tests validan la promesa central del sistema multi-tenant:
una clínica NUNCA puede ver datos de otra clínica.
"""

import uuid
from collections.abc import Generator

import pytest
from django.db import connection, models
from django.utils import timezone

from apps.core.managers import TenantManager
from apps.core.tenant_context import (
    get_current_tenant,
    is_tenant_context_active,
    set_current_tenant,
    set_tenant_context_active,
)
from tests.factories import TenantFactory

_TEST_TABLE = "core_tenantawaretest_nofk"


# ---------------------------------------------------------------------------
# Modelo dummy — usa UUIDField para tenant_id en lugar de FK.
# Esto evita que Django registre un ManyToOneRel en Tenant._meta, lo cual
# causaría que otros tests que hacen tenant.delete() fallen con UndefinedTable.
# El TenantManager filtra por tenant_id (no por FK), así que funciona igual.
# ---------------------------------------------------------------------------


class TenantAwareNoFKModel(models.Model):
    """Modelo temporal para ejercitar TenantManager sin FK a Tenant.

    Replica la estructura mínima de TenantAwareModel necesaria para que
    TenantManager funcione: tenant_id como UUID y deleted_at para soft-delete.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # tenant_id como UUID simple — NO como ForeignKey para evitar ManyToOneRel
    tenant_id = models.UUIDField(db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    name = models.CharField(max_length=100)

    objects: TenantManager = TenantManager()
    all_objects: models.Manager = models.Manager()  # type: ignore[type-arg]

    class Meta:
        app_label = "core"
        db_table = _TEST_TABLE
        managed = False


# ---------------------------------------------------------------------------
# Fixture de módulo: DDL en autocommit fuera de las transacciones de pytest
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def isolated_tenant_table(  # type: ignore[no-untyped-def]
    django_db_setup: None,
    django_db_blocker: pytest.FixtureRequest,
) -> Generator[None, None, None]:
    """Crea la tabla antes de todos los tests del módulo y la dropea al final.

    Usa autocommit=True para el DDL para evitar savepoints activos que
    causan 'pending trigger events' en PostgreSQL al hacer DROP TABLE.
    """
    from django.db import connections

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        conn = connection.connection
        if conn is None:
            connection.ensure_connection()
            conn = connection.connection
        was_autocommit = conn.autocommit
        conn.autocommit = True
        try:
            if _TEST_TABLE in connection.introspection.table_names():
                with connection.schema_editor() as se:
                    se.delete_model(TenantAwareNoFKModel)
            with connection.schema_editor() as se:
                se.create_model(TenantAwareNoFKModel)
        finally:
            conn.autocommit = was_autocommit

    yield

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        conn = connection.connection
        if conn is None:
            connection.ensure_connection()
            conn = connection.connection
        was_autocommit = conn.autocommit
        conn.autocommit = True
        try:
            if _TEST_TABLE in connection.introspection.table_names():
                with connection.schema_editor() as se:
                    se.delete_model(TenantAwareNoFKModel)
        finally:
            conn.autocommit = was_autocommit

        connections.close_all()


# ---------------------------------------------------------------------------
# Helper: crear instancias del modelo de test con el tenant_id correcto
# ---------------------------------------------------------------------------


def _create(tenant: object, name: str, **kwargs: object) -> TenantAwareNoFKModel:
    """Crea un registro en el modelo de test pasando tenant_id explícitamente."""
    return TenantAwareNoFKModel.all_objects.create(
        tenant_id=tenant.id,  # type: ignore[union-attr]
        name=name,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Tests de aislamiento
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_manager_returns_all_records_when_no_tenant_in_context(
    isolated_tenant_table: None,
) -> None:
    """Sin tenant en el contexto (modo admin/migraciones), objects devuelve todo.

    AJUSTE FIX-2: ahora la condición de "sin filtro" es context_active=False,
    no solo tenant=None. Fuera de request (Celery/migraciones) context_active
    nunca se pone a True, por lo que el manager devuelve todos los registros.
    """
    # Arrange
    tenant_a = TenantFactory()
    tenant_b = TenantFactory()
    _create(tenant_a, "A1")
    _create(tenant_b, "B1")
    assert get_current_tenant() is None  # precondición
    assert not is_tenant_context_active()  # precondición: fuera de request

    # Act
    count = TenantAwareNoFKModel.objects.count()

    # Assert
    assert count == 2


@pytest.mark.django_db
def test_manager_filters_by_current_tenant(isolated_tenant_table: None) -> None:
    """Con tenant en contexto de request, objects filtra solo los datos de ese tenant.

    AJUSTE FIX-2: se requiere set_tenant_context_active(True) para simular un request HTTP.
    Sin esa llamada el manager asume contexto Celery/migraciones y no filtra.
    """
    # Arrange
    tenant_a = TenantFactory()
    tenant_b = TenantFactory()
    _create(tenant_a, "A1")
    _create(tenant_a, "A2")
    _create(tenant_b, "B1")

    # Act — simular request HTTP con tenant_a activo
    set_tenant_context_active(True)
    set_current_tenant(tenant_a)
    count = TenantAwareNoFKModel.objects.count()
    names = set(TenantAwareNoFKModel.objects.values_list("name", flat=True))

    # Assert
    assert count == 2
    assert names == {"A1", "A2"}


@pytest.mark.django_db
def test_tenant_a_cannot_see_tenant_b_data(isolated_tenant_table: None) -> None:
    """Tenant A NO puede ver NINGÚN dato de tenant B — regla de aislamiento CRÍTICA.

    AJUSTE FIX-2: se activa el contexto de request para ejercitar el filtrado.
    """
    # Arrange
    tenant_a = TenantFactory()
    tenant_b = TenantFactory()
    _create(tenant_a, "solo-A")
    _create(tenant_b, "solo-B")

    # Act — simular request HTTP con tenant_a activo
    set_tenant_context_active(True)
    set_current_tenant(tenant_a)
    names_visible = list(TenantAwareNoFKModel.objects.values_list("name", flat=True))

    # Assert
    assert "solo-B" not in names_visible, "FUGA DE DATOS: tenant_a ve datos de tenant_b"


@pytest.mark.django_db
def test_tenant_b_cannot_see_tenant_a_data(isolated_tenant_table: None) -> None:
    """Simétrico: tenant B tampoco puede ver datos de tenant A.

    AJUSTE FIX-2: se activa el contexto de request para ejercitar el filtrado.
    """
    # Arrange
    tenant_a = TenantFactory()
    tenant_b = TenantFactory()
    _create(tenant_a, "solo-A")
    _create(tenant_b, "solo-B")

    # Act — simular request HTTP con tenant_b activo
    set_tenant_context_active(True)
    set_current_tenant(tenant_b)
    names_visible = list(TenantAwareNoFKModel.objects.values_list("name", flat=True))

    # Assert
    assert "solo-A" not in names_visible, "FUGA DE DATOS: tenant_b ve datos de tenant_a"


@pytest.mark.django_db
def test_manager_excludes_soft_deleted(isolated_tenant_table: None) -> None:
    """Filas con deleted_at != NULL no aparecen en .objects (sí en all_objects).

    AJUSTE FIX-2: se activa el contexto de request para que el filtrado por tenant funcione.
    """
    # Arrange
    tenant = TenantFactory()
    set_tenant_context_active(True)
    set_current_tenant(tenant)
    _create(tenant, "alive")
    _create(tenant, "dead", deleted_at=timezone.now())

    # Assert
    assert TenantAwareNoFKModel.objects.count() == 1
    assert TenantAwareNoFKModel.all_objects.filter(tenant_id=tenant.id).count() == 2


@pytest.mark.django_db
def test_all_objects_bypasses_tenant_filter(isolated_tenant_table: None) -> None:
    """all_objects ignora el contexto de tenant y devuelve todos los registros.

    AJUSTE FIX-2: aunque context_active=True, all_objects siempre ignora el filtro.
    """
    # Arrange
    tenant_a = TenantFactory()
    tenant_b = TenantFactory()
    _create(tenant_a, "A1")
    _create(tenant_b, "B1")
    set_tenant_context_active(True)
    set_current_tenant(tenant_a)

    # Assert
    assert TenantAwareNoFKModel.all_objects.count() == 2


@pytest.mark.django_db
def test_all_objects_includes_soft_deleted(isolated_tenant_table: None) -> None:
    """all_objects devuelve también los registros soft-deleted."""
    # Arrange
    tenant = TenantFactory()
    _create(tenant, "alive")
    _create(tenant, "dead", deleted_at=timezone.now())

    # Assert
    assert TenantAwareNoFKModel.all_objects.filter(tenant_id=tenant.id).count() == 2


@pytest.mark.django_db
def test_manager_returns_none_when_context_active_but_no_tenant(
    isolated_tenant_table: None,
) -> None:
    """FIX-2 (falla segura): dentro de un request sin tenant resuelto, objects devuelve vacío.

    Escenario: endpoint olvidó autenticación o el usuario no tiene membresía.
    El manager NO debe exponer datos de todos los tenants — devuelve QuerySet vacío.
    Esta es la regla más crítica de seguridad del sistema multi-tenant.
    """
    # Arrange — crear datos de dos tenants distintos
    tenant_a = TenantFactory()
    tenant_b = TenantFactory()
    _create(tenant_a, "secreto-A")
    _create(tenant_b, "secreto-B")

    # Simular: contexto de request activo pero sin tenant (usuario sin membresía activa)
    set_tenant_context_active(True)
    set_current_tenant(None)  # tenant=None dentro de request

    # Act
    count = TenantAwareNoFKModel.objects.count()
    names = list(TenantAwareNoFKModel.objects.values_list("name", flat=True))

    # Assert — ningún dato visible, falla segura
    assert count == 0, (
        "FUGA DE DATOS CRÍTICA: con context_active=True y tenant=None, "
        "el manager NO debe devolver ningún registro."
    )
    assert names == []


@pytest.mark.django_db
def test_switching_tenant_context_changes_visible_data(isolated_tenant_table: None) -> None:
    """Cambiar el tenant en el contexto cambia inmediatamente los datos visibles.

    AJUSTE FIX-2: se activa el contexto de request una sola vez al inicio.
    """
    # Arrange
    tenant_a = TenantFactory()
    tenant_b = TenantFactory()
    _create(tenant_a, "dato-A")
    _create(tenant_b, "dato-B")

    # Act — simular request HTTP, cambiando el tenant activo
    set_tenant_context_active(True)

    set_current_tenant(tenant_a)
    names_as_a = list(TenantAwareNoFKModel.objects.values_list("name", flat=True))

    set_current_tenant(tenant_b)
    names_as_b = list(TenantAwareNoFKModel.objects.values_list("name", flat=True))

    # Assert
    assert names_as_a == ["dato-A"]
    assert names_as_b == ["dato-B"]
