"""
Services de la app authn (escrituras sobre la identidad del usuario autenticado).

password_change — único caso de uso hoy: cambio de contraseña propio (voluntario
o forzado por must_change_password=True). Sigue el mismo patrón de auditoría y
validación que apps/tenancy/services.member_update (validate_password de Django)
y de apps/plataforma/services (invalidar refresh tokens vigentes con la blacklist
de SimpleJWT tras un cambio de credencial).
"""

import logging

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.authn.models import User
from apps.core.tenant_context import resolve_membership_for_user

logger = logging.getLogger("apps.authn.services")


def password_change(*, user: User, current_password: str, new_password: str) -> User:
    """Cambia la contraseña del usuario autenticado (voluntario o forzado).

    Valida la contraseña actual (evita que un token robado, sin conocer la
    contraseña, pueda cambiarla) y corre los validadores de contraseña de
    Django (AUTH_PASSWORD_VALIDATORS: longitud mínima, no común, no numérica,
    no similar a los atributos del usuario) sobre la nueva.

    Efectos:
      - Contraseña actualizada.
      - must_change_password se limpia a False (si estaba en True, el usuario
        queda desbloqueado para operar el resto de la API — ver
        apps.core.views.enforce_password_change).
      - Invalida TODAS las refresh tokens vigentes emitidas ANTES de este
        cambio (blacklist de SimpleJWT), INCLUYENDO el refresh de la cookie
        actual del propio usuario: si la contraseña se filtró y alguien más
        tiene una sesión activa, cambiar la contraseña debe cerrarla.
        NOTA: este servicio NO rota la sesión propia — eso es responsabilidad
        de PasswordChangeApi (apps/authn/views.py), que tras un 200 emite un
        RefreshToken.for_user(user) nuevo y lo deposita en la cookie
        httpOnly, para que el usuario que acaba de autenticarse con su
        contraseña actual no quede desconectado en cuanto expire su access
        token en memoria. Contraste: el reset por un admin
        (platform_staff_password_reset en apps/plataforma/services.py)
        invalida TODO sin emitir sesión nueva — ahí es correcto, porque el
        admin no es quien sigue operando esa cuenta.
      - Registra PASSWORD_CHANGE en la bitácora (SIN contraseñas en metadata).

    Args:
        user:             Usuario autenticado que cambia su propia contraseña.
        current_password: Contraseña actual (se valida contra el hash).
        new_password:     Contraseña nueva (debe pasar los validadores de Django).

    Returns:
        El User actualizado.

    Raises:
        ValidationError: contraseña actual incorrecta, o la nueva no pasa los
            validadores de Django.
    """
    if not user.check_password(current_password):
        raise ValidationError("La contraseña actual no es correcta.")

    validate_password(new_password, user=user)

    with transaction.atomic():
        user.set_password(new_password)
        user.must_change_password = False
        user.save(update_fields=["password", "must_change_password"])

        # Invalidar sesiones activas emitidas antes del cambio (mismo patrón
        # que platform_staff_password_reset en apps/plataforma/services.py).
        from rest_framework_simplejwt.token_blacklist.models import (
            BlacklistedToken,
            OutstandingToken,
        )

        outstanding = OutstandingToken.objects.filter(user=user)
        for token in outstanding:
            BlacklistedToken.objects.get_or_create(token=token)

    membership = resolve_membership_for_user(user)
    audit_record(
        action=ActionType.PASSWORD_CHANGE,
        resource_type="User",
        actor=user,
        tenant=membership.tenant if membership is not None else None,
        resource_id=user.id,
        resource_repr=user.email,
        actor_role=(
            membership.role if membership is not None else getattr(user, "platform_role", "")
        ),
    )

    logger.info("password_change: user=%s", user.id)

    return user
