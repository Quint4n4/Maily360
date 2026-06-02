"""
Managers reutilizables para el sistema multi-tenant.

TenantManager: filtro automático por tenant del request + soft-delete.
Se usa como `objects` en TenantAwareModel.
Para bypass explícito (migraciones, admin, tareas) usar `Model.all_objects`.
"""

from django.db import models

from apps.core.tenant_context import get_current_tenant, is_tenant_context_active


class TenantManager(models.Manager):  # type: ignore[type-arg]
    """Manager por defecto de todo TenantAwareModel.

    Comportamiento (FIX-2 — falla segura):
    - Excluye registros con deleted_at IS NOT NULL (soft-delete).
    - Fuera de request (Celery, migraciones, management commands):
      context_active=False → devuelve todos los registros no eliminados SIN filtrar por tenant.
    - Dentro de request (context_active=True):
      * tenant != None → filtra por ese tenant.
      * tenant is None → devuelve QuerySet VACÍO (falla segura: usuario autenticado sin tenant).
        Esto evita que un endpoint que olvidó autenticación exponga datos de todos los tenants.
    """

    def get_queryset(self) -> models.QuerySet:  # type: ignore[type-arg]
        qs = super().get_queryset().filter(deleted_at__isnull=True)
        if is_tenant_context_active():
            tenant = get_current_tenant()
            if tenant is None:
                # Dentro de request pero sin tenant resuelto: falla segura.
                return qs.none()
            return qs.filter(tenant_id=tenant.id)
        # Fuera de request (Celery, migraciones, management commands): sin filtro de tenant.
        return qs
