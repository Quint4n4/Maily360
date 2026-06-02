"""
Middleware de tenant para Maily Soft.

TenantMiddleware está en MIDDLEWARE DESPUÉS de AuthenticationMiddleware.

IMPORTANTE — arquitectura de resolución de tenant (FIX-A2):
  Para peticiones con autenticación JWT (la mayoría de la API), el tenant se
  resuelve en TenantAPIView.initial(), NOT aquí. Esto es porque DRF resuelve la
  autenticación JWT a nivel de vista (en APIView.initial()), DESPUÉS de que todo
  el middleware ya se ejecutó. En ese punto request.user aún es AnonymousUser
  cuando este middleware corre.

  Este middleware cumple dos roles:
  1. Para sesión de Django (admin): resuelve el tenant desde request.user de
     Django (que sí está poblado por AuthenticationMiddleware de sesión).
  2. Para TODA petición: limpia el GUC de PostgreSQL en el finally, garantizando
     que la variable app.current_tenant_id no se filtre a la siguiente petición
     que reutilice la misma conexión (FIX-A1).

  La resolución de tenant para peticiones JWT ocurre en:
  apps/core/views.py → TenantAPIView.initial()
"""

from typing import Callable, Optional

from django.db import connection
from django.http import HttpRequest, HttpResponse

from apps.core.tenant_context import (
    clear_current_tenant,
    resolve_tenant_for_user,
    set_current_tenant,
    set_tenant_context_active,
)


class TenantMiddleware:
    """Middleware de tenant para sesión Django (admin) y limpieza de GUC.

    Para peticiones JWT la resolución ocurre en TenantAPIView.initial().
    Ver módulo docstring arriba para la explicación completa.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Marcar el contexto como activo ANTES de resolver el tenant.
        # A partir de aquí el TenantManager usará falla segura (qs.none() si tenant=None).
        set_tenant_context_active(True)

        user = getattr(request, "user", None)
        # Solo resuelve para sesión Django (admin). Las peticiones JWT se resuelven
        # en TenantAPIView.initial() después de que DRF autentica el token.
        tenant = resolve_tenant_for_user(user) if user is not None else None
        set_current_tenant(tenant)

        # FIX-A1: propagar el tenant a la sesión de PostgreSQL para que RLS funcione.
        # is_local=False (nivel sesión/conexión) para que persista en modo autocommit
        # con CONN_MAX_AGE>0. La limpieza en el finally garantiza que no se filtre
        # a la siguiente petición que reutilice esta conexión.
        if tenant is not None:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('app.current_tenant_id', %s, false)",
                    [str(tenant.id)],
                )

        try:
            return self.get_response(request)
        finally:
            # SIEMPRE limpiar thread-local Y el GUC en la conexión de Postgres.
            # El GUC se limpia con string vacío (is_local=false) para que la
            # próxima petición que reutilice esta conexión vea NULL, no el tenant
            # del request anterior (FIX-A1).
            clear_current_tenant()
            set_tenant_context_active(False)
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('app.current_tenant_id', '', false)")
