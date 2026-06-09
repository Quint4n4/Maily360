"""
Tests de servicios de la app tenancy — member_create y member_update.

Cubre:
- member_create: camino feliz, rol inválido, email duplicado, password débil,
  auditoría MEMBER_CREATE, is_active=True, is_platform_staff=False.
- member_update: cambio de nombre, cambio de rol, cambio de rol inválido,
  restablecimiento de contraseña (robusta y débil), bloqueo/reactivación,
  auto-bloqueo rechazado.

Patrón: AAA (Arrange-Act-Assert). Todas tocan BD → fixture db.
"""

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.audit.models import ActionType, AuditLog
from apps.tenancy.models import TenantMembership
from apps.tenancy.services import member_create, member_update
from tests.factories import TenantFactory, TenantMembershipFactory, UserFactory

User = get_user_model()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STRONG_PASSWORD = "Maily2026$Segura"
_WEAK_PASSWORD = "12345"


def _create_member(tenant: Any, actor: Any, **overrides: Any) -> TenantMembership:
    """Llama a member_create con datos mínimos válidos y aplica overrides."""
    defaults: dict[str, Any] = {
        "email": f"miembro-{id(overrides)}@clinic.test",
        "first_name": "Lucia",
        "last_name": "Ríos",
        "password": _STRONG_PASSWORD,
        "role": "doctor",
    }
    defaults.update(overrides)
    return member_create(tenant=tenant, actor=actor, **defaults)


# ===========================================================================
# member_create
# ===========================================================================


class TestMemberCreate:
    """Casos de uso del servicio member_create."""

    def test_member_create_happy_path_returns_membership(self, db: None) -> None:
        """Crear un miembro con datos válidos devuelve la TenantMembership activa."""
        # Arrange
        tenant = TenantFactory()
        actor = UserFactory()

        # Act
        membership = _create_member(tenant, actor, email="nuevo@clinic.test")

        # Assert
        assert membership.pk is not None
        assert membership.tenant_id == tenant.id
        assert membership.role == "doctor"
        assert membership.is_active is True

    def test_member_create_user_is_active_and_not_platform_staff(self, db: None) -> None:
        """El usuario creado tiene is_active=True e is_platform_staff=False."""
        # Arrange
        tenant = TenantFactory()
        actor = UserFactory()

        # Act
        membership = _create_member(tenant, actor, email="nuevo2@clinic.test")

        # Assert
        user = membership.user
        assert user.is_active is True
        assert user.is_platform_staff is False

    def test_member_create_password_is_hashed(self, db: None) -> None:
        """La contraseña se almacena hasheada; check_password valida el texto plano."""
        # Arrange
        tenant = TenantFactory()
        actor = UserFactory()

        # Act
        membership = _create_member(
            tenant, actor, email="hash@clinic.test", password=_STRONG_PASSWORD
        )

        # Assert — el hash no es el texto plano
        assert membership.user.password != _STRONG_PASSWORD
        assert membership.user.check_password(_STRONG_PASSWORD)

    def test_member_create_password_can_be_used_for_login(self, db: None) -> None:
        """La contraseña creada permite hacer login real vía JWT."""
        from rest_framework.test import APIClient

        # Arrange
        tenant = TenantFactory()
        actor = UserFactory()
        email = "logintest@clinic.test"
        password = _STRONG_PASSWORD
        _create_member(tenant, actor, email=email, password=password)

        # Act — obtener JWT real
        client = APIClient()
        response = client.post(
            "/api/v1/auth/login/",
            data={"email": email, "password": password},
            format="json",
        )

        # Assert — 200 y token en la respuesta
        assert response.status_code == 200, (
            f"Login con nueva cuenta fallido: {response.json()}"
        )
        assert "access" in response.json()

    def test_member_create_invalid_role_raises_validation_error(self, db: None) -> None:
        """Rol no registrado en TenantMembership.Role debe lanzar ValidationError."""
        # Arrange
        tenant = TenantFactory()
        actor = UserFactory()

        # Act / Assert
        with pytest.raises(ValidationError, match="[Rr]ol"):
            _create_member(tenant, actor, email="rol@clinic.test", role="superheroe")

    @pytest.mark.parametrize(
        "role",
        ["owner", "admin", "doctor", "nurse", "reception", "finance", "readonly"],
    )
    def test_member_create_all_valid_roles_are_accepted(self, db: None, role: str) -> None:
        """Cada rol válido de la plataforma puede usarse al crear un miembro."""
        # Arrange
        tenant = TenantFactory()
        actor = UserFactory()
        email = f"rol-{role}@clinic.test"

        # Act — no debe lanzar
        membership = _create_member(tenant, actor, email=email, role=role)

        # Assert
        membership.refresh_from_db()
        assert membership.role == role

    def test_member_create_duplicate_email_raises_validation_error(self, db: None) -> None:
        """Email ya registrado en la plataforma debe lanzar ValidationError con mensaje claro."""
        # Arrange
        existing_user = UserFactory(email="existente@clinic.test")
        tenant = TenantFactory()
        actor = UserFactory()

        # Act / Assert
        with pytest.raises(ValidationError, match="correo"):
            _create_member(tenant, actor, email=existing_user.email)

    def test_member_create_weak_password_raises_validation_error(self, db: None) -> None:
        """Contraseña débil (demasiado corta/numérica) debe lanzar ValidationError."""
        # Arrange
        tenant = TenantFactory()
        actor = UserFactory()

        # Act / Assert — "12345" es demasiado corta y totalmente numérica
        with pytest.raises(ValidationError):
            _create_member(tenant, actor, email="debil@clinic.test", password=_WEAK_PASSWORD)

    def test_member_create_short_password_raises_validation_error(self, db: None) -> None:
        """Contraseña de menos de 10 caracteres debe lanzar ValidationError."""
        # Arrange
        tenant = TenantFactory()
        actor = UserFactory()

        # Act / Assert
        with pytest.raises(ValidationError):
            _create_member(tenant, actor, email="corta@clinic.test", password="Short1!")

    def test_member_create_common_password_raises_validation_error(self, db: None) -> None:
        """Contraseña muy común ("password1234") debe lanzar ValidationError."""
        # Arrange
        tenant = TenantFactory()
        actor = UserFactory()

        # Act / Assert
        with pytest.raises(ValidationError):
            _create_member(tenant, actor, email="comun@clinic.test", password="password1234")

    def test_member_create_audits_member_create_action(self, db: None) -> None:
        """Crear un miembro debe registrar una entrada de auditoría MEMBER_CREATE."""
        # Arrange
        tenant = TenantFactory()
        actor = UserFactory()

        # Act
        membership = _create_member(tenant, actor, email="audit@clinic.test")

        # Assert — buscar el audit log por acción y resource_id
        log = AuditLog.all_objects.filter(
            action=ActionType.MEMBER_CREATE,
            resource_id=membership.id,
            tenant=tenant,
            actor=actor,
        ).first()
        assert log is not None, "No se encontró el AuditLog MEMBER_CREATE esperado."
        assert log.metadata.get("role") == membership.role

    def test_member_create_does_not_persist_on_validation_failure(self, db: None) -> None:
        """Si member_create falla (password débil), NO debe quedar ningún User en BD."""
        # Arrange
        tenant = TenantFactory()
        actor = UserFactory()
        email = "nopersist@clinic.test"
        initial_count = User.objects.count()

        # Act / Assert
        with pytest.raises(ValidationError):
            _create_member(tenant, actor, email=email, password="12345")

        # La BD no creció
        assert User.objects.count() == initial_count

    def test_member_create_normalizes_email_to_lowercase(self, db: None) -> None:
        """El email se normaliza a minúsculas antes de guardar."""
        # Arrange
        tenant = TenantFactory()
        actor = UserFactory()

        # Act
        membership = _create_member(tenant, actor, email="MAYUS@CLINIC.TEST")

        # Assert
        assert membership.user.email == "mayus@clinic.test"

    def test_member_create_duplicate_email_case_insensitive(self, db: None) -> None:
        """Email en mayúsculas que ya existe en minúsculas debe rechazarse."""
        # Arrange
        UserFactory(email="existente2@clinic.test")
        tenant = TenantFactory()
        actor = UserFactory()

        # Act / Assert
        with pytest.raises(ValidationError, match="correo"):
            _create_member(tenant, actor, email="EXISTENTE2@CLINIC.TEST")


# ===========================================================================
# member_update
# ===========================================================================


class TestMemberUpdate:
    """Casos de uso del servicio member_update."""

    def test_member_update_changes_first_name_and_last_name(self, db: None) -> None:
        """Actualizar first_name y last_name persiste en el usuario."""
        # Arrange
        tenant = TenantFactory()
        actor = UserFactory()
        membership = TenantMembershipFactory(
            tenant=tenant, role="doctor", is_active=True
        )

        # Act
        member_update(
            membership=membership,
            actor=actor,
            first_name="Nuevo",
            last_name="Apellido",
        )

        # Assert
        membership.user.refresh_from_db()
        assert membership.user.first_name == "Nuevo"
        assert membership.user.last_name == "Apellido"

    def test_member_update_changes_role(self, db: None) -> None:
        """Cambiar el rol de un miembro persiste en la membresía."""
        # Arrange
        tenant = TenantFactory()
        actor = UserFactory()
        membership = TenantMembershipFactory(tenant=tenant, role="doctor", is_active=True)

        # Act
        updated = member_update(membership=membership, actor=actor, role="admin")

        # Assert
        updated.refresh_from_db()
        assert updated.role == "admin"

    def test_member_update_invalid_role_raises_validation_error(self, db: None) -> None:
        """Cambiar a un rol inexistente debe lanzar ValidationError."""
        # Arrange
        tenant = TenantFactory()
        actor = UserFactory()
        membership = TenantMembershipFactory(tenant=tenant, role="doctor", is_active=True)

        # Act / Assert
        with pytest.raises(ValidationError, match="[Rr]ol"):
            member_update(membership=membership, actor=actor, role="dios")

    def test_member_update_resets_password_with_strong_password(self, db: None) -> None:
        """Restablecer la contraseña con una contraseña robusta persiste el nuevo hash."""
        # Arrange
        tenant = TenantFactory()
        actor = UserFactory()
        membership = TenantMembershipFactory(tenant=tenant, is_active=True)

        new_password = "NuevaPassword2026$"

        # Act
        member_update(membership=membership, actor=actor, password=new_password)

        # Assert — la nueva contraseña funciona
        membership.user.refresh_from_db()
        assert membership.user.check_password(new_password)

    def test_member_update_weak_password_raises_validation_error(self, db: None) -> None:
        """Restablecer con contraseña débil debe lanzar ValidationError sin modificar el user."""
        # Arrange
        tenant = TenantFactory()
        actor = UserFactory()
        membership = TenantMembershipFactory(tenant=tenant, is_active=True)
        # La contraseña original es "password-segura-123" (de UserFactory)

        # Act / Assert
        with pytest.raises(ValidationError):
            member_update(membership=membership, actor=actor, password=_WEAK_PASSWORD)

        # La contraseña original sigue siendo válida
        membership.user.refresh_from_db()
        assert membership.user.check_password("password-segura-123")

    def test_member_update_blocked_true_deactivates_user(self, db: None) -> None:
        """blocked=True pone user.is_active=False (no puede iniciar sesión)."""
        # Arrange
        tenant = TenantFactory()
        actor = UserFactory()
        target_user = UserFactory(is_active=True)
        membership = TenantMembershipFactory(
            user=target_user, tenant=tenant, is_active=True
        )

        # Act
        member_update(membership=membership, actor=actor, blocked=True)

        # Assert
        target_user.refresh_from_db()
        assert target_user.is_active is False

    def test_member_update_blocked_false_reactivates_user(self, db: None) -> None:
        """blocked=False restaura user.is_active=True."""
        # Arrange
        tenant = TenantFactory()
        actor = UserFactory()
        target_user = UserFactory(is_active=False)
        membership = TenantMembershipFactory(
            user=target_user, tenant=tenant, is_active=True
        )

        # Act
        member_update(membership=membership, actor=actor, blocked=False)

        # Assert
        target_user.refresh_from_db()
        assert target_user.is_active is True

    def test_member_update_self_block_raises_validation_error(self, db: None) -> None:
        """Un actor no puede bloquear su propia membresía (blocked=True, membership.user == actor)."""
        # Arrange
        tenant = TenantFactory()
        actor = UserFactory()
        membership = TenantMembershipFactory(user=actor, tenant=tenant, is_active=True)

        # Act / Assert
        with pytest.raises(ValidationError, match="[Bb]loquear"):
            member_update(membership=membership, actor=actor, blocked=True)

    def test_member_update_self_unblock_is_allowed(self, db: None) -> None:
        """Un actor SÍ puede desbloquearse a sí mismo (blocked=False)."""
        # Arrange
        tenant = TenantFactory()
        actor = UserFactory(is_active=False)
        membership = TenantMembershipFactory(user=actor, tenant=tenant, is_active=True)

        # Act — no debe lanzar
        member_update(membership=membership, actor=actor, blocked=False)

        # Assert
        actor.refresh_from_db()
        assert actor.is_active is True

    def test_member_update_blocked_user_cannot_login(self, db: None) -> None:
        """Un usuario bloqueado no puede hacer login (JWT devuelve error)."""
        from rest_framework.test import APIClient

        # Arrange
        tenant = TenantFactory()
        actor = UserFactory()
        target_user = UserFactory(email="bloqueado@clinic.test", is_active=True)
        # Establecer contraseña conocida para el login
        target_user.set_password("PasswordSegura2026$")
        target_user.save()
        membership = TenantMembershipFactory(
            user=target_user, tenant=tenant, is_active=True
        )

        # Act — bloquear
        member_update(membership=membership, actor=actor, blocked=True)

        # Intentar login
        client = APIClient()
        response = client.post(
            "/api/v1/auth/login/",
            data={"email": "bloqueado@clinic.test", "password": "PasswordSegura2026$"},
            format="json",
        )

        # Assert — 401 porque is_active=False
        assert response.status_code in (400, 401), (
            f"Usuario bloqueado consiguió login: status {response.status_code}."
        )

    def test_member_update_serializer_exposes_is_blocked_true_when_deactivated(
        self, db: None
    ) -> None:
        """is_blocked en el serializer de salida es True cuando user.is_active=False."""
        from apps.tenancy.serializers import MemberOutputSerializer

        # Arrange
        tenant = TenantFactory()
        actor = UserFactory()
        target_user = UserFactory(is_active=True)
        membership = TenantMembershipFactory(
            user=target_user, tenant=tenant, is_active=True
        )

        # Act
        member_update(membership=membership, actor=actor, blocked=True)

        # Assert — releer desde BD y serializar
        membership.refresh_from_db()
        data = MemberOutputSerializer(membership).data
        assert data["is_blocked"] is True

    def test_member_update_audits_member_block_when_blocking(self, db: None) -> None:
        """Bloquear un miembro registra una entrada MEMBER_BLOCK en la bitácora."""
        # Arrange
        tenant = TenantFactory()
        actor = UserFactory()
        target_user = UserFactory(is_active=True)
        membership = TenantMembershipFactory(
            user=target_user, tenant=tenant, is_active=True
        )

        # Act
        member_update(membership=membership, actor=actor, blocked=True)

        # Assert
        log = AuditLog.all_objects.filter(
            action=ActionType.MEMBER_BLOCK,
            resource_id=membership.id,
            actor=actor,
        ).first()
        assert log is not None
        assert log.metadata.get("blocked") is True

    def test_member_update_audits_password_change(self, db: None) -> None:
        """Restablecer contraseña registra MEMBER_PASSWORD en la bitácora."""
        # Arrange
        tenant = TenantFactory()
        actor = UserFactory()
        membership = TenantMembershipFactory(tenant=tenant, is_active=True)

        # Act
        member_update(membership=membership, actor=actor, password="NuevaPwd2026$$")

        # Assert
        log = AuditLog.all_objects.filter(
            action=ActionType.MEMBER_PASSWORD,
            resource_id=membership.id,
        ).first()
        assert log is not None
