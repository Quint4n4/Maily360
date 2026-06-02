"""
Vistas base de Maily Soft.

TenantAPIView — base para TODAS las vistas de la API que requieren contexto de tenant.

Por qué existe esta clase (FIX-A2):
    DRF resuelve la autenticación JWT en APIView.initial(), que se ejecuta DENTRO
    del handler de la vista, DESPUÉS de que el middleware ya procesó el request.
    Esto significa que cuando TenantMiddleware corre, request.user aún es
    AnonymousUser para peticiones JWT, y el middleware no puede resolver el tenant.

    TenantAPIView.initial() sobreescribe el método de DRF para:
    1. Llamar a super().initial() primero → DRF resuelve JWT, request.user queda
       poblado con el usuario real.
    2. Resolver el tenant desde request.user (usando resolve_tenant_for_user).
    3. Actualizar el thread-local (set_current_tenant + set_tenant_context_active).
    4. Propagar el GUC a PostgreSQL (is_local=false, FIX-A1) para que RLS funcione.

    El TenantMiddleware sigue limpiando el GUC en su finally, por lo que no hay
    riesgo de filtración entre peticiones.
"""

from typing import Any

from django.db import connection
from rest_framework.request import Request
from rest_framework.views import APIView

from apps.core.tenant_context import (
    resolve_tenant_for_user,
    set_current_tenant,
    set_tenant_context_active,
)


class TenantAPIView(APIView):
    """Vista base DRF con resolución de tenant para peticiones JWT.

    Todas las vistas de la API que accedan a datos de tenant deben heredar
    de esta clase en lugar de APIView.

    El flujo garantizado es:
        middleware.set_tenant_context_active(True)
        → middleware.set_current_tenant(None)   ← user aún es AnonymousUser aquí
        → TenantAPIView.initial():
            super().initial()                   ← DRF autentica JWT → request.user poblado
            resolve_tenant_for_user(request.user)
            set_current_tenant(tenant)
            set_config('app.current_tenant_id', ..., false)
        → handler (get/post/patch/delete)
        → middleware.finally: clear_current_tenant() + limpiar GUC
    """

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        """Resuelve autenticación JWT PRIMERO, luego el tenant del usuario.

        Sobreescribe APIView.initial() para que el tenant quede en el
        thread-local y en el GUC de Postgres antes de que el handler corra.
        """
        # 1. Autenticación, permisos y throttling de DRF (resuelve JWT → request.user).
        super().initial(request, *args, **kwargs)

        # 2. Ahora request.user está poblado. Resolver el tenant.
        tenant = resolve_tenant_for_user(request.user)
        set_current_tenant(tenant)
        set_tenant_context_active(True)

        # 3. Propagar a PostgreSQL para que la política RLS use el tenant correcto.
        # is_local=false: nivel sesión/conexión, no desaparece entre sentencias
        # en modo autocommit con CONN_MAX_AGE>0 (FIX-A1).
        tenant_id_str: str = str(tenant.id) if tenant is not None else ""
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('app.current_tenant_id', %s, false)",
                [tenant_id_str],
            )
