"""
Selectors de la app tenancy — lectura de miembros de la clínica.

Las membresías NO heredan de TenantAwareModel, así que el aislamiento por tenant
se aplica EXPLÍCITAMENTE filtrando por el tenant activo del request.

Scoping por sucursal (multi-sede — cierre del clúster F, ver
docs/design/sucursales-hallazgos-seguridad.md): `_sucursal_scope_q` es el
ÚNICO lugar que decide "¿esta membresía cae dentro de este conjunto de
sedes?" — lo reutilizan tanto `membership_list` (filtro de listado, vía
`sucursal_scope_ids`) como `membership_in_sucursal_scope`/
`membership_get_in_scope` (comprobación puntual de PERMISO, vía
`allowed_sucursales`, consumida por las vistas de detalle/avatar y por
`apps.tenancy.services.member_update`). Una sola fuente de verdad evita que
el criterio de "quién ve/toca a quién" diverja entre el listado y las
comprobaciones de autorización.
"""

import uuid

from django.db.models import Exists, OuterRef, Prefetch, Q, QuerySet

from apps.clinica.models import MembershipSucursal, Sucursal
from apps.core.tenant_context import get_current_tenant
from apps.tenancy.models import TenantMembership


def _sucursal_scope_q(*, tenant_id: uuid.UUID, sucursal_ids: list[uuid.UUID]) -> Q:
    """Q: ¿la membresía cae dentro de `sucursal_ids`? Helper compartido.

    Una TenantMembership "cae" dentro de un conjunto de sedes si:
        - su rol es OWNER (SIEMPRE, en cualquier scope — pertenece a todas
          las sedes por definición de negocio).
        - tiene AL MENOS UNA fila activa de MembershipSucursal y alguna de
          sus sedes asignadas está en `sucursal_ids`.
        - NO tiene ninguna fila activa de MembershipSucursal (nunca se le
          asignó nada) y la sucursal `is_default` del tenant está en
          `sucursal_ids` (mismo fallback anti-lockout que
          `apps.clinica.sucursal_scope.allowed_sucursales`).

    Compatibilidad retro: si el tenant NO tiene NINGUNA Sucursal configurada
    (ni activa ni inactiva — nunca adoptó multi-sede), el filtro es un no-op
    (`Q()` vacío, siempre verdadero) — mismo criterio que
    `apps.clinica.sucursal_scope.sucursal_scope_ids`. Sin este corte, un
    tenant sin sucursales perdería acceso a TODO su equipo (no existe ni
    `allowed_sucursales` ni sede default contra la cual comparar), rompiendo
    la operación normal de una clínica de una sola sede.

    Usa `Exists()` (subquery correlacionada) en lugar de un JOIN vía
    `sucursales_asignadas__...`: el JOIN reverso bypassa el manager de
    MembershipSucursal (no filtraría soft-deleted) y multiplicaría filas
    (exigiendo `.distinct()`). Con `Exists()` no hay multiplicación de filas
    ni N+1 — una sola query con subqueries correlacionadas por fila.

    Args:
        tenant_id:    Tenant de las membresías a evaluar.
        sucursal_ids: Conjunto de sedes contra las que se compara. Puede ser
                      vacío — en ese caso solo los OWNER (o el no-op de
                      compatibilidad retro) hacen match.

    Returns:
        Q combinable directamente en `.filter()`.
    """
    tenant_has_sucursales = Sucursal.all_objects.filter(
        tenant_id=tenant_id, deleted_at__isnull=True
    ).exists()
    if not tenant_has_sucursales:
        return Q()

    active_assignments = MembershipSucursal.all_objects.filter(
        membership_id=OuterRef("pk"), tenant_id=tenant_id, deleted_at__isnull=True
    )
    q = Q(role=TenantMembership.Role.OWNER) | Q(
        Exists(active_assignments.filter(sucursal_id__in=sucursal_ids))
    )

    default_id = (
        Sucursal.all_objects.filter(tenant_id=tenant_id, is_default=True, deleted_at__isnull=True)
        .values_list("id", flat=True)
        .first()
    )
    if default_id is not None and default_id in sucursal_ids:
        q |= ~Q(Exists(active_assignments))

    return q


def membership_in_sucursal_scope(
    *, membership: TenantMembership, sucursal_ids: list[uuid.UUID]
) -> bool:
    """¿`membership` cae dentro de `sucursal_ids`? Comprobación puntual.

    Mismo criterio EXACTO que `membership_list(sucursal_ids=...)` (comparten
    `_sucursal_scope_q`) — así el filtro de listado y las comprobaciones de
    autorización puntuales (`apps.tenancy.services.member_update`,
    `membership_get_in_scope`) nunca divergen.

    Args:
        membership:   Membresía ya resuelta a evaluar.
        sucursal_ids: Conjunto de sedes contra las que se compara (p. ej.
                      los ids de `allowed_sucursales(...)` del actor).

    Returns:
        True si la membresía cae dentro del scope, False si no.
    """
    return (
        TenantMembership.objects.filter(pk=membership.pk)
        .filter(_sucursal_scope_q(tenant_id=membership.tenant_id, sucursal_ids=sucursal_ids))
        .exists()
    )


def membership_list(
    *,
    sucursal_ids: list[uuid.UUID] | None = None,
    viewer_is_owner: bool = True,
    viewer_membership_id: uuid.UUID | None = None,
) -> QuerySet[TenantMembership]:
    """Membresías del tenant activo, con el usuario y sus sedes precargados.

    Ordena por rol y nombre para que el panel pueda agrupar por rol fácilmente.
    Incluye membresías activas e inactivas; el estado de bloqueo de la cuenta
    se lee de user.is_active.

    Precarga `sucursales_asignadas__sucursal` (multi-sede — Fase 4) para que
    `MemberOutputSerializer.get_sucursales` no dispare una query por miembro
    (cero N+1): el manager de MembershipSucursal (TenantManager) ya filtra
    por tenant activo y excluye soft-deleted, así que el Prefetch reutiliza
    ese mismo filtrado.

    Visibilidad por jerarquía de roles (decisión del dueño 2026-07-16 —
    `TenantMembership.operational_roles()`): un viewer OWNER ve todo
    (comportamiento de siempre, sin cambios, acotado solo por
    `sucursal_ids`). Un viewer NO owner (el "administrador de sucursal")
    NUNCA ve a otros owners ni a otros admins — una membresía le es visible
    solo si (su rol es operacional Y cae en `sucursal_ids`) O si es su
    PROPIA membresía (`viewer_membership_id`, sin importar su rol ni la sede
    activa: el actor siempre se ve a sí mismo en su propia lista).

    Selector PURO (sin `Request`): la vista calcula `viewer_is_owner` y
    `viewer_membership_id` a partir de `request.membership` y se los pasa.

    Args:
        sucursal_ids: alcance de sucursales a aplicar (típicamente
            `apps.clinica.sucursal_scope.sucursal_scope_ids(request)`).
            `None` = sin filtro de sede (comportamiento retro: todas las
            membresías del tenant, o todas las de rol operacional si el
            viewer no es owner). Una lista concreta filtra con
            `_sucursal_scope_q` (los OWNER siempre "caen" en cualquier
            sede — ver su docstring — pero un viewer no-owner nunca ve
            owners de todas formas, por la regla de rol de arriba).
        viewer_is_owner: True (default, retro-compatible) = sin restricción
            de rol adicional, el comportamiento de siempre. False = aplica
            la regla de jerarquía descrita arriba.
        viewer_membership_id: id de la propia membresía del viewer. Solo se
            usa cuando `viewer_is_owner=False`, para garantizar que el actor
            siempre aparezca en su propia lista aunque su rol no sea
            operacional (p. ej. un admin de sucursal).
    """
    tenant = get_current_tenant()
    qs = (
        TenantMembership.objects.filter(tenant=tenant)
        .select_related("user")
        .prefetch_related(
            Prefetch(
                "sucursales_asignadas",
                queryset=MembershipSucursal.objects.select_related("sucursal").order_by(
                    "sucursal__name"
                ),
            )
        )
    )

    if viewer_is_owner:
        if sucursal_ids is not None and tenant is not None:
            qs = qs.filter(_sucursal_scope_q(tenant_id=tenant.id, sucursal_ids=sucursal_ids))
        return qs.order_by("role", "user__first_name", "user__last_name")

    # Viewer NO owner: solo personal operacional dentro del alcance de sede,
    # más su propia membresía (siempre visible).
    visibility_q = Q(role__in=TenantMembership.operational_roles())
    if sucursal_ids is not None and tenant is not None:
        visibility_q &= _sucursal_scope_q(tenant_id=tenant.id, sucursal_ids=sucursal_ids)
    if viewer_membership_id is not None:
        visibility_q |= Q(id=viewer_membership_id)

    qs = qs.filter(visibility_q)
    return qs.order_by("role", "user__first_name", "user__last_name")


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


def membership_get_in_scope(
    *, membership_id: uuid.UUID, sucursal_ids: list[uuid.UUID]
) -> TenantMembership:
    """Recupera una membresía del tenant activo, acotada a `sucursal_ids` (PERMISO).

    A diferencia de `membership_get` (solo aísla por tenant), esta variante
    además exige que la membresía caiga dentro de `sucursal_ids` —
    típicamente los ids de `apps.clinica.sucursal_scope.allowed_sucursales`
    del actor, NO el scope de un listado (`sucursal_scope_ids`): el
    detalle/avatar de un miembro se acota a lo que el actor puede TOCAR
    (permiso), sin importar qué sede tenga seleccionada en el header en ese
    momento.

    Fuera de alcance, o de otro tenant → DoesNotExist. La vista debe
    traducirlo a 404 "Miembro no encontrado" sin distinguir el motivo (no
    revela si el miembro existe en otra sede o en otro tenant).

    Args:
        membership_id: id de la membresía a recuperar.
        sucursal_ids:  ids de sucursal permitidos del actor.

    Raises:
        TenantMembership.DoesNotExist: sin tenant activo, membresía de otro
            tenant, o fuera de `sucursal_ids`.
    """
    tenant = get_current_tenant()
    if tenant is None:
        raise TenantMembership.DoesNotExist()
    return (
        TenantMembership.objects.filter(tenant=tenant)
        .filter(_sucursal_scope_q(tenant_id=tenant.id, sucursal_ids=sucursal_ids))
        .select_related("user")
        .get(id=membership_id)
    )
