"""
Middleware de tenant para Maily Soft.

TenantMiddleware debe ir en MIDDLEWARE DESPUÉS de AuthenticationMiddleware,
ya que depende de request.user resuelto.

En el Paso 3 (autenticación JWT con claims de tenant) este middleware
se enriquecerá para leer el tenant desde el claim `tenant_id` del token,
permitiendo que un usuario con múltiples membresías elija el tenant activo
mediante el header X-Tenant-ID o el claim del JWT.
"""

from typing import Callable

from django.http import HttpRequest, HttpResponse

from apps.core.tenant_context import clear_current_tenant, set_current_tenant


class TenantMiddleware:
    """Lee el tenant del usuario autenticado y lo deja en el thread-local.

    Lógica actual (Paso 2):
    - Si el usuario está autenticado y tiene membresías activas, toma la primera.
    - Si no hay usuario o no tiene membresías, el tenant queda en None.

    Lógica del Paso 3 (pendiente):
    - Leer header X-Tenant-ID para usuarios con múltiples membresías.
    - Validar que el tenant pedido pertenece realmente al usuario autenticado.
    - Integrarse con el claim `tenant_id` del JWT de SimpleJWT.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        tenant = None
        user = getattr(request, "user", None)

        if user is not None and getattr(user, "is_authenticated", False):
            # hasattr guard: User puede no tener `memberships` si el modelo
            # aún no está migrado (p. ej. primera ejecución en CI).
            if hasattr(user, "memberships"):
                membership = (
                    user.memberships.filter(is_active=True)
                    .select_related("tenant")
                    .first()
                )
                if membership is not None:
                    tenant = membership.tenant

        set_current_tenant(tenant)
        try:
            return self.get_response(request)
        finally:
            # SIEMPRE limpiar para que el thread no filtre datos en el
            # próximo request que reutilice este worker (gunicorn/uvicorn).
            clear_current_tenant()
