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

from django.db import connection
from django.http import HttpRequest, HttpResponse

from apps.core.tenant_context import (
    clear_current_tenant,
    set_current_tenant,
    set_tenant_context_active,
)


class TenantMiddleware:
    """Lee el tenant del usuario autenticado y lo deja en el thread-local.

    Lógica actual (Paso 2):
    - Marca el contexto como activo (FIX-2) para que el TenantManager falle seguro.
    - Solo resuelve membresías is_active=True de tenants con status="active" (FIX-3).
    - Ignora membresías soft-deleted (deleted_at IS NOT NULL) (FIX-4).
    - Orden determinista por created_at (FIX-5).
    - Propaga el tenant a la sesión PostgreSQL con set_config para que RLS funcione (FIX-1).
    - El finally siempre limpia contexto y context_active aunque la view lance excepción.

    Lógica del Paso 3 (pendiente):
    - Leer header X-Tenant-ID para usuarios con múltiples membresías.
    - Validar que el tenant pedido pertenece realmente al usuario autenticado.
    - Integrarse con el claim `tenant_id` del JWT de SimpleJWT.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # FIX-2: marcar el contexto como activo ANTES de resolver el tenant.
        # A partir de aquí el TenantManager usará falla segura (qs.none() si tenant=None).
        set_tenant_context_active(True)
        tenant = None
        user = getattr(request, "user", None)

        if user is not None and getattr(user, "is_authenticated", False):
            # hasattr guard: User puede no tener `memberships` si el modelo
            # aún no está migrado (p. ej. primera ejecución en CI).
            if hasattr(user, "memberships"):
                # FIX-3: solo membresías activas de tenants ACTIVOS.
                # FIX-4: excluye membresías soft-deleted (deleted_at__isnull=True).
                # FIX-5: orden determinista para evitar resultados no reproducibles.
                membership = (
                    user.memberships.filter(
                        is_active=True,
                        tenant__status="active",
                        deleted_at__isnull=True,
                    )
                    .select_related("tenant")
                    .order_by("created_at")
                    .first()
                )
                if membership is not None:
                    tenant = membership.tenant

        set_current_tenant(tenant)

        # FIX-1: propagar el tenant a la sesión de PostgreSQL para que RLS funcione.
        # set_config con is_local=true hace el valor transacción-local (se limpia al terminar).
        if tenant is not None:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('app.current_tenant_id', %s, true)",
                    [str(tenant.id)],
                )

        try:
            return self.get_response(request)
        finally:
            # SIEMPRE limpiar para que el thread no filtre datos en el
            # próximo request que reutilice este worker (gunicorn/uvicorn).
            # clear_current_tenant() también pone context_active=False (FIX-2).
            clear_current_tenant()
