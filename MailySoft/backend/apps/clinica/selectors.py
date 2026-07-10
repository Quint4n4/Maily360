"""
Selectors de la app clinica — lecturas/queries. NUNCA modifican datos.

El TenantManager (objects) filtra automáticamente por el tenant activo en el
thread-local cuando context_active=True. Usar all_objects solo cuando se
necesita cruzar tenants (tests de aislamiento, management commands).

Convención: keyword-only args, nombrado acción+entidad.
"""

import uuid

from django.db.models import QuerySet

from apps.clinica.models import (
    ClinicSettings,
    ClinicTeamMember,
    ClinicTemplate,
    DoctorCredential,
    DoctorUniversity,
    PatientCategory,
)


def clinic_settings_get(*, tenant_id: uuid.UUID) -> ClinicSettings | None:
    """Retorna la ClinicSettings activa del tenant, o None si no existe aún.

    No lanza DoesNotExist: el flujo de upsert puede llamar a esta función
    antes de que se haya creado la configuración. La vista y el service
    manejan el None (creación de primera vez).

    Args:
        tenant_id: UUID del tenant cuya configuración se desea.

    Returns:
        Instancia ClinicSettings o None.
    """
    return ClinicSettings.objects.filter(tenant_id=tenant_id, deleted_at__isnull=True).first()


def clinic_settings_get_strict(*, tenant_id: uuid.UUID) -> ClinicSettings:
    """Retorna la ClinicSettings activa del tenant.

    Args:
        tenant_id: UUID del tenant.

    Returns:
        Instancia ClinicSettings.

    Raises:
        ClinicSettings.DoesNotExist: si no existe configuración para el tenant.
    """
    return ClinicSettings.objects.get(tenant_id=tenant_id, deleted_at__isnull=True)


def clinic_template_get(*, template_id: uuid.UUID) -> ClinicTemplate:
    """Retorna una ClinicTemplate por su UUID.

    Usa el TenantManager: un template de otro tenant → DoesNotExist → 404.

    Args:
        template_id: UUID del template.

    Returns:
        Instancia ClinicTemplate.

    Raises:
        ClinicTemplate.DoesNotExist: si no existe o no pertenece al tenant activo.
    """
    return ClinicTemplate.objects.get(id=template_id)


def clinic_template_list(*, kind: str | None = None) -> QuerySet[ClinicTemplate]:
    """Retorna el QuerySet de plantillas activas del tenant actual.

    Args:
        kind: Filtrar por tipo (recipe/document/consent). None = todos los tipos.

    Returns:
        QuerySet[ClinicTemplate] ordenado por kind, name.
    """
    qs: QuerySet[ClinicTemplate] = ClinicTemplate.objects.filter(is_active=True)

    if kind is not None:
        qs = qs.filter(kind=kind)

    return qs.order_by("kind", "name")


def patient_category_get(*, category_id: uuid.UUID) -> PatientCategory:
    """Retorna una PatientCategory por su UUID.

    Usa el TenantManager: una categoría de otro tenant → DoesNotExist → 404.

    Args:
        category_id: UUID de la categoría.

    Returns:
        Instancia PatientCategory.

    Raises:
        PatientCategory.DoesNotExist: si no existe o no pertenece al tenant activo.
    """
    return PatientCategory.objects.get(id=category_id)


def patient_category_list() -> QuerySet[PatientCategory]:
    """Retorna el QuerySet de categorías activas del tenant actual.

    Returns:
        QuerySet[PatientCategory] activas, ordenadas por nombre.
    """
    return PatientCategory.objects.filter(is_active=True).order_by("name")


def doctor_university_list(*, doctor_id: uuid.UUID) -> QuerySet[DoctorUniversity]:
    """Retorna las universidades activas de un médico.

    Usa el TenantManager para filtrar por tenant. El doctor_id adicional
    restringe a las filas de ese médico específico.

    Args:
        doctor_id: UUID del Doctor.

    Returns:
        QuerySet[DoctorUniversity] ordenado por nombre.
    """
    return DoctorUniversity.objects.filter(doctor_id=doctor_id, deleted_at__isnull=True).order_by(
        "name"
    )


def doctor_credential_list(*, doctor_id: uuid.UUID) -> QuerySet[DoctorCredential]:
    """Retorna las credenciales activas de un médico ordenadas por `order`.

    Usa el TenantManager para filtrar por tenant. El doctor_id adicional
    restringe a las filas de ese médico específico.

    Args:
        doctor_id: UUID del Doctor.

    Returns:
        QuerySet[DoctorCredential] activas, ordenadas por order, id.
    """
    return DoctorCredential.objects.filter(
        doctor_id=doctor_id, is_active=True, deleted_at__isnull=True
    ).order_by("order", "id")


def doctor_credentials_for_tenant(*, status: str | None = None) -> QuerySet[DoctorCredential]:
    """Retorna las credenciales activas de TODOS los médicos del tenant activo.

    Para la bandeja de validación del administrador. El TenantManager limita al
    tenant actual (RLS). Opcionalmente filtra por estado de validación.

    Args:
        status: 'pendiente' | 'validada' | 'rechazada' o None (todas).

    Returns:
        QuerySet[DoctorCredential] activas del tenant, con el doctor precargado.
    """
    qs = (
        DoctorCredential.objects.filter(is_active=True, deleted_at__isnull=True)
        .select_related("doctor", "doctor__membership__user")
        .order_by("validation_status", "doctor", "order", "id")
    )
    if status:
        qs = qs.filter(validation_status=status)
    return qs


def doctor_credential_get(*, credential_id: uuid.UUID) -> DoctorCredential:
    """Retorna una DoctorCredential por su UUID.

    Usa el TenantManager: una credencial de otro tenant → DoesNotExist → 404.

    Args:
        credential_id: UUID de la DoctorCredential.

    Returns:
        Instancia DoctorCredential.

    Raises:
        DoctorCredential.DoesNotExist: si no existe o no pertenece al tenant activo.
    """
    return DoctorCredential.objects.select_related("doctor").get(id=credential_id)


def doctor_university_get(*, university_id: uuid.UUID) -> DoctorUniversity:
    """Retorna una DoctorUniversity por su UUID.

    Usa el TenantManager: una universidad de otro tenant → DoesNotExist → 404.

    Args:
        university_id: UUID de la DoctorUniversity.

    Returns:
        Instancia DoctorUniversity.

    Raises:
        DoctorUniversity.DoesNotExist: si no existe o no pertenece al tenant activo.
    """
    return DoctorUniversity.objects.select_related("doctor").get(id=university_id)


# ---------------------------------------------------------------------------
# ClinicTeamMember — equipo/departamentos de la clínica (Fase 4)
# ---------------------------------------------------------------------------


def clinic_team_get(*, member_id: uuid.UUID) -> ClinicTeamMember:
    """Retorna un ClinicTeamMember por su UUID.

    Usa el TenantManager: un miembro de otro tenant → DoesNotExist → 404.

    Raises:
        ClinicTeamMember.DoesNotExist: si no existe o no pertenece al tenant activo.
    """
    return ClinicTeamMember.objects.get(id=member_id)


def clinic_team_list(*, only_active: bool = True) -> QuerySet[ClinicTeamMember]:
    """Retorna el equipo/departamentos de la clínica del tenant actual.

    Usado también por `apps.expediente.services_plan_integral.longevity_plan_draft`
    (para mostrarlo) y `longevity_plan_create` (para snapshotearlo en `equipo`).

    Args:
        only_active: si True (default), excluye miembros desactivados.
    """
    qs: QuerySet[ClinicTeamMember] = ClinicTeamMember.objects.all()
    if only_active:
        qs = qs.filter(is_active=True)
    return qs.order_by("order", "departamento", "nombre")
