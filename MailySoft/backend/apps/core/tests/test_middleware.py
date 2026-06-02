"""
Tests para apps/core/middleware.py — TenantMiddleware.

Verifica que el middleware establezca/limpie correctamente el tenant
del thread-local en función del usuario autenticado y sus membresías.
"""

from typing import Callable
from unittest.mock import MagicMock

import pytest
from django.http import HttpRequest, HttpResponse

from apps.core.middleware import TenantMiddleware
from apps.core.tenant_context import get_current_tenant
from tests.factories import TenantFactory, TenantMembershipFactory, UserFactory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(user: object = None) -> HttpRequest:
    """Construye un HttpRequest mínimo con el user dado."""
    request = HttpRequest()
    request.user = user  # type: ignore[assignment]
    return request


def _make_middleware(view_response: HttpResponse = None) -> TenantMiddleware:
    """Devuelve un TenantMiddleware con un get_response que retorna un 200."""
    if view_response is None:
        view_response = HttpResponse("ok", status=200)

    def get_response(request: HttpRequest) -> HttpResponse:
        return view_response  # type: ignore[return-value]

    return TenantMiddleware(get_response=get_response)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_middleware_sets_tenant_for_authenticated_user_with_membership() -> None:
    """Arrange: usuario autenticado con una membresía activa.
    Act: el middleware procesa el request.
    Assert: el tenant queda seteado DURANTE la ejecución de la view.
    """
    # Arrange
    tenant = TenantFactory()
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, is_active=True)

    tenant_during_view: list[object] = []

    def get_response(request: HttpRequest) -> HttpResponse:
        # Captura el tenant activo DENTRO de la view
        tenant_during_view.append(get_current_tenant())
        return HttpResponse("ok")

    middleware = TenantMiddleware(get_response=get_response)

    # Simular usuario autenticado
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.memberships = user.memberships
    request = _make_request(user=mock_user)

    # Usar el usuario real de Django para que las queries funcionen
    request.user = user

    # Act
    middleware(request)

    # Assert
    assert len(tenant_during_view) == 1
    assert tenant_during_view[0] is not None
    assert tenant_during_view[0].id == tenant.id  # type: ignore[union-attr]


@pytest.mark.django_db
def test_middleware_sets_none_when_user_anonymous() -> None:
    """Arrange: usuario anónimo (is_authenticated=False).
    Act: el middleware procesa el request.
    Assert: el tenant queda en None durante la view.
    """
    # Arrange
    tenant_during_view: list[object] = []

    def get_response(request: HttpRequest) -> HttpResponse:
        tenant_during_view.append(get_current_tenant())
        return HttpResponse("ok")

    middleware = TenantMiddleware(get_response=get_response)

    anon_user = MagicMock()
    anon_user.is_authenticated = False
    request = _make_request(user=anon_user)

    # Act
    middleware(request)

    # Assert
    assert tenant_during_view[0] is None


@pytest.mark.django_db
def test_middleware_sets_none_when_user_has_no_membership() -> None:
    """Arrange: usuario autenticado pero sin ninguna membresía.
    Act: el middleware procesa el request.
    Assert: el tenant queda en None (sin clínica asignada).
    """
    # Arrange
    user = UserFactory()
    # No creamos ninguna membresía para este usuario

    tenant_during_view: list[object] = []

    def get_response(request: HttpRequest) -> HttpResponse:
        tenant_during_view.append(get_current_tenant())
        return HttpResponse("ok")

    middleware = TenantMiddleware(get_response=get_response)
    request = _make_request(user=user)

    # Act
    middleware(request)

    # Assert
    assert tenant_during_view[0] is None


@pytest.mark.django_db
def test_middleware_uses_active_membership_only() -> None:
    """Arrange: usuario con una membresía INACTIVA y ninguna activa.
    Act: el middleware procesa el request.
    Assert: el tenant queda en None — membresías inactivas no se usan.
    """
    # Arrange
    user = UserFactory()
    tenant = TenantFactory()
    TenantMembershipFactory(user=user, tenant=tenant, is_active=False)  # inactiva

    tenant_during_view: list[object] = []

    def get_response(request: HttpRequest) -> HttpResponse:
        tenant_during_view.append(get_current_tenant())
        return HttpResponse("ok")

    middleware = TenantMiddleware(get_response=get_response)
    request = _make_request(user=user)

    # Act
    middleware(request)

    # Assert
    assert tenant_during_view[0] is None


@pytest.mark.django_db
def test_middleware_clears_thread_local_after_response() -> None:
    """Arrange: usuario con membresía activa.
    Act: el middleware procesa el request completamente.
    Assert: tras la respuesta el thread-local queda limpio (finally siempre corre).
    """
    # Arrange
    user = UserFactory()
    tenant = TenantFactory()
    TenantMembershipFactory(user=user, tenant=tenant, is_active=True)

    middleware = _make_middleware()
    request = _make_request(user=user)

    # Act
    middleware(request)

    # Assert — después del request el contexto debe estar limpio
    assert get_current_tenant() is None


@pytest.mark.django_db
def test_middleware_clears_thread_local_even_on_exception() -> None:
    """Arrange: view que lanza una excepción no capturada.
    Act: el middleware llama a get_response que lanza RuntimeError.
    Assert: el thread-local queda limpio aunque haya lanzado (finally corre).

    Este test valida el bloque `finally` del middleware — la regla más
    importante para evitar fuga de datos entre requests en el mismo worker.
    """
    # Arrange
    user = UserFactory()
    tenant = TenantFactory()
    TenantMembershipFactory(user=user, tenant=tenant, is_active=True)

    def exploding_view(request: HttpRequest) -> HttpResponse:
        raise RuntimeError("boom — error simulado en la view")

    middleware = TenantMiddleware(get_response=exploding_view)
    request = _make_request(user=user)

    # Act + Assert
    with pytest.raises(RuntimeError, match="boom"):
        middleware(request)

    # El finally debe haber corrido aunque la view haya lanzado
    assert get_current_tenant() is None, (
        "El thread-local NO fue limpiado tras una excepción — "
        "el siguiente request en este worker vería datos del tenant incorrecto."
    )


@pytest.mark.django_db
def test_middleware_selects_first_active_membership_when_multiple_exist() -> None:
    """Arrange: usuario con dos membresías activas en clínicas distintas.
    Act: el middleware procesa el request.
    Assert: el tenant corresponde a alguna de las membresías activas (no None).

    Nota: el Paso 3 introducirá el header X-Tenant-ID para que el usuario
    elija; por ahora simplemente no debe quedar en None.
    """
    # Arrange
    user = UserFactory()
    tenant_1 = TenantFactory()
    tenant_2 = TenantFactory()
    TenantMembershipFactory(user=user, tenant=tenant_1, is_active=True)
    TenantMembershipFactory(user=user, tenant=tenant_2, is_active=True)

    tenant_during_view: list[object] = []

    def get_response(request: HttpRequest) -> HttpResponse:
        tenant_during_view.append(get_current_tenant())
        return HttpResponse("ok")

    middleware = TenantMiddleware(get_response=get_response)
    request = _make_request(user=user)

    # Act
    middleware(request)

    # Assert
    resolved_tenant = tenant_during_view[0]
    assert resolved_tenant is not None
    assert resolved_tenant.id in {tenant_1.id, tenant_2.id}  # type: ignore[union-attr]
