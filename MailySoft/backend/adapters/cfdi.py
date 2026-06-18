"""
Adapter CFDI 4.0 (PAC) para Maily Soft.

Define la interfaz abstracta CfdiAdapter y dos implementaciones:
  - SimulatedCfdiAdapter: para desarrollo/tests. NO timbra nada real; genera un
                          folio fiscal (UUID) simulado y URLs ficticias.
  - FacturamaCfdiAdapter: para producción (Facturama). Placeholder: la llamada
                          HTTP real se implementa cuando haya credenciales del PAC.

La factory `get_cfdi_adapter()` decide cuál retornar según settings.

DISEÑO DESACOPLADO:
  Services SOLO importan `get_cfdi_adapter`, `CfdiStampResult` y `CfdiCancelResult`.
  Cambiar de simulado a real (Facturama) no requiere tocar services/views.

SECRETOS:
  FACTURAMA_API_USER, FACTURAMA_API_PASSWORD, FACTURAMA_BASE_URL se leen de
  settings (entorno, django-environ). Este módulo NO los hardcodea jamás.
  Los certificados CSD viven en el PAC o en un secret store, nunca en la BD.
"""

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CfdiStampResult:
    """Resultado de un intento de timbrado de CFDI.

    Attributes:
        success:  True si el PAC timbró el comprobante.
        uuid_sat: Folio fiscal (UUID) asignado por el SAT (vacío si falla).
        pac_id:   Identificador del comprobante en el PAC (vacío si falla).
        xml_url:  URL del XML timbrado (vacío si falla).
        pdf_url:  URL del PDF (vacío si falla).
        error:    Descripción del error (vacío si exitoso).
    """

    success: bool
    uuid_sat: str = field(default="")
    pac_id: str = field(default="")
    xml_url: str = field(default="")
    pdf_url: str = field(default="")
    error: str = field(default="")


@dataclass(frozen=True)
class CfdiCancelResult:
    """Resultado de un intento de cancelación de CFDI.

    Attributes:
        success: True si el PAC aceptó la cancelación.
        error:   Descripción del error (vacío si exitoso).
    """

    success: bool
    error: str = field(default="")


class CfdiAdapter(ABC):
    """Interfaz abstracta de timbrado/cancelación de CFDI 4.0.

    Todas las implementaciones deben satisfacer esta interfaz. La implementación
    real (FacturamaCfdiAdapter) se inyecta cuando haya credenciales del PAC.
    """

    @abstractmethod
    def stamp(self, *, payload: dict[str, Any]) -> CfdiStampResult:
        """Timbra un comprobante.

        Args:
            payload: estructura del comprobante (emisor, receptor, conceptos,
                     formas/método de pago, totales). La arma el servicio a
                     partir de ClinicFiscalConfig + CfdiDocument.

        Returns:
            CfdiStampResult con uuid_sat/xml_url/pdf_url si el timbrado fue exitoso.
        """

    @abstractmethod
    def cancel(self, *, pac_id: str, uuid_sat: str, reason: str) -> CfdiCancelResult:
        """Cancela un comprobante previamente timbrado.

        Args:
            pac_id:   identificador del comprobante en el PAC.
            uuid_sat: folio fiscal del SAT.
            reason:   motivo de cancelación SAT (01, 02, 03, 04).

        Returns:
            CfdiCancelResult con success=True si el PAC aceptó la cancelación.
        """


class SimulatedCfdiAdapter(CfdiAdapter):
    """Adapter de desarrollo/tests: NO timbra real, genera datos simulados.

    Seguro para usar en dev/staging sin credenciales del PAC. El `uuid_sat`
    es un UUID4 determinista por llamada; las URLs apuntan a un host ficticio.
    """

    def stamp(self, *, payload: dict[str, Any]) -> CfdiStampResult:
        """Simula el timbrado: genera folio fiscal y URLs ficticias.

        Loguea a nivel INFO sin PII (solo el total y el RFC receptor enmascarado).
        """
        fiscal_uuid = str(uuid.uuid4())
        pac_id = f"sim-{uuid.uuid4().hex[:16]}"
        receptor_rfc = str(payload.get("receptor_rfc", ""))
        masked_rfc = (receptor_rfc[:3] + "****") if len(receptor_rfc) > 3 else "***"
        logger.info(
            "SIMULATED CFDI stamp | receptor=%s | total=%s | uuid=%s",
            masked_rfc,
            payload.get("total", Decimal("0")),
            fiscal_uuid,
        )
        return CfdiStampResult(
            success=True,
            uuid_sat=fiscal_uuid,
            pac_id=pac_id,
            xml_url=f"https://sandbox.cfdi.local/xml/{fiscal_uuid}.xml",
            pdf_url=f"https://sandbox.cfdi.local/pdf/{fiscal_uuid}.pdf",
        )

    def cancel(self, *, pac_id: str, uuid_sat: str, reason: str) -> CfdiCancelResult:
        """Simula la cancelación: siempre acepta."""
        logger.info(
            "SIMULATED CFDI cancel | pac_id=%s | uuid=%s | reason=%s",
            pac_id,
            uuid_sat,
            reason,
        )
        return CfdiCancelResult(success=True)


class FacturamaCfdiAdapter(CfdiAdapter):
    """Adapter de producción para Facturama (PAC).

    PLACEHOLDER: la integración HTTP real se implementa cuando existan
    credenciales del PAC. Por ahora cada método indica claramente que no está
    disponible para evitar timbrados silenciosamente fallidos en producción.

    CUANDO SE INTEGRE FACTURAMA:
      1. Leer FACTURAMA_API_USER / FACTURAMA_API_PASSWORD / FACTURAMA_BASE_URL de settings.
      2. POST {base}/3/cfdis con el payload mapeado al esquema de Facturama (Basic Auth).
      3. Mapear la respuesta (Id, Complement.TaxStamp.Uuid, links de XML/PDF) a CfdiStampResult.
      4. DELETE {base}/cfdi/{id}?motive=... para cancelar.
    """

    def __init__(self, *, base_url: str, api_user: str, api_password: str) -> None:
        self._base_url = base_url
        self._api_user = api_user
        self._api_password = api_password

    def stamp(self, *, payload: dict[str, Any]) -> CfdiStampResult:
        # TODO(cfdi-real): implementar POST a Facturama con requests + Basic Auth.
        raise NotImplementedError(
            "FacturamaCfdiAdapter.stamp no implementado: faltan credenciales del PAC."
        )

    def cancel(self, *, pac_id: str, uuid_sat: str, reason: str) -> CfdiCancelResult:
        # TODO(cfdi-real): implementar DELETE a Facturama con requests + Basic Auth.
        raise NotImplementedError(
            "FacturamaCfdiAdapter.cancel no implementado: faltan credenciales del PAC."
        )


def get_cfdi_adapter() -> CfdiAdapter:
    """Factory que devuelve el adapter CFDI adecuado según la configuración.

    HOY: retorna SimulatedCfdiAdapter salvo que FACTURAMA_API_USER esté presente
    en settings (lo que indica que se quiere usar el PAC real).

    Returns:
        Instancia de CfdiAdapter lista para usar.
    """
    # Import diferido para no acoplar el adapter al ciclo de carga de Django
    # y permitir tests que mockeen settings sin importar este módulo.
    try:
        from django.conf import settings

        api_user: str = getattr(settings, "FACTURAMA_API_USER", "") or ""
        api_password: str = getattr(settings, "FACTURAMA_API_PASSWORD", "") or ""
        base_url: str = getattr(settings, "FACTURAMA_BASE_URL", "") or ""
    except Exception:  # noqa: BLE001 — fuera del contexto Django, usar simulado.
        api_user = api_password = base_url = ""

    if api_user and api_password and base_url:
        return FacturamaCfdiAdapter(
            base_url=base_url,
            api_user=api_user,
            api_password=api_password,
        )
    return SimulatedCfdiAdapter()
