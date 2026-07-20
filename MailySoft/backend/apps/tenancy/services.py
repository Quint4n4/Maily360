"""
Services de la app tenancy — gestión de miembros de la clínica.

Crear un miembro = crear (o validar) la cuenta de usuario + su membresía con un
rol. Bloquear un miembro = desactivar su cuenta de usuario (no puede iniciar
sesión). Toda escritura pasa por aquí; las vistas son delgadas.

Autorización por sucursal (multi-sede — cierre del clúster F, ver
docs/design/sucursales-hallazgos-seguridad.md): hasta ahora esta app NUNCA
supo de sucursales, lo que permitía que un "admin de sucursal" (acotado a una
sede vía MembershipSucursal) se auto-promoviera a owner, modificara a
cualquier owner (incluida su contraseña) o creara miembros con rol owner —
verificado con exploits reales. `member_create`/`member_update` ahora
resuelven la membresía ACTIVA del actor (mismo patrón que
`apps.personal.services.doctor_set_sucursales` /
`apps.clinica.services.membership_sucursales_set`) y aplican:
    - owner del tenant → sin restricciones adicionales (puede todo,
      incluido resetear la contraseña de otro owner).
    - cualquier otro rol (admin incluido) → solo puede tocar personal
      dentro de `allowed_sucursales`, nunca a un owner, y nunca puede
      otorgar el rol owner (anti-escalada: nadie otorga un poder que él
      mismo no tiene).

Jerarquía de roles (decisión del dueño 2026-07-16 — ver
`TenantMembership.operational_roles()`): la regla de arriba se AMPLÍA de
"nunca un owner" a "nunca un owner NI un admin". Un actor NO owner (el
"administrador de sucursal") solo puede crear/editar/gestionar (incluida la
foto) personal con un rol OPERACIONAL, y nunca puede otorgar/ascender a
alguien a `admin` u `owner`. Esto cierra dos huecos reportados por el dueño:
un admin de sucursal podía ver y dar de alta a otros admins.
"""

import uuid
from typing import Optional

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.clinica.models import MembershipSucursal
from apps.clinica.sucursal_scope import allowed_sucursales
from apps.tenancy.models import Tenant, TenantMembership
from apps.tenancy.selectors import membership_in_sucursal_scope

User = get_user_model()

_VALID_ROLES = frozenset(choice[0] for choice in TenantMembership.Role.choices)


def _resolve_actor_membership(*, actor: "User", tenant: Tenant) -> TenantMembership:  # type: ignore[valid-type]
    """Membresía ACTIVA de `actor` en `tenant`, o ValidationError si no tiene.

    Mismo patrón que `apps.personal.services.doctor_set_sucursales` /
    `apps.clinica.services.membership_sucursales_set`: primera membresía
    activa (no soft-deleted) por fecha de creación. `member_create` y
    `member_update` la usan para decidir si el actor es owner (sin
    restricciones) o debe acotarse a `allowed_sucursales`.
    """
    membership = (
        TenantMembership.objects.filter(
            user=actor, tenant=tenant, is_active=True, deleted_at__isnull=True
        )
        .order_by("created_at")
        .first()
    )
    if membership is None:
        raise ValidationError("No tienes una membresía activa en esta clínica.")
    return membership


def _authorize_write_on_member(
    *,
    actor: "User",  # type: ignore[valid-type]
    actor_membership: TenantMembership,
    membership: TenantMembership,
) -> None:
    """Autoriza que `actor` escriba sobre `membership` (cualquier campo).

    Compartido por `member_update`, `member_set_avatar` y `member_clear_avatar`
    — D2 es una regla de negocio sobre el MIEMBRO, no sobre el campo que se
    edita: un admin de sucursal no puede modificar a un dueño (ni a otro
    admin) de NINGUNA forma, tampoco su foto. Sin este helper común, cada
    service tendría que reimplementar el mismo criterio y correría el riesgo
    de divergir (el hueco real que tenía `member_set_avatar`/
    `member_clear_avatar` antes de este fix: no validaban nada de sucursal ni
    de rol del target).

    No-op si `actor_membership` es owner (puede todo, incluidos otros owners
    y admins — sin cambios). Si no (jerarquía de roles, decisión del dueño
    2026-07-16):
        - `membership` debe caer en `allowed_sucursales` del actor, o
          ValidationError (fuera de alcance).
        - si `membership.role` NO es un rol operacional (es decir, ya es
          OWNER o ADMIN) → ValidationError (nunca se modifica a un dueño ni
          a otro admin).
    """
    if actor_membership.role == TenantMembership.Role.OWNER:
        return

    actor_allowed_ids = list(
        allowed_sucursales(user=actor, tenant=membership.tenant).values_list("id", flat=True)
    )
    if not membership_in_sucursal_scope(membership=membership, sucursal_ids=actor_allowed_ids):
        raise ValidationError("No tienes acceso a este miembro.")
    if membership.role not in TenantMembership.operational_roles():
        raise ValidationError("No puedes modificar a un dueño o a un administrador.")


def _ensure_role_grantable(*, actor_is_owner: bool, role: Optional[str]) -> None:
    """Anti-escalada: un actor NO owner solo puede otorgar roles operacionales.

    Compartido por `member_create` (rol del nuevo miembro) y `member_update`
    (rol pedido para un miembro existente). Jerarquía de roles (decisión del
    dueño 2026-07-16): nadie que no sea owner puede crear ni ascender a
    alguien a `admin` u `owner` — nadie otorga un poder que él mismo no
    tiene.

    No-op si `actor_is_owner` es True (sin restricción) o si `role` es None
    (no se está pidiendo cambiar el rol).

    Raises:
        ValidationError: `role` no es None, el actor no es owner, y `role`
            no es un rol operacional.
    """
    if actor_is_owner or role is None:
        return
    if role not in TenantMembership.operational_roles():
        raise ValidationError("No tienes permiso para asignar ese rol.")


def member_create(
    *,
    tenant: Tenant,
    actor: "User",  # type: ignore[valid-type]
    email: str,
    first_name: str,
    last_name: str,
    password: str,
    role: str,
    active_sucursal_id: Optional[uuid.UUID] = None,
) -> TenantMembership:
    """Crea un miembro de la clínica: cuenta de usuario + membresía con rol.

    Valida:
    - rol válido.
    - anti-escalada (jerarquía de roles, decisión del dueño 2026-07-16): si
      `actor` NO es owner, solo puede crear un miembro con un rol
      OPERACIONAL (`TenantMembership.operational_roles()`) — nunca `admin`
      ni `owner` (nadie otorga un poder que él mismo no tiene).
    - email no registrado (no se reutiliza ni se "secuestra" una cuenta existente).
    - contraseña robusta (validadores de Django: longitud, no común, no numérica).

    Bootstrap de un tenant recién creado (excepción explícita, NO un hueco):
    `apps.plataforma.services.tenant_and_owner_create` llama a este service
    para dar de alta al PRIMER miembro (el owner) de una clínica que
    `plataforma` acaba de crear. Ese `actor` es staff de plataforma
    (super_admin/sales) y por diseño NUNCA tiene `TenantMembership` en
    ninguna clínica (opera cross-tenant vía `is_platform_staff`/
    `platform_role`, ya autorizado aguas arriba en `tenant_and_owner_create`).
    Por eso, si `actor` NO tiene membresía activa en `tenant`, SOLO se
    permite continuar (tratándolo como owner, sin restricción de sede) si
    el tenant AÚN NO tiene NINGÚN miembro y el rol solicitado es
    exactamente "owner" — el primer miembro de una clínica siempre es su
    dueño. Cualquier otro caso (tenant con miembros existentes y un actor
    ajeno, o un actor ajeno pidiendo un rol distinto de owner) se rechaza:
    esta excepción no debe convertirse en una puerta alterna para crear
    miembros sin tener membresía propia.

    Asignación de sede del nuevo miembro (multi-sede — D2 del plan de
    sucursales: "el personal que da de alta un admin de sucursal cae en SU
    sede, nunca en la default ajena"), por precedencia:
        1. `active_sucursal_id` explícito (sede activa del selector en la
           vista) → esa, validada contra `allowed_sucursales(actor, tenant)`.
        2. Sin sede activa y `actor` NO es owner → TODAS las sedes
           permitidas del actor (`allowed_sucursales`).
        3. Sin sede activa y `actor` ES owner (incluido el bootstrap) → sin
           asignación (el miembro cae en la sede `is_default` del tenant vía
           el fallback de `allowed_sucursales` — comportamiento de hoy, sin
           cambios).

    Args:
        tenant:             Clínica a la que se agrega el miembro.
        actor:              Usuario que realiza el alta (auditoría + autorización).
        email:              Correo del nuevo miembro (será su usuario de acceso).
        first_name:         Nombre(s).
        last_name:          Apellidos.
        password:           Contraseña inicial (debe pasar los validadores).
        role:               Rol clínico (owner/admin/doctor/nurse/reception/finance/readonly).
        active_sucursal_id: Sede activa resuelta por la vista (header
                            X-Sucursal-Id), o None si no hay ninguna.

    Returns:
        La TenantMembership creada (con su user).

    Raises:
        ValidationError: rol inválido, actor sin membresía activa (y sin
            calificar para el bootstrap), actor no-owner intentando crear un
            owner, email ya registrado, contraseña débil, o
            `active_sucursal_id` fuera del alcance del actor.
    """
    if role not in _VALID_ROLES:
        raise ValidationError(f"Rol inválido '{role}'.")

    actor_membership = (
        TenantMembership.objects.filter(
            user=actor, tenant=tenant, is_active=True, deleted_at__isnull=True
        )
        .order_by("created_at")
        .first()
    )

    if actor_membership is not None:
        actor_is_owner = actor_membership.role == TenantMembership.Role.OWNER
        _ensure_role_grantable(actor_is_owner=actor_is_owner, role=role)
    elif (
        role == TenantMembership.Role.OWNER
        and not TenantMembership.objects.filter(tenant=tenant).exists()
    ):
        # Bootstrap: primer miembro (owner) de un tenant recién creado por
        # plataforma (ver docstring). Se comporta como owner: sin
        # restricción de sede.
        actor_is_owner = True
    else:
        raise ValidationError("No tienes una membresía activa en esta clínica.")

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

    # Resolución de sede(s) a asignar al nuevo miembro (ver docstring).
    sucursal_assignment_ids: list[uuid.UUID]
    if active_sucursal_id is not None:
        if not (
            allowed_sucursales(user=actor, tenant=tenant).filter(id=active_sucursal_id).exists()
        ):
            raise ValidationError("No tienes acceso a esa sucursal para asignar al nuevo miembro.")
        sucursal_assignment_ids = [active_sucursal_id]
    elif not actor_is_owner:
        sucursal_assignment_ids = list(
            allowed_sucursales(user=actor, tenant=tenant).values_list("id", flat=True)
        )
    else:
        sucursal_assignment_ids = []

    with transaction.atomic():
        user.set_password(password)
        user.save()
        membership = TenantMembership.objects.create(
            user=user,
            tenant=tenant,
            role=role,
            is_active=True,
        )
        if sucursal_assignment_ids:
            MembershipSucursal.all_objects.bulk_create(
                [
                    MembershipSucursal(
                        tenant=tenant,
                        created_by=actor,
                        membership=membership,
                        sucursal_id=sucursal_id,
                    )
                    for sucursal_id in sucursal_assignment_ids
                ]
            )

    audit_record(
        action=ActionType.MEMBER_CREATE,
        resource_type="TenantMembership",
        actor=actor,
        tenant=tenant,
        resource_id=membership.id,
        resource_repr=normalized_email,
        metadata={
            "role": role,
            "sucursal_ids": [str(sucursal_id) for sucursal_id in sucursal_assignment_ids],
        },
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

    Autorización por sucursal (defensa en profundidad — la vista ya acota la
    membresía resuelta a `allowed_sucursales`, aplica el 404 por rol no
    operacional descrito en `apps.tenancy.views._member_get_or_404`, y
    devuelve 404 fuera de alcance; este chequeo revalida por si el service se
    invoca desde otro lugar, p. ej. tests o comandos):
        - `actor` debe tener una membresía activa en el tenant de `membership`.
        - owner del tenant → puede modificar a CUALQUIERA, incluido otro
          owner (D3: el owner puede resetear la contraseña de otro owner).
        - cualquier otro rol (admin incluido) — jerarquía de roles, decisión
          del dueño 2026-07-16:
            * `membership` debe caer en `allowed_sucursales` del actor, o
              ValidationError.
            * si `membership.role` NO es un rol operacional (ya es OWNER o
              ADMIN) → ValidationError (nunca se modifica a un dueño ni a
              otro admin, ni su contraseña, ni bloqueo, ni nombre).
            * si se pide un `role` que NO es operacional (`"owner"` o
              `"admin"`) → ValidationError (anti-escalada: nadie otorga un
              poder que él mismo no tiene).

    Args:
        membership: Membresía a actualizar (recuperada por el selector).
        actor:      Usuario que realiza el cambio (auditoría y autorización).
        first_name: Nuevo nombre, opcional.
        last_name:  Nuevos apellidos, opcional.
        role:       Nuevo rol, opcional.
        blocked:    Estado de bloqueo, opcional.

    Returns:
        La membresía actualizada.

    Raises:
        ValidationError: actor sin membresía activa, rol inválido, intento
            de autobloqueo, o cualquiera de las reglas de autorización de
            sucursal/anti-escalada descritas arriba.
    """
    actor_membership = _resolve_actor_membership(actor=actor, tenant=membership.tenant)
    _authorize_write_on_member(
        actor=actor, actor_membership=actor_membership, membership=membership
    )
    _ensure_role_grantable(
        actor_is_owner=actor_membership.role == TenantMembership.Role.OWNER,
        role=role,
    )

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
    """Asigna (o reemplaza) la foto de un miembro. La imagen ya viene validada por la vista.

    Autorización por sucursal y jerarquía de roles (cierre de hueco — ver
    `_authorize_write_on_member`): un admin de sucursal no puede subir/
    reemplazar la foto de un dueño, de otro admin, ni de un miembro fuera de
    sus sedes permitidas — solo de personal con rol operacional.
    """
    actor_membership = _resolve_actor_membership(actor=actor, tenant=membership.tenant)
    _authorize_write_on_member(
        actor=actor, actor_membership=actor_membership, membership=membership
    )

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
    """Elimina la foto de un miembro.

    Autorización por sucursal y jerarquía de roles (cierre de hueco — ver
    `_authorize_write_on_member`): un admin de sucursal no puede borrar la
    foto de un dueño, de otro admin, ni de un miembro fuera de sus sedes
    permitidas — solo de personal con rol operacional.
    """
    actor_membership = _resolve_actor_membership(actor=actor, tenant=membership.tenant)
    _authorize_write_on_member(
        actor=actor, actor_membership=actor_membership, membership=membership
    )

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
