"""
Modelos abstractos base de Maily Soft.

BaseModel        — UUID pk, timestamps, soft-delete.
TenantAwareModel — BaseModel + tenant FK + created_by + TenantManager.

REGLA: TODOS los modelos de negocio heredan de TenantAwareModel.
       Los modelos de plataforma (Tenant, User) heredan de BaseModel.
"""

import uuid

from django.conf import settings
from django.db import models

from apps.core.managers import TenantManager


class BaseModel(models.Model):
    """Base abstracta para toda tabla del proyecto.

    Provee:
    - id: UUIDv4, primary key, no editable.
    - created_at / updated_at: gestionados automáticamente.
    - deleted_at: NULL significa activo; rellenado = borrado lógico (soft-delete).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="NULL = activo. Rellenar para borrado lógico.",
    )

    class Meta:
        abstract = True


class TenantAwareModel(BaseModel):
    """Modelo de negocio vinculado a un Tenant (clínica).

    Provee:
    - tenant: FK a tenancy.Tenant, protegida contra borrado.
    - created_by: FK al usuario que creó el registro (nullable para seeds/imports).
    - objects: TenantManager — filtra por tenant del request + excluye soft-deleted.
    - all_objects: Manager estándar — para management commands, migraciones y tests.

    NUNCA usar `all_objects` en vistas o servicios sin justificación explícita.
    """

    tenant = models.ForeignKey(
        "tenancy.Tenant",
        on_delete=models.PROTECT,
        related_name="+",
        db_index=True,
        help_text="Clínica a la que pertenece este registro.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        # FIX-7: SET_NULL en lugar de PROTECT para que borrar un usuario no bloquee
        # el borrado de todos los registros que creó. Ya tiene null=True/blank=True.
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
        help_text="Usuario que creó el registro. Null en imports/seeds o si el usuario fue borrado.",
    )

    objects: TenantManager = TenantManager()
    all_objects: models.Manager = models.Manager()  # type: ignore[type-arg]

    class Meta:
        abstract = True
