"""
Sistema declarativo de permisos por rol clínico para Maily Platform.

Diseño:
    - HasClinicRole es la clase base method-aware. Las subclases solo declaran
      `policy: ClassVar[dict[str, frozenset[str]]]` con la matriz de roles
      permitidos por método HTTP.
    - La política se evalúa contra `request.active_role`, que
      TenantAPIView.check_permissions() adjunta al request ANTES de que DRF
      evalúe los permisos (sin query extra).
    - Un usuario sin membresía activa (active_role=None) → 403, nunca 404.
      La denegación por rol es siempre 403 — el recurso existe y pertenece al
      tenant, pero el rol del actor no tiene acceso. El 404 está reservado para
      recursos de OTRO tenant (aislamiento multi-tenant a nivel de selector/ORM).

Manejo de OPTIONS y HEAD (FIX-B):
    OPTIONS es el preflight CORS que el navegador envía antes de cada petición
    con credenciales. Si OPTIONS devuelve 403, el frontend queda completamente
    bloqueado. IsAuthenticated (primera en permission_classes) ya requiere token;
    HasClinicRole solo debe asegurarse de no bloquear el preflight por rol.

    HEAD sigue la política de GET: se traduce al método "GET" antes de consultar
    la policy, de forma consistente con el comportamiento estándar de HTTP.

Nota sobre platform staff:
    Un usuario con is_platform_staff=True pero SIN TenantMembership tendrá
    request.active_role = None y será denegado (403) en todos los endpoints de
    clínica. Esto es correcto en v1: el staff de plataforma opera vía el admin
    de Django, no vía la API de clínica.

Constantes:
    ALL_ROLES    — todos los roles posibles (lectura segura para cualquier miembro).
    MANAGE_ROLES — solo owner y admin (acciones administrativas).

Uso en vistas:
    class MyView(TenantAPIView):
        permission_classes = [IsAuthenticated, PatientPermission]
"""

from typing import ClassVar

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from apps.tenancy.models import TenantMembership

Role = TenantMembership.Role

# Conjuntos canónicos de roles — referencia única para toda la plataforma.
ALL_ROLES: frozenset[str] = frozenset(
    {
        Role.OWNER,
        Role.ADMIN,
        Role.DOCTOR,
        Role.NURSE,
        Role.RECEPTION,
        Role.FINANCE,
        Role.READONLY,
    }
)

MANAGE_ROLES: frozenset[str] = frozenset({Role.OWNER, Role.ADMIN})


class HasClinicRole(BasePermission):
    """Permiso base method-aware para roles clínicos.

    Las subclases deben declarar `policy` como un diccionario que mapea
    métodos HTTP (GET, POST, PATCH, PUT, DELETE) a conjuntos de roles
    permitidos. Se puede usar '*' como clave de fallback para métodos
    no declarados explícitamente.

    Comportamiento especial:
        OPTIONS → siempre True (preflight CORS; IsAuthenticated ya requirió token).
        HEAD    → sigue la política de GET (traducción de método antes de lookup).

    Si el usuario no tiene rol activo (active_role=None), la solicitud se
    deniega con 403 independientemente del método (salvo OPTIONS).

    Ejemplo:
        class MyPermission(HasClinicRole):
            policy: ClassVar[dict[str, frozenset[str]]] = {
                "GET":    ALL_ROLES,
                "POST":   MANAGE_ROLES,
                "PATCH":  MANAGE_ROLES,
                "DELETE": MANAGE_ROLES,
            }
    """

    policy: ClassVar[dict[str, frozenset[str]]] = {}
    message: str = "Tu rol no tiene permiso para realizar esta acción."

    def has_permission(self, request: Request, view: APIView) -> bool:
        """Evalúa si el rol activo del usuario está permitido para el método HTTP.

        Args:
            request: request de DRF con `active_role` adjunto por TenantAPIView.
            view:    vista que invoca el permiso (no usado directamente).

        Returns:
            True si el rol del usuario está en el conjunto permitido para el método.
            False si el rol es None o no está en el conjunto (fail-closed).
        """
        # OPTIONS = preflight CORS. No debe bloquearse por rol: si lo hace, el
        # navegador cancela todas las peticiones XHR subsiguientes (frontend roto).
        # IsAuthenticated (primera en permission_classes) ya exige token válido.
        if request.method == "OPTIONS":
            return True

        # HEAD sigue la política de GET según semántica HTTP (RFC 9110 §9.3.2).
        request_method: str = "GET" if request.method == "HEAD" else (request.method or "")

        role: str | None = getattr(request, "active_role", None)
        if role is None:
            return False

        allowed: frozenset[str] = self.policy.get(request_method) or self.policy.get(
            "*", frozenset()
        )
        return role in allowed


# ---------------------------------------------------------------------------
# Permisos concretos por dominio — matriz aprobada de la plataforma
# ---------------------------------------------------------------------------


class PatientPermission(HasClinicRole):
    """Permisos para el recurso Paciente.

    Matriz:
        GET    → todos los roles (incluso finanzas y solo-lectura pueden consultar).
        POST   → owner, admin, doctor, nurse, reception (recepción crea expedientes).
        PATCH  → owner, admin, doctor, nurse, reception (idem: actualizan datos).
        DELETE → solo owner y admin (desactivación; acción sensible).
    """

    policy: dict[str, frozenset[str]] = {
        "GET": ALL_ROLES,
        "POST": frozenset(
            {Role.OWNER, Role.ADMIN, Role.DOCTOR, Role.NURSE, Role.RECEPTION}
        ),
        "PATCH": frozenset(
            {Role.OWNER, Role.ADMIN, Role.DOCTOR, Role.NURSE, Role.RECEPTION}
        ),
        "DELETE": MANAGE_ROLES,
    }


class PersonalPermission(HasClinicRole):
    """Permisos para el módulo de personal (doctores, consultorios, horarios).

    Matriz:
        GET    → todos los roles.
        POST   → solo owner y admin (crear/vincular personal es administrativo).
        PATCH  → solo owner y admin.
        DELETE → solo owner y admin.
    """

    policy: dict[str, frozenset[str]] = {
        "GET": ALL_ROLES,
        "POST": MANAGE_ROLES,
        "PATCH": MANAGE_ROLES,
        "DELETE": MANAGE_ROLES,
    }


class AppointmentPermission(HasClinicRole):
    """Permisos para citas (list, create, detail, patch, reagendar, DELETE=cancelar).

    Matriz:
        GET    → todos menos finanzas (readonly también puede ver agenda).
        POST   → owner, admin, doctor, reception (nurse NO crea citas en v1).
        PATCH  → owner, admin, doctor, reception.
        DELETE → owner, admin, reception (cancela cita — sin doctor; el doctor
                 solo confirma/atiende, no cancela en nombre de la clínica).
    """

    policy: dict[str, frozenset[str]] = {
        "GET": frozenset(
            {Role.OWNER, Role.ADMIN, Role.DOCTOR, Role.NURSE, Role.RECEPTION, Role.READONLY}
        ),
        "POST": frozenset({Role.OWNER, Role.ADMIN, Role.DOCTOR, Role.RECEPTION}),
        "PATCH": frozenset({Role.OWNER, Role.ADMIN, Role.DOCTOR, Role.RECEPTION}),
        "DELETE": frozenset({Role.OWNER, Role.ADMIN, Role.RECEPTION}),
    }


class AppointmentStatusPermission(HasClinicRole):
    """Permisos para el endpoint POST /citas/<id>/estado/.

    Solo este endpoint puede cambiar el estado de una cita.
    Matriz:
        POST → owner, admin, doctor, nurse, reception.
        (readonly y finance NO pueden cambiar estados de cita.)
    """

    policy: dict[str, frozenset[str]] = {
        "POST": frozenset(
            {Role.OWNER, Role.ADMIN, Role.DOCTOR, Role.NURSE, Role.RECEPTION}
        ),
    }


class AgendaConfigPermission(HasClinicRole):
    """Permisos para GET/PATCH /agenda/config/.

    La configuración de agenda es administrativa; solo owner y admin la ven y editan.
    Matriz:
        GET   → solo owner y admin.
        PATCH → solo owner y admin.
    """

    policy: dict[str, frozenset[str]] = {
        "GET": MANAGE_ROLES,
        "PATCH": MANAGE_ROLES,
    }
