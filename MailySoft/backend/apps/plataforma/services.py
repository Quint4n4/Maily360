"""
Services del panel interno de plataforma (escrituras cross-tenant).

Principios:
  - Keyword-only args siempre.
  - Registran auditoría con audit_record() — tenant=None porque la acción
    es de plataforma (no de una clínica específica), pero se incluye en metadata.
  - Validan el estado de destino antes de mutar.
  - Usan save(update_fields=[...]) para commits mínimos y seguros.

SEGURIDAD ESPECIAL — tenant_and_owner_create:
  - La contraseña temporal se genera en memoria con `secrets`, NUNCA se persiste
    ni aparece en logs, auditoría ni metadata.
  - La función _generar_password_temporal() usa únicamente `secrets.choice` para
    garantizar entropía criptográficamente segura.
  - La transacción es atómica: si cualquier paso falla, ni el Tenant ni el User
    quedan en base de datos (no orphans).
  - set_current_tenant / clear_current_tenant se usan para que los models
    TenantAware de semilla se creen con el tenant correcto. El finally garantiza
    que el contexto se limpia incluso si hay excepciones.
"""

import logging
import secrets
from datetime import timedelta
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.text import slugify
from django.utils.timezone import now

from apps.agenda.services import appointment_type_create
from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.authn.models import User
from apps.core.tenant_context import clear_current_tenant, set_current_tenant
from apps.personal.services import consultorio_create
from apps.tenancy.models import Tenant
from apps.tenancy.services import member_create

logger = logging.getLogger("apps.plataforma.services")

# Transiciones de estado permitidas:
# - 'active'    ← cualquier estado (reactivar trial o suspended).
# - 'suspended' ← cualquier estado (suspender trial o active).
# NO se permite cambiar a 'trial' desde plataforma (trial es el estado inicial
# que se asigna al crear la clínica).
_ALLOWED_TARGET_STATUSES: frozenset[str] = frozenset(
    {Tenant.Status.ACTIVE, Tenant.Status.SUSPENDED}
)

# Roles de plataforma autorizados a cambiar el estado de una clínica.
# Espejo de _PLATFORM_ROLES_MANAGE_CLINICS en apps/core/permissions.py.
_ALLOWED_ACTOR_ROLES: frozenset[str] = frozenset(
    {User.PlatformRole.SUPER_ADMIN, User.PlatformRole.SALES}
)

# ---------------------------------------------------------------------------
# Alfabeto de la contraseña temporal (sin caracteres ambiguos: 0/O, 1/l/I).
# ---------------------------------------------------------------------------
_PWD_UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"   # sin I, O
_PWD_LOWER = "abcdefghjkmnpqrstuvwxyz"    # sin i, l, o
_PWD_DIGITS = "23456789"                   # sin 0, 1
_PWD_SYMBOLS = "!@#$%^&*"                 # seguros en todos los sistemas
_PWD_ALL = _PWD_UPPER + _PWD_LOWER + _PWD_DIGITS + _PWD_SYMBOLS


def _generar_password_temporal() -> str:
    """Genera una contraseña temporal criptográficamente segura.

    Garantiza que la contraseña pase los validadores de Django:
    - Mínimo 10 caracteres (producimos 16).
    - No completamente numérica (mezcla letras y símbolos).
    - No está en la lista de contraseñas comunes (es aleatoria con entropía alta).

    La función garantiza al menos 1 carácter de cada clase (mayúscula, minúscula,
    dígito, símbolo) antes de completar el resto aleatoriamente, luego baraja el
    resultado para que el orden no sea predecible.

    Returns:
        Contraseña temporal de 16 caracteres.

    NUNCA loguear ni persistir el valor devuelto.
    """
    # Garantizar al menos un char de cada clase requerida.
    obligatorios: list[str] = [
        secrets.choice(_PWD_UPPER),
        secrets.choice(_PWD_UPPER),
        secrets.choice(_PWD_LOWER),
        secrets.choice(_PWD_LOWER),
        secrets.choice(_PWD_DIGITS),
        secrets.choice(_PWD_DIGITS),
        secrets.choice(_PWD_SYMBOLS),
        secrets.choice(_PWD_SYMBOLS),
    ]
    # Completar hasta 16 caracteres con caracteres del alfabeto completo.
    resto: list[str] = [secrets.choice(_PWD_ALL) for _ in range(8)]
    todos: list[str] = obligatorios + resto
    # Barajar con secrets para que el orden no sea predecible.
    # secrets.SystemRandom es criptográficamente seguro en todos los OS.
    secretos_rng = secrets.SystemRandom()
    secretos_rng.shuffle(todos)
    return "".join(todos)


def _slug_unico(name: str) -> str:
    """Genera un slug único para el nombre de la clínica.

    Usa slugify de Django y agrega sufijo -2, -3, ... hasta encontrar
    uno libre. Hace N queries (una por intento), pero solo ocurre al crear
    una clínica (evento raro) y el límite práctico es muy bajo.

    Args:
        name: Nombre comercial de la clínica.

    Returns:
        Slug único que no existe aún en Tenant.objects.
    """
    base_slug = slugify(name)
    if not base_slug:
        # Nombre imposible de slugificar (ej: solo caracteres especiales).
        base_slug = "clinica"

    candidate = base_slug
    counter = 2
    while Tenant.objects.filter(slug=candidate).exists():
        candidate = f"{base_slug}-{counter}"
        counter += 1
    return candidate


def tenant_and_owner_create(
    *,
    actor: User,
    name: str,
    owner_email: str,
    owner_first_name: str,
    owner_last_name: str,
    timezone: str = "America/Mexico_City",
    trial_days: int = 60,
) -> dict[str, Any]:
    """Crea una clínica nueva (Tenant) con su dueño y datos semilla.

    Esta es la operación más privilegiada de la plataforma. Valida en
    el servicio que el actor sea staff de plataforma con rol autorizado
    (defensa en profundidad: la vista ya comprueba PlatformClinicWritePermission,
    pero el service puede llamarse desde management commands / seeds).

    Proceso dentro de la transacción atómica:
    1. Genera slug único para el nombre.
    2. Genera contraseña temporal con entropía criptográfica.
    3. Crea el Tenant con status=TRIAL y trial_ends_at=now()+trial_days.
    4. Activa el contexto de tenant para que los modelos TenantAware se creen
       con el FK correcto.
    5. Crea el owner vía member_create (valida email único + password Django).
    6. Crea datos semilla: 1 consultorio + 3 tipos de cita por defecto.
    7. Registra TENANT_CREATE en auditoría (SIN contraseña en metadata).

    La contraseña temporal SOLO se devuelve en el dict resultado para que
    la vista la muestre una vez. NUNCA se persiste ni se loguea.

    Args:
        actor:            Usuario del equipo de plataforma (super_admin o sales).
        name:             Nombre comercial de la clínica.
        owner_email:      Email del dueño (será su usuario de acceso).
        owner_first_name: Nombre(s) del dueño.
        owner_last_name:  Apellidos del dueño.
        timezone:         Zona horaria IANA de la clínica (default: America/Mexico_City).
        trial_days:       Duración del periodo de prueba en días (default 60).

    Returns:
        Dict con:
            - tenant (Tenant): la clínica creada.
            - owner (TenantMembership): membresía del dueño.
            - temporary_password (str): contraseña a mostrar UNA VEZ.

    Raises:
        ValidationError: si el actor no está autorizado, el email ya existe,
                         o la contraseña generada no pasa los validadores de Django.
    """
    if not getattr(actor, "is_platform_staff", False):
        raise ValidationError(
            "Solo el staff de plataforma puede crear clínicas."
        )
    if getattr(actor, "platform_role", "") not in _ALLOWED_ACTOR_ROLES:
        raise ValidationError(
            f"Rol de plataforma '{getattr(actor, 'platform_role', '')}' "
            "no autorizado para crear clínicas."
        )

    # Generar slug y contraseña ANTES de la transacción para no contaminarna
    # con errores de validación lógica (el slug puede variar si hay concurrencia,
    # pero en la práctica es un evento muy raro y el retry es simple).
    slug = _slug_unico(name)
    password_temporal = _generar_password_temporal()

    with transaction.atomic():
        tenant = Tenant.objects.create(
            name=name,
            slug=slug,
            status=Tenant.Status.TRIAL,
            trial_ends_at=now() + timedelta(days=trial_days),
            timezone=timezone,
        )

        # Activar el contexto de tenant para que los insertos de modelos
        # TenantAware funcionen con el FK correcto (TenantManager lo requiere).
        set_current_tenant(tenant)
        try:
            # Crear el owner como miembro con rol "owner".
            owner = member_create(
                tenant=tenant,
                actor=actor,
                email=owner_email,
                first_name=owner_first_name,
                last_name=owner_last_name,
                password=password_temporal,
                role="owner",
            )

            # -----------------------------------------------------------------
            # Datos semilla: consultorio y tipos de cita por defecto.
            # El user de la semilla es el owner recién creado.
            # -----------------------------------------------------------------
            consultorio_create(
                tenant=tenant,
                user=owner.user,
                name="Consultorio 1",
                location="",
                color_hex="#3B82F6",
            )

            for tipo_nombre in ("Consulta", "Primera vez", "Seguimiento"):
                appointment_type_create(
                    tenant=tenant,
                    user=owner.user,
                    name=tipo_nombre,
                )

        finally:
            # SIEMPRE limpiar el contexto de tenant, incluso si hubo excepción.
            # Si hay excepción, la transacción se revierte y el tenant no queda
            # en BD, pero el thread-local sí quedaría sucio sin este finally.
            clear_current_tenant()

    # Auditoría FUERA de la transacción (absorbe errores según audit_record).
    # IMPORTANTE: metadata NO incluye la contraseña temporal.
    audit_record(
        action=ActionType.TENANT_CREATE,
        resource_type="Tenant",
        actor=actor,
        tenant=None,  # evento de plataforma, no de clínica
        resource_id=tenant.id,
        resource_repr=str(tenant),
        description=(
            f"Clínica '{tenant.name}' (slug='{tenant.slug}') creada "
            f"con trial de {trial_days} días "
            f"por {actor.email} ({getattr(actor, 'platform_role', '')})."
        ),
        actor_role=getattr(actor, "platform_role", ""),
        metadata={
            "tenant_id": str(tenant.id),
            "tenant_slug": tenant.slug,
            "trial_days": trial_days,
            "timezone": timezone,
            # NO incluir PII (owner_email) ni nada de contraseña. El alta del
            # dueño queda trazada por su propio registro MEMBER_CREATE.
        },
    )

    logger.info(
        "tenant_and_owner_create: tenant=%s slug=%s por actor_id=%s",
        tenant.id,
        tenant.slug,
        actor.id,
    )

    return {
        "tenant": tenant,
        "owner": owner,
        "temporary_password": password_temporal,
    }


def tenant_set_status(
    *,
    tenant: Tenant,
    actor: User,
    status: str,
) -> Tenant:
    """Cambia el estado de una clínica (suspender o reactivar).

    Registra el cambio en la bitácora de auditoría con ActionType.TENANT_STATUS_CHANGE.
    La vista ya restringe el acceso (PlatformClinicWritePermission); este servicio
    REVALIDA el rol del actor como defensa en profundidad, por si se le llama
    desde una shell, un management command o una tarea fuera del flujo HTTP.

    Args:
        tenant: Instancia de Tenant a modificar.
        actor:  Usuario del equipo de plataforma que realiza el cambio.
        status: Estado de destino ('active' o 'suspended').

    Returns:
        La instancia de Tenant actualizada.

    Raises:
        ValidationError: Si el actor no está autorizado o el estado es inválido.
    """
    if not getattr(actor, "is_platform_staff", False):
        raise ValidationError(
            "Solo el staff de plataforma puede cambiar el estado de una clínica."
        )
    if getattr(actor, "platform_role", "") not in _ALLOWED_ACTOR_ROLES:
        raise ValidationError(
            f"Rol de plataforma '{getattr(actor, 'platform_role', '')}' "
            "no autorizado para cambiar el estado de una clínica."
        )

    if status not in _ALLOWED_TARGET_STATUSES:
        raise ValidationError(
            f"Estado '{status}' no permitido. "
            f"Valores válidos: {', '.join(sorted(_ALLOWED_TARGET_STATUSES))}."
        )

    old_status = tenant.status
    tenant.status = status
    tenant.save(update_fields=["status", "updated_at"])

    audit_record(
        action=ActionType.TENANT_STATUS_CHANGE,
        resource_type="Tenant",
        actor=actor,
        tenant=None,  # evento de plataforma, no de clínica
        resource_id=tenant.id,
        resource_repr=str(tenant),
        description=(
            f"Estado de la clínica '{tenant.name}' cambiado "
            f"de '{old_status}' a '{status}' "
            f"por {actor.email} ({getattr(actor, 'platform_role', '')})."
        ),
        actor_role=getattr(actor, "platform_role", ""),
        metadata={
            "tenant_id": str(tenant.id),
            "tenant_slug": tenant.slug,
            "old_status": old_status,
            "new_status": status,
        },
    )

    logger.info(
        "tenant_set_status: tenant=%s slug=%s %s→%s por actor=%s",
        tenant.id,
        tenant.slug,
        old_status,
        status,
        actor.email,
    )

    return tenant
