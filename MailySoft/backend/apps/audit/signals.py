"""
Receptores de señales para la app audit.

handle_login_failed — receptor de user_login_failed (Django auth).

Nota: user_login_failed se dispara cuando authenticate() retorna None.
SimpleJWT llama a authenticate() internamente, por lo que esta señal
sí se dispara al fallar la autenticación JWT.

El evento de LOGIN exitoso se registra en MailyTokenObtainPairView
(apps/authn) porque SimpleJWT no dispara user_logged_in.
"""

import hashlib
import logging
from typing import Any

logger = logging.getLogger("apps.audit.signals")


def handle_login_failed(
    sender: Any,
    credentials: dict[str, Any],
    request: Any,
    **kwargs: Any,
) -> None:
    """Registra un intento de login fallido en la bitácora.

    Se guarda un HASH del email del intento (no el email en claro) para permitir
    correlación de ataques de fuerza bruta sin almacenar PII (LFPDPPP).
    La contraseña NUNCA se registra ni se hashea aquí.

    Args:
        sender:      Clase que emitió la señal (backend de auth).
        credentials: Dict de credenciales del intento (username/password/email).
        request:     Request HTTP original (puede ser None en algunos paths).
        **kwargs:    Kwargs adicionales de la señal.
    """
    # Import local para evitar import circular en el arranque.
    from apps.audit.models import ActionType
    from apps.audit.services import audit_record
    from apps.core.tenant_context import clear_request_context, set_request_context

    # Extraer el email/username del intento — NUNCA la contraseña.
    email_attempt: str = (
        credentials.get("username")
        or credentials.get("email")
        or ""
    )

    # Hash corto del email: permite detectar intentos repetidos sin guardar PII.
    metadata: dict[str, Any] = {}
    if email_attempt:
        metadata["email_hint"] = hashlib.sha256(
            email_attempt.lower().encode()
        ).hexdigest()[:16]

    description = "Intento de inicio de sesión fallido"

    # Poblar contexto HTTP desde el request si está disponible.
    ip_address: str = ""
    user_agent: str = ""
    if request is not None:
        x_forwarded = getattr(request, "META", {}).get("HTTP_X_FORWARDED_FOR", "")
        if x_forwarded:
            ip_address = x_forwarded.split(",")[0].strip()
        else:
            ip_address = getattr(request, "META", {}).get("REMOTE_ADDR", "")
        user_agent = getattr(request, "META", {}).get("HTTP_USER_AGENT", "")[:512]

    # Setear el contexto de request SOLO para esta llamada y limpiarlo en finally
    # (evita fugar la IP a otro evento en el mismo hilo si la señal corre fuera
    # del ciclo de vida de un request HTTP).
    context_set = False
    if ip_address or user_agent:
        set_request_context(ip=ip_address, user_agent=user_agent, request_id="")
        context_set = True
    try:
        audit_record(
            action=ActionType.LOGIN_FAILED,
            resource_type="User",
            actor=None,
            tenant=None,  # El usuario no está resuelto en un intento fallido.
            description=description,
            metadata=metadata,
        )
    finally:
        if context_set:
            clear_request_context()
