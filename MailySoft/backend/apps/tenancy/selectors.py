"""
Selectors de la app tenancy — lectura de miembros de la clínica.

Las membresías NO heredan de TenantAwareModel, así que el aislamiento por tenant
se aplica EXPLÍCITAMENTE filtrando por el tenant activo del request.
"""

import uuid

from django.db.models import QuerySet

from apps.core.tenant_context import get_current_tenant
from apps.tenancy.models import TenantMembership


def membership_list() -> QuerySet[TenantMembership]:
    """Membresías del tenant activo, con el usuario precargado.

    Ordena por rol y nombre para que el panel pueda agrupar por rol fácilmente.
    Incluye membresías activas e inactivas; el estado de bloqueo de la cuenta
    se lee de user.is_active.
    """
    tenant = get_current_tenant()
    return (
        TenantMembership.objects.filter(tenant=tenant)
        .select_related("user")
        .order_by("role", "user__first_name", "user__last_name")
    )


def membership_get(*, membership_id: uuid.UUID) -> TenantMembership:
    """Recupera una membresía del tenant activo o lanza DoesNotExist.

    El filtro por tenant garantiza el aislamiento multi-tenant: una membresía
    de otro tenant produce DoesNotExist (404), nunca se expone.
    """
    tenant = get_current_tenant()
    return TenantMembership.objects.select_related("user").get(
        id=membership_id,
        tenant=tenant,
    )
