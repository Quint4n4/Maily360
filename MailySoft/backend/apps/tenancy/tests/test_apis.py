"""
Tests de las APIs de la app tenancy — gestión de miembros.

Endpoints:
    GET   /api/v1/miembros/               — lista de miembros.
    POST  /api/v1/miembros/               — crear miembro.
    PATCH /api/v1/miembros/<id>/          — actualizar miembro.
    POST  /api/v1/miembros/<id>/avatar/   — subir avatar de miembro.
    DELETE /api/v1/miembros/<id>/avatar/  — eliminar avatar.

Cubre:
- Permisos: solo owner/admin (MemberPermission). Roles no-admin → 403.
- Crear miembro: 201 en camino feliz, 400 en errores (rol inválido, email dup, pwd débil).
- Listar miembros: 200 con membresías del tenant; no-admin → 403.
- Actualizar miembro: cambio de rol → 200; contraseña débil → 400.
- Bloquear/reactivar: is_blocked=True en respuesta; auto-bloqueo → 400.
- Aislamiento multi-tenant: membership de tenant B inaccesible desde tenant A → 404.
- Avatares: PNG válido → 200; bytes de texto → 400 (no 500); sin campo → 400.

Patrón: AAA. Todas tocan BD → fixture db.
"""

import io
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIClient

from apps.tenancy.tests.conftest import role_context
from tests.factories import TenantFactory, TenantMembershipFactory, UserFactory

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

LIST_URL = "/api/v1/miembros/"


def _detail_url(membership_id: Any) -> str:
    return f"/api/v1/miembros/{membership_id}/"


def _avatar_url(membership_id: Any) -> str:
    return f"/api/v1/miembros/{membership_id}/avatar/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STRONG_PASSWORD = "Maily2026$Segura"
_WEAK_PASSWORD = "12345"


def _make_member_client(tenant: Any, role: str) -> tuple[APIClient, Any]:
    """Crea user con membresía real en BD y devuelve (APIClient autenticado, user)."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


def _create_payload(n: int = 0) -> dict[str, Any]:
    """Payload mínimo válido para POST /miembros/."""
    return {
        "email": f"nuevo-miembro-{n}@clinic.test",
        "first_name": "Nuevo",
        "last_name": "Miembro",
        "password": _STRONG_PASSWORD,
        "role": "doctor",
    }


def _make_png_file(name: str = "avatar.png") -> SimpleUploadedFile:
    """Genera un PNG válido en memoria usando Pillow."""
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), "gold").save(buf, "PNG")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/png")


def _make_jpeg_file(name: str = "avatar.jpg") -> SimpleUploadedFile:
    """Genera un JPEG válido en memoria usando Pillow."""
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), "red").save(buf, "JPEG")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/jpeg")


# ===========================================================================
# GET /api/v1/miembros/ — lista
# ===========================================================================


class TestMemberListApi:
    """GET /api/v1/miembros/ — lista de miembros de la clínica."""

    def test_list_members_returns_200_for_owner(self, db: None) -> None:
        """Owner recibe 200 en GET /miembros/."""
        # Arrange
        tenant = TenantFactory()
        client, user = _make_member_client(tenant, "owner")

        # Act
        with role_context(tenant, "owner"):
            response = client.get(LIST_URL)

        # Assert
        assert response.status_code == 200

    def test_list_members_returns_200_for_admin(self, db: None) -> None:
        """Admin recibe 200 en GET /miembros/."""
        # Arrange
        tenant = TenantFactory()
        client, user = _make_member_client(tenant, "admin")

        # Act
        with role_context(tenant, "admin"):
            response = client.get(LIST_URL)

        # Assert
        assert response.status_code == 200

    @pytest.mark.parametrize(
        "role",
        ["doctor", "nurse", "reception", "finance", "readonly"],
    )
    def test_list_members_returns_403_for_non_admin_roles(self, db: None, role: str) -> None:
        """Roles no-admin (doctor, nurse, reception, finance, readonly) reciben 403."""
        # Arrange
        tenant = TenantFactory()
        client, user = _make_member_client(tenant, role)

        # Act
        with role_context(tenant, role):
            response = client.get(LIST_URL)

        # Assert
        assert (
            response.status_code == 403
        ), f"GET /miembros/ con rol '{role}' esperaba 403, obtuvo {response.status_code}."

    def test_list_members_returns_401_without_auth(self, db: None) -> None:
        """Sin token devuelve 401."""
        # Arrange
        client = APIClient()

        # Act
        response = client.get(LIST_URL)

        # Assert
        assert response.status_code == 401

    def test_list_members_only_shows_own_tenant_members(self, db: None) -> None:
        """El listado solo contiene miembros del tenant activo, no del otro."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()

        # 2 miembros en A + 1 owner que hace el request
        client, owner_user = _make_member_client(tenant_a, "owner")
        TenantMembershipFactory.create_batch(2, tenant=tenant_a)

        # 3 miembros en B (no deben verse)
        TenantMembershipFactory.create_batch(3, tenant=tenant_b)

        # Act
        with role_context(tenant_a, "owner"):
            response = client.get(LIST_URL)

        # Assert — owner es 1 + 2 extras = 3 miembros de A; nunca los 3 de B
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert (
            len(data) == 3
        ), f"Fuga cross-tenant: se obtuvieron {len(data)} miembros en lugar de 3 de A."

    def test_list_members_response_includes_expected_fields(self, db: None) -> None:
        """Cada elemento de la lista incluye id, user, role, is_blocked."""
        # Arrange
        tenant = TenantFactory()
        client, _ = _make_member_client(tenant, "owner")

        # Act
        with role_context(tenant, "owner"):
            response = client.get(LIST_URL)

        # Assert
        assert response.status_code == 200
        item = response.json()[0]
        assert "id" in item
        assert "user" in item
        assert "role" in item
        assert "is_blocked" in item
        assert "sucursales" in item

    def test_list_members_includes_assigned_sucursales(self, db: None) -> None:
        """Fase 4 — el listado del equipo trae las sedes asignadas de cada miembro.

        Es el endpoint que EquipoTab.tsx consume para mostrar qué sucursal(es)
        administra cada usuario (apps.clinica.models.MembershipSucursal).
        """
        from apps.clinica.models import MembershipSucursal, Sucursal

        # Arrange
        tenant = TenantFactory()
        client, _ = _make_member_client(tenant, "owner")
        target = TenantMembershipFactory(tenant=tenant, role="admin", is_active=True)
        sucursal = Sucursal.all_objects.create(
            tenant=tenant, name="Sucursal Centro", is_active=True
        )
        MembershipSucursal.all_objects.create(tenant=tenant, membership=target, sucursal=sucursal)

        # Act
        with role_context(tenant, "owner"):
            response = client.get(LIST_URL)

        # Assert
        assert response.status_code == 200
        items = {item["id"]: item for item in response.json()}
        assert items[str(target.id)]["sucursales"] == [
            {"id": str(sucursal.id), "name": "Sucursal Centro"}
        ]

    def test_list_members_no_sucursales_returns_empty_list(self, db: None) -> None:
        """Un miembro sin ninguna sede asignada trae sucursales=[] (no null, no error)."""
        # Arrange
        tenant = TenantFactory()
        client, _ = _make_member_client(tenant, "owner")
        target = TenantMembershipFactory(tenant=tenant, role="reception", is_active=True)

        # Act
        with role_context(tenant, "owner"):
            response = client.get(LIST_URL)

        # Assert
        items = {item["id"]: item for item in response.json()}
        assert items[str(target.id)]["sucursales"] == []


# ===========================================================================
# POST /api/v1/miembros/ — crear miembro
# ===========================================================================


class TestMemberCreateApi:
    """POST /api/v1/miembros/ — alta de miembro."""

    def test_create_member_returns_201(self, db: None) -> None:
        """Owner con payload válido recibe 201 y la membresía en la respuesta."""
        # Arrange
        tenant = TenantFactory()
        client, _ = _make_member_client(tenant, "owner")
        payload = _create_payload(1)

        # Act
        with role_context(tenant, "owner"):
            response = client.post(LIST_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 201
        data = response.json()
        assert data["role"] == "doctor"
        assert data["is_blocked"] is False

    def test_create_member_invalid_role_returns_400(self, db: None) -> None:
        """Rol no válido devuelve 400."""
        # Arrange
        tenant = TenantFactory()
        client, _ = _make_member_client(tenant, "owner")
        payload = {**_create_payload(2), "role": "superadmin"}

        # Act
        with role_context(tenant, "owner"):
            response = client.post(LIST_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 400

    def test_create_member_duplicate_email_returns_400(self, db: None) -> None:
        """Email ya registrado en la plataforma devuelve 400 con mensaje."""
        # Arrange
        tenant = TenantFactory()
        client, _ = _make_member_client(tenant, "owner")
        existing = UserFactory(email="dup@clinic.test")
        payload = {**_create_payload(3), "email": existing.email}

        # Act
        with role_context(tenant, "owner"):
            response = client.post(LIST_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 400
        assert "correo" in str(response.json()).lower() or "detail" in response.json()

    def test_create_member_weak_password_returns_400(self, db: None) -> None:
        """Contraseña débil devuelve 400, no 201."""
        # Arrange
        tenant = TenantFactory()
        client, _ = _make_member_client(tenant, "owner")
        payload = {**_create_payload(4), "password": _WEAK_PASSWORD}

        # Act
        with role_context(tenant, "owner"):
            response = client.post(LIST_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 400

    def test_create_member_missing_email_returns_400(self, db: None) -> None:
        """Falta de campo requerido (email) devuelve 400."""
        # Arrange
        tenant = TenantFactory()
        client, _ = _make_member_client(tenant, "owner")
        payload = {k: v for k, v in _create_payload(5).items() if k != "email"}

        # Act
        with role_context(tenant, "owner"):
            response = client.post(LIST_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 400

    def test_create_member_non_admin_returns_403(self, db: None) -> None:
        """Rol no-admin (doctor) recibe 403 al intentar crear un miembro."""
        # Arrange
        tenant = TenantFactory()
        client, _ = _make_member_client(tenant, "doctor")

        # Act
        with role_context(tenant, "doctor"):
            response = client.post(LIST_URL, data=_create_payload(6), format="json")

        # Assert
        assert response.status_code == 403

    def test_create_member_persists_to_database(self, db: None) -> None:
        """El miembro creado vía API existe en BD."""
        from apps.tenancy.models import TenantMembership

        # Arrange
        tenant = TenantFactory()
        client, _ = _make_member_client(tenant, "owner")
        payload = _create_payload(7)

        # Act
        with role_context(tenant, "owner"):
            response = client.post(LIST_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 201
        membership_id = response.json()["id"]
        assert TenantMembership.objects.filter(id=membership_id).exists()


# ===========================================================================
# PATCH /api/v1/miembros/<id>/ — actualizar miembro
# ===========================================================================


class TestMemberPatchApi:
    """PATCH /api/v1/miembros/<id>/ — actualización de miembro."""

    def test_patch_changes_role_returns_200(self, db: None) -> None:
        """Cambiar el rol de un miembro devuelve 200 y el nuevo rol en la respuesta."""
        # Arrange
        tenant = TenantFactory()
        client, _ = _make_member_client(tenant, "owner")
        target = TenantMembershipFactory(tenant=tenant, role="doctor", is_active=True)

        # Act
        with role_context(tenant, "owner"):
            response = client.patch(_detail_url(target.id), data={"role": "nurse"}, format="json")

        # Assert
        assert response.status_code == 200
        assert response.json()["role"] == "nurse"

    def test_patch_persists_role_change_in_db(self, db: None) -> None:
        """El cambio de rol persiste en BD tras el PATCH."""
        # Arrange
        tenant = TenantFactory()
        client, _ = _make_member_client(tenant, "owner")
        target = TenantMembershipFactory(tenant=tenant, role="doctor", is_active=True)

        # Act
        with role_context(tenant, "owner"):
            client.patch(_detail_url(target.id), data={"role": "admin"}, format="json")

        # Assert
        target.refresh_from_db()
        assert target.role == "admin"

    def test_patch_weak_password_returns_400(self, db: None) -> None:
        """Restablecer con contraseña débil devuelve 400."""
        # Arrange
        tenant = TenantFactory()
        client, _ = _make_member_client(tenant, "owner")
        target = TenantMembershipFactory(tenant=tenant, is_active=True)

        # Act
        with role_context(tenant, "owner"):
            response = client.patch(
                _detail_url(target.id),
                data={"password": _WEAK_PASSWORD},
                format="json",
            )

        # Assert
        assert response.status_code == 400

    def test_patch_strong_password_returns_200_and_login_works(self, db: None) -> None:
        """Restablecer contraseña robusta devuelve 200 y el nuevo usuario puede iniciar sesión."""
        # Arrange
        tenant = TenantFactory()
        client, _ = _make_member_client(tenant, "owner")
        target_user = UserFactory(email="reset@clinic.test")
        target_user.set_password("OldPassword123!")
        target_user.save()
        target = TenantMembershipFactory(user=target_user, tenant=tenant, is_active=True)
        new_password = "NuevaPassword2026$$"

        # Act
        with role_context(tenant, "owner"):
            response = client.patch(
                _detail_url(target.id),
                data={"password": new_password},
                format="json",
            )

        # Assert — PATCH exitoso
        assert response.status_code == 200

        # Assert — login con nueva contraseña funciona
        login_client = APIClient()
        login_response = login_client.post(
            "/api/v1/auth/login/",
            data={"email": "reset@clinic.test", "password": new_password},
            format="json",
        )
        assert (
            login_response.status_code == 200
        ), f"Login con nueva contraseña falló: {login_response.json()}"

    def test_patch_blocked_true_deactivates_user_and_sets_is_blocked(self, db: None) -> None:
        """blocked=True → is_blocked=True en la respuesta; user.is_active=False en BD."""
        from django.contrib.auth import get_user_model

        User = get_user_model()

        # Arrange
        tenant = TenantFactory()
        client, actor_user = _make_member_client(tenant, "owner")
        target_user = UserFactory(is_active=True)
        target = TenantMembershipFactory(user=target_user, tenant=tenant, is_active=True)

        # Act
        with role_context(tenant, "owner"):
            response = client.patch(_detail_url(target.id), data={"blocked": True}, format="json")

        # Assert — respuesta
        assert response.status_code == 200
        assert response.json()["is_blocked"] is True

        # Assert — BD
        target_user.refresh_from_db()
        assert target_user.is_active is False

    def test_patch_self_block_returns_400(self, db: None) -> None:
        """Un actor no puede bloquearse a sí mismo; debe recibir 400."""
        # Arrange
        tenant = TenantFactory()
        actor_user = UserFactory()
        actor_membership = TenantMembershipFactory(
            user=actor_user, tenant=tenant, role="owner", is_active=True
        )
        client = APIClient()
        client.force_authenticate(user=actor_user)

        # Act — el actor intenta bloquearse a sí mismo
        with role_context(tenant, "owner"):
            response = client.patch(
                _detail_url(actor_membership.id),
                data={"blocked": True},
                format="json",
            )

        # Assert
        assert response.status_code == 400

    def test_patch_empty_body_returns_400(self, db: None) -> None:
        """PATCH sin campos válidos devuelve 400."""
        # Arrange
        tenant = TenantFactory()
        client, _ = _make_member_client(tenant, "owner")
        target = TenantMembershipFactory(tenant=tenant, is_active=True)

        # Act
        with role_context(tenant, "owner"):
            response = client.patch(_detail_url(target.id), data={}, format="json")

        # Assert
        assert response.status_code == 400

    def test_patch_other_tenant_membership_returns_404(self, db: None) -> None:
        """PATCH a membresía de otro tenant devuelve 404 (aislamiento multi-tenant)."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        client, _ = _make_member_client(tenant_a, "owner")
        member_b = TenantMembershipFactory(tenant=tenant_b, role="doctor", is_active=True)

        # Act — contexto de A, intentando editar membresía de B
        with role_context(tenant_a, "owner"):
            response = client.patch(_detail_url(member_b.id), data={"role": "nurse"}, format="json")

        # Assert — 404, no 403 (no revelar existencia)
        assert response.status_code == 404, (
            f"Se esperaba 404 para membership de otro tenant, obtuvo {response.status_code}. "
            "BUG CRÍTICO de aislamiento multi-tenant."
        )

    def test_patch_non_admin_returns_403(self, db: None) -> None:
        """Rol no-admin (doctor) recibe 403 al intentar PATCH."""
        # Arrange
        tenant = TenantFactory()
        client, _ = _make_member_client(tenant, "doctor")
        target = TenantMembershipFactory(tenant=tenant, is_active=True)

        # Act
        with role_context(tenant, "doctor"):
            response = client.patch(_detail_url(target.id), data={"role": "nurse"}, format="json")

        # Assert
        assert response.status_code == 403


# ===========================================================================
# POST + DELETE /api/v1/miembros/<id>/avatar/
# ===========================================================================


class TestMemberAvatarApi:
    """Avatar de miembros — POST y DELETE."""

    def test_upload_png_avatar_returns_200_and_avatar_url(
        self, db: None, tmp_path: "Any", settings: "Any"
    ) -> None:
        """Subir un PNG válido para un miembro devuelve 200 y avatar no nulo."""
        settings.MEDIA_ROOT = str(tmp_path)

        # Arrange
        tenant = TenantFactory()
        client, _ = _make_member_client(tenant, "owner")
        target_user = UserFactory()
        target = TenantMembershipFactory(user=target_user, tenant=tenant, is_active=True)

        # Act
        with role_context(tenant, "owner"):
            response = client.post(
                _avatar_url(target.id),
                {"avatar": _make_png_file()},
                format="multipart",
            )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["user"]["avatar"] is not None

    def test_upload_jpeg_avatar_returns_200(
        self, db: None, tmp_path: "Any", settings: "Any"
    ) -> None:
        """Subir un JPEG válido para un miembro devuelve 200."""
        settings.MEDIA_ROOT = str(tmp_path)

        # Arrange
        tenant = TenantFactory()
        client, _ = _make_member_client(tenant, "owner")
        target = TenantMembershipFactory(tenant=tenant, is_active=True)

        # Act
        with role_context(tenant, "owner"):
            response = client.post(
                _avatar_url(target.id),
                {"avatar": _make_jpeg_file()},
                format="multipart",
            )

        # Assert
        assert response.status_code == 200

    def test_upload_non_image_bytes_returns_400_not_500(
        self, db: None, tmp_path: "Any", settings: "Any"
    ) -> None:
        """CRÍTICO: bytes de texto (no imagen) devuelven 400, NO 500.

        Bug histórico: Pillow lanzaba SyntaxError/UnidentifiedImageError sin
        atrapar y el servidor devolvía 500. validate_avatar debe atrapar
        CUALQUIER excepción de Pillow y relevarla como ValidationError → 400.
        """
        settings.MEDIA_ROOT = str(tmp_path)

        # Arrange
        tenant = TenantFactory()
        client, _ = _make_member_client(tenant, "owner")
        target = TenantMembershipFactory(tenant=tenant, is_active=True)

        fake_file = SimpleUploadedFile(
            "notanimage.jpg",
            b"esto no es una imagen, es texto plano con bytes invalidos \x00\x01",
            content_type="image/jpeg",
        )

        # Act
        with role_context(tenant, "owner"):
            response = client.post(
                _avatar_url(target.id),
                {"avatar": fake_file},
                format="multipart",
            )

        # Assert — 400, nunca 500
        assert response.status_code == 400, (
            f"Se esperaba 400 para bytes inválidos, obtuvo {response.status_code}. "
            "BUG CRÍTICO: validate_avatar debe atrapar TODAS las excepciones de Pillow."
        )

    def test_upload_gif_returns_400(self, db: None, tmp_path: "Any", settings: "Any") -> None:
        """GIF (formato no permitido) devuelve 400."""
        settings.MEDIA_ROOT = str(tmp_path)

        # Arrange
        tenant = TenantFactory()
        client, _ = _make_member_client(tenant, "owner")
        target = TenantMembershipFactory(tenant=tenant, is_active=True)

        buf = io.BytesIO()
        Image.new("RGB", (20, 20), "blue").save(buf, "GIF")
        buf.seek(0)
        gif_file = SimpleUploadedFile("avatar.gif", buf.read(), content_type="image/gif")

        # Act
        with role_context(tenant, "owner"):
            response = client.post(
                _avatar_url(target.id),
                {"avatar": gif_file},
                format="multipart",
            )

        # Assert
        assert response.status_code == 400

    def test_upload_avatar_without_field_returns_400(self, db: None) -> None:
        """POST sin el campo 'avatar' devuelve 400."""
        # Arrange
        tenant = TenantFactory()
        client, _ = _make_member_client(tenant, "owner")
        target = TenantMembershipFactory(tenant=tenant, is_active=True)

        # Act
        with role_context(tenant, "owner"):
            response = client.post(_avatar_url(target.id), data={}, format="multipart")

        # Assert
        assert response.status_code == 400

    def test_upload_avatar_non_admin_returns_403(self, db: None) -> None:
        """Rol no-admin recibe 403 al intentar subir avatar de miembro."""
        # Arrange
        tenant = TenantFactory()
        client, _ = _make_member_client(tenant, "doctor")
        target = TenantMembershipFactory(tenant=tenant, is_active=True)

        # Act
        with role_context(tenant, "doctor"):
            response = client.post(
                _avatar_url(target.id),
                {"avatar": _make_png_file()},
                format="multipart",
            )

        # Assert
        assert response.status_code == 403

    def test_delete_avatar_returns_200_and_avatar_is_null(
        self, db: None, tmp_path: "Any", settings: "Any"
    ) -> None:
        """DELETE /miembros/<id>/avatar/ elimina la foto; avatar queda nulo.

        MemberPermission incluye 'DELETE': MANAGE_ROLES, así que owner/admin
        pueden quitar el avatar de un miembro.
        """
        settings.MEDIA_ROOT = str(tmp_path)

        # Arrange — subir primero
        tenant = TenantFactory()
        client, _ = _make_member_client(tenant, "owner")
        target = TenantMembershipFactory(tenant=tenant, is_active=True)

        with role_context(tenant, "owner"):
            post_resp = client.post(
                _avatar_url(target.id),
                {"avatar": _make_png_file()},
                format="multipart",
            )
        assert post_resp.status_code == 200

        # Act — eliminar (dentro del mismo role_context para mantener el tenant)
        with role_context(tenant, "owner"):
            response = client.delete(_avatar_url(target.id))

        # Assert — 200 y el avatar queda nulo (en la respuesta y en BD).
        assert response.status_code == 200
        assert response.data["user"]["avatar"] is None
        target.user.refresh_from_db()
        assert not target.user.avatar
