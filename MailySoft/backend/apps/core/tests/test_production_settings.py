"""
Tests del candado de variables obligatorias en producción (M0.3).

`config/settings/production.py` exige cuatro variables que en `base.py` tienen
un default pensado para desarrollo local. Ese default es correcto en la máquina
del programador y peligroso en Railway: la app arranca "sana" y falla en silencio
—archivos que se borran en cada redespliegue, QR de recetas apuntando a
localhost, límite de intentos de login desactivado—. Sin el candado, nada avisa.

Estos tests existen para que nadie pueda deshacer el candado sin que CI lo note.
Cubren las tres formas de deshacerlo:

1. Quitar una variable de la lista de obligatorias.
2. Aceptar un valor en blanco como si fuera un valor válido (en el panel de
   Railway `REDIS_URL=` se ve puesta y no lo está).
3. Aceptar solo la primera que falte, en vez de reportarlas todas juntas.

Y uno de control: con las cuatro puestas, el módulo importa sin error. Sin él,
un candado trabado de forma permanente pasaría por candado que funciona.

Verificado por mutación el 2026-08-13: revirtiendo `production.py` a la versión
anterior al arreglo, 17 de estos 21 tests fallan. Los 4 que sobreviven son el
control y los tres del valor efectivo, que por diseño no distinguen cuál de los
dos archivos de settings asignó el valor (ver la segunda clase).

Patrón: AAA. No tocan BD — solo importan el módulo de settings.
"""

import importlib
import sys
from collections.abc import Iterator
from types import ModuleType

import environ
import pytest
from django.core.exceptions import ImproperlyConfigured

# Las cuatro bajo prueba. Si alguien agrega una quinta al candado, este test
# NO la cubre solo: hay que sumarla aquí a propósito.
VARIABLES_OBLIGATORIAS: tuple[str, ...] = (
    "DJANGO_DEFAULT_FILE_STORAGE",
    "PRESCRIPTION_VERIFY_SECRET",
    "PRESCRIPTION_VERIFY_BASE_URL",
    "REDIS_URL",
)

# Entorno mínimo con el que `production.py` importa sin errores. Incluye las
# variables que el módulo ya exigía antes de M0.3 (SECRET_KEY, JWT, hosts,
# orígenes CSRF) porque sin ellas fallaría por la razón equivocada y el test
# no probaría nada. Valores de mentira: nada de esto se conecta a ningún lado.
ENTORNO_DE_PRODUCCION_VALIDO: dict[str, str] = {
    "DJANGO_SECRET_KEY": "secreto-de-prueba-" + "x" * 40,
    "JWT_SIGNING_KEY": "firma-de-prueba-" + "y" * 40,
    "DJANGO_ALLOWED_HOSTS": ".railway.app",
    "CSRF_TRUSTED_ORIGINS": "https://ejemplo.railway.app",
    "DATABASE_URL": "postgres://usuario:clave@localhost:5432/base",
    "DJANGO_DEFAULT_FILE_STORAGE": "django.core.files.storage.FileSystemStorage",
    "PRESCRIPTION_VERIFY_SECRET": "secreto-del-qr-de-prueba",
    "PRESCRIPTION_VERIFY_BASE_URL": "https://ejemplo.railway.app",
    "REDIS_URL": "redis://localhost:6379/9",
}

MODULOS_DE_SETTINGS: tuple[str, ...] = ("config.settings.production", "config.settings.base")


def importar_settings_de_produccion() -> ModuleType:
    """Importa `production.py` de cero, como en un arranque real del proceso.

    Hay que sacar los dos módulos de `sys.modules` antes: Python cachea los
    imports, así que sin esto el segundo caso de prueba reusaría el resultado
    del primero y pasaría siempre, mirara lo que mirara el entorno.
    """
    for modulo in MODULOS_DE_SETTINGS:
        sys.modules.pop(modulo, None)
    return importlib.import_module("config.settings.production")


@pytest.fixture
def entorno_de_produccion(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Deja el proceso listo para importar `production.py` sin efectos colaterales.

    Tres cosas, y las tres hacen falta:

    - Neutraliza `read_env`, que lee el archivo `.env` del disco. Sin esto, el
      resultado dependería de si la máquina que corre los tests tiene `.env` y
      de qué dice — o sea, el test pasaría o fallaría según la computadora.
    - Quita `SENTRY_DSN`, porque `base.py` inicializa Sentry de verdad cuando
      está presente. Un test no debe abrir un cliente de telemetría.
    - Restaura `sys.modules` al terminar, para no dejarle a los tests que
      siguen una versión reimportada de los settings.
    """
    originales = {n: sys.modules[n] for n in MODULOS_DE_SETTINGS if n in sys.modules}

    monkeypatch.setattr(environ.Env, "read_env", lambda *args, **kwargs: None)
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    for nombre, valor in ENTORNO_DE_PRODUCCION_VALIDO.items():
        monkeypatch.setenv(nombre, valor)

    yield

    for nombre in MODULOS_DE_SETTINGS:
        sys.modules.pop(nombre, None)
    sys.modules.update(originales)


@pytest.mark.usefixtures("entorno_de_produccion")
class TestVariablesObligatoriasEnProduccion:
    """El candado: sin estas cuatro, el proceso no arranca."""

    def test_importa_sin_error_con_las_cuatro_puestas(self) -> None:
        """Control: el candado abre. Sin esto, un candado trabado pasaría por bueno."""
        modulo = importar_settings_de_produccion()

        assert modulo.DEBUG is False

    @pytest.mark.parametrize("variable", VARIABLES_OBLIGATORIAS)
    def test_falla_si_falta_una_variable(
        self, variable: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ausente por completo: el arranque muere y el mensaje nombra cuál falta."""
        monkeypatch.delenv(variable)

        with pytest.raises(ImproperlyConfigured) as error:
            importar_settings_de_produccion()

        assert variable in str(error.value)

    @pytest.mark.parametrize("variable", VARIABLES_OBLIGATORIAS)
    @pytest.mark.parametrize("valor_en_blanco", ["", " ", "   \t  "])
    def test_un_valor_en_blanco_cuenta_como_ausente(
        self, variable: str, valor_en_blanco: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """En el panel de Railway `REDIS_URL=` se ve puesta. No lo está."""
        monkeypatch.setenv(variable, valor_en_blanco)

        with pytest.raises(ImproperlyConfigured) as error:
            importar_settings_de_produccion()

        assert variable in str(error.value)

    def test_el_mensaje_lista_todas_las_que_faltan_no_solo_la_primera(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Es la razón de validarlas juntas.

        Con una comprobación por variable, un servicio nuevo al que le falten
        cuatro las revela de a una: cuatro ciclos de despliegue para enterarse
        de cuatro nombres.
        """
        for variable in VARIABLES_OBLIGATORIAS:
            monkeypatch.delenv(variable)

        with pytest.raises(ImproperlyConfigured) as error:
            importar_settings_de_produccion()

        mensaje = str(error.value)
        for variable in VARIABLES_OBLIGATORIAS:
            assert variable in mensaje
        assert "4 de 4" in mensaje


@pytest.mark.usefixtures("entorno_de_produccion")
class TestElValorEfectivoEnProduccionSaleDelEntorno:
    """Que la variable se exija no basta: hay que usarla, y con el valor correcto.

    Alcance honesto de esta clase: NO distingue si el valor lo asignó
    `production.py` o `base.py`, porque los dos leen las mismas variables y el
    resultado observable es idéntico. Se comprobó revirtiendo el arreglo entero:
    estos asserts siguen pasando.

    Lo que sí atrapan es una regresión en el valor efectivo desde cualquiera de
    los dos archivos — que es donde vive el peligro. Los defaults de desarrollo
    de `base.py` (FileSystemStorage, localhost:5173, la SECRET_KEY como secreto
    del QR) son exactamente lo que no debe llegar a producción, y aquí se
    verifica que no llegan.
    """

    def test_el_backend_de_media_sale_de_la_variable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DJANGO_DEFAULT_FILE_STORAGE", "prueba.storage.Inventado")

        modulo = importar_settings_de_produccion()

        assert modulo.STORAGES["default"]["BACKEND"] == "prueba.storage.Inventado"

    def test_la_cache_y_los_canales_salen_de_redis_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ambos: `base.py` los lee por separado y es fácil actualizar solo uno."""
        monkeypatch.setenv("REDIS_URL", "redis://ejemplo-de-prueba:6379/7")

        modulo = importar_settings_de_produccion()

        assert modulo.CACHES["default"]["LOCATION"] == "redis://ejemplo-de-prueba:6379/7"
        assert modulo.CHANNEL_LAYERS["default"]["CONFIG"]["hosts"] == [
            "redis://ejemplo-de-prueba:6379/7"
        ]

    def test_el_qr_de_recetas_no_cae_al_secret_key_ni_a_localhost(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Los dos defaults de `base.py` que este candado existe para prohibir."""
        # Los noqa S105 son el detector de secretos de ruff: aquí no hay ninguno,
        # es una cadena de mentira que solo existe dentro de este test.
        monkeypatch.setenv("PRESCRIPTION_VERIFY_SECRET", "secreto-propio-del-qr")  # noqa: S105
        monkeypatch.setenv("PRESCRIPTION_VERIFY_BASE_URL", "https://clinica.example.mx")

        modulo = importar_settings_de_produccion()

        assert modulo.PRESCRIPTION_VERIFY_SECRET == "secreto-propio-del-qr"  # noqa: S105
        assert modulo.PRESCRIPTION_VERIFY_SECRET != modulo.SECRET_KEY
        assert modulo.PRESCRIPTION_VERIFY_BASE_URL == "https://clinica.example.mx"
        assert "localhost" not in modulo.PRESCRIPTION_VERIFY_BASE_URL
