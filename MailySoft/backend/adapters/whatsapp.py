"""
Adapter WhatsApp para Maily Soft.

Define la interfaz abstracta WhatsAppAdapter y dos implementaciones:
  - SimulatedWhatsAppAdapter: para desarrollo. NO envía nada real, solo loguea.
  - MetaWhatsAppAdapter:       para producción (pendiente de implementar cuando
                               haya credenciales Meta). Placeholder vacío hoy.

La factory `get_whatsapp_adapter()` decide cuál retornar según settings.

DISEÑO DESACOPLADO:
  Services y tasks SOLO importan `get_whatsapp_adapter` y `WhatsAppResult`.
  Cambiar de simulado a real no requiere tocar services/tasks.

SECRETOS:
  WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_VERIFY_TOKEN
  se leen en settings/base.py desde entorno. Este módulo NO los accede
  directamente; la factory los recibe de settings cuando sea necesario.
"""

import logging
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger("apps.adapters.whatsapp")


@dataclass(frozen=True)
class WhatsAppResult:
    """Resultado de un intento de envío de mensaje WhatsApp.

    Attributes:
        success:             True si el mensaje fue aceptado por el proveedor.
        external_message_id: ID asignado por el proveedor (vacío si falla).
        error:               Descripción del error (vacío si exitoso).
    """

    success: bool
    external_message_id: str = field(default="")
    error: str = field(default="")


class WhatsAppAdapter:
    """Interfaz de envío de mensajes WhatsApp.

    Todas las implementaciones deben satisfacer esta interfaz.
    La implementación real (MetaWhatsAppAdapter) se inyecta cuando haya
    credenciales Meta configuradas en el entorno.
    """

    def send_template(
        self,
        *,
        to: str,
        template: str,
        params: dict[str, str],
    ) -> WhatsAppResult:
        """Envía un mensaje de plantilla WhatsApp.

        Args:
            to:       Número de teléfono destino en formato E.164 (+521XXXXXXXXXX).
            template: Nombre del template aprobado en Meta Business Manager.
            params:   Parámetros de los componentes del template (clave→valor).

        Returns:
            WhatsAppResult con success=True y external_message_id si fue aceptado.
        """
        raise NotImplementedError


class SimulatedWhatsAppAdapter(WhatsAppAdapter):
    """Adapter de desarrollo: NO envía nada real, solo loguea y devuelve éxito simulado.

    Seguro para usar en dev/staging sin credenciales reales.
    El `external_message_id` es un UUID determinista (sim- + 12 hex chars) que
    permite rastrear en logs sin depender de estado externo.
    """

    def send_template(
        self,
        *,
        to: str,
        template: str,
        params: dict[str, str],
    ) -> WhatsAppResult:
        """Simula el envío: loguea a nivel INFO y retorna éxito."""
        simulated_id = f"sim-{uuid.uuid4().hex[:12]}"
        logger.info(
            "SIMULATED WhatsApp | to=%s | template=%s | params=%s | sim_id=%s",
            to,
            template,
            params,
            simulated_id,
        )
        return WhatsAppResult(
            success=True,
            external_message_id=simulated_id,
        )


def get_whatsapp_adapter() -> WhatsAppAdapter:
    """Factory que devuelve el adapter adecuado según la configuración del entorno.

    HOY: siempre retorna SimulatedWhatsAppAdapter (no hay credenciales Meta).

    CUANDO SE INTEGRE META:
      1. Implementar MetaWhatsAppAdapter que llame a la Graph API.
      2. Leer WHATSAPP_ACCESS_TOKEN desde django.conf.settings (ya está en base.py).
      3. Retornar MetaWhatsAppAdapter() si el token está presente.

    Returns:
        Instancia de WhatsAppAdapter lista para usar.
    """
    # TODO(whatsapp-real): cuando existan credenciales Meta, importar settings y
    # retornar MetaWhatsAppAdapter() si settings.WHATSAPP_ACCESS_TOKEN != "".
    return SimulatedWhatsAppAdapter()
