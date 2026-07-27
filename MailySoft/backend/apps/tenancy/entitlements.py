"""
Derechos efectivos de una clínica: qué módulos y qué límites tiene contratados.

Esta es la ÚNICA fuente de verdad del gating. La lee tanto el backend (que
bloquea de verdad) como el endpoint que alimenta al frontend (que solo oculta).
Si cada capa calculara lo suyo, tarde o temprano se contradirían y el usuario
vería un botón que al presionarlo da 403.

Resolución:
    módulos = (módulos del plan  ∪  modules_on)  −  modules_off
    límite  = override de la clínica si no es NULL, si no el del plan,
              y NULL en ambos = ilimitado

Sin plan y sin ajustes, una clínica NO tiene módulos. Las clínicas que ya
existían se migraron al plan "Legacy full" para que nada cambie de golpe.
"""

import uuid
from dataclasses import dataclass, field

from apps.core.modules import Module, roles_disponibles
from apps.tenancy.models import Tenant, TenantEntitlements, TenantSubscription

#: Límites que se resuelven plan → override.
LIMITES: tuple[str, ...] = ("max_sucursales", "max_consultorios", "max_usuarios")


@dataclass(frozen=True)
class Entitlements:
    """Lo que una clínica tiene contratado, ya resuelto."""

    tenant_id: uuid.UUID
    modules: frozenset[str] = field(default_factory=frozenset)
    max_sucursales: int | None = None
    max_consultorios: int | None = None
    max_usuarios: int | None = None
    plan_slug: str = ""
    plan_name: str = ""
    # Roles que el plan ofrece (allow-list). Vacío = sin restricción extra: valen
    # todos los que los módulos permitan.
    plan_roles: frozenset[str] = field(default_factory=frozenset)

    def tiene(self, module: str) -> bool:
        """¿La clínica tiene contratado este módulo?"""
        return module in self.modules

    @property
    def roles(self) -> set[str]:
        """Roles asignables: los que los MÓDULOS permiten Y el PLAN ofrece.

        Dos capas: `roles_disponibles` quita los que no tienen su módulo (finance
        sin cobranza); `plan_roles` es la decisión comercial de qué ofrece el plan
        (Básico no ofrece admin ni solo-lectura aunque no dependan de módulos).
        Un plan sin restricción (`plan_roles` vacío) usa solo la primera capa.
        """
        por_modulos = roles_disponibles(self.modules)
        if not self.plan_roles:
            return por_modulos
        return por_modulos & set(self.plan_roles)

    @property
    def sede_unica(self) -> bool:
        """True si la clínica opera en modo sede única (se oculta la UI de sucursales)."""
        return self.max_sucursales == 1

    def limite(self, nombre: str) -> int | None:
        """Devuelve un límite por nombre. None = ilimitado."""
        return getattr(self, nombre)


def entitlements_for_tenant(*, tenant: Tenant) -> Entitlements:
    """Resuelve los derechos efectivos de una clínica.

    Args:
        tenant: Clínica a resolver.

    Returns:
        Entitlements ya resueltos (plan + ajustes por clínica).
    """
    suscripcion = (
        TenantSubscription.objects.select_related("plan")
        .filter(tenant=tenant)
        .first()
    )
    ajustes = TenantEntitlements.objects.filter(tenant=tenant).first()

    plan = suscripcion.plan if suscripcion else None

    modulos: set[str] = set(plan.modules) if plan else set()
    if ajustes:
        modulos |= set(ajustes.modules_on)
        modulos -= set(ajustes.modules_off)

    # Un slug que ya no existe en el catálogo (módulo retirado del código) se
    # descarta: dejarlo pasar haría que `tiene()` respondiera True para algo
    # que ya no tiene implementación detrás.
    modulos &= set(Module.values)

    limites: dict[str, int | None] = {}
    for nombre in LIMITES:
        override = getattr(ajustes, nombre, None) if ajustes else None
        limites[nombre] = override if override is not None else getattr(plan, nombre, None)

    return Entitlements(
        tenant_id=tenant.id,
        modules=frozenset(modulos),
        plan_slug=plan.slug if plan else "",
        plan_name=plan.name if plan else "",
        plan_roles=frozenset(plan.roles) if plan and plan.roles else frozenset(),
        **limites,
    )
