"""
Selectors de la app authn.

Lecturas/queries del dominio de autenticación. NUNCA modifican datos.

Nota de manager:
    TenantMembership hereda de BaseModel (no de TenantAwareModel), por lo que
    su manager por defecto es el manager estándar de Django — NO filtra por
    tenant del thread-local. Esto es intencional y correcto: la membresía no
    "pertenece" a un tenant, sino que *liga* un user con un tenant. Por lo
    tanto, podemos usar TenantMembership.objects directamente aquí sin
    depender de ningún contexto de tenant activo.
"""

from django.db.models import QuerySet

from apps.authn.models import User
from apps.tenancy.models import TenantMembership


def user_active_memberships(*, user: User) -> QuerySet[TenantMembership]:
    """Retorna todas las membresías activas del usuario.

    Una membresía se considera activa si cumple TODAS las condiciones:
    - is_active = True (el acceso no ha sido suspendido)
    - tenant__status = "active" (la clínica está activa, no en trial o suspendida)
    - deleted_at IS NULL (la membresía no ha sido borrada lógicamente)
    - tenant__deleted_at IS NULL (la clínica no ha sido borrada lógicamente)

    El QuerySet incluye select_related("tenant") para evitar N+1 al serializar.
    Se ordena por created_at para un orden determinista y reproducible.

    Contexto de manager:
        Usa TenantMembership.objects (manager estándar de Django). Esto es
        seguro porque TenantMembership hereda de BaseModel, no de
        TenantAwareModel — su manager NO filtra por tenant del thread-local.
        Este selector puede ejecutarse desde cualquier contexto (request HTTP,
        Celery, management commands) sin efectos secundarios de tenant-context.

    Args:
        user: instancia de User cuyas membresías se consultan.

    Returns:
        QuerySet[TenantMembership] filtrado, con select_related("tenant"),
        ordenado por created_at ascendente. Sin paginar.
    """
    return (
        TenantMembership.objects.filter(
            user=user,
            is_active=True,
            deleted_at__isnull=True,
            tenant__status="active",
            tenant__deleted_at__isnull=True,
        )
        .select_related("tenant")
        .order_by("created_at")
    )
