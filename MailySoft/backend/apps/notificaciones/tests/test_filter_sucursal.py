"""Filtro de destinatarios de campana por sede (multi-sede — 2026-07-16).

`filter_recipients_by_sucursal` es el helper compartido que usan los fanouts de
notas/agenda/expediente para no sonarle la campana a quien no puede ver esa sede.
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from apps.notificaciones.recipients import filter_recipients_by_sucursal
from apps.tenancy.models import TenantMembership
from tests.factories import (
    MembershipSucursalFactory,
    SucursalFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)


@contextmanager
def _ctx(tenant: Any) -> Generator[None, None, None]:
    set_current_tenant(tenant)
    set_tenant_context_active(True)
    try:
        yield
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)


def _scoped(tenant: Any, role: str, sucursal: Any) -> Any:
    user = UserFactory()
    m = TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    MembershipSucursalFactory(tenant=tenant, membership=m, sucursal=sucursal)
    return user


class TestFilterRecipientsBySucursal:
    def test_sede_especifica_solo_miembros_sin_el_dueno(self, db: Any) -> None:
        """Aviso de UNA sede: suena solo al personal de esa sede. El DUEÑO
        queda fuera de la campana (lo ve en la lista, no lo pingamos)."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True)
        norte = SucursalFactory(tenant=tenant, name="Norte")

        owner = UserFactory()
        TenantMembershipFactory(
            user=owner, tenant=tenant, role=TenantMembership.Role.OWNER, is_active=True
        )
        recep_norte = _scoped(tenant, TenantMembership.Role.RECEPTION, norte)
        recep_centro = _scoped(tenant, TenantMembership.Role.RECEPTION, centro)

        recipients = [owner, recep_norte, recep_centro]
        with _ctx(tenant):
            filtrados = filter_recipients_by_sucursal(
                tenant=tenant, recipients=recipients, sucursal_id=norte.id
            )

        assert owner not in filtrados  # el dueño NO recibe la campana de una sede
        assert recep_norte in filtrados  # es de Norte
        assert recep_centro not in filtrados  # NO es de Norte

    def test_todas_las_sedes_incluye_al_dueno(self, db: Any) -> None:
        """Aviso a TODAS las sedes (sucursal_id=None): no filtra a nadie,
        incluido el dueño."""
        tenant = TenantFactory()
        SucursalFactory(tenant=tenant, name="Centro", is_default=True)
        norte = SucursalFactory(tenant=tenant, name="Norte")

        owner = UserFactory()
        TenantMembershipFactory(
            user=owner, tenant=tenant, role=TenantMembership.Role.OWNER, is_active=True
        )
        recep_norte = _scoped(tenant, TenantMembership.Role.RECEPTION, norte)

        recipients = [owner, recep_norte]
        with _ctx(tenant):
            filtrados = filter_recipients_by_sucursal(
                tenant=tenant, recipients=recipients, sucursal_id=None
            )

        assert filtrados == recipients  # None = todas las sedes → nadie se filtra
