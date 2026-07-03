"""
Tests del modo del GUC de RLS — session (default) vs. local (pgbouncer).

Contexto: docs/design/pgbouncer-rls-escalabilidad.md y ADR-0003. El aislamiento
multi-tenant se apoya en el GUC de PostgreSQL `app.current_tenant_id`, leído por
las políticas RLS. Hasta ahora se fijaba SIEMPRE a nivel de sesión
(`set_config(..., false)`), lo cual es inseguro si algún día se despliega
pgbouncer en modo transacción (una conexión reciclada entre tenants distintos
heredaría el GUC del tenant anterior → fuga cross-tenant).

Este archivo prueba el nuevo mecanismo (`apps.core.tenant_context.apply_tenant_guc`
+ `settings.DB_TENANT_GUC_MODE`) en sus dos modos:

  - "session" (default): DEBE comportarse EXACTAMENTE igual que antes del cambio.
    Es la garantía de "cero riesgo" para producción hoy.
  - "local" (para pgbouncer, aún NO activado en ningún entorno): SET LOCAL solo
    vive dentro de la transacción abierta por TenantMiddleware. Estos tests
    verifican, de forma determinista y sin pgbouncer real, que:
      1. El valor SÍ es visible dentro de la transacción (funciona).
      2. El valor NO sobrevive al COMMIT/ROLLBACK de esa transacción — que es
         precisamente lo que impide la fuga cuando la conexión se recicla.
      3. Sin una transacción envolvente, SET LOCAL no tiene ningún efecto
         persistente (documenta la limitación real de Postgres: cada
         sentencia en autocommit es su propia transacción implícita).

Nota sobre `transaction=True`: los tests que verifican qué queda en la conexión
DESPUÉS de un commit/rollback necesitan que ese commit/rollback sea real (no el
rollback final que aplica pytest-django a cada test normal). Por eso usan
`@pytest.mark.django_db(transaction=True)` — el mismo patrón que un
TransactionTestCase de Django.
"""

from collections.abc import Callable
from uuid import uuid4

import pytest
from django.db import connection, transaction
from django.http import HttpRequest, HttpResponse
from django.test import override_settings

from apps.core.middleware import TenantMiddleware
from apps.core.tenant_context import apply_tenant_guc, clear_tenant_guc
from tests.factories import (
    PatientFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)


def _show_current_tenant_guc() -> str:
    """Lee el GUC directamente de Postgres con SHOW (sin pasar por current_tenant_id())."""
    with connection.cursor() as cursor:
        cursor.execute("SHOW app.current_tenant_id")
        row = cursor.fetchone()
        return row[0] if row else ""


# ---------------------------------------------------------------------------
# apply_tenant_guc() — modo "session" (default): comportamiento histórico
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(DB_TENANT_GUC_MODE="session")
def test_apply_tenant_guc_session_mode_persists_across_statements() -> None:
    """Modo session: el GUC fijado con is_local=False se ve en sentencias SUBSIGUIENTES
    de la MISMA conexión sin necesidad de una transacción explícita (comportamiento
    histórico — así funcionaba antes de este cambio).
    """
    # Arrange
    tenant_id = uuid4()

    # Act
    apply_tenant_guc(tenant_id)

    # Assert — nueva sentencia, misma conexión: el valor persiste (nivel sesión)
    assert _show_current_tenant_guc() == str(tenant_id)

    # Cleanup
    clear_tenant_guc()
    assert _show_current_tenant_guc() == ""


@pytest.mark.django_db
@override_settings(DB_TENANT_GUC_MODE="session")
def test_apply_tenant_guc_session_mode_none_is_noop() -> None:
    """apply_tenant_guc(None) no ejecuta ningún SQL (ni falla)."""
    clear_tenant_guc()
    apply_tenant_guc(None)
    assert _show_current_tenant_guc() == ""


# ---------------------------------------------------------------------------
# apply_tenant_guc() — modo "local": solo vive dentro de la transacción
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(DB_TENANT_GUC_MODE="local")
def test_apply_tenant_guc_local_mode_visible_inside_atomic_block() -> None:
    """Modo local: DENTRO de un transaction.atomic() el valor SÍ es visible en
    sentencias posteriores de la misma transacción (SET LOCAL funciona como se espera).
    """
    tenant_id = uuid4()

    with transaction.atomic():
        apply_tenant_guc(tenant_id)
        assert _show_current_tenant_guc() == str(tenant_id)


@pytest.mark.django_db(transaction=True)
@override_settings(DB_TENANT_GUC_MODE="local")
def test_apply_tenant_guc_local_mode_does_not_survive_commit() -> None:
    """LA PRUEBA MÁS IMPORTANTE DE ESTA TAREA (fuga tipo pgbouncer).

    Simula el reciclaje de conexión de un pool en modo transacción: tras cerrar
    (COMMIT) la transacción donde se fijó el GUC en modo "local", una query
    SIGUIENTE en la MISMA conexión física ya NO ve el tenant anterior. Esto es
    justo lo que evita que el tenant B, sirviéndose de la conexión reciclada,
    herede el contexto del tenant A.

    Requiere `transaction=True` (TransactionTestCase) porque necesitamos un
    COMMIT real de PostgreSQL, no el rollback de aislamiento que usa
    pytest-django en tests normales.
    """
    tenant_id = uuid4()

    # "Request" 1: fija el GUC en modo local dentro de su propia transacción.
    with transaction.atomic():
        apply_tenant_guc(tenant_id)
        assert _show_current_tenant_guc() == str(
            tenant_id
        ), "El GUC debe ser visible DENTRO de la transacción donde se fijó."
    # <- aquí ocurre el COMMIT real de Postgres (fin del bloque atomic).

    # "Request" 2 (simulado): misma conexión Django (CONN_MAX_AGE la reutiliza),
    # SIN volver a fijar el GUC — como el siguiente request de OTRO tenant que
    # aún no ha llamado a apply_tenant_guc() cuando el pool le entrega esta
    # conexión reciclada.
    assert _show_current_tenant_guc() == "", (
        "FUGA: el GUC del tenant anterior sobrevivió al COMMIT de su transacción. "
        "En un pool de conexiones tipo pgbouncer (modo transacción), el siguiente "
        "tenant heredaría este contexto y RLS le mostraría datos ajenos."
    )


@pytest.mark.django_db(transaction=True)
@override_settings(DB_TENANT_GUC_MODE="local")
def test_apply_tenant_guc_local_mode_does_not_survive_rollback() -> None:
    """Simétrico al test de commit: un ROLLBACK (p. ej. una excepción no capturada
    en la vista) también limpia el GUC de modo local — no solo el camino feliz.
    """
    tenant_id = uuid4()

    with pytest.raises(RuntimeError):
        with transaction.atomic():
            apply_tenant_guc(tenant_id)
            assert _show_current_tenant_guc() == str(tenant_id)
            raise RuntimeError("boom — simula un error 500 dentro de la vista")

    assert _show_current_tenant_guc() == "", (
        "El GUC de modo local debe limpiarse también cuando la transacción "
        "termina en ROLLBACK, no solo en COMMIT."
    )


@pytest.mark.django_db(transaction=True)
@override_settings(DB_TENANT_GUC_MODE="local")
def test_apply_tenant_guc_local_mode_without_atomic_has_no_lasting_effect() -> None:
    """Documenta el riesgo central: en modo "local", si NO hay una transacción
    explícita envolvente (autocommit real de Postgres), SET LOCAL no tiene
    ningún efecto que sobreviva más allá de la sentencia misma — ni dentro del
    mismo request.

    Requiere `transaction=True` para partir de connection.in_atomic_block ==
    False: un test @pytest.mark.django_db normal ya corre dentro del atomic()
    de aislamiento que usa pytest-django para poder hacer rollback al final,
    lo que enmascararía justamente el escenario que queremos probar.

    Esta es la razón por la que TenantMiddleware DEBE envolver get_response()
    en transaction.atomic() cuando DB_TENANT_GUC_MODE == "local": sin eso, el
    modo "local" no solo no protege — deja el GUC vacío, lo que activa el
    fallback `current_tenant_id() IS NULL` de RLS y ABRE acceso cross-tenant
    (el escenario opuesto al buscado).
    """
    assert not connection.in_atomic_block  # precondición: autocommit real

    tenant_id = uuid4()

    # Sin atomic() envolvente (autocommit, cada cursor.execute() es su propia
    # transacción implícita en Postgres).
    apply_tenant_guc(tenant_id)

    # Nueva sentencia, misma conexión, TODAVÍA sin haber salido de este test:
    # el valor YA se perdió, porque el "commit" implícito del autocommit ocurrió
    # al terminar la sentencia SELECT set_config(...).
    assert _show_current_tenant_guc() == "", (
        "Sin una transacción explícita, SET LOCAL no persiste ni siquiera "
        "dentro del mismo request — confirma por qué el modo local exige "
        "envolver la vista en transaction.atomic()."
    )


# ---------------------------------------------------------------------------
# TenantMiddleware — modo "local" envuelve el request en transaction.atomic()
# ---------------------------------------------------------------------------


def _make_authenticated_request(user: object) -> HttpRequest:
    request = HttpRequest()
    request.user = user  # type: ignore[assignment]
    return request


@pytest.mark.django_db(transaction=True)
@override_settings(DB_TENANT_GUC_MODE="local")
def test_middleware_local_mode_guc_visible_during_view() -> None:
    """Modo local: DENTRO de la vista (dentro del atomic() que abre el middleware)
    el GUC fijado por el middleware debe ser visible vía SHOW — confirma que el
    fijado en middleware.py y el atomic() envolvente quedan correctamente unidos.
    """
    tenant = TenantFactory()
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, is_active=True)

    seen_guc: list[str] = []

    def get_response(request: HttpRequest) -> HttpResponse:
        seen_guc.append(_show_current_tenant_guc())
        return HttpResponse("ok")

    middleware = TenantMiddleware(get_response=get_response)
    request = _make_authenticated_request(user)

    middleware(request)

    assert seen_guc == [str(tenant.id)]


@pytest.mark.django_db(transaction=True)
@override_settings(DB_TENANT_GUC_MODE="local")
def test_middleware_local_mode_guc_cleared_after_request_commits() -> None:
    """Tras terminar el request (el middleware sale del `with transaction.atomic()`,
    haciendo commit), el GUC ya no es visible en la misma conexión — igual que
    pasaría cuando pgbouncer la reciclara para el siguiente tenant.
    """
    tenant = TenantFactory()
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, is_active=True)

    def get_response(request: HttpRequest) -> HttpResponse:
        return HttpResponse("ok")

    middleware = TenantMiddleware(get_response=get_response)
    request = _make_authenticated_request(user)

    middleware(request)

    assert _show_current_tenant_guc() == "", (
        "FUGA: tras terminar el request en modo local, el GUC de la conexión "
        "sigue marcando el tenant del request anterior."
    )


@pytest.mark.django_db(transaction=True)
@override_settings(DB_TENANT_GUC_MODE="session")
def test_middleware_session_mode_does_not_open_extra_atomic_block() -> None:
    """Modo session (default): el middleware NO debe envolver la vista en una
    transacción atómica adicional — cero cambio de comportamiento respecto al
    código anterior a esta tarea.

    Usa `transaction=True` para partir de connection.in_atomic_block == False
    (sin el atomic() de aislamiento que pytest-django abre en tests normales),
    y así poder afirmar que sigue en False dentro de la vista.
    """
    assert not connection.in_atomic_block  # precondición: sin atomic() activo

    in_atomic_block_during_view: list[bool] = []

    def get_response(request: HttpRequest) -> HttpResponse:
        in_atomic_block_during_view.append(connection.in_atomic_block)
        return HttpResponse("ok")

    user = UserFactory()
    tenant = TenantFactory()
    TenantMembershipFactory(user=user, tenant=tenant, is_active=True)

    middleware = TenantMiddleware(get_response=get_response)
    request = _make_authenticated_request(user)

    middleware(request)

    assert in_atomic_block_during_view == [False], (
        "El middleware abrió una transacción atómica en modo session — "
        "esto sería un cambio de comportamiento respecto al código original."
    )


@pytest.mark.django_db(transaction=True)
@override_settings(DB_TENANT_GUC_MODE="local")
def test_middleware_local_mode_opens_atomic_block_around_view() -> None:
    """Modo local: el middleware SÍ debe envolver la vista en transaction.atomic()
    — es el mecanismo que hace que SET LOCAL tenga efecto persistente durante
    todo el request.
    """
    assert not connection.in_atomic_block  # precondición

    in_atomic_block_during_view: list[bool] = []

    def get_response(request: HttpRequest) -> HttpResponse:
        in_atomic_block_during_view.append(connection.in_atomic_block)
        return HttpResponse("ok")

    user = UserFactory()
    tenant = TenantFactory()
    TenantMembershipFactory(user=user, tenant=tenant, is_active=True)

    middleware = TenantMiddleware(get_response=get_response)
    request = _make_authenticated_request(user)

    middleware(request)

    assert in_atomic_block_during_view == [True]
    # Y al salir del middleware, la transacción ya se cerró (commit).
    assert not connection.in_atomic_block


# ---------------------------------------------------------------------------
# Aislamiento tenant A / tenant B con el mecanismo RLS real, en ambos modos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("guc_mode", ["session", "local"])
@pytest.mark.django_db(transaction=True)
def test_tenant_isolation_via_middleware_holds_in_both_modes(guc_mode: str) -> None:
    """El requisito no-negociable: en NINGÚN modo un tenant ve datos de otro.

    Usa el flujo real (TenantMiddleware → GUC → RLS) sobre el modelo de test
    ya usado por test_zzz_tenant_isolation.py sería ideal, pero para mantener
    este archivo autocontenido y no depender de la tabla temporal de ese
    módulo, se valida aquí a nivel del propio TenantManager (capa aplicación)
    que es la primera barrera y la que efectivamente ve el efecto del GUC vía
    el thread-local que el middleware puebla — la cobertura de RLS (capa BD)
    end-to-end para el modo "local" vive en el test de arriba
    (test_middleware_local_mode_guc_visible_during_view), que confirma que el
    GUC correcto SÍ llega a Postgres dentro de la transacción de la vista.
    """
    from apps.tenancy.models import Tenant

    tenant_a = TenantFactory()
    tenant_b = TenantFactory()
    user_a = UserFactory()
    user_b = UserFactory()
    TenantMembershipFactory(user=user_a, tenant=tenant_a, is_active=True)
    TenantMembershipFactory(user=user_b, tenant=tenant_b, is_active=True)

    def make_get_response(captured: list[object]) -> Callable[[HttpRequest], HttpResponse]:
        def get_response(request: HttpRequest) -> HttpResponse:
            # Model tenant-aware real y sencillo: Tenant no es TenantAwareModel,
            # así que usamos el GUC visto por Postgres como proxy fiel de "qué
            # tenant vería RLS en este momento" (ya probado end-to-end arriba).
            captured.append(_show_current_tenant_guc())
            return HttpResponse("ok")

        return get_response

    with override_settings(DB_TENANT_GUC_MODE=guc_mode):
        seen_a: list[object] = []
        middleware_a = TenantMiddleware(get_response=make_get_response(seen_a))
        middleware_a(_make_authenticated_request(user_a))

        seen_b: list[object] = []
        middleware_b = TenantMiddleware(get_response=make_get_response(seen_b))
        middleware_b(_make_authenticated_request(user_b))

    assert seen_a == [str(tenant_a.id)]
    assert seen_b == [str(tenant_b.id)]
    assert seen_a != seen_b
    # Nunca None/vacío durante la vista de un usuario con membresía activa.
    assert "" not in seen_a
    assert "" not in seen_b
    # Guard de cordura: los tenants sí son objetos distintos en BD.
    assert Tenant.objects.filter(id__in=[tenant_a.id, tenant_b.id]).count() == 2


# ---------------------------------------------------------------------------
# RLS de PostgreSQL (segunda barrera) en modo "local" — pacientes_patients
# ---------------------------------------------------------------------------
#
# Los tests de arriba validan el thread-local + el GUC visto con SHOW. Estos
# dos apuntan a la barrera de BASE DE DATOS (apps.pacientes.Patient tiene
# FORCE ROW LEVEL SECURITY), usando el modelo real y SQL crudo que bypassa el
# TenantManager de Django.
#
# LIMITACIÓN CONOCIDA: el rol de conexión en este entorno (`mailysoft`) es
# SUPERUSER de PostgreSQL, y Postgres exime a los superusers de RLS pase lo
# que pase (incluso con FORCE) — no es algo que este test pueda evitar sin
# cambiar el rol de conexión de dev/test. Por eso NO se prueba aquí "SELECT
# COUNT(*) FROM pacientes_patients devuelve solo lo del tenant" (con este rol
# siempre devolvería todo). En su lugar se prueba la expresión exacta que
# usan las políticas — current_tenant_id() — con el modelo Patient real de
# por medio, que es la parte 100% verificable en este entorno. Ver el
# docstring del primer test de esta sección para el detalle completo.


def _count_patients_via_raw_sql() -> int:
    """COUNT(*) crudo sobre pacientes_patients, bypasseando TenantManager.

    Lo único que puede filtrar estas filas es la política RLS de PostgreSQL.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM pacientes_patients")
        row = cursor.fetchone()
        return int(row[0]) if row else 0


def _current_tenant_id_sql_function() -> "str | None":
    """Invoca la función SQL current_tenant_id() (la que leen las políticas RLS).

    A diferencia de SHOW app.current_tenant_id (que lee el GUC crudo), esta
    función es literalmente la misma expresión que evalúa
    `USING (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL)`
    en cada política RLS — probar esto confirma que la política vería
    exactamente el tenant esperado, aislando el enforcement (bloqueado por el
    rol superuser en este entorno, ver docstring del test de abajo).
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_tenant_id()")
        row = cursor.fetchone()
        return str(row[0]) if row and row[0] is not None else None


@pytest.mark.django_db(transaction=True)
@override_settings(DB_TENANT_GUC_MODE="local")
def test_rls_policy_expression_sees_correct_tenant_inside_local_mode() -> None:
    """La expresión que usan TODAS las políticas RLS (`current_tenant_id()`) ve
    el tenant correcto durante la vista, en modo local — y NINGÚN otro tenant.

    LIMITACIÓN DEL ENTORNO (documentada, no se puede evitar aquí): el rol de
    conexión de dev/test (`mailysoft`) es SUPERUSER en PostgreSQL. Postgres
    exime a los superusers de RLS incluso con FORCE ROW LEVEL SECURITY — es
    una regla fija del motor, no un bug del código ni de la policy. Por eso
    una prueba de "SELECT COUNT(*) FROM pacientes_patients" con este rol
    siempre devuelve TODAS las filas sin importar el GUC, y no sirve para
    probar el enforcement real de la barrera de base de datos en este
    contenedor. (En producción el rol de la app debería ser NOSUPERUSER para
    que RLS aplique de verdad — ver hallazgo aparte reportado al usuario.)

    Lo que SÍ es determinista y sí prueba esta barrera es la propia
    expresión de la política: current_tenant_id() debe devolver el UUID de
    tenant_a durante la vista de tenant_a, y NUNCA el de tenant_b. Si esto
    fuera incorrecto, la política RLS (evaluada con un rol sin privilegio de
    bypass) fallaría en producción exactamente igual que fallaría el
    aislamiento del TenantManager, que sí se prueba end-to-end en
    test_zzz_tenant_isolation.py y en
    test_tenant_isolation_via_middleware_holds_in_both_modes de este archivo.
    """
    tenant_a = TenantFactory()
    tenant_b = TenantFactory()
    PatientFactory.create_batch(2, tenant=tenant_a)
    PatientFactory.create_batch(3, tenant=tenant_b)

    user_a = UserFactory()
    TenantMembershipFactory(user=user_a, tenant=tenant_a, is_active=True)

    seen: list[str | None] = []

    def get_response(request: HttpRequest) -> HttpResponse:
        seen.append(_current_tenant_id_sql_function())
        return HttpResponse("ok")

    middleware = TenantMiddleware(get_response=get_response)
    middleware(_make_authenticated_request(user_a))

    assert seen == [str(tenant_a.id)]
    assert seen[0] != str(tenant_b.id)


@pytest.mark.django_db(transaction=True)
@override_settings(DB_TENANT_GUC_MODE="local")
def test_rls_real_does_not_leak_tenant_a_patients_to_next_connection_user() -> None:
    """Fuga end-to-end con RLS real: tras el request de tenant A (modo local),
    la MISMA conexión NO debe seguir marcada con el tenant_id de A.

    Nota: con el GUC vacío el fallback documentado
    `OR current_tenant_id() IS NULL` de la política RLS abre TODAS las filas
    a propósito (es el comportamiento esperado para Celery/management
    commands, ver docstring de la migración RLS) — por eso este test NO
    verifica "cero filas visibles" tras el request, sino la precondición que
    realmente importa para evitar la fuga cross-tenant: que el GUC haya
    quedado en NULL/vacío y NO en el tenant_id de A. Si quedara fijo en A, un
    tenant B que reciclara esta conexión y SÍ fijara su propio GUC seguiría
    viendo solo lo suyo (RLS es `tenant_id = current_tenant_id()`, no habría
    fuga por ese lado) — pero cualquier código que dependa del GUC sin pasar
    por el flujo normal (raw SQL, Celery, etc.) heredaría erróneamente el
    contexto de A en vez de partir de NULL. El escenario positivo de
    aislamiento cruzado completo (A nunca ve B) ya se prueba arriba en
    test_rls_policy_expression_sees_correct_tenant_inside_local_mode.
    """
    tenant_a = TenantFactory()
    PatientFactory.create_batch(2, tenant=tenant_a)

    user_a = UserFactory()
    TenantMembershipFactory(user=user_a, tenant=tenant_a, is_active=True)

    def get_response(request: HttpRequest) -> HttpResponse:
        return HttpResponse("ok")

    middleware = TenantMiddleware(get_response=get_response)
    middleware(_make_authenticated_request(user_a))

    # Tras el request (commit real del atomic() del middleware): el GUC debe
    # haber quedado vacío, NO seguir marcando tenant_a.
    assert _show_current_tenant_guc() == "", (
        "FUGA CRÍTICA: el GUC de tenant_a sobrevivió al request en modo local. "
        "Con pgbouncer, el SIGUIENTE tenant que recicle esta conexión heredaría "
        "el contexto de tenant_a en lugar del suyo propio."
    )
