"""
Permisos declarativos para el módulo Mi Consultorio.

Matices de acceso:
    ClinicSettings GET    → roles clínicos (la usan las recetas para encabezado).
    ClinicSettings PUT    → solo owner y admin (configuración administrativa).
    ClinicTemplate GET    → roles clínicos (la usan al redactar recetas).
    ClinicTemplate write  → owner, admin, doctor (los médicos crean sus propias plantillas).
    PatientCategory       → GET = todos los roles; escritura = owner y admin.
    Doctor profile images → owner, admin y el propio doctor (validado en service).
    DoctorUniversity      → GET = todos los roles; escritura = owner, admin, doctor.
"""

from typing import ClassVar

from apps.core.permissions import ALL_ROLES, CLINICAL_READ, MANAGE_ROLES, HasClinicRole
from apps.tenancy.models import TenantMembership

Role = TenantMembership.Role

# Roles que pueden escribir plantillas: doctores también (crean sus plantillas propias).
_TEMPLATE_WRITE_ROLES: frozenset[str] = frozenset({Role.OWNER, Role.ADMIN, Role.DOCTOR})

# Roles que pueden gestionar perfil médico (imágenes, universidades):
# owner y admin siempre; doctor también (perfil propio — la vista valida doctor == user).
_DOCTOR_PROFILE_WRITE: frozenset[str] = frozenset({Role.OWNER, Role.ADMIN, Role.DOCTOR})


class ClinicSettingsPermission(HasClinicRole):
    """Permisos para GET/PUT de la configuración de la clínica.

    Matriz:
        GET → CLINICAL_READ (roles clínicos necesitan el encabezado para recetas).
        PUT → solo owner y admin (configuración administrativa sensible).
    """

    policy: ClassVar[dict[str, frozenset[str]]] = {
        "GET": CLINICAL_READ,
        "PUT": MANAGE_ROLES,
    }


class ClinicTemplatePermission(HasClinicRole):
    """Permisos para CRUD de plantillas clínicas.

    Matriz:
        GET    → CLINICAL_READ (todos los que redactan pueden ver plantillas).
        POST   → owner, admin, doctor (médicos pueden crear sus propias plantillas).
        PATCH  → owner, admin, doctor.
        DELETE → owner, admin, doctor (baja lógica).
    """

    policy: ClassVar[dict[str, frozenset[str]]] = {
        "GET": CLINICAL_READ,
        "POST": _TEMPLATE_WRITE_ROLES,
        "PATCH": _TEMPLATE_WRITE_ROLES,
        "DELETE": _TEMPLATE_WRITE_ROLES,
    }


class PatientCategoryPermission(HasClinicRole):
    """Permisos para el catálogo de categorías de paciente.

    Matriz:
        GET    → todos los roles (catálogo de sugerencias, no datos clínicos sensibles).
        POST   → solo owner y admin (gestión del catálogo).
        DELETE → solo owner y admin.
    """

    policy: ClassVar[dict[str, frozenset[str]]] = {
        "GET": ALL_ROLES,
        "POST": MANAGE_ROLES,
        "DELETE": MANAGE_ROLES,
    }


class DoctorProfilePermission(HasClinicRole):
    """Permisos para el perfil ampliado del médico (sello, foto, universidades).

    Matriz:
        GET    → todos los roles (los datos de perfil son visibles en el sistema).
        POST   → owner, admin, doctor.
        PATCH  → owner, admin, doctor.
        DELETE → owner, admin, doctor.
    """

    policy: ClassVar[dict[str, frozenset[str]]] = {
        "GET": ALL_ROLES,
        "POST": _DOCTOR_PROFILE_WRITE,
        "PATCH": _DOCTOR_PROFILE_WRITE,
        "DELETE": _DOCTOR_PROFILE_WRITE,
    }


class ClinicTeamPermission(HasClinicRole):
    """Permisos para el catálogo del equipo/departamentos de la clínica (Fase 4).

    Matriz:
        GET    → owner, admin, doctor (el médico lo consulta al armar el Plan Integral).
        POST   → solo owner y admin (mantener el catálogo es administrativo).
        PATCH  → solo owner y admin.
        DELETE → solo owner y admin.
    """

    policy: ClassVar[dict[str, frozenset[str]]] = {
        "GET": frozenset({Role.OWNER, Role.ADMIN, Role.DOCTOR}),
        "POST": MANAGE_ROLES,
        "PATCH": MANAGE_ROLES,
        "DELETE": MANAGE_ROLES,
    }


class SucursalPermission(HasClinicRole):
    """Permisos para el CRUD de Sucursal (multi-sede).

    Multi-sede (decisión del dueño, 2026-07-16): dar de alta, editar o dar de
    baja SUCURSALES es dominio EXCLUSIVO del dueño. El administrador (incluido
    el "admin de sucursal") ya NO puede crear/editar/borrar sedes — antes era
    owner+admin. El GET se mantiene para TODOS (el selector de sucursal del
    encabezado); la VISTA sigue acotando el resultado a `allowed_sucursales`.

    Matriz:
        GET    → todos los roles (selector de sucursal; la VISTA acota a
                 `allowed_sucursales` — owner ve todas; el resto solo las suyas).
        POST   → solo owner (alta de sedes).
        PATCH  → solo owner.
        DELETE → solo owner (baja lógica — is_active=False).
    """

    #: Gestión de sucursales: solo el dueño.
    _OWNER_ONLY: ClassVar[frozenset[str]] = frozenset({Role.OWNER})

    policy: ClassVar[dict[str, frozenset[str]]] = {
        "GET": ALL_ROLES,
        "POST": _OWNER_ONLY,
        "PATCH": _OWNER_ONLY,
        "DELETE": _OWNER_ONLY,
    }


class MembershipSucursalPermission(HasClinicRole):
    """Permisos para gestionar la asignación de sucursales a un miembro (Fase 4).

    Matriz:
        GET → solo owner y admin (ver qué sedes administra cada quien es dato
              administrativo).
        PUT → solo owner y admin.

    La granularidad fina —un admin solo puede otorgar/quitar sucursales que él
    mismo tiene permitidas, reglas anti-lockout del owner y del propio admin—
    NO se valida aquí: este permiso solo gatea por ROL (método-consciente, sin
    acceso al payload ni al actor's `allowed_sucursales`). Esa lógica de
    negocio vive en el service `membership_sucursales_set` — mismo patrón que
    `apps.clinica.sucursal_scope.resolve_write_sucursal`, que también autoriza
    en la capa de servicio en vez de en un permiso DRF.
    """

    policy: ClassVar[dict[str, frozenset[str]]] = {
        "GET": MANAGE_ROLES,
        "PUT": MANAGE_ROLES,
    }
