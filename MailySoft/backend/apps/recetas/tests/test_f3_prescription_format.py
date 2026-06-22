"""
Tests F3 — PrescriptionFormat: modelo, servicios, selectores, API, RLS, IDOR.

Cobertura objetivo >= 80% del código nuevo de F3:

Modelo:
  - clean() valida accent_color con regex.
  - clean() rechaza claves desconocidas en sections.
  - get_sections_full() rellena flags faltantes con True.
  - font_family devuelve el CSS correcto según font choice.

Servicios:
  - prescription_format_create: crea correctamente.
  - prescription_format_create: falla con accent_color inválido.
  - prescription_format_create: falla con base_layout inválido.
  - prescription_format_create: falla con sections inválido.
  - prescription_format_create: falla si doctor no pertenece al tenant.
  - prescription_format_create: is_default=True desmarca el anterior.
  - prescription_format_update: actualiza campos.
  - prescription_format_update: rechaza campos inmutables.
  - prescription_format_update: is_authorized rechazado sin is_admin.
  - prescription_format_delete: baja lógica + cleared is_default.
  - prescription_format_delete: falla si ya inactivo.

Selectores:
  - prescription_format_list: solo devuelve formatos activos del tenant.
  - prescription_format_get: devuelve el correcto; DoesNotExist para otro tenant.
  - prescription_format_resolve: prioridad override_id > médico autorizado > default > fábrica.
  - prescription_format_resolve: layout_override construye objeto en memoria.

PDF / contexto:
  - _build_context incluye accent, font_family, sections con formato custom.
  - prescription_pdf_build genera %PDF con formato custom (accent + secciones).
  - prescription_pdf_build sin formato → usa fábrica (accent default).

API:
  - GET /recetas/formatos/ → 200, lista de formatos del tenant.
  - POST /recetas/formatos/ → 201 para owner/admin.
  - POST /recetas/formatos/ → 403 para reception/finance.
  - GET /recetas/formatos/<id>/ → 200.
  - PATCH /recetas/formatos/<id>/ → 200 para owner.
  - DELETE /recetas/formatos/<id>/ → 204 para owner.
  - DELETE /recetas/formatos/<id>/ → 403 para doctor.
  - PATCH is_authorized por doctor → 400 (solo admin).

RLS / IDOR:
  - GET /recetas/formatos/<id>/ de otro tenant → 404.
  - prescription_format_get con UUID de otro tenant → DoesNotExist.
"""

import uuid as _uuid
from typing import Any
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.recetas.models import PrescriptionFormat, SECTIONS_KEYS
from apps.recetas.pdf import _build_context, prescription_pdf_build
from apps.recetas.selectors import (
    prescription_format_get,
    prescription_format_list,
    prescription_format_resolve,
)
from apps.recetas.services import (
    prescription_format_create,
    prescription_format_delete,
    prescription_format_update,
)
from apps.recetas.tests.conftest import api_tenant_ctx, tenant_ctx
from apps.tenancy.models import TenantMembership
from tests.factories import (
    DoctorFactory,
    PrescriptionFactory,
    PrescriptionFormatFactory,
    PrescriptionItemFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

FORMAT_LIST_URL = "/api/v1/recetas/formatos/"
FORMAT_DETAIL_URL = "/api/v1/recetas/formatos/{format_id}/"


def _format_detail_url(fmt_id: Any) -> str:
    return FORMAT_DETAIL_URL.format(format_id=str(fmt_id))


def _make_user_role(tenant: Any, role: str) -> tuple[Any, Any]:
    """Crea usuario con membresía en el tenant y opcionalmente perfil Doctor."""
    user = UserFactory()
    membership = TenantMembershipFactory(user=user, tenant=tenant, role=role)
    if role == TenantMembership.Role.DOCTOR:
        DoctorFactory(tenant=tenant, membership=membership)
    return user, membership


# ---------------------------------------------------------------------------
# Modelo — validación y propiedades
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_clean_accent_color_invalid() -> None:
    """clean() lanza ValidationError si accent_color no es #RRGGBB."""
    fmt = PrescriptionFormatFactory.build(accent_color="rojo")
    with pytest.raises(ValidationError, match="RRGGBB"):
        fmt.clean()


@pytest.mark.django_db
def test_clean_accent_color_valid() -> None:
    """clean() no lanza si accent_color es válido."""
    fmt = PrescriptionFormatFactory.build(accent_color="#1A2B3C")
    fmt.clean()  # no debe lanzar


@pytest.mark.django_db
def test_clean_sections_unknown_key() -> None:
    """clean() rechaza claves desconocidas en sections."""
    fmt = PrescriptionFormatFactory.build(sections={"unknown_key": True})
    with pytest.raises(ValidationError, match="unknown_key"):
        fmt.clean()


@pytest.mark.django_db
def test_clean_sections_non_bool_value() -> None:
    """clean() rechaza valores no booleanos en sections."""
    fmt = PrescriptionFormatFactory.build(sections={"signos": "yes"})
    with pytest.raises(ValidationError):
        fmt.clean()


@pytest.mark.django_db
def test_get_sections_full_fills_defaults() -> None:
    """get_sections_full() rellena flags faltantes con True."""
    fmt = PrescriptionFormatFactory.build(sections={"signos": False})
    full = fmt.get_sections_full()
    assert full["signos"] is False
    # los demás deben estar True (defaults)
    for key in SECTIONS_KEYS - {"signos"}:
        assert full[key] is True


@pytest.mark.django_db
def test_font_family_helvetica() -> None:
    fmt = PrescriptionFormatFactory.build(font="helvetica")
    assert "Helvetica" in fmt.font_family


@pytest.mark.django_db
def test_font_family_times() -> None:
    fmt = PrescriptionFormatFactory.build(font="times")
    assert "Times" in fmt.font_family


# ---------------------------------------------------------------------------
# Servicios — prescription_format_create
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_format_create_ok() -> None:
    """prescription_format_create crea el formato correctamente."""
    tenant = TenantFactory()
    user = UserFactory()
    with tenant_ctx(tenant):
        fmt = prescription_format_create(
            tenant=tenant,
            user=user,
            name="Mi formato",
            base_layout="digital",
            accent_color="#AABBCC",
            font="times",
            sections={"signos": False},
            letterhead_mode="preprinted",
            is_default=False,
        )
    assert fmt.pk is not None
    assert fmt.tenant_id == tenant.id
    assert fmt.accent_color == "#AABBCC"
    assert fmt.font == "times"
    assert fmt.sections == {"signos": False}
    assert fmt.letterhead_mode == "preprinted"
    assert fmt.is_authorized is False
    assert fmt.is_active is True


@pytest.mark.django_db
def test_format_create_invalid_accent() -> None:
    tenant = TenantFactory()
    user = UserFactory()
    with tenant_ctx(tenant):
        with pytest.raises(ValidationError, match="RRGGBB"):
            prescription_format_create(
                tenant=tenant, user=user, name="X", accent_color="rojo"
            )


@pytest.mark.django_db
def test_format_create_invalid_layout() -> None:
    tenant = TenantFactory()
    user = UserFactory()
    with tenant_ctx(tenant):
        with pytest.raises(ValidationError, match="base_layout"):
            prescription_format_create(
                tenant=tenant, user=user, name="X", base_layout="fancy"
            )


@pytest.mark.django_db
def test_format_create_invalid_sections_key() -> None:
    tenant = TenantFactory()
    user = UserFactory()
    with tenant_ctx(tenant):
        with pytest.raises(ValidationError, match="desconocidas"):
            prescription_format_create(
                tenant=tenant, user=user, name="X", sections={"hack": True}
            )


@pytest.mark.django_db
def test_format_create_doctor_wrong_tenant() -> None:
    """prescription_format_create rechaza doctor de otro tenant."""
    tenant = TenantFactory()
    other_tenant = TenantFactory()
    user = UserFactory()
    membership = TenantMembershipFactory(user=user, tenant=other_tenant, role=TenantMembership.Role.DOCTOR)
    doctor = DoctorFactory(tenant=other_tenant, membership=membership)
    with tenant_ctx(tenant):
        with pytest.raises(ValidationError, match="no pertenece"):
            prescription_format_create(
                tenant=tenant, user=user, name="X", doctor_id=doctor.id
            )


@pytest.mark.django_db
def test_format_create_is_default_clears_previous() -> None:
    """Crear con is_default=True desmarca el anterior default del tenant."""
    tenant = TenantFactory()
    user = UserFactory()
    with tenant_ctx(tenant):
        first = PrescriptionFormatFactory(tenant=tenant, is_default=True, created_by=user)
        prescription_format_create(
            tenant=tenant, user=user, name="Nuevo default", is_default=True
        )
    first.refresh_from_db()
    assert first.is_default is False


@pytest.mark.django_db
def test_format_create_empty_name_raises() -> None:
    tenant = TenantFactory()
    user = UserFactory()
    with tenant_ctx(tenant):
        with pytest.raises(ValidationError, match="vacío"):
            prescription_format_create(tenant=tenant, user=user, name="   ")


# ---------------------------------------------------------------------------
# Servicios — prescription_format_update
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_format_update_ok() -> None:
    tenant = TenantFactory()
    user = UserFactory()
    with tenant_ctx(tenant):
        fmt = PrescriptionFormatFactory(tenant=tenant, created_by=user, name="Viejo")
        updated = prescription_format_update(
            fmt=fmt, user=user, tenant=tenant, is_admin=True, name="Nuevo"
        )
    assert updated.name == "Nuevo"


@pytest.mark.django_db
def test_format_update_immutable_field() -> None:
    tenant = TenantFactory()
    user = UserFactory()
    with tenant_ctx(tenant):
        fmt = PrescriptionFormatFactory(tenant=tenant, created_by=user)
        with pytest.raises(ValidationError, match="No se pueden modificar"):
            prescription_format_update(
                fmt=fmt, user=user, tenant=tenant, is_admin=True, tenant_id=_uuid.uuid4()
            )


@pytest.mark.django_db
def test_format_update_is_authorized_requires_admin() -> None:
    tenant = TenantFactory()
    user = UserFactory()
    with tenant_ctx(tenant):
        fmt = PrescriptionFormatFactory(tenant=tenant, created_by=user)
        with pytest.raises(ValidationError, match="administrador"):
            prescription_format_update(
                fmt=fmt, user=user, tenant=tenant, is_admin=False, is_authorized=True
            )


@pytest.mark.django_db
def test_format_update_is_authorized_by_admin_ok() -> None:
    tenant = TenantFactory()
    user = UserFactory()
    with tenant_ctx(tenant):
        fmt = PrescriptionFormatFactory(tenant=tenant, created_by=user)
        updated = prescription_format_update(
            fmt=fmt, user=user, tenant=tenant, is_admin=True, is_authorized=True
        )
    assert updated.is_authorized is True


# ---------------------------------------------------------------------------
# Servicios — prescription_format_delete
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_format_delete_ok() -> None:
    tenant = TenantFactory()
    user = UserFactory()
    with tenant_ctx(tenant):
        fmt = PrescriptionFormatFactory(tenant=tenant, created_by=user, is_default=True, is_active=True)
        prescription_format_delete(fmt=fmt, user=user, tenant=tenant)
    fmt.refresh_from_db()
    assert fmt.is_active is False
    assert fmt.is_default is False
    assert fmt.deleted_at is not None


@pytest.mark.django_db
def test_format_delete_already_inactive() -> None:
    tenant = TenantFactory()
    user = UserFactory()
    with tenant_ctx(tenant):
        fmt = PrescriptionFormatFactory(tenant=tenant, created_by=user, is_active=False)
        with pytest.raises(ValidationError, match="inactivo"):
            prescription_format_delete(fmt=fmt, user=user, tenant=tenant)


# ---------------------------------------------------------------------------
# Selectores
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_format_list_only_active() -> None:
    """prescription_format_list solo devuelve formatos activos del tenant."""
    tenant = TenantFactory()
    user = UserFactory()
    with tenant_ctx(tenant):
        active = PrescriptionFormatFactory(tenant=tenant, created_by=user, is_active=True)
        PrescriptionFormatFactory(tenant=tenant, created_by=user, is_active=False)
        qs = list(prescription_format_list(tenant=tenant))
    ids = [f.id for f in qs]
    assert active.id in ids
    assert len([f for f in qs if not f.is_active]) == 0


@pytest.mark.django_db
def test_format_list_isolates_tenants() -> None:
    """prescription_format_list no devuelve formatos de otro tenant."""
    tenant_a = TenantFactory()
    tenant_b = TenantFactory()
    user = UserFactory()
    with tenant_ctx(tenant_a):
        own = PrescriptionFormatFactory(tenant=tenant_a, created_by=user)
        PrescriptionFormatFactory(tenant=tenant_b, created_by=user)
        qs = list(prescription_format_list(tenant=tenant_a))
    assert all(f.tenant_id == tenant_a.id for f in qs)
    assert own.id in [f.id for f in qs]


@pytest.mark.django_db
def test_format_get_ok() -> None:
    tenant = TenantFactory()
    user = UserFactory()
    with tenant_ctx(tenant):
        fmt = PrescriptionFormatFactory(tenant=tenant, created_by=user)
        fetched = prescription_format_get(format_id=fmt.id)
    assert fetched.id == fmt.id


@pytest.mark.django_db
def test_format_get_wrong_tenant_raises() -> None:
    """prescription_format_get lanza DoesNotExist para formato de otro tenant."""
    tenant_a = TenantFactory()
    tenant_b = TenantFactory()
    user = UserFactory()
    with tenant_ctx(tenant_b):
        fmt_b = PrescriptionFormatFactory(tenant=tenant_b, created_by=user)
    with tenant_ctx(tenant_a):
        with pytest.raises(PrescriptionFormat.DoesNotExist):
            prescription_format_get(format_id=fmt_b.id)


# ---------------------------------------------------------------------------
# Selectores — prescription_format_resolve (prioridad)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_resolve_override_id_wins() -> None:
    """format_override_id tiene prioridad sobre todo."""
    tenant = TenantFactory()
    user = UserFactory()
    with tenant_ctx(tenant):
        default_fmt = PrescriptionFormatFactory(tenant=tenant, created_by=user, is_default=True)
        override_fmt = PrescriptionFormatFactory(tenant=tenant, created_by=user, accent_color="#111111")
        prescription = PrescriptionFactory(tenant=tenant)
        result = prescription_format_resolve(
            prescription=prescription,
            format_override_id=override_fmt.id,
        )
    assert result.id == override_fmt.id


@pytest.mark.django_db
def test_resolve_layout_override_creates_memory_object() -> None:
    """layout_override devuelve un objeto en memoria con el layout indicado."""
    tenant = TenantFactory()
    user = UserFactory()
    with tenant_ctx(tenant):
        prescription = PrescriptionFactory(tenant=tenant)
        result = prescription_format_resolve(
            prescription=prescription,
            layout_override="compact",
        )
    assert result.base_layout == "compact"
    # objeto en memoria no tiene pk
    assert not hasattr(result, "pk") or getattr(result, "pk", None) is None


@pytest.mark.django_db
def test_resolve_doctor_authorized_format() -> None:
    """Formato autorizado del médico tiene prioridad sobre default del tenant."""
    tenant = TenantFactory()
    user = UserFactory()
    membership = TenantMembershipFactory(user=user, tenant=tenant, role=TenantMembership.Role.DOCTOR)
    doctor = DoctorFactory(tenant=tenant, membership=membership)
    with tenant_ctx(tenant):
        default_fmt = PrescriptionFormatFactory(tenant=tenant, is_default=True)
        doctor_fmt = PrescriptionFormatFactory(
            tenant=tenant,
            doctor=doctor,
            is_authorized=True,
            accent_color="#FEDCBA",
        )
        prescription = PrescriptionFactory(tenant=tenant, doctor=doctor)
        result = prescription_format_resolve(prescription=prescription)
    assert result.id == doctor_fmt.id


@pytest.mark.django_db
def test_resolve_default_tenant_format() -> None:
    """Cuando no hay formato de médico, se usa el default del tenant."""
    tenant = TenantFactory()
    with tenant_ctx(tenant):
        default_fmt = PrescriptionFormatFactory(tenant=tenant, is_default=True)
        prescription = PrescriptionFactory(tenant=tenant)
        result = prescription_format_resolve(prescription=prescription)
    assert result.id == default_fmt.id


@pytest.mark.django_db
def test_resolve_factory_fallback() -> None:
    """Sin formatos en BD, devuelve objeto fábrica con defaults."""
    tenant = TenantFactory()
    with tenant_ctx(tenant):
        prescription = PrescriptionFactory(tenant=tenant)
        result = prescription_format_resolve(prescription=prescription)
    assert result.base_layout == "digital"
    assert result.accent_color == "#9A7B1E"


# ---------------------------------------------------------------------------
# PDF — contexto y generación
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_build_context_includes_format_vars() -> None:
    """_build_context inyecta accent, font_family, sections desde el formato."""
    tenant = TenantFactory()
    user = UserFactory()
    membership = TenantMembershipFactory(user=user, tenant=tenant, role=TenantMembership.Role.DOCTOR)
    doctor = DoctorFactory(tenant=tenant, membership=membership)
    with tenant_ctx(tenant):
        prescription = PrescriptionFactory(tenant=tenant, doctor=doctor)
        PrescriptionItemFactory(prescription=prescription, tenant=tenant)
        fmt = PrescriptionFormatFactory(
            tenant=tenant,
            accent_color="#FF0000",
            font="times",
            sections={"signos": False, "sueros": False},
        )
        ctx = _build_context(prescription, fmt=fmt)

    assert ctx["accent"] == "#FF0000"
    assert "Times" in ctx["font_family"]
    assert ctx["sections"]["signos"] is False
    assert ctx["sections"]["sueros"] is False
    # las secciones no especificadas se rellenan con True
    assert ctx["sections"]["diagnostico"] is True


@pytest.mark.django_db
def test_build_context_defaults_without_format() -> None:
    """_build_context usa los defaults de fábrica cuando fmt=None."""
    tenant = TenantFactory()
    user = UserFactory()
    membership = TenantMembershipFactory(user=user, tenant=tenant, role=TenantMembership.Role.DOCTOR)
    doctor = DoctorFactory(tenant=tenant, membership=membership)
    with tenant_ctx(tenant):
        prescription = PrescriptionFactory(tenant=tenant, doctor=doctor)
        PrescriptionItemFactory(prescription=prescription, tenant=tenant)
        ctx = _build_context(prescription, fmt=None)

    assert ctx["accent"] == "#9A7B1E"
    assert "Helvetica" in ctx["font_family"]
    for key in SECTIONS_KEYS:
        assert ctx["sections"][key] is True


@pytest.mark.django_db
def test_pdf_build_with_custom_format_generates_pdf() -> None:
    """prescription_pdf_build con formato custom genera bytes que inician %PDF."""
    tenant = TenantFactory()
    user = UserFactory()
    membership = TenantMembershipFactory(user=user, tenant=tenant, role=TenantMembership.Role.DOCTOR)
    doctor = DoctorFactory(tenant=tenant, membership=membership)
    with tenant_ctx(tenant):
        prescription = PrescriptionFactory(tenant=tenant, doctor=doctor)
        PrescriptionItemFactory(prescription=prescription, tenant=tenant)
        fmt = PrescriptionFormatFactory(
            tenant=tenant,
            accent_color="#1A2B3C",
            font="times",
            sections={"signos": False},
            base_layout="digital",
        )
        from apps.recetas.selectors import prescription_get as pg

        full_rx = pg(prescription_id=prescription.id)
        pdf_bytes = prescription_pdf_build(prescription=full_rx, format_override=fmt)

    assert pdf_bytes[:4] == b"%PDF"


@pytest.mark.django_db
def test_pdf_build_without_format_uses_factory_defaults() -> None:
    """prescription_pdf_build sin formato usa defaults y genera PDF válido."""
    tenant = TenantFactory()
    user = UserFactory()
    membership = TenantMembershipFactory(user=user, tenant=tenant, role=TenantMembership.Role.DOCTOR)
    doctor = DoctorFactory(tenant=tenant, membership=membership)
    with tenant_ctx(tenant):
        prescription = PrescriptionFactory(tenant=tenant, doctor=doctor)
        PrescriptionItemFactory(prescription=prescription, tenant=tenant)
        from apps.recetas.selectors import prescription_get as pg

        full_rx = pg(prescription_id=prescription.id)
        pdf_bytes = prescription_pdf_build(prescription=full_rx)

    assert pdf_bytes[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# API — lista y creación
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_api_list_formats_ok() -> None:
    """GET /recetas/formatos/ → 200 con formatos del tenant."""
    client = APIClient()
    tenant = TenantFactory()
    user, _ = _make_user_role(tenant, TenantMembership.Role.OWNER)
    with tenant_ctx(tenant):
        PrescriptionFormatFactory(tenant=tenant, is_active=True)

    with api_tenant_ctx(tenant):
        client.force_authenticate(user=user)
        resp = client.get(FORMAT_LIST_URL)

    assert resp.status_code == 200
    assert isinstance(resp.data, list)
    assert len(resp.data) >= 1


@pytest.mark.django_db
def test_api_list_formats_unauthenticated() -> None:
    client = APIClient()
    with patch("apps.recetas.views.get_current_tenant", return_value=TenantFactory()):
        resp = client.get(FORMAT_LIST_URL)
    assert resp.status_code == 401


@pytest.mark.django_db
def test_api_create_format_owner_ok() -> None:
    """POST /recetas/formatos/ → 201 para owner."""
    client = APIClient()
    tenant = TenantFactory()
    user, _ = _make_user_role(tenant, TenantMembership.Role.OWNER)

    payload = {
        "name": "Formato Nuevo",
        "base_layout": "compact",
        "accent_color": "#AABBCC",
        "font": "times",
        "sections": {"signos": False},
        "letterhead_mode": "preprinted",
        "is_default": True,
    }

    with api_tenant_ctx(tenant):
        client.force_authenticate(user=user)
        with patch("apps.recetas.views.get_current_tenant", return_value=tenant):
            user.active_role = TenantMembership.Role.OWNER
            resp = client.post(FORMAT_LIST_URL, data=payload, format="json")

    assert resp.status_code == 201
    assert resp.data["name"] == "Formato Nuevo"
    assert resp.data["accent_color"] == "#AABBCC"


@pytest.mark.django_db
def test_api_create_format_reception_forbidden() -> None:
    """POST /recetas/formatos/ → 403 para recepción."""
    client = APIClient()
    tenant = TenantFactory()
    user, _ = _make_user_role(tenant, TenantMembership.Role.RECEPTION)

    with api_tenant_ctx(tenant):
        client.force_authenticate(user=user)
        resp = client.post(FORMAT_LIST_URL, data={"name": "X"}, format="json")

    assert resp.status_code == 403


@pytest.mark.django_db
def test_api_create_format_invalid_accent() -> None:
    """POST /recetas/formatos/ → 400 si accent_color es inválido."""
    client = APIClient()
    tenant = TenantFactory()
    user, _ = _make_user_role(tenant, TenantMembership.Role.OWNER)

    payload = {"name": "Test", "accent_color": "rojo"}

    with api_tenant_ctx(tenant):
        client.force_authenticate(user=user)
        with patch("apps.recetas.views.get_current_tenant", return_value=tenant):
            user.active_role = TenantMembership.Role.OWNER
            resp = client.post(FORMAT_LIST_URL, data=payload, format="json")

    assert resp.status_code == 400


@pytest.mark.django_db
def test_api_create_format_unknown_field_rejected() -> None:
    """POST /recetas/formatos/ → 400 si envía campo desconocido."""
    client = APIClient()
    tenant = TenantFactory()
    user, _ = _make_user_role(tenant, TenantMembership.Role.OWNER)

    payload = {"name": "Test", "campo_inexistente": "valor"}

    with api_tenant_ctx(tenant):
        client.force_authenticate(user=user)
        with patch("apps.recetas.views.get_current_tenant", return_value=tenant):
            user.active_role = TenantMembership.Role.OWNER
            resp = client.post(FORMAT_LIST_URL, data=payload, format="json")

    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# API — detalle, PATCH, DELETE
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_api_get_format_detail() -> None:
    client = APIClient()
    tenant = TenantFactory()
    user, _ = _make_user_role(tenant, TenantMembership.Role.OWNER)
    with tenant_ctx(tenant):
        fmt = PrescriptionFormatFactory(tenant=tenant)

    with api_tenant_ctx(tenant):
        client.force_authenticate(user=user)
        resp = client.get(_format_detail_url(fmt.id))

    assert resp.status_code == 200
    assert resp.data["id"] == str(fmt.id)


@pytest.mark.django_db
def test_api_get_format_wrong_tenant_404() -> None:
    """GET /recetas/formatos/<id>/ de otro tenant → 404."""
    client = APIClient()
    tenant_a = TenantFactory()
    tenant_b = TenantFactory()
    user_a, _ = _make_user_role(tenant_a, TenantMembership.Role.OWNER)
    with tenant_ctx(tenant_b):
        fmt_b = PrescriptionFormatFactory(tenant=tenant_b)

    with api_tenant_ctx(tenant_a):
        client.force_authenticate(user=user_a)
        resp = client.get(_format_detail_url(fmt_b.id))

    assert resp.status_code == 404


@pytest.mark.django_db
def test_api_patch_format_ok() -> None:
    """PATCH /recetas/formatos/<id>/ → 200 para owner."""
    client = APIClient()
    tenant = TenantFactory()
    user, _ = _make_user_role(tenant, TenantMembership.Role.OWNER)
    with tenant_ctx(tenant):
        fmt = PrescriptionFormatFactory(tenant=tenant, name="Original")

    with api_tenant_ctx(tenant):
        client.force_authenticate(user=user)
        with patch("apps.recetas.views.get_current_tenant", return_value=tenant):
            user.active_role = TenantMembership.Role.OWNER
            resp = client.patch(
                _format_detail_url(fmt.id),
                data={"name": "Actualizado"},
                format="json",
            )

    assert resp.status_code == 200
    assert resp.data["name"] == "Actualizado"


@pytest.mark.django_db
def test_api_patch_is_authorized_by_doctor_rejected() -> None:
    """PATCH is_authorized por médico → 400 (solo admin)."""
    client = APIClient()
    tenant = TenantFactory()
    user, _ = _make_user_role(tenant, TenantMembership.Role.DOCTOR)
    with tenant_ctx(tenant):
        fmt = PrescriptionFormatFactory(tenant=tenant)

    with api_tenant_ctx(tenant):
        client.force_authenticate(user=user)
        with patch("apps.recetas.views.get_current_tenant", return_value=tenant):
            user.active_role = TenantMembership.Role.DOCTOR
            resp = client.patch(
                _format_detail_url(fmt.id),
                data={"is_authorized": True},
                format="json",
            )

    assert resp.status_code == 400


@pytest.mark.django_db
def test_api_delete_format_owner_ok() -> None:
    """DELETE /recetas/formatos/<id>/ → 204 para owner."""
    client = APIClient()
    tenant = TenantFactory()
    user, _ = _make_user_role(tenant, TenantMembership.Role.OWNER)
    with tenant_ctx(tenant):
        fmt = PrescriptionFormatFactory(tenant=tenant)

    with api_tenant_ctx(tenant):
        client.force_authenticate(user=user)
        with patch("apps.recetas.views.get_current_tenant", return_value=tenant):
            user.active_role = TenantMembership.Role.OWNER
            resp = client.delete(_format_detail_url(fmt.id))

    assert resp.status_code == 204
    fmt.refresh_from_db()
    assert fmt.is_active is False


@pytest.mark.django_db
def test_api_delete_format_doctor_forbidden() -> None:
    """DELETE /recetas/formatos/<id>/ → 403 para médico."""
    client = APIClient()
    tenant = TenantFactory()
    user, _ = _make_user_role(tenant, TenantMembership.Role.DOCTOR)
    with tenant_ctx(tenant):
        fmt = PrescriptionFormatFactory(tenant=tenant)

    with api_tenant_ctx(tenant):
        client.force_authenticate(user=user)
        resp = client.delete(_format_detail_url(fmt.id))

    assert resp.status_code == 403
