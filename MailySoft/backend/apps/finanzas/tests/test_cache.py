"""
Tests del caché de Redis del dashboard de finanzas (P1).

Cubre:
  - 2ª llamada con mismo (tenant, rango) viene del caché (no recomputa).
  - Invalidar (o escribir Payment/Charge/Quote) fuerza recomputar.
  - Aislamiento multi-tenant: el caché de un tenant no se sirve a otro.
  - Distinto rango de fechas → caché distinto.
"""

import datetime
from contextlib import contextmanager
from typing import Any, Generator
from unittest.mock import patch

from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from apps.finanzas.cache import finance_cache_invalidate, finance_cache_version
from apps.finanzas.selectors import finance_dashboard_metrics
from tests.factories import ChargeFactory, PaymentFactory, QuoteFactory, TenantFactory

_COMPUTE = "apps.finanzas.selectors._finance_dashboard_compute"


@contextmanager
def _tenant_ctx(tenant: Any) -> Generator[None, None, None]:
    set_current_tenant(tenant)
    set_tenant_context_active(True)
    try:
        yield
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)


class TestFinanceDashboardCache:
    def test_segunda_llamada_usa_cache(self, db: Any) -> None:
        tenant = TenantFactory()
        with _tenant_ctx(tenant):
            with patch(_COMPUTE, return_value={"kpis": 1}) as m:
                r1 = finance_dashboard_metrics()
                r2 = finance_dashboard_metrics()
        assert r1 == r2 == {"kpis": 1}
        m.assert_called_once()  # la 2ª llamada vino del caché

    def test_invalidacion_recomputa(self, db: Any) -> None:
        tenant = TenantFactory()
        with _tenant_ctx(tenant):
            with patch(_COMPUTE, side_effect=[{"v": 1}, {"v": 2}]) as m:
                r1 = finance_dashboard_metrics()
                finance_cache_invalidate(tenant.id)
                r2 = finance_dashboard_metrics()
        assert r1 == {"v": 1}
        assert r2 == {"v": 2}
        assert m.call_count == 2

    def test_aislamiento_por_tenant(self, db: Any) -> None:
        ta = TenantFactory()
        tb = TenantFactory()
        with _tenant_ctx(ta):
            with patch(_COMPUTE, return_value={"t": "a"}):
                ra = finance_dashboard_metrics()
        with _tenant_ctx(tb):
            with patch(_COMPUTE, return_value={"t": "b"}):
                rb = finance_dashboard_metrics()
        assert ra == {"t": "a"}
        assert rb == {"t": "b"}  # B NO recibe el caché de A

    def test_distinto_rango_distinto_cache(self, db: Any) -> None:
        tenant = TenantFactory()
        d1 = datetime.date(2026, 1, 1)
        d2 = datetime.date(2026, 2, 1)
        with _tenant_ctx(tenant):
            with patch(_COMPUTE, side_effect=[{"r": 1}, {"r": 2}]) as m:
                finance_dashboard_metrics(date_from=d1, date_to=d2)
                finance_dashboard_metrics(date_from=d1, date_to=d2)  # hit
                finance_dashboard_metrics(date_from=d2, date_to=d2)  # otro rango → recomputa
        assert m.call_count == 2


class TestFinanceCacheInvalidationSignal:
    def test_crear_charge_invalida(self, db: Any) -> None:
        tenant = TenantFactory()
        v0 = finance_cache_version(tenant.id)
        ChargeFactory(tenant=tenant)
        assert finance_cache_version(tenant.id) > v0

    def test_crear_payment_invalida(self, db: Any) -> None:
        tenant = TenantFactory()
        v0 = finance_cache_version(tenant.id)
        PaymentFactory(tenant=tenant)
        assert finance_cache_version(tenant.id) > v0

    def test_crear_quote_invalida(self, db: Any) -> None:
        tenant = TenantFactory()
        v0 = finance_cache_version(tenant.id)
        QuoteFactory(tenant=tenant)
        assert finance_cache_version(tenant.id) > v0
