"""
Services de los catálogos que alimentan el Plan Integral de Longevidad.

DocumentTemplate (Fase 2) — plantillas de texto reutilizables para pre-rellenar
    las secciones de texto del Plan Integral (reporte médico, seguimiento,
    interconsulta, estudios, condiciones a mejorar, general).
LabAnalyte (Fase 3)       — analitos de laboratorio con rango de referencia,
    usados por `services_plan_integral.longevity_plan_create` para calcular
    `out_of_range` de cada resultado capturado.

Ambos son catálogos simples por tenant (mismo patrón que
`apps.finanzas.services.concept_create/update` y
`apps.clinica.services.template_create/update/deactivate`):
    - create: valida entrada, crea el registro, audita.
    - update: rechaza campos inmutables (id/tenant/timestamps/is_active),
      audita.
    - activate/deactivate: toggle explícito de is_active (NUNCA vía update
      genérico — regla de oro de campos sensibles).
    - delete: baja lógica vía `deleted_at` (mismo patrón que
      `apps.finanzas.services.package_delete`) — el TenantManager ya no lo
      retorna tras el borrado.

Convención: keyword-only args, nombrado acción+entidad.
"""

from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.expediente.models import DocumentTemplate, DocumentTemplateSection, LabAnalyte
from apps.tenancy.models import Tenant

# ---------------------------------------------------------------------------
# DocumentTemplate (Fase 2)
# ---------------------------------------------------------------------------

_DOCUMENT_TEMPLATE_IMMUTABLE: frozenset[str] = frozenset(
    {"id", "tenant", "tenant_id", "created_at", "updated_at", "deleted_at", "is_active"}
)


def document_template_create(
    *,
    tenant: Tenant,
    user: Any,
    name: str,
    section: str,
    body: str,
    is_active: bool = True,
) -> DocumentTemplate:
    """Crea una plantilla de documento en el catálogo del tenant.

    Raises:
        ValidationError: si `section` no es un valor válido.
    """
    valid_sections = {c[0] for c in DocumentTemplateSection.choices}
    if section not in valid_sections:
        raise ValidationError(
            f"Sección inválida '{section}'. Las válidas son: {', '.join(sorted(valid_sections))}."
        )

    template = DocumentTemplate.objects.create(
        tenant=tenant,
        created_by=user,
        name=name,
        section=section,
        body=body,
        is_active=is_active,
    )
    audit_record(
        action=ActionType.DOCUMENT_TEMPLATE_CREATE,
        resource_type="DocumentTemplate",
        actor=user,
        tenant=tenant,
        resource_id=template.id,
        resource_repr=template.name,
    )
    return template


def document_template_update(
    *,
    template: DocumentTemplate,
    user: Any,
    **fields: Any,
) -> DocumentTemplate:
    """Actualiza campos permitidos de una plantilla de documento.

    No permite modificar is_active (solo vía document_template_activate/
    deactivate) ni campos de identidad.

    Raises:
        ValidationError: si se intenta modificar un campo inmutable, o si
            `section` viene con un valor inválido.
    """
    bad = _DOCUMENT_TEMPLATE_IMMUTABLE & set(fields)
    if bad:
        raise ValidationError(f"No se pueden modificar los campos: {', '.join(sorted(bad))}.")

    if "section" in fields:
        valid_sections = {c[0] for c in DocumentTemplateSection.choices}
        if fields["section"] not in valid_sections:
            raise ValidationError(
                f"Sección inválida '{fields['section']}'. "
                f"Las válidas son: {', '.join(sorted(valid_sections))}."
            )

    for field_name, value in fields.items():
        setattr(template, field_name, value)

    update_fields = [*fields.keys(), "updated_at"]
    template.save(update_fields=update_fields)

    audit_record(
        action=ActionType.DOCUMENT_TEMPLATE_UPDATE,
        resource_type="DocumentTemplate",
        actor=user,
        tenant=template.tenant,
        resource_id=template.id,
        resource_repr=template.name,
    )
    return template


def document_template_activate(*, template: DocumentTemplate, user: Any) -> DocumentTemplate:
    """Reactiva una plantilla de documento (is_active=True)."""
    template.is_active = True
    template.save(update_fields=["is_active", "updated_at"])
    audit_record(
        action=ActionType.DOCUMENT_TEMPLATE_UPDATE,
        resource_type="DocumentTemplate",
        actor=user,
        tenant=template.tenant,
        resource_id=template.id,
        resource_repr=template.name,
    )
    return template


def document_template_deactivate(*, template: DocumentTemplate, user: Any) -> DocumentTemplate:
    """Oculta una plantilla de documento del catálogo (is_active=False)."""
    template.is_active = False
    template.save(update_fields=["is_active", "updated_at"])
    audit_record(
        action=ActionType.DOCUMENT_TEMPLATE_UPDATE,
        resource_type="DocumentTemplate",
        actor=user,
        tenant=template.tenant,
        resource_id=template.id,
        resource_repr=template.name,
    )
    return template


def document_template_delete(*, template: DocumentTemplate, user: Any) -> None:
    """Baja lógica (deleted_at) de una plantilla de documento — no borra físicamente."""
    template.deleted_at = timezone.now()
    template.save(update_fields=["deleted_at", "updated_at"])
    audit_record(
        action=ActionType.DOCUMENT_TEMPLATE_DELETE,
        resource_type="DocumentTemplate",
        actor=user,
        tenant=template.tenant,
        resource_id=template.id,
        resource_repr=template.name,
    )


# ---------------------------------------------------------------------------
# LabAnalyte (Fase 3)
# ---------------------------------------------------------------------------

_LAB_ANALYTE_IMMUTABLE: frozenset[str] = frozenset(
    {"id", "tenant", "tenant_id", "created_at", "updated_at", "deleted_at", "is_active"}
)


def _validate_ref_range(*, ref_low: Any, ref_high: Any) -> None:
    """Valida que ref_low <= ref_high cuando ambos vienen poblados.

    Compara vía Decimal(str(...)) — defensa en profundidad: el serializer ya
    entrega Decimal, pero el service puede invocarse desde management
    commands/tests con str/int/float.

    Raises:
        ValidationError: si el rango es inconsistente.
    """
    if ref_low is None or ref_high is None:
        return
    if Decimal(str(ref_low)) > Decimal(str(ref_high)):
        raise ValidationError(
            "El límite inferior del rango de referencia no puede ser mayor al límite superior."
        )


def lab_analyte_create(
    *,
    tenant: Tenant,
    user: Any,
    name: str,
    unit: str = "",
    ref_low: Any = None,
    ref_high: Any = None,
    is_active: bool = True,
) -> LabAnalyte:
    """Crea un analito de laboratorio en el catálogo del tenant.

    Raises:
        ValidationError: si ref_low > ref_high.
    """
    _validate_ref_range(ref_low=ref_low, ref_high=ref_high)

    analyte = LabAnalyte.objects.create(
        tenant=tenant,
        created_by=user,
        name=name,
        unit=unit,
        ref_low=ref_low,
        ref_high=ref_high,
        is_active=is_active,
    )
    audit_record(
        action=ActionType.LAB_ANALYTE_CREATE,
        resource_type="LabAnalyte",
        actor=user,
        tenant=tenant,
        resource_id=analyte.id,
        resource_repr=analyte.name,
    )
    return analyte


def lab_analyte_update(
    *,
    analyte: LabAnalyte,
    user: Any,
    **fields: Any,
) -> LabAnalyte:
    """Actualiza campos permitidos de un analito de laboratorio.

    No permite modificar is_active (solo vía lab_analyte_activate/deactivate)
    ni campos de identidad.

    Raises:
        ValidationError: si se intenta modificar un campo inmutable, o si el
            rango resultante es inconsistente (ref_low > ref_high).
    """
    bad = _LAB_ANALYTE_IMMUTABLE & set(fields)
    if bad:
        raise ValidationError(f"No se pueden modificar los campos: {', '.join(sorted(bad))}.")

    ref_low = fields.get("ref_low", analyte.ref_low)
    ref_high = fields.get("ref_high", analyte.ref_high)
    _validate_ref_range(ref_low=ref_low, ref_high=ref_high)

    for field_name, value in fields.items():
        setattr(analyte, field_name, value)

    update_fields = [*fields.keys(), "updated_at"]
    analyte.save(update_fields=update_fields)

    audit_record(
        action=ActionType.LAB_ANALYTE_UPDATE,
        resource_type="LabAnalyte",
        actor=user,
        tenant=analyte.tenant,
        resource_id=analyte.id,
        resource_repr=analyte.name,
    )
    return analyte


def lab_analyte_activate(*, analyte: LabAnalyte, user: Any) -> LabAnalyte:
    """Reactiva un analito de laboratorio (is_active=True)."""
    analyte.is_active = True
    analyte.save(update_fields=["is_active", "updated_at"])
    audit_record(
        action=ActionType.LAB_ANALYTE_UPDATE,
        resource_type="LabAnalyte",
        actor=user,
        tenant=analyte.tenant,
        resource_id=analyte.id,
        resource_repr=analyte.name,
    )
    return analyte


def lab_analyte_deactivate(*, analyte: LabAnalyte, user: Any) -> LabAnalyte:
    """Oculta un analito de laboratorio del catálogo (is_active=False)."""
    analyte.is_active = False
    analyte.save(update_fields=["is_active", "updated_at"])
    audit_record(
        action=ActionType.LAB_ANALYTE_UPDATE,
        resource_type="LabAnalyte",
        actor=user,
        tenant=analyte.tenant,
        resource_id=analyte.id,
        resource_repr=analyte.name,
    )
    return analyte


def lab_analyte_delete(*, analyte: LabAnalyte, user: Any) -> None:
    """Baja lógica (deleted_at) de un analito de laboratorio — no borra físicamente."""
    analyte.deleted_at = timezone.now()
    analyte.save(update_fields=["deleted_at", "updated_at"])
    audit_record(
        action=ActionType.LAB_ANALYTE_DELETE,
        resource_type="LabAnalyte",
        actor=user,
        tenant=analyte.tenant,
        resource_id=analyte.id,
        resource_repr=analyte.name,
    )
