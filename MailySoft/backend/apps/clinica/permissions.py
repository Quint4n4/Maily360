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
