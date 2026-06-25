"""
Sistema declarativo de permisos para Maily Platform.

Incluye:
  - HasClinicRole: permisos por rol clínico (para endpoints de clínica).
  - PlatformPermission: permisos para el panel interno del equipo Maily (cross-tenant).

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

from typing import ClassVar, Optional

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from apps.authn.models import User
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


class MemberPermission(HasClinicRole):
    """Permisos para la gestión de miembros de la clínica.

    Listar, crear, cambiar rol y bloquear/reactivar cuentas es una acción
    administrativa sensible (toca cuentas de usuario y PII).
    Matriz:
        GET    → solo owner y admin.
        POST   → solo owner y admin.
        PATCH  → solo owner y admin.
    """

    policy: dict[str, frozenset[str]] = {
        "GET": MANAGE_ROLES,
        "POST": MANAGE_ROLES,
        "PATCH": MANAGE_ROLES,
        "DELETE": MANAGE_ROLES,  # quitar avatar de un miembro
    }


class AppointmentTypePermission(HasClinicRole):
    """Permisos para los tipos de cita (catálogo configurable).

    Matriz:
        GET    → todos los roles (necesitan listarlos para agendar).
        POST   → solo owner y admin (administrar el catálogo).
        PATCH  → solo owner y admin.
        DELETE → solo owner y admin.
    """

    policy: dict[str, frozenset[str]] = {
        "GET": ALL_ROLES,
        "POST": MANAGE_ROLES,
        "PATCH": MANAGE_ROLES,
        "DELETE": MANAGE_ROLES,
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


# ---------------------------------------------------------------------------
# Finanzas — matriz reconciliada (ver documentacion/arquitectura_maily.html y
# MailySoft/docs/design/plan-paneles-roles.md). Reglas:
#   - finance es el rol financiero por excelencia (ve y opera todo el módulo).
#   - reception cobra y cotiza (atiende la caja) pero NO emite/cancela CFDI ni
#     toca la configuración fiscal.
#   - readonly ve todo el módulo sin poder crear/editar (solo-ver).
#   - doctor y nurse NO acceden a finanzas.
#   - finance NO ve la agenda (ya garantizado por AppointmentPermission).
# ---------------------------------------------------------------------------

# Roles que pueden VER el módulo de finanzas (incluye readonly como solo-ver).
FINANCE_VIEW_ROLES: frozenset[str] = frozenset(
    {Role.OWNER, Role.ADMIN, Role.FINANCE, Role.RECEPTION, Role.READONLY}
)

# Roles que pueden OPERAR caja (cotizar, registrar pagos): incluye recepción.
FINANCE_DESK_ROLES: frozenset[str] = frozenset(
    {Role.OWNER, Role.ADMIN, Role.FINANCE, Role.RECEPTION}
)

# Roles financieros "duros" (cargos, CFDI): owner/admin/finance, sin recepción.
FINANCE_CORE_ROLES: frozenset[str] = frozenset(
    {Role.OWNER, Role.ADMIN, Role.FINANCE}
)


class FinanceDashboardPermission(HasClinicRole):
    """Permisos para GET /finanzas/dashboard/ (métricas y series para gráficas).

    Matriz:
        GET → owner, admin, finance (operan) + readonly (solo-ver).
        (reception NO ve el panel analítico; opera caja pero no reportes globales.)
    """

    policy: dict[str, frozenset[str]] = {
        "GET": frozenset({Role.OWNER, Role.ADMIN, Role.FINANCE, Role.READONLY}),
    }


class FinanceConceptPermission(HasClinicRole):
    """Permisos para el catálogo de conceptos cobrables.

    Matriz:
        GET    → roles que ven finanzas (recepción/finance los necesitan para cotizar).
        POST   → solo owner y admin (mantener el catálogo es administrativo).
        PATCH  → solo owner y admin.
        DELETE → solo owner y admin (desactivación del concepto).
    """

    policy: dict[str, frozenset[str]] = {
        "GET": FINANCE_VIEW_ROLES,
        "POST": MANAGE_ROLES,
        "PATCH": MANAGE_ROLES,
        "DELETE": MANAGE_ROLES,
    }


class FinanceQuotePermission(HasClinicRole):
    """Permisos para cotizaciones (list/create/detail/patch/acciones de estado).

    Matriz:
        GET    → roles que ven finanzas (incluye readonly).
        POST   → caja: owner, admin, finance, reception.
        PATCH  → caja: owner, admin, finance, reception (editar/cambiar estado).
        DELETE → caja: owner, admin, finance, reception (descartar borrador).
    """

    policy: dict[str, frozenset[str]] = {
        "GET": FINANCE_VIEW_ROLES,
        "POST": FINANCE_DESK_ROLES,
        "PATCH": FINANCE_DESK_ROLES,
        "DELETE": FINANCE_DESK_ROLES,
    }


class FinanceChargePermission(HasClinicRole):
    """Permisos para cargos / cuentas por cobrar.

    Matriz:
        GET    → roles que ven finanzas (incluye readonly).
        POST   → owner, admin, finance (crear un adeudo es acción financiera).
        PATCH  → owner, admin, finance.
        DELETE → owner, admin, finance (cancelar el cargo).
    """

    policy: dict[str, frozenset[str]] = {
        "GET": FINANCE_VIEW_ROLES,
        "POST": FINANCE_CORE_ROLES,
        "PATCH": FINANCE_CORE_ROLES,
        "DELETE": FINANCE_CORE_ROLES,
    }


class FinancePaymentPermission(HasClinicRole):
    """Permisos para cobros / pagos.

    Matriz:
        GET  → roles que ven finanzas (incluye readonly).
        POST → caja: owner, admin, finance, reception (recepción cobra).
    """

    policy: dict[str, frozenset[str]] = {
        "GET": FINANCE_VIEW_ROLES,
        "POST": FINANCE_DESK_ROLES,
    }


class FinanceStatementPermission(HasClinicRole):
    """Permisos para el estado de cuenta del paciente (datos para vista/exportación).

    Matriz:
        GET → roles que ven finanzas (incluye readonly y recepción).
    """

    policy: dict[str, frozenset[str]] = {
        "GET": FINANCE_VIEW_ROLES,
    }


def _tenant_doctors_see_costs(request: Request) -> bool:
    """Lee el flag doctors_see_costs del ClinicSettings del tenant activo.

    Cachea el resultado en request._doctors_see_costs para que sólo se
    realice UNA query por request (evita N+1 si el permiso se verifica varias veces).

    Args:
        request: DRF request con tenant activo (resuelto por TenantAPIView).

    Returns:
        True si la clínica permite que los médicos vean costos; False en cualquier
        otro caso (tenant no encontrado, ClinicSettings no existe, flag apagado).
    """
    cached: Optional[bool] = getattr(request, "_doctors_see_costs", None)
    if cached is not None:
        return cached

    # Importación tardía para evitar circular imports (core ← clinica).
    from apps.clinica.models import ClinicSettings  # noqa: PLC0415

    tenant = getattr(request, "tenant", None)
    if tenant is None:
        # Fallback: intentar vía tenant_context (usado en algunos tests).
        from apps.core.tenant_context import get_current_tenant  # noqa: PLC0415

        tenant = get_current_tenant()

    if tenant is None:
        request._doctors_see_costs = False  # type: ignore[attr-defined]
        return False

    result: bool = (
        ClinicSettings.objects
        .filter(tenant_id=tenant.id, deleted_at__isnull=True)
        .values_list("doctors_see_costs", flat=True)
        .first()
        or False
    )
    request._doctors_see_costs = result  # type: ignore[attr-defined]
    return result


class PatientStatementPermission(BasePermission):
    """Permiso para el estado de cuenta del paciente (AccountStatementApi — solo GET).

    Implementa la Decisión D-2 del plan de Fase 1:
        - FINANCE_VIEW_ROLES (owner/admin/finance/reception/readonly) → SIEMPRE.
        - doctor → SOLO cuando ClinicSettings.doctors_see_costs == True.
        - Cualquier otro rol → 403.

    El flag se lee UNA sola vez por request (cacheado en request._doctors_see_costs).

    Uso:
        Aplicar en AccountStatementApi (reemplaza FinanceStatementPermission).
    """

    message: str = "Tu rol no tiene permiso para ver el estado de cuenta del paciente."

    def has_permission(self, request: Request, view: APIView) -> bool:
        """Evalúa si el rol activo puede ver el estado de cuenta.

        Args:
            request: DRF request con active_role adjunto por TenantAPIView.
            view:    vista DRF invocante (no usada directamente).

        Returns:
            True si el rol tiene acceso; False en caso contrario.
        """
        if request.method == "OPTIONS":
            return True

        role: Optional[str] = getattr(request, "active_role", None)
        if role is None:
            return False

        # Roles con acceso financiero siempre tienen acceso.
        if role in FINANCE_VIEW_ROLES:
            return True

        # Médico: solo si la clínica habilitó doctors_see_costs (D-2).
        if role == Role.DOCTOR:
            return _tenant_doctors_see_costs(request)

        return False


class ChargeListPermission(BasePermission):
    """Permiso combinado para ChargeListCreateApi (GET y escrituras).

    Implementa la Decisión D-2 del plan de Fase 1 solo para GET:
        GET  → FINANCE_VIEW_ROLES siempre; doctor solo si doctors_see_costs.
        POST → FINANCE_CORE_ROLES (owner/admin/finance — igual que FinanceChargePermission).
        PATCH/DELETE → FINANCE_CORE_ROLES.

    El flag solo afecta al GET: este permiso NO amplía escrituras al médico.
    """

    message: str = "Tu rol no tiene permiso para acceder a los cargos."

    def has_permission(self, request: Request, view: APIView) -> bool:
        """Evalúa permisos de cargos con visibilidad condicional para médicos.

        Args:
            request: DRF request con active_role adjunto por TenantAPIView.
            view:    vista DRF invocante.

        Returns:
            True si el rol tiene acceso para el método solicitado.
        """
        if request.method == "OPTIONS":
            return True

        request_method: str = "GET" if request.method == "HEAD" else (request.method or "")

        role: Optional[str] = getattr(request, "active_role", None)
        if role is None:
            return False

        if request_method == "GET":
            # GET: igual que PatientStatementPermission.
            if role in FINANCE_VIEW_ROLES:
                return True
            if role == Role.DOCTOR:
                return _tenant_doctors_see_costs(request)
            return False

        # POST / PATCH / DELETE: solo roles financieros duros (sin recepción).
        return role in FINANCE_CORE_ROLES


class CfdiPermission(HasClinicRole):
    """Permisos para CFDI 4.0 (emitir / consultar / cancelar).

    Matriz:
        GET  → owner, admin, finance + readonly (solo-ver).
        POST → owner, admin, finance (emitir/cancelar). Recepción NO factura.
    """

    policy: dict[str, frozenset[str]] = {
        "GET": frozenset({Role.OWNER, Role.ADMIN, Role.FINANCE, Role.READONLY}),
        "POST": FINANCE_CORE_ROLES,
    }


class FinanceConfigPermission(HasClinicRole):
    """Permisos para GET/PATCH /finanzas/config/ (datos fiscales del emisor).

    La configuración fiscal es administrativa: solo owner y admin.
    """

    policy: dict[str, frozenset[str]] = {
        "GET": MANAGE_ROLES,
        "PATCH": MANAGE_ROLES,
    }


class AgendaItemNotePermission(HasClinicRole):
    """Permisos para el hilo de notas colaborativas de la agenda.

    Spec §5: agregar/ver = cualquier rol con acceso a la agenda (todos menos Finanzas);
             borrar = autor / Dueño / Admin (la granularidad real la valida el service).

    Matriz:
        GET    → todos menos FINANCE (incluye READONLY: puede VER el hilo).
        POST   → roles con edición en agenda (READONLY y FINANCE excluidos: no escriben).
        DELETE → roles con edición en agenda (el service valida autor/Dueño/Admin).
    """

    policy: dict[str, frozenset[str]] = {
        "GET": frozenset(
            {Role.OWNER, Role.ADMIN, Role.DOCTOR, Role.NURSE, Role.RECEPTION, Role.READONLY}
        ),
        # READONLY puede ver el hilo pero NO escribir (rol de solo lectura).
        "POST": frozenset(
            {Role.OWNER, Role.ADMIN, Role.DOCTOR, Role.NURSE, Role.RECEPTION}
        ),
        "DELETE": frozenset(
            {Role.OWNER, Role.ADMIN, Role.DOCTOR, Role.NURSE, Role.RECEPTION}
        ),
    }


class NotePermission(HasClinicRole):
    """Permisos para el módulo Notas y Tareas.

    Diseño (documentado en apps/notas/views.py):
        GET    → todos los roles (el selector filtra lo que cada quien puede ver).
        POST   → todos los roles (la restricción owner-only para scope=role|all
                 la hace el SERVICE note_create, no el permiso HTTP).
                 Razón: permite que cualquier usuario cree notas personales sin
                 requerir roles admin/owner en el permiso HTTP.
        PATCH  → todos los roles (el service valida author/owner antes de mutar).
        DELETE → todos los roles (idem: el service valida).
        POST (toggle-done) → todos los roles (el service valida author + is_task).

    La granularidad real la da el service, no el permiso HTTP.
    El permiso HTTP solo garantiza que el usuario está autenticado y tiene membresía activa.
    """

    policy: dict[str, frozenset[str]] = {
        "GET": ALL_ROLES,
        "POST": ALL_ROLES,
        "PATCH": ALL_ROLES,
        "DELETE": ALL_ROLES,
    }


# ---------------------------------------------------------------------------
# Expediente Clínico — permisos (plan §5, sub-fase A1)
# ---------------------------------------------------------------------------

# Conjunto para lectura de contenido clínico.
# Recepción (RECEPTION) y finanzas (FINANCE) NO tienen acceso al contenido clínico.
# Las alergias son la excepción: son una bandera de seguridad visible para TODOS.
CLINICAL_READ: frozenset[str] = frozenset(
    {Role.OWNER, Role.ADMIN, Role.DOCTOR, Role.NURSE, Role.READONLY}
)


class AllergyPermission(HasClinicRole):
    """Permisos para el recurso Alergia (bandera de seguridad).

    Las alergias son visibles para TODOS los roles activos de la clínica porque
    constituyen una bandera de seguridad que cualquier miembro (incluso recepción
    y finanzas) debe poder ver en la ficha del paciente.

    Matriz:
        GET    → todos los roles (ALL_ROLES): bandera de seguridad, visible siempre.
        POST   → owner, admin, doctor, nurse (personal clínico y directivo).
        PATCH  → owner, admin, doctor, nurse.
        DELETE → owner, admin, doctor, nurse (baja lógica, no borrado físico).
    """

    policy: dict[str, frozenset[str]] = {
        "GET": ALL_ROLES,
        "POST": frozenset({Role.OWNER, Role.ADMIN, Role.DOCTOR, Role.NURSE}),
        "PATCH": frozenset({Role.OWNER, Role.ADMIN, Role.DOCTOR, Role.NURSE}),
        "DELETE": frozenset({Role.OWNER, Role.ADMIN, Role.DOCTOR, Role.NURSE}),
    }


class MedicalHistoryPermission(HasClinicRole):
    """Permisos para la Historia Clínica formal (A2).

    La HC es contenido clínico sensible protegido por NOM-004. Solo el personal
    clínico cualificado puede leerla o actualizarla. Recepción y finanzas no tienen
    acceso (a diferencia de las alergias, que son una bandera de seguridad para todos).

    Enfermería puede LEER la HC (consulta de antecedentes antes de la toma de signos)
    pero NO escribirla (la HC la redacta el médico tratante).

    CLINICAL_READ = {owner, admin, doctor, nurse, readonly}.
    Recepción y Finanzas quedan fuera tanto de lectura como de escritura.

    Matriz:
        GET → CLINICAL_READ: owner, admin, doctor, nurse, readonly.
        PUT → owner, admin, doctor (upsert de la historia clínica).
    """

    policy: dict[str, frozenset[str]] = {
        "GET": CLINICAL_READ,
        "PUT": frozenset({Role.OWNER, Role.ADMIN, Role.DOCTOR}),
    }


class VitalSignsPermission(HasClinicRole):
    """Permisos para el módulo de Signos Vitales (A3 — sección Enfermería).

    Diferencia clave con MedicalHistoryPermission:
        Enfermería (NURSE) SÍ puede registrar tomas de signos vitales (POST).
        Recepción y Finanzas NO tienen acceso (lectura ni escritura).

    Append-only: no hay PATCH, PUT ni DELETE; solo GET y POST.

    Matriz:
        GET  → CLINICAL_READ: owner, admin, doctor, nurse, readonly.
        POST → owner, admin, doctor, nurse (enfermería captura signos — A3 core).
    """

    policy: dict[str, frozenset[str]] = {
        "GET": CLINICAL_READ,
        "POST": frozenset({Role.OWNER, Role.ADMIN, Role.DOCTOR, Role.NURSE}),
    }


class EvolutionPermission(HasClinicRole):
    """Permisos para las Notas de Evolución (A4 — D-EC-1 inmutable) e imágenes.

    La nota de evolución es contenido clínico de alta sensibilidad:
    solo personal clínico cualificado puede leer (CLINICAL_READ) o crear
    (owner, admin, doctor). Recepción y finanzas NO tienen acceso.

    Inmutabilidad de NOTAS: no existen PATCH ni PUT sobre evoluciones.
    Si el cliente envía esos métodos sobre el endpoint de notas, DRF responde 405
    (método no ruteado). La regla del médico (doctor solo puede crear sobre citas
    propias) se valida en el service, no en el permiso HTTP.

    DELETE se permite para la baja lógica de IMÁGENES adjuntas (endpoint distinto).
    El permiso de DELETE es igual al de POST (escritura clínica):
    owner, admin, doctor.

    Matriz:
        GET    → CLINICAL_READ: owner, admin, doctor, nurse, readonly.
        POST   → owner, admin, doctor (nurse y readonly NO crean evoluciones/imágenes).
        DELETE → owner, admin, doctor (baja lógica de imágenes — D-EC-5).
    """

    policy: dict[str, frozenset[str]] = {
        "GET": CLINICAL_READ,
        "POST": frozenset({Role.OWNER, Role.ADMIN, Role.DOCTOR}),
        "DELETE": frozenset({Role.OWNER, Role.ADMIN, Role.DOCTOR}),
    }


class AddendumPermission(HasClinicRole):
    """Permisos para los Addenda sobre notas de evolución (A4).

    Solo crear y listar (append-only). Quien puede escribir addenda es
    el mismo conjunto que puede crear evoluciones (owner, admin, doctor).

    Matriz:
        GET  → CLINICAL_READ.
        POST → owner, admin, doctor.
    """

    policy: dict[str, frozenset[str]] = {
        "GET": CLINICAL_READ,
        "POST": frozenset({Role.OWNER, Role.ADMIN, Role.DOCTOR}),
    }


class DiagnosisPermission(HasClinicRole):
    """Permisos para el módulo de Diagnósticos (A4).

    Lectura: CLINICAL_READ (mismo conjunto que evolución y signos).
    Escritura y resolución: owner, admin, doctor. Recepción, finanzas y
    readonly NO escriben diagnósticos.

    Matriz:
        GET  → CLINICAL_READ.
        POST → owner, admin, doctor (create + resolver).
    """

    policy: dict[str, frozenset[str]] = {
        "GET": CLINICAL_READ,
        "POST": frozenset({Role.OWNER, Role.ADMIN, Role.DOCTOR}),
    }


class NursingInstructionPermission(HasClinicRole):
    """Permisos para el listado de indicaciones de enfermería por paciente.

    Las indicaciones son contenido clínico que enfermería necesita leer para
    ejecutar las órdenes del médico. Recepción y finanzas NO tienen acceso
    (CLINICAL_READ excluye esos roles).

    Readonly (READONLY) sí puede leer (observadores clínicos).

    Solo GET está expuesto en este endpoint (solo lectura).

    Matriz:
        GET → CLINICAL_READ: owner, admin, doctor, nurse, readonly.
    """

    policy: dict[str, frozenset[str]] = {
        "GET": CLINICAL_READ,
    }


class PrescriptionPermission(HasClinicRole):
    """Permisos para el módulo de Recetas (B1.2 — DR-6).

    Crear (POST): solo el médico con perfil Doctor activo. El servicio verifica
        adicionalmente que el usuario tenga Doctor activo en el tenant; si no, 403.
        El permiso HTTP aquí solo filtra por rol (capa de defensa externa).
        owner y admin NO crean recetas directamente (no tienen perfil médico en
        la mayoría de los casos); solo el rol doctor puede emitirlas.

    Leer (GET): CLINICAL_READ — roles clínicos con acceso al expediente.
        Recepción y finanzas NO ven recetas (DR-6).

    Anular POST /anular/: se recibe como POST; mismo rol de escritura = doctor.
        La validación fina (solo el médico emisor o owner/admin puede anular)
        la hace el servicio, no el permiso HTTP.

    Consistencia con el expediente clínico (MEDIO-5 — DR-6):
        La política de lectura (GET → CLINICAL_READ) es deliberadamente idéntica
        a la de historia clínica (MedicalHistoryPermission), signos vitales
        (VitalSignsPermission), notas de evolución (EvolutionPermission) y
        diagnósticos (DiagnosisPermission). Una receta es un documento clínico
        de igual sensibilidad: su contenido revela diagnósticos y tratamientos.

        Roles con acceso de LECTURA:
            - owner, admin  → gestión del tenant; acceso completo.
            - doctor        → médico tratante; acceso pleno al expediente.
            - nurse         → enfermería; consulta sin modificación.
            - readonly      → observador clínico (p. ej. médico de guardia);
                              puede consultar el historial de recetas sin emitir.

        Roles SIN acceso (ni lectura ni escritura):
            - reception     → recepción ve la agenda, no el expediente clínico.
            - finance       → finanzas ve facturación, no registros clínicos.

        Esta matriz NO se modifica sin aprobación del comité clínico (NOM-004
        exige restricción de acceso al expediente según función del personal).

    Matriz:
        GET  → CLINICAL_READ: owner, admin, doctor, nurse, readonly.
        POST → owner, admin, doctor.
    """

    policy: dict[str, frozenset[str]] = {
        "GET": CLINICAL_READ,
        "POST": frozenset({Role.OWNER, Role.ADMIN, Role.DOCTOR}),
    }


class MedicationPermission(HasClinicRole):
    """Permisos para el catálogo de medicamentos (B1.1).

    Búsqueda (GET): lectura clínica — roles que acceden al expediente.
      CLINICAL_READ = {owner, admin, doctor, nurse, readonly}.
      Recepción y finanzas NO tienen acceso a la sección de recetas (DR-6).

    Creación (POST) de medicamento custom: owner, admin, doctor.
      Solo personal médico/directivo puede extender el catálogo.
      Nurse puede buscar pero no crear entradas custom.

    Matriz:
        GET  → CLINICAL_READ.
        POST → owner, admin, doctor.
    """

    policy: dict[str, frozenset[str]] = {
        "GET": CLINICAL_READ,
        "POST": frozenset({Role.OWNER, Role.ADMIN, Role.DOCTOR}),
    }


class PrescriptionFormatPermission(HasClinicRole):
    """Permisos para la gestión de formatos de receta (F3).

    Listar/leer (GET): cualquier miembro activo puede ver los formatos disponibles
        para elegir al imprimir. ALL_ROLES (incluyendo recepción).

    Crear/actualizar/eliminar (POST/PATCH/DELETE): solo owner y admin configuran
        los formatos de la clínica. Los médicos pueden crear su formato personal
        (la validación fina de "solo el propio médico" la hace el servicio).

    Matriz:
        GET    → ALL_ROLES
        POST   → MANAGE_ROLES + DOCTOR (el médico puede crear su propio formato)
        PATCH  → MANAGE_ROLES + DOCTOR
        DELETE → MANAGE_ROLES
    """

    _DOCTOR_ROLES: frozenset[str] = frozenset({Role.OWNER, Role.ADMIN, Role.DOCTOR})

    policy: dict[str, frozenset[str]] = {
        "GET": ALL_ROLES,
        "POST": frozenset({Role.OWNER, Role.ADMIN, Role.DOCTOR}),
        "PATCH": frozenset({Role.OWNER, Role.ADMIN, Role.DOCTOR}),
        "DELETE": MANAGE_ROLES,
    }


class MedicalHistoryQuestionPermission(HasClinicRole):
    """Permisos para el CRUD de preguntas extra de HC (Fase 2).

    Las preguntas son configuración clínica del catálogo de la clínica:
        GET    → CLINICAL_READ: owner, admin, doctor, nurse, readonly.
                 Todos los roles clínicos necesitan leer el catálogo para
                 renderizar el formulario de HC en el frontend.
        POST   → MANAGE_ROLES: solo owner y admin configuran el catálogo.
        PATCH  → MANAGE_ROLES.
        DELETE → MANAGE_ROLES (baja lógica — D-EC-5).

    Recepción y finanzas NO tienen acceso (la HC es contenido clínico sensible).

    Matriz:
        GET    → CLINICAL_READ: owner, admin, doctor, nurse, readonly.
        POST   → MANAGE_ROLES: owner, admin.
        PATCH  → MANAGE_ROLES: owner, admin.
        DELETE → MANAGE_ROLES: owner, admin.
    """

    policy: dict[str, frozenset[str]] = {
        "GET": CLINICAL_READ,
        "POST": MANAGE_ROLES,
        "PATCH": MANAGE_ROLES,
        "DELETE": MANAGE_ROLES,
    }


class NotificationPermission(HasClinicRole):
    """Permisos para la campana de notificaciones.

    Una notificación es PRIVADA de su destinatario. La autoridad real no es el
    permiso HTTP sino:
        - el selector notification_list_for_user (filtra recipient=request.user);
        - el service notification_mark_read (verifica recipient == user).

    Por eso el permiso HTTP solo exige autenticación + membresía activa y abre
    todos los métodos a cualquier rol (cada quien opera SOLO sobre lo suyo).

    Matriz:
        GET  → todos los roles (listar mis avisos / contar no leídas).
        POST → todos los roles (marcar mías como leídas).
    """

    policy: dict[str, frozenset[str]] = {
        "GET": ALL_ROLES,
        "POST": ALL_ROLES,
    }


# ---------------------------------------------------------------------------
# Permisos del panel interno de plataforma (cross-tenant)
# ---------------------------------------------------------------------------

# Módulos de plataforma y qué roles pueden acceder en GET.
# Super-admin puede hacer todo. Sales puede ver clínicas y cambiar estado.
# Engineering puede ver métricas y clínicas, pero no cambiar estado ni ver staff.
_PLATFORM_ROLES_ALL: frozenset[str] = frozenset(
    {
        User.PlatformRole.SUPER_ADMIN,
        User.PlatformRole.SALES,
        User.PlatformRole.ENGINEERING,
    }
)
_PLATFORM_ROLES_MANAGE_CLINICS: frozenset[str] = frozenset(
    {User.PlatformRole.SUPER_ADMIN, User.PlatformRole.SALES}
)
_PLATFORM_ROLES_SUPER_ADMIN_ONLY: frozenset[str] = frozenset(
    {User.PlatformRole.SUPER_ADMIN}
)


class RetentionPermission(HasClinicRole):
    """Permisos para GET /finanzas/retencion/ — panel de analítica RFM.

    El panel de retención contiene datos de negocio sensibles (gasto por paciente,
    frecuencia de visitas, listas de pacientes en riesgo con datos de contacto).
    Recepción, médicos y enfermería NO acceden: es analítica de dirección/finanzas.

    Decisión D-7 (plan §3): solo visualización; ninguna escritura desde aquí.

    Matriz:
        GET → owner, admin, finance + readonly (solo-ver).
        (Recepción NO: opera caja pero no ve analítica de retención/RFM.)
        (Doctor/Nurse NO: acceden a la agenda y expediente, no a finanzas.)
    """

    policy: dict[str, frozenset[str]] = {
        "GET": frozenset({Role.OWNER, Role.ADMIN, Role.FINANCE, Role.READONLY}),
    }


class IsPlatformStaff(BasePermission):
    """Permiso base para el panel interno: exige is_platform_staff=True.

    Esta clase es la puerta de entrada a CUALQUIER endpoint de plataforma.
    Las subclases refinan qué platform_role es necesario.

    Devuelve 403 (no 404) cuando el usuario está autenticado pero no es staff
    de plataforma: la existencia del panel no es un secreto para los usuarios
    de clínicas. Si el usuario no está autenticado, también devuelve 403
    (IsAuthenticated en permission_classes ya habrá devuelto 401 antes).
    """

    message: str = "Acceso denegado: se requiere ser staff de la plataforma Maily."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if request.method == "OPTIONS":
            return True
        user = request.user
        return bool(
            getattr(user, "is_authenticated", False)
            and getattr(user, "is_platform_staff", False)
        )


class PlatformMetricsPermission(IsPlatformStaff):
    """Métricas del dashboard: ven los tres roles de plataforma."""

    message: str = "Solo el equipo de plataforma puede ver las métricas."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if not super().has_permission(request, view):
            return False
        if request.method == "OPTIONS":
            return True
        role: str = getattr(request.user, "platform_role", "")
        return role in _PLATFORM_ROLES_ALL


class PlatformClinicReadPermission(IsPlatformStaff):
    """Lectura de clínicas (GET/HEAD): ven los tres roles de plataforma.

    Solo lectura. El cambio de estado usa PlatformClinicWritePermission.
    """

    message: str = "Acceso denegado al módulo de clínicas de plataforma."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if not super().has_permission(request, view):
            return False
        if request.method == "OPTIONS":
            return True
        method = "GET" if request.method == "HEAD" else (request.method or "")
        role: str = getattr(request.user, "platform_role", "")
        if method in ("GET",):
            return role in _PLATFORM_ROLES_ALL
        return False


class PlatformClinicWritePermission(IsPlatformStaff):
    """Cambio de estado de una clínica (suspender/reactivar): super_admin y sales.

    Permiso dedicado para escrituras sobre clínicas. Separado de
    PlatformClinicReadPermission a propósito: así una modificación futura del
    permiso de lectura no relaja por accidente el control del endpoint de escritura.
    """

    message: str = "Solo super_admin y sales pueden cambiar el estado de una clínica."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if not super().has_permission(request, view):
            return False
        if request.method == "OPTIONS":
            return True
        role: str = getattr(request.user, "platform_role", "")
        return role in _PLATFORM_ROLES_MANAGE_CLINICS


class PlatformStaffListPermission(IsPlatformStaff):
    """Listado de usuarios de plataforma: solo super_admin."""

    message: str = "Solo el super_admin puede ver la lista de usuarios de plataforma."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if not super().has_permission(request, view):
            return False
        if request.method == "OPTIONS":
            return True
        role: str = getattr(request.user, "platform_role", "")
        return role in _PLATFORM_ROLES_SUPER_ADMIN_ONLY
