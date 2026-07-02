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
import uuid
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils.text import slugify
from django.utils.timezone import now

from apps.agenda.services import appointment_type_create
from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.authn.models import User
from apps.clinica.services import seed_system_patient_categories
from apps.core.permissions import _PLATFORM_ROLES_SUPER_ADMIN_ONLY
from apps.core.tenant_context import clear_current_tenant, set_current_tenant
from apps.personal.services import consultorio_create
from apps.plataforma.selectors import plan_get
from apps.tenancy.models import Plan, Tenant, TenantSubscription
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
_PWD_UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # sin I, O
_PWD_LOWER = "abcdefghjkmnpqrstuvwxyz"  # sin i, l, o
_PWD_DIGITS = "23456789"  # sin 0, 1
_PWD_SYMBOLS = "!@#$%^&*"  # seguros en todos los sistemas
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


def _slug_unico_generico(*, name: str, fallback: str, existe: Callable[[str], bool]) -> str:
    """Helper genérico de slug único, parametrizado por una función de existencia.

    Generaliza el mismo patrón que `_slug_unico` (slugify + sufijo -2, -3, ...)
    para reutilizarlo en modelos distintos a Tenant (aquí: Plan) sin duplicar
    la lógica de generación. `_slug_unico` se deja intacta (no se toca código
    que ya funciona) porque tiene su propio fallback ("clinica") y su propio
    querier fijo (Tenant.objects); este helper es la versión reutilizable para
    el resto de la plataforma.

    Args:
        name:     Texto de origen para slugificar (ej. nombre del plan).
        fallback: Slug base a usar si `slugify(name)` da cadena vacía.
        existe:   Callable(candidate: str) -> bool que indica si el slug ya
                  existe en el modelo destino.

    Returns:
        Slug único que `existe()` confirma como libre.
    """
    base_slug = slugify(name) or fallback
    candidate = base_slug
    counter = 2
    while existe(candidate):
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
        raise ValidationError("Solo el staff de plataforma puede crear clínicas.")
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

            # Etiquetas de sistema (Favorito y VIP) para clasificar pacientes.
            seed_system_patient_categories(tenant=tenant)

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
        raise ValidationError("Solo el staff de plataforma puede cambiar el estado de una clínica.")
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


def tenant_subscription_set(
    *,
    tenant: Tenant,
    actor: User,
    plan_id: uuid.UUID,
    billing_cycle: str,
    current_period_end: date,
) -> TenantSubscription:
    """Crea o actualiza la suscripción (OneToOne) de una clínica a un plan.

    Idempotente en el sentido de "asignar de nuevo": si el tenant ya tenía
    suscripción, esta función la actualiza en el sitio (update_or_create)
    en lugar de crear una fila duplicada — TenantSubscription.tenant es
    OneToOne, así que un segundo INSERT violaría la constraint de todos modos;
    se prefiere el update explícito para poder registrar plan_anterior→nuevo
    en la auditoría.

    Args:
        tenant:             Clínica a la que se asigna/cambia el plan.
        actor:              Usuario de plataforma que realiza el cambio (auditoría).
        plan_id:             UUID del Plan a asignar. Debe existir y estar activo.
        billing_cycle:       'monthly' | 'annual'.
        current_period_end:  Fecha de fin del periodo. Debe ser futura.

    Returns:
        La TenantSubscription creada o actualizada.

    Raises:
        ValidationError: actor no autorizado, plan inexistente/inactivo, o
            current_period_end no es una fecha futura.
    """
    if not getattr(actor, "is_platform_staff", False):
        raise ValidationError("Solo el staff de plataforma puede gestionar suscripciones.")
    if getattr(actor, "platform_role", "") not in _ALLOWED_ACTOR_ROLES:
        raise ValidationError(
            f"Rol de plataforma '{getattr(actor, 'platform_role', '')}' "
            "no autorizado para gestionar suscripciones."
        )

    try:
        plan = Plan.objects.get(id=plan_id)
    except Plan.DoesNotExist as exc:
        raise ValidationError("El plan indicado no existe.") from exc

    if not plan.is_active:
        raise ValidationError("No se puede asignar un plan inactivo.")

    if billing_cycle not in TenantSubscription.BillingCycle.values:
        raise ValidationError(f"Ciclo de facturación inválido: '{billing_cycle}'.")

    if current_period_end <= now().date():
        raise ValidationError("La fecha de fin de periodo debe ser futura.")

    with transaction.atomic():
        existing: TenantSubscription | None = TenantSubscription.objects.filter(
            tenant=tenant
        ).first()
        old_plan_slug = existing.plan.slug if existing else None
        old_billing_cycle = existing.billing_cycle if existing else None

        subscription, _created = TenantSubscription.objects.update_or_create(
            tenant=tenant,
            defaults={
                "plan": plan,
                "billing_cycle": billing_cycle,
                "current_period_end": current_period_end,
                # Nueva fecha futura → resetea la idempotencia del aviso de
                # vencimiento (D-3 del encargo: extender/renovar debe poder
                # volver a avisar en el futuro).
                "period_expired_notified_at": None,
            },
        )

    audit_record(
        action=ActionType.SUBSCRIPTION_CHANGE,
        resource_type="TenantSubscription",
        actor=actor,
        tenant=None,  # evento de plataforma, no de clínica
        resource_id=subscription.id,
        resource_repr=str(subscription),
        description=(
            f"Suscripción de la clínica '{tenant.name}' cambiada "
            f"de plan '{old_plan_slug or '(sin plan)'}' a '{plan.slug}' "
            f"({billing_cycle}, vence {current_period_end}) "
            f"por {actor.email} ({getattr(actor, 'platform_role', '')})."
        ),
        actor_role=getattr(actor, "platform_role", ""),
        metadata={
            "tenant_id": str(tenant.id),
            "tenant_slug": tenant.slug,
            "old_plan_slug": old_plan_slug,
            "new_plan_slug": plan.slug,
            "old_billing_cycle": old_billing_cycle,
            "new_billing_cycle": billing_cycle,
            "current_period_end": current_period_end.isoformat(),
        },
    )

    logger.info(
        "tenant_subscription_set: tenant=%s plan=%s ciclo=%s vence=%s por actor=%s",
        tenant.id,
        plan.slug,
        billing_cycle,
        current_period_end,
        actor.email,
    )

    return subscription


# ---------------------------------------------------------------------------
# Catálogo de planes — alta y edición (Fase 3.1)
# ---------------------------------------------------------------------------

# Campos inmutables del servicio de update: identidad, timestamps y el slug
# (estable a propósito — lo referencian TenantSubscription y el frontend).
_PLAN_IMMUTABLE_FIELDS: frozenset[str] = frozenset(
    {"id", "slug", "tenant", "tenant_id", "created_at", "updated_at", "deleted_at"}
)

# Campos editables por plan_update (allowlist explícita, no blocklist: un
# campo nuevo del modelo Plan queda fuera de PATCH hasta que se agregue aquí
# a propósito).
_PLAN_UPDATABLE_FIELDS: frozenset[str] = frozenset(
    {"name", "description", "price_monthly", "is_featured", "features", "is_active", "order"}
)


def _validar_campos_plan(fields: dict[str, Any]) -> None:
    """Valida name/price_monthly/features para plan_create y plan_update.

    Solo valida los campos presentes en `fields` — permite validación
    parcial en PATCH (no exige que todos los campos estén presentes).

    Args:
        fields: subconjunto de campos que se van a persistir.

    Raises:
        ValidationError: price_monthly negativo, name vacío, o features no
            es una lista de strings no vacíos.
    """
    if "name" in fields and not str(fields["name"]).strip():
        raise ValidationError("El nombre del plan no puede estar vacío.")

    if "price_monthly" in fields and fields["price_monthly"] is not None:
        if fields["price_monthly"] < 0:
            raise ValidationError("El precio mensual no puede ser negativo.")

    if "features" in fields and fields["features"] is not None:
        features = fields["features"]
        if not isinstance(features, list):
            raise ValidationError("features debe ser una lista de strings.")
        for item in features:
            if not isinstance(item, str) or not item.strip():
                raise ValidationError("Cada elemento de features debe ser un string no vacío.")


def _validar_actor_plan_write(actor: User) -> None:
    """Revalida en el service que el actor sea super_admin (defensa en profundidad).

    Espeja PlatformPlanWritePermission (apps/core/permissions.py), incluyendo
    su misma fuente de roles (_PLATFORM_ROLES_SUPER_ADMIN_ONLY, importada de
    apps.core.permissions — NO se duplica el frozenset aquí). La vista ya
    exige ese permiso, pero el service puede invocarse desde management
    commands/seeds/Celery sin pasar por HTTP, así que se revalida — mismo
    patrón que _ALLOWED_ACTOR_ROLES en tenant_and_owner_create /
    tenant_subscription_set (esos dos SÍ mantienen su propio frozenset
    porque su conjunto de roles, super_admin+sales, no coincide con ningún
    otro permiso existente; aquí el conjunto es idéntico al de
    PlatformStaffListPermission, así que reutilizar es lo correcto).

    Raises:
        ValidationError: actor no es staff de plataforma o su platform_role
            no es super_admin.
    """
    if not getattr(actor, "is_platform_staff", False):
        raise ValidationError("Solo el staff de plataforma puede gestionar el catálogo de planes.")
    if getattr(actor, "platform_role", "") not in _PLATFORM_ROLES_SUPER_ADMIN_ONLY:
        raise ValidationError(
            f"Rol de plataforma '{getattr(actor, 'platform_role', '')}' "
            "no autorizado: solo super_admin edita el catálogo de planes."
        )


def plan_create(
    *,
    actor: User,
    name: str,
    price_monthly: Decimal,
    description: str = "",
    is_featured: bool = False,
    features: list[str] | None = None,
    is_active: bool = True,
    order: int | None = None,
) -> Plan:
    """Crea un plan nuevo en el catálogo global de suscripción.

    Solo super_admin (revalidado aquí, defensa en profundidad — ver
    _validar_actor_plan_write). El slug se genera de `name` con slugify y
    sufijo -2/-3/... si ya existe (reutiliza _slug_unico_generico, el mismo
    algoritmo que _slug_unico usa para Tenant). Si `order` no se especifica,
    se asigna al final del catálogo (max(order) + 1).

    Args:
        actor:         Usuario de plataforma que crea el plan (auditoría).
        name:          Nombre comercial del plan.
        price_monthly: Precio mensual en MXN. Debe ser >= 0.
        description:   Descripción comercial breve (default "").
        is_featured:   Si se destaca en la vitrina (default False).
        features:      Lista de strings no vacíos con las características
                       incluidas (default: lista vacía).
        is_active:     Si el plan queda activo/asignable de inmediato
                       (default True).
        order:         Orden de despliegue. Si es None, se asigna
                       max(order actual) + 1.

    Returns:
        El Plan creado.

    Raises:
        ValidationError: actor no autorizado, price_monthly negativo, name
            vacío, o features con formato inválido.
    """
    _validar_actor_plan_write(actor)

    features_norm: list[str] = list(features) if features is not None else []
    _validar_campos_plan({"name": name, "price_monthly": price_monthly, "features": features_norm})

    slug = _slug_unico_generico(
        name=name,
        fallback="plan",
        existe=lambda candidate: Plan.objects.filter(slug=candidate).exists(),
    )

    with transaction.atomic():
        if order is None:
            max_order = Plan.objects.aggregate(m=models.Max("order"))["m"]
            order = (max_order + 1) if max_order is not None else 0

        plan = Plan.objects.create(
            slug=slug,
            name=name,
            description=description,
            price_monthly=price_monthly,
            is_featured=is_featured,
            features=features_norm,
            is_active=is_active,
            order=order,
        )

    audit_record(
        action=ActionType.PLAN_CREATE,
        resource_type="Plan",
        actor=actor,
        tenant=None,  # catálogo global, no evento de una clínica
        resource_id=plan.id,
        resource_repr=str(plan),
        description=(
            f"Plan '{plan.name}' ({plan.slug}) creado por {actor.email} "
            f"({getattr(actor, 'platform_role', '')}), precio {plan.price_monthly}."
        ),
        actor_role=getattr(actor, "platform_role", ""),
        metadata={
            "slug": plan.slug,
            "price": str(plan.price_monthly),
        },
    )

    logger.info(
        "plan_create: plan=%s slug=%s precio=%s por actor=%s",
        plan.id,
        plan.slug,
        plan.price_monthly,
        actor.email,
    )

    return plan


def plan_update(*, actor: User, plan_id: uuid.UUID, **fields: Any) -> Plan:
    """Actualiza un subconjunto de campos de un plan existente.

    Solo super_admin (revalidado aquí, defensa en profundidad). El slug
    NUNCA se puede modificar por este servicio (es el identificador estable
    que usan TenantSubscription y el frontend) — está en
    _PLAN_IMMUTABLE_FIELDS.

    EXCEPCIÓN documentada a la regla general "is_active nunca en PATCH
    genérico": aquí SÍ se permite, a propósito. Plan no tiene delete físico
    (TenantSubscription.plan es PROTECT) y el dueño pidió explícitamente
    poder desactivar un plan retirándolo del catálogo sin necesidad de un
    endpoint separado de activar/desactivar. No hay ambigüedad de "estado de
    negocio complejo" aquí: is_active de Plan es un simple flag de catálogo
    (visible/no-asignable), no un ciclo de vida con transiciones que validar.

    Args:
        actor:    Usuario de plataforma que edita el plan (auditoría).
        plan_id:  UUID del plan a actualizar.
        **fields: subconjunto de {name, description, price_monthly,
            is_featured, features, is_active, order}.

    Returns:
        El Plan actualizado.

    Raises:
        ValidationError: actor no autorizado, campo inmutable/desconocido
            en fields, o valores inválidos (precio negativo, features mal
            formado, name vacío).
        Plan.DoesNotExist: no existe un plan con ese id (→ 404 en la vista).
    """
    _validar_actor_plan_write(actor)

    bad_immutable = set(fields) & _PLAN_IMMUTABLE_FIELDS
    if bad_immutable:
        raise ValidationError(
            f"No se pueden modificar los campos: {', '.join(sorted(bad_immutable))}."
        )

    bad_unknown = set(fields) - _PLAN_UPDATABLE_FIELDS
    if bad_unknown:
        raise ValidationError(
            f"Campos no reconocidos para actualizar un plan: {', '.join(sorted(bad_unknown))}."
        )

    if "features" in fields and fields["features"] is not None:
        fields["features"] = list(fields["features"])

    _validar_campos_plan(fields)

    plan = plan_get(plan_id=plan_id)

    old_price = plan.price_monthly
    changed_fields = sorted(fields.keys())

    with transaction.atomic():
        for field_name, value in fields.items():
            setattr(plan, field_name, value)
        plan.save(update_fields=[*fields.keys(), "updated_at"])

    metadata: dict[str, Any] = {
        "slug": plan.slug,
        "cambios": changed_fields,
    }
    if "price_monthly" in fields and fields["price_monthly"] != old_price:
        metadata["price_old"] = str(old_price)
        metadata["price_new"] = str(plan.price_monthly)

    audit_record(
        action=ActionType.PLAN_UPDATE,
        resource_type="Plan",
        actor=actor,
        tenant=None,
        resource_id=plan.id,
        resource_repr=str(plan),
        description=(
            f"Plan '{plan.name}' ({plan.slug}) actualizado por {actor.email} "
            f"({getattr(actor, 'platform_role', '')}). Campos: {', '.join(changed_fields)}."
        ),
        actor_role=getattr(actor, "platform_role", ""),
        metadata=metadata,
    )

    logger.info(
        "plan_update: plan=%s slug=%s campos=%s por actor=%s",
        plan.id,
        plan.slug,
        changed_fields,
        actor.email,
    )

    return plan
