"""
Services de la app audit.

audit_record — helper explícito para registrar eventos auditables.

Principios:
  - NUNCA lanza excepciones al caller. Una falla de auditoría no debe tumbar
    una operación de negocio (una cita no da 500 porque falló el INSERT de audit).
  - Lee ip/user_agent/request_id del thread-local (get_request_context),
    sin acoplar los services de negocio a HTTP.
  - Escribe síncronamente (INSERT simple <2ms). NOM-024 no acepta pérdida de
    eventos que tendría un Celery fire-and-forget.
  - metadata SIN PII clínica (ver §3.4 del diseño).
"""

import logging
import uuid
from typing import TYPE_CHECKING, Any, Optional

from apps.audit.models import ActionType, AuditLog
from apps.core.tenant_context import get_request_context

if TYPE_CHECKING:
    from apps.tenancy.models import Tenant

logger = logging.getLogger("apps.audit.services")


def audit_record(
    *,
    action: str,
    resource_type: str,
    actor: Optional[Any] = None,
    tenant: Optional["Tenant"] = None,
    resource_id: Optional[uuid.UUID] = None,
    resource_repr: str = "",
    description: str = "",
    metadata: Optional[dict[str, Any]] = None,
    actor_role: str = "",
) -> Optional[AuditLog]:
    """Registra un evento auditable en la bitácora append-only.

    Absorbe todas las excepciones: si el INSERT falla, loguea el error con
    nivel ERROR y devuelve None. El caller nunca recibe una excepción de auditoría.

    El contexto HTTP (ip, user_agent, request_id) se lee automáticamente del
    thread-local poblado por TenantAPIView.check_permissions(). En contextos
    fuera de HTTP (Celery, management commands) esos campos quedan vacíos.

    Args:
        action:        Tipo de acción (valor de ActionType). Requerido.
        resource_type: Nombre del modelo afectado ("Patient", "Appointment"...). Requerido.
        actor:         Usuario que realizó la acción (instancia User o None).
        tenant:        Tenant del evento (None para eventos globales como LOGIN_FAILED).
        resource_id:   UUID del objeto afectado (None si el evento no tiene objeto).
        resource_repr: Representación legible del recurso (snapshot inmutable).
        description:   Descripción en lenguaje natural del evento.
        metadata:      Contexto adicional SIN PII (changed_fields, old/new_status, etc.).
        actor_role:    Snapshot del rol del actor en el momento del evento.

    Returns:
        La instancia AuditLog creada, o None si hubo un error al escribir.
    """
    try:
        ctx = get_request_context()
        raw_ip: str = ctx.get("ip", "") or ""

        # GenericIPAddressField requiere None para nulo (no string vacío).
        ip_address: Optional[str] = raw_ip if raw_ip else None

        log = AuditLog(
            tenant=tenant,
            actor=actor,
            actor_role=actor_role or "",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_repr=resource_repr or "",
            description=description or "",
            ip_address=ip_address,
            user_agent=ctx.get("user_agent", "") or "",
            request_id=ctx.get("request_id", "") or "",
            metadata=metadata if metadata is not None else {},
        )
        # Usar all_objects para crear: TenantManager requiere tenant no-None,
        # pero aquí tenant puede ser None (eventos globales como LOGIN_FAILED).
        # AuditLog.all_objects.create() bypasa el TenantManager.
        log.save()
        return log

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "audit_record: fallo al escribir entrada de auditoría — "
            "action=%s resource_type=%s resource_id=%s — %s",
            action,
            resource_type,
            resource_id,
            exc,
            exc_info=True,
        )
        return None
