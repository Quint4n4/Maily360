"""
Middleware de tenant para Maily Soft.

TenantMiddleware está en MIDDLEWARE DESPUÉS de AuthenticationMiddleware.

IMPORTANTE — arquitectura de resolución de tenant (FIX-A2):
  Para peticiones con autenticación JWT (la mayoría de la API), el tenant se
  resuelve en TenantAPIView.check_permissions(), NOT aquí. Esto es porque DRF
  resuelve la autenticación JWT a nivel de vista (en APIView.initial()), DESPUÉS
  de que todo el middleware ya se ejecutó. En ese punto request.user aún es
  AnonymousUser cuando este middleware corre.

  Este middleware cumple tres roles:
  1. Para sesión de Django (admin): resuelve el tenant desde request.user de
     Django (que sí está poblado por AuthenticationMiddleware de sesión).
  2. Para TODA petición: limpia el GUC de PostgreSQL en el finally, garantizando
     que la variable app.current_tenant_id no se filtre a la siguiente petición
     que reutilice la misma conexión (FIX-A1).
  3. Modo "local" del GUC (settings.DB_TENANT_GUC_MODE, ver pgbouncer-rls-
     escalabilidad.md): envuelve TODA la petición (incluido el path JWT que
     resuelve tenant más adelante, en TenantAPIView) en transaction.atomic(),
     porque SET LOCAL solo tiene efecto dentro de una transacción abierta.
     En modo "session" (default) el comportamiento es EXACTAMENTE el de
     siempre — no se abre ninguna transacción extra.

  La resolución de tenant para peticiones JWT ocurre en:
  apps/core/views.py → TenantAPIView.check_permissions()
  Ambos puntos (este middleware y TenantAPIView) fijan el GUC llamando al
  mismo helper apps.core.tenant_context.apply_tenant_guc(), que es el único
  lugar que decide session vs. local. Así el modo se controla en un solo
  sitio aunque el fijado siga ocurriendo en dos puntos del request.

  Estados de tenant (FIX-C):
  resolve_tenant_for_user → resolve_membership_for_user filtra
  tenant__status__in=["active", "trial"]. El middleware hereda este comportamiento
  automáticamente al delegar en resolve_tenant_for_user.
  suspended → bloqueado; trial y active → acceso permitido.
"""

from collections.abc import Callable

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest, HttpResponse

from apps.core.tenant_context import (
    apply_tenant_guc,
    clear_current_tenant,
    clear_request_context,
    clear_tenant_guc,
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

        # FIX-A1: propagar el tenant a la sesión/transacción de PostgreSQL para
        # que RLS funcione. apply_tenant_guc() decide session vs. local según
        # settings.DB_TENANT_GUC_MODE (ver docstring del módulo y de la función).
        #
        # CRÍTICO: en modo "local" el SET LOCAL solo tiene efecto DENTRO de la
        # transacción; por eso apply_tenant_guc() se llama dentro de _dispatch(),
        # ya con el atomic() abierto. Fijarlo antes (en autocommit real) lo
        # perdería de inmediato y el fallback `current_tenant_id() IS NULL`
        # abriría acceso cross-tenant en el path de sesión Django (/admin).
        def _dispatch() -> HttpResponse:
            if tenant is not None:
                apply_tenant_guc(tenant.id)
            return self.get_response(request)

        try:
            if settings.DB_TENANT_GUC_MODE == "local":
                # Modo "local": envolver TODA la petición (incluida la
                # resolución de tenant JWT que ocurre más adelante, dentro de
                # get_response, en TenantAPIView.check_permissions) en una
                # única transacción. SET LOCAL solo vive dentro de ella; al
                # salir de este bloque (commit normal o rollback en excepción
                # no capturada) el GUC desaparece solo — no hace falta
                # limpiarlo a mano como en modo "session".
                with transaction.atomic():
                    return _dispatch()
            return _dispatch()
        finally:
            # SIEMPRE limpiar thread-local. El GUC de sesión también se limpia
            # aquí en ambos modos (ver clear_tenant_guc(): en modo "local" es
            # un no-op de cinturón y tirantes, la limpieza real ya la hizo el
            # COMMIT/ROLLBACK de la transacción al salir del bloque `with` de
            # arriba).
            clear_current_tenant()
            clear_request_context()
            set_tenant_context_active(False)
            clear_tenant_guc()
