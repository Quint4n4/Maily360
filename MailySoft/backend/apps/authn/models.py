"""
Modelo User custom para Maily Soft.

Reemplaza al User de Django por un modelo email-based con:
- Autenticación por email (no username).
- Bandera `is_platform_staff` para el equipo interno de Maily.
- Integración con TenantMembership para acceso multi-tenant.

IMPORTANTE: AUTH_USER_MODEL debe apuntar a este modelo ANTES de la
primera migración. Si ya hay migraciones de Django por defecto, se
requiere un reset completo de la base de datos.
"""

import uuid

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from apps.authn.managers import UserManager
from apps.core.files import user_avatar_path


class User(AbstractBaseUser, PermissionsMixin):
    """Usuario global de Maily Soft.

    Un usuario puede ser:
    a) Staff de plataforma (equipo de Maily): is_platform_staff=True.
    b) Miembro de una o más clínicas: vía tenancy.TenantMembership.
    c) Ambos (p. ej. un ingeniero de Maily que también usa una clínica demo).

    El acceso a cada clínica y el rol dentro de ella se gestiona
    exclusivamente a través de TenantMembership.
    """

    class PlatformRole(models.TextChoices):
        """Roles del equipo interno de la plataforma Maily."""

        SUPER_ADMIN = "super_admin", "Súper Admin"
        SALES = "sales", "Ventas / Éxito de Cliente"
        ENGINEERING = "engineering", "Ingeniería"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(
        unique=True,
        help_text="Dirección de correo electrónico. Usado como nombre de usuario.",
    )
    first_name = models.CharField(max_length=120, blank=True)
    last_name = models.CharField(max_length=120, blank=True)
    avatar = models.ImageField(
        upload_to=user_avatar_path,
        null=True,
        blank=True,
        help_text="Foto de perfil del usuario (opcional).",
    )

    is_active = models.BooleanField(
        default=True,
        help_text="Desactivar en lugar de borrar para preservar historial.",
    )
    is_staff = models.BooleanField(
        default=False,
        help_text="Permite acceder al Django Admin. NO implica ser staff de plataforma.",
    )
    is_platform_staff = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True = pertenece al equipo interno de Maily Soft.",
    )
    platform_role = models.CharField(
        max_length=20,
        choices=PlatformRole.choices,
        blank=True,
        default="",
        help_text="Rol dentro del equipo de plataforma. Ignorado si is_platform_staff=False.",
    )
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []  # email ya es el USERNAME_FIELD

    class Meta:
        db_table = "authn_users"
        ordering = ["email"]
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"

    def __str__(self) -> str:
        return self.email

    @property
    def full_name(self) -> str:
        """Nombre completo legible. Si está vacío, devuelve el email."""
        return f"{self.first_name} {self.last_name}".strip() or self.email
