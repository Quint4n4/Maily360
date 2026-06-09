"""
Services de la app tenancy — gestión de miembros de la clínica.

Crear un miembro = crear (o validar) la cuenta de usuario + su membresía con un
rol. Bloquear un miembro = desactivar su cuenta de usuario (no puede iniciar
sesión). Toda escritura pasa por aquí; las vistas son delgadas.
"""

from typing import Optional

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.tenancy.models import Tenant, TenantMembership

User = get_user_model()

_VALID_ROLES = frozenset(choice[0] for choice in TenantMembership.Role.choices)


def member_create(
    *,
    tenant: Tenant,
    actor: "User",  # type: ignore[valid-type]
    email: str,
    first_name: str,
    last_name: str,
    password: str,
    role: str,
) -> TenantMembership:
    """Crea un miembro de la clínica: cuenta de usuario + membresía con rol.

    Valida:
    - rol válido.
    - email no registrado (no se reutiliza ni se "secuestra" una cuenta existente).
    - contraseña robusta (validadores de Django: longitud, no común, no numérica).

    Args:
        tenant:     Clínica a la que se agrega el miembro.
        actor:      Usuario que realiza el alta (auditoría).
        email:      Correo del nuevo miembro (será su usuario de acceso).
        first_name: Nombre(s).
        last_name:  Apellidos.
        password:   Contraseña inicial (debe pasar los validadores).
        role:       Rol clínico (owner/admin/doctor/nurse/reception/finance/readonly).

    Returns:
        La TenantMembership creada (con su user).

    Raises:
        ValidationError: rol inválido, email ya registrado o contraseña débil.
    """
    if role not in _VALID_ROLES:
        raise ValidationError(f"Rol inválido '{role}'.")

    normalized_email = email.strip().lower()
    if User.objects.filter(email=normalized_email).exists():
        raise ValidationError("Ya existe una cuenta con ese correo.")

    # Construir el usuario sin guardar para validar la contraseña contra sus
    # atributos (similitud con email/nombre) antes de persistir nada.
    user = User(
        email=normalized_email,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        is_active=True,
        is_platform_staff=False,
    )
    validate_password(password, user=user)

    with transaction.atomic():
        user.set_password(password)
        user.save()
        membership = TenantMembership.objects.create(
            user=user,
            tenant=tenant,
            role=role,
            is_active=True,
        )

    audit_record(
        action=ActionType.MEMBER_CREATE,
        resource_type="TenantMembership",
        actor=actor,
        tenant=tenant,
        resource_id=membership.id,
        resource_repr=normalized_email,
        metadata={"role": role},
    )
    return membership


def member_update(
    *,
    membership: TenantMembership,
    actor: "User",  # type: ignore[valid-type]
    role: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    password: Optional[str] = None,
    blocked: Optional[bool] = None,
) -> TenantMembership:
    """Actualiza datos de un miembro (nombre, rol) y/o bloquea/reactiva su cuenta.

    - first_name / last_name: si se proveen, actualizan el nombre del usuario.
    - role:    si se provee, cambia el rol (validado).
    - blocked: True desactiva la cuenta (no puede iniciar sesión); False la reactiva.
               No se permite que el actor se bloquee a sí mismo (evita lockout).

    Args:
        membership: Membresía a actualizar (recuperada por el selector).
        actor:      Usuario que realiza el cambio (auditoría).
        first_name: Nuevo nombre, opcional.
        last_name:  Nuevos apellidos, opcional.
        role:       Nuevo rol, opcional.
        blocked:    Estado de bloqueo, opcional.

    Returns:
        La membresía actualizada.

    Raises:
        ValidationError: rol inválido o intento de autobloqueo.
    """
    cambios: dict[str, object] = {}

    # Datos del usuario (nombre).
    user_fields: list[str] = []
    if first_name is not None:
        membership.user.first_name = first_name.strip()
        user_fields.append("first_name")
        cambios["first_name"] = membership.user.first_name
    if last_name is not None:
        membership.user.last_name = last_name.strip()
        user_fields.append("last_name")
        cambios["last_name"] = membership.user.last_name
    if user_fields:
        membership.user.save(update_fields=user_fields)

    # Rol de la membresía.
    if role is not None:
        if role not in _VALID_ROLES:
            raise ValidationError(f"Rol inválido '{role}'.")
        membership.role = role
        membership.save(update_fields=["role", "updated_at"])
        cambios["role"] = role

    if cambios:
        audit_record(
            action=ActionType.MEMBER_UPDATE,
            resource_type="TenantMembership",
            actor=actor,
            tenant=membership.tenant,
            resource_id=membership.id,
            resource_repr=membership.user.email,
            metadata={"changed": sorted(cambios.keys())},
        )

    # Restablecer contraseña (la valida con los validadores de Django).
    if password is not None:
        validate_password(password, user=membership.user)
        membership.user.set_password(password)
        membership.user.save(update_fields=["password"])
        audit_record(
            action=ActionType.MEMBER_PASSWORD,
            resource_type="TenantMembership",
            actor=actor,
            tenant=membership.tenant,
            resource_id=membership.id,
            resource_repr=membership.user.email,
        )

    if blocked is not None:
        if blocked and membership.user_id == getattr(actor, "id", None):
            raise ValidationError("No puedes bloquear tu propia cuenta.")
        membership.user.is_active = not blocked
        membership.user.save(update_fields=["is_active"])
        audit_record(
            action=ActionType.MEMBER_BLOCK,
            resource_type="TenantMembership",
            actor=actor,
            tenant=membership.tenant,
            resource_id=membership.id,
            resource_repr=membership.user.email,
            metadata={"blocked": blocked},
        )

    return membership


def member_set_avatar(*, membership: TenantMembership, actor: "User", image: object) -> TenantMembership:  # type: ignore[valid-type]
    """Asigna (o reemplaza) la foto de un miembro. La imagen ya viene validada por la vista."""
    if membership.user.avatar:
        membership.user.avatar.delete(save=False)
    membership.user.avatar = image  # type: ignore[assignment]
    membership.user.save(update_fields=["avatar"])
    audit_record(
        action=ActionType.MEMBER_UPDATE,
        resource_type="TenantMembership",
        actor=actor,
        tenant=membership.tenant,
        resource_id=membership.id,
        resource_repr=membership.user.email,
        metadata={"changed": ["avatar"]},
    )
    return membership


def member_clear_avatar(*, membership: TenantMembership, actor: "User") -> TenantMembership:  # type: ignore[valid-type]
    """Elimina la foto de un miembro."""
    if membership.user.avatar:
        membership.user.avatar.delete(save=False)
    membership.user.avatar = None  # type: ignore[assignment]
    membership.user.save(update_fields=["avatar"])
    audit_record(
        action=ActionType.MEMBER_UPDATE,
        resource_type="TenantMembership",
        actor=actor,
        tenant=membership.tenant,
        resource_id=membership.id,
        resource_repr=membership.user.email,
        metadata={"changed": ["avatar"], "cleared": True},
    )
    return membership
