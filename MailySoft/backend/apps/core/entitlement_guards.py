"""
Guards de entitlements: el backend como AUTORIDAD del gating por plan.

Sin esto, ocultar módulos en el frontend es cosmético — cualquiera con la URL
entra. Aquí se bloquea de verdad.

Dos guards:
  - `RequiresModule` (permiso DRF) y `require_module` (para services): ¿la
    clínica tiene contratado este módulo?
  - `assert_within_limit`: ¿le queda cupo para una sucursal/consultorio/usuario más?

Por qué 404 y no 403 al faltar un módulo:
    Un 403 dice "esto existe pero no lo pagas" — delata el catálogo e invita a
    curiosear. Un módulo no contratado simplemente NO EXISTE para esa clínica.
    (Distinto del 403 por ROL, que sí es correcto: ahí el recurso existe para la
    clínica y es el usuario quien no alcanza.)
"""

from typing import ClassVar

from django.core.exceptions import ValidationError
from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from apps.core.modules import Module
from apps.core.tenant_context import get_current_tenant
from apps.tenancy.entitlements import Entitlements, entitlements_for_tenant
from apps.tenancy.models import Tenant

#: Nombre legible de cada límite, para los mensajes de error.
_LIMITE_LABEL: dict[str, str] = {
    "max_sucursales": "sucursales",
    "max_consultorios": "consultorios",
    "max_usuarios": "usuarios",
}


def entitlements_del_request(request: Request) -> Entitlements | None:
    """Entitlements de la clínica del request, cacheados por request.

    El gating consulta esto en cada endpoint; sin caché serían 2 queries por
    petición solo para saber qué tiene contratado la clínica.
    """
    cache = getattr(request, "_entitlements_cache", None)
    if cache is not None:
        return cache

    tenant = get_current_tenant()
    if tenant is None:
        return None

    ent = entitlements_for_tenant(tenant=tenant)
    request._entitlements_cache = ent  # type: ignore[attr-defined]
    return ent


class RequiresModule(BasePermission):
    """Exige que la clínica tenga contratado `module`.

    Se combina con el permiso de rol, no lo sustituye:

        permission_classes = [IsAuthenticated, RecetaPermission, RequiresRecetas]

    La regla de oro: se pasa solo si **el rol lo permite Y la clínica lo tiene
    contratado**.
    """

    module: ClassVar[str] = ""

    def has_permission(self, request: Request, view: APIView) -> bool:
        """Deja pasar solo si la clínica tiene el módulo. Si no, 404."""
        # OPTIONS = preflight CORS. Bloquearlo rompe el frontend entero.
        if request.method == "OPTIONS":
            return True

        ent = entitlements_del_request(request)
        if ent is not None and ent.tiene(self.module):
            return True

        # NotFound en vez de devolver False (que daría 403): un módulo no
        # contratado no debe delatar que existe.
        raise NotFound("No encontrado.")


def _guard(module: str, nombre: str) -> type[RequiresModule]:
    """Fabrica una clase de permiso para un módulo (evita 12 clases idénticas)."""
    return type(nombre, (RequiresModule,), {"module": module})


RequiresAgenda = _guard(Module.AGENDA, "RequiresAgenda")
RequiresRecordatorios = _guard(Module.RECORDATORIOS, "RequiresRecordatorios")
RequiresExpediente = _guard(Module.EXPEDIENTE, "RequiresExpediente")
RequiresRecetas = _guard(Module.RECETAS, "RequiresRecetas")
RequiresNotas = _guard(Module.NOTAS, "RequiresNotas")
RequiresServicios = _guard(Module.SERVICIOS, "RequiresServicios")
RequiresPaquetes = _guard(Module.PAQUETES, "RequiresPaquetes")
RequiresCotizaciones = _guard(Module.COTIZACIONES, "RequiresCotizaciones")
RequiresCobranza = _guard(Module.COBRANZA, "RequiresCobranza")
RequiresCfdi = _guard(Module.CFDI, "RequiresCfdi")
RequiresCalendarizacion = _guard(Module.CALENDARIZACION, "RequiresCalendarizacion")
RequiresPersonal = _guard(Module.PERSONAL, "RequiresPersonal")


def require_module(*, tenant: Tenant, module: str) -> None:
    """Versión para services (fuera del ciclo request/response).

    Se usa cuando la comprobación no cabe en un permiso de vista: tareas Celery,
    management commands, o reglas que dependen del cuerpo de la petición.

    Args:
        tenant: Clínica que ejecuta la acción.
        module: Slug del módulo requerido.

    Raises:
        NotFound: si la clínica no tiene el módulo contratado.
    """
    if not entitlements_for_tenant(tenant=tenant).tiene(module):
        raise NotFound("No encontrado.")


def assert_within_limit(*, tenant: Tenant, limite: str, actual: int) -> None:
    """Verifica que quede cupo antes de crear un recurso limitado por el plan.

    Args:
        tenant: Clínica que crea el recurso.
        limite: 'max_sucursales' | 'max_consultorios' | 'max_usuarios'.
        actual: Cuántos existen YA (sin contar el que se va a crear).

    Raises:
        ValidationError: si el plan no permite uno más. El mensaje es accionable:
            dice el tope y qué hacer, no solo que falló.
    """
    tope = entitlements_for_tenant(tenant=tenant).limite(limite)
    if tope is None:  # ilimitado
        return
    if actual >= tope:
        etiqueta = _LIMITE_LABEL.get(limite, limite)
        raise ValidationError(
            f"El plan de esta clínica permite {tope} {etiqueta} y ya "
            f"{'hay' if actual == 1 else 'hay'} {actual}. "
            f"Para ampliarlo, contacta a soporte de Maily."
        )
