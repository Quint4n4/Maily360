"""
Managers reutilizables para el sistema multi-tenant.

TenantManager: filtro automático por tenant del request + soft-delete.
Se usa como `objects` en TenantAwareModel.
Para bypass explícito (migraciones, admin, tareas) usar `Model.all_objects`.
"""

from django.db import models

from apps.core.tenant_context import get_current_tenant


class TenantManager(models.Manager):  # type: ignore[type-arg]
    """Manager por defecto de todo TenantAwareModel.

    Comportamiento:
    - Excluye registros con deleted_at IS NOT NULL (soft-delete).
    - Si hay un tenant en el thread-local (es decir, estamos dentro de un
      request autenticado), filtra adicionalmente por ese tenant.
    - Si NO hay tenant en el thread-local (management commands, migraciones,
      workers Celery sin contexto de tenant) devuelve todos los registros
      no eliminados SIN filtrar por tenant.
    """

    def get_queryset(self) -> models.QuerySet:  # type: ignore[type-arg]
        qs = super().get_queryset().filter(deleted_at__isnull=True)
        tenant = get_current_tenant()
        if tenant is None:
            return qs
        return qs.filter(tenant_id=tenant.id)
