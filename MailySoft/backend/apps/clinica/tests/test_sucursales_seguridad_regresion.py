"""
Regresión de seguridad — Clústeres B y C-clínica (multi-sede).

Reproduce, con las MISMAS condiciones que usó el equipo de auditoría (2026-07-10,
docs/design/sucursales-hallazgos-seguridad.md), el ataque de extremo a extremo
que combinaba ambos hallazgos:

  1. Un admin acotado SOLO a la sucursal Centro (vía MembershipSucursal) sabía
     el id de la sucursal Norte (obtenido del estado de cuenta del paciente,
     compartido a propósito entre sedes) y hacía DELETE/PATCH sobre ella —
     Clúster C: `SucursalDetailApi` no validaba la sede permitida.
  2. Ese DELETE (baja lógica, is_active=False) disparaba el Clúster B:
     `sucursal_scope_ids` inferría "alcance total" comparando contra el
     conteo de sedes ACTIVAS, así que al bajar ese denominador el admin de
     Centro pasaba a "cubrir todas las activas" y el listado de cargos
     (`GET /api/v1/finanzas/cargos/`) dejaba de filtrar, exponiendo la caja
     privada de Norte.

Este archivo reemplaza el `test_zzz_exploit_tmp.py` efímero que dejó el
equipo de auditoría (marcado "EFÍMERO — BORRAR"): mismas condiciones, pero
las aserciones ahora esperan el comportamiento SEGURO (post-fix), no el
vulnerable.
"""

from collections.abc import Generator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any
from unittest.mock import patch

from rest_framework.test import APIClient

from apps.clinica.models import Sucursal
from apps.clinica.sucursal_scope import sucursal_scope_ids
from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from apps.tenancy.models import TenantMembership
from tests.factories import (
    ChargeFactory,
    MembershipSucursalFactory,
    PatientFactory,
    SucursalFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

CHARGES_URL = "/api/v1/finanzas/cargos/"
_SUCURSAL_URL = "/api/v1/clinica/sucursales/{}/"


@contextmanager
def _api_tenant_ctx(tenant: Any) -> Generator[None, None, None]:
    """Inyecta el tenant en el middleware y el TenantManager para tests HTTP.

    Mismo helper que usan test_sucursales.py / test_membership_sucursales.py,
    extendido a apps.finanzas.views porque este ataque cruza ambos módulos.
    """
    with (
        patch("apps.clinica.views.get_current_tenant", return_value=tenant),
        patch("apps.finanzas.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
    ):
        yield


@contextmanager
def _tenant_ctx(tenant: Any) -> Generator[None, None, None]:
    """Activa el thread-local de tenant para llamar `sucursal_scope_ids` directo."""
    set_current_tenant(tenant)
    set_tenant_context_active(True)
    try:
        yield
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)


def _setup_centro_norte(tenant: Any) -> tuple[Any, Any, Any, Any]:
    """Centro (default) + Norte, y un admin acotado SOLO a Centro.

    Returns:
        (centro, norte, admin_user, admin_membership)
    """
    centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True, is_active=True)
    norte = SucursalFactory(tenant=tenant, name="Norte", is_default=False, is_active=True)
    admin = UserFactory()
    membership = TenantMembershipFactory(
        user=admin, tenant=tenant, role=TenantMembership.Role.ADMIN, is_active=True
    )
    MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)
    return centro, norte, admin, membership


class TestAtaqueClusterBYCadenaCompleta:
    """Reproduce el ataque encadenado C→B del PoC original, ahora bloqueado."""

    def test_admin_de_centro_no_puede_desactivar_norte_ni_ganar_lectura_total(
        self, db: Any
    ) -> None:
        tenant = TenantFactory()
        centro, norte, admin, _ = _setup_centro_norte(tenant)

        # Un cargo privado de Norte (caja de Norte) y uno de Centro.
        ChargeFactory(
            tenant=tenant,
            patient=PatientFactory(tenant=tenant),
            sucursal=norte,
            description="CARGO SECRETO DE NORTE",
            amount=Decimal("999.00"),
        )
        ChargeFactory(
            tenant=tenant,
            patient=PatientFactory(tenant=tenant),
            sucursal=centro,
            description="cargo de centro",
            amount=Decimal("10.00"),
        )

        client = APIClient()
        client.force_authenticate(user=admin)

        with _api_tenant_ctx(tenant):
            # --- BASELINE: el admin de Centro solo ve su propia caja ---
            r0 = client.get(CHARGES_URL)
            assert r0.status_code == 200, r0.content
            descs0 = [c["description"] for c in r0.json()["results"]]
            assert not any("NORTE" in d for d in descs0)

            # --- ATAQUE (Clúster C): DELETE de la sucursal Norte, ajena ---
            # Multi-sede (2026-07-16): gestionar sucursales pasó a ser SOLO del
            # dueño, así que un admin queda bloqueado en la capa de PERMISO (403)
            # antes de llegar al scoping (que daba 404). Cualquiera de los dos
            # deja a Norte intacta — el bloqueo por permiso es aún más fuerte
            # (el admin no puede tocar NINGUNA sucursal, ni la suya).
            r1 = client.delete(_SUCURSAL_URL.format(norte.id))
            assert r1.status_code in (403, 404), (
                f"el admin de Centro pudo desactivar Norte (status={r1.status_code}) "
                "-> Clúster C sigue vulnerable"
            )

            # --- ATAQUE 2 (Clúster C): PATCH renombrar Norte, ajena ---
            r1b = client.patch(_SUCURSAL_URL.format(norte.id), {"name": "HACKEADA"}, format="json")
            assert r1b.status_code in (403, 404)

            norte.refresh_from_db()
            assert norte.is_active is True, "Norte quedó desactivada por un actor sin permiso"
            assert norte.name == "Norte"

            # --- EFECTO DE SEGUNDO ORDEN (Clúster B): sin el ataque de
            # Clúster C, Norte nunca se desactivó, así que el bug B (que
            # dependía de que se desactivara una sede ajena) no tiene forma
            # de dispararse. La caja de Norte sigue oculta. ---
            r2 = client.get(CHARGES_URL)
            assert r2.status_code == 200, r2.content
            descs2 = [c["description"] for c in r2.json()["results"]]
            assert not any(
                "NORTE" in d for d in descs2
            ), "fuga de la caja de Norte al admin de Centro"

    def test_si_el_owner_desactiva_norte_el_admin_de_centro_sigue_sin_ver_su_caja(
        self, db: Any
    ) -> None:
        """Variante directa del Clúster B: aunque una sede AJENA se
        desactive por una vía legítima (el owner), el admin acotado a
        Centro no debe ganar lectura consolidada."""
        tenant = TenantFactory()
        centro, norte, admin, _ = _setup_centro_norte(tenant)
        owner = UserFactory()
        TenantMembershipFactory(
            user=owner, tenant=tenant, role=TenantMembership.Role.OWNER, is_active=True
        )

        ChargeFactory(
            tenant=tenant,
            patient=PatientFactory(tenant=tenant),
            sucursal=norte,
            description="CARGO SECRETO DE NORTE",
            amount=Decimal("7777.00"),
        )

        owner_client = APIClient()
        owner_client.force_authenticate(user=owner)
        admin_client = APIClient()
        admin_client.force_authenticate(user=admin)

        with _api_tenant_ctx(tenant):
            r_baseline = admin_client.get(CHARGES_URL)
            assert r_baseline.json()["count"] == 0

            r_deactivate = owner_client.delete(_SUCURSAL_URL.format(norte.id))
            assert r_deactivate.status_code == 204

            r_post = admin_client.get(CHARGES_URL)

        assert r_post.status_code == 200, r_post.content
        descs = [c["description"] for c in r_post.json()["results"]]
        assert not any("NORTE" in d for d in descs), "fuga tras desactivar Norte legítimamente"

    def test_control_sin_ataque_no_hay_fuga(self, db: Any) -> None:
        """Control: sin desactivar Norte, el admin de Centro NO ve la caja de Norte."""
        tenant = TenantFactory()
        centro, norte, admin, _ = _setup_centro_norte(tenant)
        ChargeFactory(
            tenant=tenant,
            patient=PatientFactory(tenant=tenant),
            sucursal=norte,
            description="CARGO SECRETO DE NORTE",
            amount=Decimal("999.00"),
        )
        client = APIClient()
        client.force_authenticate(user=admin)

        with _api_tenant_ctx(tenant):
            r = client.get(CHARGES_URL)

        assert r.status_code == 200, r.content
        descs = [c["description"] for c in r.json()["results"]]
        assert not any("NORTE" in d for d in descs)
        assert Sucursal.all_objects.filter(id=norte.id, is_active=True).exists()

    def test_sucursal_scope_ids_acotado_tras_desactivacion_legitima(self, db: Any) -> None:
        """Mismo escenario que el PoC pero a nivel de unidad (sin HTTP),
        para aislar exactamente la función corregida."""
        from rest_framework.test import APIRequestFactory

        tenant = TenantFactory()
        centro, norte, admin, _ = _setup_centro_norte(tenant)

        rf = APIRequestFactory()
        req = rf.get("/x/")
        req.user = admin
        from rest_framework.request import Request

        drf_req = Request(req)
        drf_req.user = admin

        with _tenant_ctx(tenant):
            baseline = sucursal_scope_ids(drf_req)
            assert baseline == [centro.id]

            from apps.clinica.services import sucursal_deactivate

            sucursal_deactivate(sucursal=norte, user=UserFactory())

            post_scope = sucursal_scope_ids(drf_req)

        assert post_scope == [centro.id], f"scope se amplió indebidamente: {post_scope}"
