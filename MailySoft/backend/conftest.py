"""
conftest raíz — fixtures globales que aplican a TODA la suite (apps/ y tests/).

reset_throttle_cache: limpia la caché de Django antes de cada test para que los
contadores de rate-limit (ScopedRateThrottle del login, AnonRateThrottle, etc.)
no se acumulen entre tests. Sin esto, varios tests que hacen login real chocarían
con el límite `auth_login` (5/min) y devolverían 429 de forma espuria.
"""

import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def reset_throttle_cache() -> None:
    """Resetea la caché (y con ella los contadores de throttling) antes de cada test."""
    cache.clear()
