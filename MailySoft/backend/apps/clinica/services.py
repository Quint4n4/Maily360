"""
Services de la app clinica — lógica de negocio de escritura.

Toda creación/modificación de ClinicSettings, ClinicTemplate, PatientCategory,
extensiones de Doctor y DoctorUniversity pasa por aquí.

Principios:
    - Keyword-only args en toda firma.
    - Nombrado acción+entidad: clinic_settings_upsert, template_create, etc.
    - Registra audit_record en cada escritura (NOM-024).
    - Valida pertenencia al tenant en cada FK externa (defensa en profundidad).
    - Campos inmutables en frozenset: no se pueden modificar vía update.
    - Lanza django.core.exceptions.ValidationError (nunca DRF, que es HTTP).
"""

import logging
import uuid
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.clinica.models import (
    ClinicSettings,
    ClinicTeamMember,
    ClinicTemplate,
    CredentialKind,
    CredentialValidationStatus,
    DoctorCredential,
    DoctorUniversity,
    MembershipSucursal,
    PatientCategory,
    Sucursal,
)
from apps.clinica.selectors import clinic_settings_get
from apps.clinica.sucursal_scope import allowed_sucursales
from apps.tenancy.models import TenantMembership

if TYPE_CHECKING:
    from apps.authn.models import User
    from apps.personal.models import Doctor
    from apps.tenancy.models import Tenant

logger = logging.getLogger(__name__)


def _notify_credential_pending(credential: DoctorCredential, actor: "User") -> None:
    """Avisa a owner/admin que hay una credencial por validar.

    Efecto secundario no crítico: si la notificación falla, NO interrumpe el alta
    de la credencial (solo se registra en el log).
    """
    try:
        from apps.notificaciones.models import NotificationKind, NotificationTarget
        from apps.notificaciones.recipients import users_with_roles
        from apps.notificaciones.services import notification_fanout

        admins = users_with_roles(tenant=credential.tenant, roles=["owner", "admin"])
        doctor_name = credential.doctor.full_name
        notification_fanout(
            tenant=credential.tenant,
            recipients=admins,
            kind=NotificationKind.CREDENTIAL_REVIEW,
            title=f"Credencial por validar — {doctor_name}",
            body=f"{credential.title} ({credential.institution}). Revísala y valídala.",
            actor=actor,
            target_type=NotificationTarget.CREDENTIAL,
            target_id=credential.id,
        )
    except Exception:  # noqa: BLE001
        logger.warning("No se pudo notificar credencial por validar (cred=%s).", credential.id)


def _notify_credential_result(credential: DoctorCredential, actor: "User", status: str) -> None:
    """Avisa al médico el resultado de la validación de su credencial.

    Efecto secundario no crítico (no interrumpe si falla).
    """
    try:
        from apps.notificaciones.models import NotificationKind, NotificationTarget
        from apps.notificaciones.services import notification_create

        doctor_user = credential.doctor.membership.user
        if status == CredentialValidationStatus.VALIDADA.value:
            title = "Tu credencial fue validada"
            body = f"{credential.title} ya aparece en tus recetas."
        else:
            motivo = credential.validation_note or "sin motivo especificado"
            title = "Tu credencial fue rechazada"
            body = f"{credential.title}: {motivo}."
        notification_create(
            tenant=credential.tenant,
            recipient=doctor_user,
            kind=NotificationKind.CREDENTIAL_RESULT,
            title=title,
            body=body,
            actor=actor,
            target_type=NotificationTarget.CREDENTIAL,
            target_id=credential.id,
        )
    except Exception:  # noqa: BLE001
        logger.warning("No se pudo notificar resultado de validación (cred=%s).", credential.id)


# ---------------------------------------------------------------------------
# Campos inmutables
# ---------------------------------------------------------------------------

_SETTINGS_IMMUTABLE: frozenset[str] = frozenset(
    {"id", "tenant", "tenant_id", "created_at", "updated_at", "deleted_at", "created_by"}
)

_TEMPLATE_IMMUTABLE: frozenset[str] = frozenset(
    {"id", "tenant", "tenant_id", "created_at", "updated_at", "deleted_at", "is_active"}
)

_CATEGORY_IMMUTABLE: frozenset[str] = frozenset(
    {"id", "tenant", "tenant_id", "created_at", "updated_at", "deleted_at", "is_active"}
)

_DOCTOR_EXTRA_IMMUTABLE: frozenset[str] = frozenset(
    {
        "id",
        "tenant",
        "tenant_id",
        "membership",
        "membership_id",
        "created_at",
        "updated_at",
        "deleted_at",
        "is_active",
    }
)


# ---------------------------------------------------------------------------
# ClinicSettings — upsert
# ---------------------------------------------------------------------------


def clinic_settings_upsert(
    *,
    tenant: "Tenant",
    user: "User",
    logo: Any = None,
    address: str = "",
    address_2: str = "",
    phone: str = "",
    mobile: str = "",
    email: str = "",
    website: str = "",
    facebook: str = "",
    instagram: str = "",
    youtube: str = "",
    letterhead_full: Any = None,
    letterhead_half: Any = None,
    letterhead_full_spaces: int | None = None,
    letterhead_half_spaces: int | None = None,
    commercial_name: str = "",
    brand_color: str = "",
    doctors_see_costs: bool | None = None,
    # Soporte partial update: solo actualiza los campos explícitamente pasados.
    _partial_fields: frozenset[str] | None = None,
) -> ClinicSettings:
    """Crea o actualiza la configuración de la clínica (upsert).

    Si ya existe un ClinicSettings activo para el tenant, lo actualiza.
    Si no existe, lo crea (primera configuración de la clínica).

    Para actualización parcial, pasar `_partial_fields` con el conjunto de
    nombres de campo que vienen en el request (los demás se ignoran).
    La vista lo hace extrayendo s.validated_data.keys() y pasándolos aquí.

    Args:
        tenant:               Clínica a configurar.
        user:                 Usuario que realiza el cambio (auditoría).
        logo:                 Archivo de imagen del logo (opcional).
        address:              Dirección principal.
        address_2:            Complemento de dirección.
        phone:                Teléfono fijo.
        mobile:               Móvil / WhatsApp.
        email:                Email de contacto.
        website:              URL del sitio web.
        facebook:             Handle o URL de Facebook.
        instagram:            Handle o URL de Instagram.
        youtube:              Handle o URL de YouTube.
        letterhead_full:      Membrete de hoja completa (archivo).
        letterhead_half:      Membrete de media hoja (archivo).
        letterhead_full_spaces:  Espacios después del membrete completo.
        letterhead_half_spaces:  Espacios después del membrete de media hoja.
        commercial_name:      Nombre comercial de la clínica para el membrete (COFEPRIS F2).
        brand_color:          Color de marca en formato #RRGGBB (PDF unificado — Fase 1).
                              Default vacío → se conserva el valor previo o el default del campo.
        doctors_see_costs:    Flag D-2: si True, los médicos ven el estado de cuenta del paciente.
        _partial_fields:      Si se provee, solo se actualizan esos campos.

    Returns:
        Instancia ClinicSettings (creada o actualizada).
    """
    settings = clinic_settings_get(tenant_id=tenant.id)
    creating = settings is None

    if creating:
        settings = ClinicSettings(
            tenant=tenant,
            created_by=user,
        )

    # Mapeo campo → valor. Solo se aplica lo que viene en _partial_fields (si existe).
    field_map: dict[str, Any] = {
        "address": address,
        "address_2": address_2,
        "phone": phone,
        "mobile": mobile,
        "email": email,
        "website": website,
        "facebook": facebook,
        "instagram": instagram,
        "youtube": youtube,
        "commercial_name": commercial_name,
        "brand_color": brand_color,
    }
    if logo is not None:
        field_map["logo"] = logo
    if letterhead_full is not None:
        field_map["letterhead_full"] = letterhead_full
    if letterhead_half is not None:
        field_map["letterhead_half"] = letterhead_half
    if letterhead_full_spaces is not None:
        field_map["letterhead_full_spaces"] = letterhead_full_spaces
    if letterhead_half_spaces is not None:
        field_map["letterhead_half_spaces"] = letterhead_half_spaces
    if doctors_see_costs is not None:
        field_map["doctors_see_costs"] = doctors_see_costs

    # Filtrar campos según _partial_fields (partial update).
    if _partial_fields is not None:
        field_map = {k: v for k, v in field_map.items() if k in _partial_fields}

    for field_name, value in field_map.items():
        setattr(settings, field_name, value)

    settings.save()

    audit_record(
        action=ActionType.CLINIC_SETTINGS_UPDATE,
        resource_type="ClinicSettings",
        actor=user,
        tenant=tenant,
        resource_id=settings.id,
        resource_repr=str(settings.id),
        description=(
            "Configuración de clínica creada."
            if creating
            else "Configuración de clínica actualizada."
        ),
        metadata={"created": creating, "changed_fields": sorted(field_map.keys())},
    )
    return settings


# ---------------------------------------------------------------------------
# ClinicTemplate
# ---------------------------------------------------------------------------


def template_create(
    *,
    tenant: "Tenant",
    user: "User",
    kind: str,
    name: str,
    body: str,
    group: str = "",
) -> ClinicTemplate:
    """Crea una plantilla clínica para el tenant.

    Args:
        tenant: Clínica a la que pertenece la plantilla.
        user:   Usuario que crea el registro.
        kind:   Tipo: recipe / document / consent.
        name:   Nombre identificador.
        body:   Cuerpo de la plantilla.
        group:  Grupo temático (opcional).

    Returns:
        Instancia ClinicTemplate recién creada.

    Raises:
        ValidationError: si el kind no es válido.
    """
    from apps.clinica.models import TemplateKind

    valid_kinds = {c[0] for c in TemplateKind.choices}
    if kind not in valid_kinds:
        raise ValidationError(
            f"Tipo de plantilla inválido '{kind}'. "
            f"Los válidos son: {', '.join(sorted(valid_kinds))}."
        )

    template = ClinicTemplate.objects.create(
        tenant=tenant,
        created_by=user,
        kind=kind,
        name=name,
        body=body,
        group=group,
        is_active=True,
    )

    audit_record(
        action=ActionType.TEMPLATE_CREATE,
        resource_type="ClinicTemplate",
        actor=user,
        tenant=tenant,
        resource_id=template.id,
        resource_repr=str(template),
        metadata={"kind": kind},
    )
    return template


def template_update(
    *,
    template: ClinicTemplate,
    user: "User",
    **fields: Any,
) -> ClinicTemplate:
    """Actualiza campos permitidos de una plantilla clínica.

    No permite modificar is_active (solo vía template_deactivate),
    ni campos de identidad.

    Args:
        template: Instancia ClinicTemplate a actualizar.
        user:     Usuario que realiza el cambio.
        **fields: Campos a actualizar (name, body, group, kind).

    Returns:
        La instancia ClinicTemplate actualizada.

    Raises:
        ValidationError: si se intenta modificar un campo inmutable.
    """
    bad = _TEMPLATE_IMMUTABLE & set(fields)
    if bad:
        raise ValidationError(f"No se pueden modificar los campos: {', '.join(sorted(bad))}.")

    for field_name, value in fields.items():
        setattr(template, field_name, value)

    update_fields = list(fields.keys()) + ["updated_at"]
    template.save(update_fields=update_fields)

    audit_record(
        action=ActionType.TEMPLATE_UPDATE,
        resource_type="ClinicTemplate",
        actor=user,
        tenant=template.tenant,
        resource_id=template.id,
        resource_repr=str(template),
        metadata={"changed_fields": sorted(fields.keys())},
    )
    return template


def template_deactivate(
    *,
    template: ClinicTemplate,
    user: "User",
) -> ClinicTemplate:
    """Desactiva una plantilla clínica (baja lógica — sin borrado físico).

    Args:
        template: Instancia ClinicTemplate a desactivar.
        user:     Usuario que realiza la acción.

    Returns:
        La instancia ClinicTemplate con is_active=False.
    """
    template.is_active = False
    template.save(update_fields=["is_active", "updated_at"])

    audit_record(
        action=ActionType.TEMPLATE_DELETE,
        resource_type="ClinicTemplate",
        actor=user,
        tenant=template.tenant,
        resource_id=template.id,
        resource_repr=str(template),
    )
    return template


# ---------------------------------------------------------------------------
# PatientCategory
# ---------------------------------------------------------------------------


def patient_category_create(
    *,
    tenant: "Tenant",
    user: "User",
    name: str,
) -> PatientCategory:
    """Crea una categoría de paciente para el tenant.

    Valida que no exista ya una categoría con ese nombre activa en el tenant.

    Args:
        tenant: Clínica a la que pertenece la categoría.
        user:   Usuario que crea el registro.
        name:   Nombre de la categoría (único por tenant activo).

    Returns:
        Instancia PatientCategory recién creada.

    Raises:
        ValidationError: si ya existe una categoría con ese nombre en el tenant.
    """
    if PatientCategory.all_objects.filter(
        tenant=tenant,
        name=name,
        deleted_at__isnull=True,
    ).exists():
        raise ValidationError(f"Ya existe una categoría con el nombre '{name}' en esta clínica.")

    category = PatientCategory.objects.create(
        tenant=tenant,
        created_by=user,
        name=name,
        is_active=True,
    )

    audit_record(
        action=ActionType.PATIENT_CATEGORY_CREATE,
        resource_type="PatientCategory",
        actor=user,
        tenant=tenant,
        resource_id=category.id,
        resource_repr=category.name,
    )
    return category


def patient_category_deactivate(
    *,
    category: PatientCategory,
    user: "User",
) -> PatientCategory:
    """Desactiva una categoría de paciente (baja lógica).

    Args:
        category: Instancia PatientCategory a desactivar.
        user:     Usuario que realiza la acción.

    Returns:
        La instancia PatientCategory con is_active=False.

    Raises:
        ValidationError: si la etiqueta es del sistema (Favorito/VIP).
    """
    if category.is_system:
        raise ValidationError("Las etiquetas del sistema (Favorito y VIP) no se pueden eliminar.")
    category.is_active = False
    category.save(update_fields=["is_active", "updated_at"])

    audit_record(
        action=ActionType.PATIENT_CATEGORY_DELETE,
        resource_type="PatientCategory",
        actor=user,
        tenant=category.tenant,
        resource_id=category.id,
        resource_repr=category.name,
    )
    return category


# Nombres visibles de las etiquetas de sistema que existen en cada clínica.
SYSTEM_CATEGORY_NAMES: dict[str, str] = {
    PatientCategory.Kind.FAVORITE: "Favorito",
    PatientCategory.Kind.VIP: "VIP",
}


def seed_system_patient_categories(tenant: "Tenant") -> None:
    """Crea (idempotente) las etiquetas de sistema Favorito y VIP del tenant.

    Se invoca al dar de alta una clínica y desde la migración de datos. No
    requiere `user`: created_by queda en null (permitido para semillas).
    """
    for kind, name in SYSTEM_CATEGORY_NAMES.items():
        exists = PatientCategory.all_objects.filter(
            tenant=tenant,
            kind=kind,
            deleted_at__isnull=True,
        ).exists()
        if not exists:
            PatientCategory.objects.create(
                tenant=tenant,
                created_by=None,
                name=name,
                kind=kind,
                is_active=True,
            )


# ---------------------------------------------------------------------------
# Doctor — ampliaciones (sello, foto, cédulas adicionales)
# ---------------------------------------------------------------------------


def doctor_update_profile_images(
    *,
    doctor: "Doctor",
    user: "User",
    sello: Any = None,
    foto: Any = None,
    cedulas_adicionales: str | None = None,
) -> "Doctor":
    """Actualiza sello, foto y/o cédulas adicionales del médico.

    Solo actualiza los campos que se pasan explícitamente (None = no cambiar).
    La validación de imagen la hace el ImageField via validators=[validate_clinic_image].

    Args:
        doctor:              Instancia Doctor a actualizar.
        user:                Usuario que realiza la acción (auditoría).
        sello:               Archivo de imagen del sello/firma (opcional).
        foto:                Fotografía del médico (opcional).
        cedulas_adicionales: Cédulas adicionales separadas por coma (opcional).

    Returns:
        La instancia Doctor actualizada.
    """
    changed: list[str] = []

    if sello is not None:
        doctor.sello = sello  # type: ignore[assignment]
        changed.append("sello")
    if foto is not None:
        doctor.foto = foto  # type: ignore[assignment]
        changed.append("foto")
    if cedulas_adicionales is not None:
        doctor.cedulas_adicionales = cedulas_adicionales  # type: ignore[assignment]
        changed.append("cedulas_adicionales")

    if not changed:
        return doctor

    doctor.save(update_fields=changed + ["updated_at"])

    audit_record(
        action=ActionType.DOCTOR_UPDATE,
        resource_type="Doctor",
        actor=user,
        tenant=doctor.tenant,
        resource_id=doctor.id,
        resource_repr=str(doctor),
        metadata={"changed_fields": changed, "context": "profile_images"},
    )
    return doctor


# ---------------------------------------------------------------------------
# DoctorUniversity
# ---------------------------------------------------------------------------


def doctor_university_create(
    *,
    tenant: "Tenant",
    user: "User",
    doctor: "Doctor",
    logo: Any,
    name: str = "",
) -> DoctorUniversity:
    """Crea un registro de universidad/institución para un médico.

    Valida que el doctor pertenezca al tenant actual (defensa en profundidad).

    Args:
        tenant: Clínica a la que pertenece el médico.
        user:   Usuario que crea el registro.
        doctor: Médico al que se asocia la institución.
        logo:   Archivo de imagen del logo de la institución.
        name:   Nombre de la institución (opcional).

    Returns:
        Instancia DoctorUniversity recién creada.

    Raises:
        ValidationError: si el doctor no pertenece al tenant.
    """
    if doctor.tenant_id != tenant.id:
        raise ValidationError("El médico no pertenece a esta clínica.")

    university = DoctorUniversity.objects.create(
        tenant=tenant,
        created_by=user,
        doctor=doctor,
        logo=logo,
        name=name,
    )

    audit_record(
        action=ActionType.DOCTOR_UPDATE,
        resource_type="DoctorUniversity",
        actor=user,
        tenant=tenant,
        resource_id=university.id,
        resource_repr=f"{name or 'Logo'} — {str(doctor)}",
        metadata={"doctor_id": str(doctor.id), "context": "university_create"},
    )
    return university


def doctor_university_delete(
    *,
    university: DoctorUniversity,
    user: "User",
) -> None:
    """Elimina físicamente un registro de universidad (no hay datos clínicos aquí).

    A diferencia de los registros clínicos, las universidades son metadatos de
    configuración; no tienen obligación de auditoría de retención. Se borra
    físicamente para que el storage (logo) pueda limpiarse.

    Args:
        university: Instancia DoctorUniversity a eliminar.
        user:       Usuario que realiza la acción.
    """
    doctor_id = university.doctor_id
    university_id = university.id
    university_name = university.name
    # B-2: capturar tenant ANTES del delete; acceder a university.tenant post-delete
    # levanta RelatedObjectDoesNotExist porque Django limpia las FK en memoria.
    tenant = university.tenant

    # Borrado físico (no hay soft-delete aquí por decisión de diseño).
    university.delete()

    audit_record(
        action=ActionType.DOCTOR_UPDATE,
        resource_type="DoctorUniversity",
        actor=user,
        tenant=tenant,
        resource_id=university_id,
        resource_repr=f"{university_name or 'Logo'} eliminado",
        metadata={"doctor_id": str(doctor_id), "context": "university_delete"},
    )


# ---------------------------------------------------------------------------
# DoctorCredential — credenciales estructuradas COFEPRIS F2
# ---------------------------------------------------------------------------


def doctor_credential_create(
    *,
    tenant: "Tenant",
    user: "User",
    doctor: "Doctor",
    title: str,
    institution: str,
    kind: str,
    credential_number: str = "",
    order: int = 0,
    logo: Any = None,
) -> DoctorCredential:
    """Crea una credencial académica estructurada para un médico.

    Valida que el doctor pertenezca al tenant actual (defensa en profundidad).
    El campo `kind` debe ser un valor de CredentialKind.
    El campo `logo` es opcional: imagen (JPG/PNG/WEBP, máx 5 MB) del logo de la
    institución que expide la credencial. Su presencia elimina la necesidad de
    emparejar credenciales con logos de DoctorUniversity por orden (bug previo).

    Args:
        tenant:            Clínica a la que pertenece el médico.
        user:              Usuario que crea el registro (auditoría).
        doctor:            Médico al que se asocia la credencial.
        title:             Nombre del título sin abreviaturas (requerido).
        institution:       Institución que expide el título (requerido).
        kind:              Tipo: profesional, especialidad o posgrado.
        credential_number: Número de cédula (opcional, puede estar en blanco).
        order:             Orden de aparición en el membrete (default 0).
        logo:              Archivo de imagen de la institución (opcional).

    Returns:
        Instancia DoctorCredential recién creada.

    Raises:
        ValidationError: si el doctor no pertenece al tenant o kind es inválido.
    """
    if doctor.tenant_id != tenant.id:
        raise ValidationError("El médico no pertenece a esta clínica.")

    valid_kinds = {c[0] for c in CredentialKind.choices}
    if kind not in valid_kinds:
        raise ValidationError(
            f"Tipo de credencial inválido '{kind}'. "
            f"Los válidos son: {', '.join(sorted(valid_kinds))}."
        )

    title = title.strip()
    if not title:
        raise ValidationError("El título de la credencial no puede estar vacío.")

    institution = institution.strip()
    if not institution:
        raise ValidationError("La institución de la credencial no puede estar vacía.")

    create_kwargs: dict[str, Any] = {
        "tenant": tenant,
        "created_by": user,
        "doctor": doctor,
        "title": title,
        "institution": institution,
        "kind": kind,
        "credential_number": credential_number.strip(),
        "order": order,
        "is_active": True,
    }
    if logo is not None:
        create_kwargs["logo"] = logo

    credential = DoctorCredential.objects.create(**create_kwargs)

    audit_record(
        action=ActionType.CREDENTIAL_CREATE,
        resource_type="DoctorCredential",
        actor=user,
        tenant=tenant,
        resource_id=credential.id,
        resource_repr=f"[{kind}] {title} — doctor={str(doctor.id)}",
        metadata={"doctor_id": str(doctor.id), "kind": kind},
    )
    _notify_credential_pending(credential, user)
    return credential


def doctor_credential_update(
    *,
    credential: DoctorCredential,
    user: "User",
    title: str | None = None,
    institution: str | None = None,
    kind: str | None = None,
    credential_number: str | None = None,
    order: int | None = None,
    logo: Any = None,
    logo_provided: bool = False,
) -> DoctorCredential:
    """Actualiza (edición parcial) una credencial existente del médico.

    Solo modifica los campos provistos (no-None). El logo se actualiza únicamente
    cuando `logo_provided=True`: así se distingue "no enviar logo" (no tocar) de
    "enviar logo nuevo" o "quitar logo" (logo=None). Valida `kind` y campos no vacíos.

    Args:
        credential:        Instancia DoctorCredential a editar.
        user:              Usuario que realiza la acción (auditoría).
        title/institution/kind/credential_number/order: campos opcionales a cambiar.
        logo:              Nuevo archivo de logo (o None para quitarlo).
        logo_provided:     True si se debe aplicar el cambio de logo.

    Returns:
        La instancia DoctorCredential actualizada.

    Raises:
        ValidationError: si kind es inválido o un campo de texto queda vacío.
    """
    update_fields: list[str] = []

    if title is not None:
        title = title.strip()
        if not title:
            raise ValidationError("El título de la credencial no puede estar vacío.")
        credential.title = title
        update_fields.append("title")

    if institution is not None:
        institution = institution.strip()
        if not institution:
            raise ValidationError("La institución de la credencial no puede estar vacía.")
        credential.institution = institution
        update_fields.append("institution")

    if kind is not None:
        valid_kinds = {c[0] for c in CredentialKind.choices}
        if kind not in valid_kinds:
            raise ValidationError(
                f"Tipo de credencial inválido '{kind}'. "
                f"Los válidos son: {', '.join(sorted(valid_kinds))}."
            )
        credential.kind = kind
        update_fields.append("kind")

    if credential_number is not None:
        credential.credential_number = credential_number.strip()
        update_fields.append("credential_number")

    if order is not None:
        credential.order = order
        update_fields.append("order")

    if logo_provided:
        credential.logo = logo
        update_fields.append("logo")

    # Si cambió información académica, la credencial vuelve a "pendiente" de
    # validación (su contenido validado cambió). Cambios de logo/orden no invalidan.
    academic_changed = any(
        f in update_fields for f in ("title", "institution", "credential_number", "kind")
    )
    if academic_changed and credential.validation_status != CredentialValidationStatus.PENDIENTE:
        credential.validation_status = CredentialValidationStatus.PENDIENTE
        credential.validation_note = ""
        update_fields.append("validation_status")
        update_fields.append("validation_note")

    if update_fields:
        update_fields.append("updated_at")
        credential.save(update_fields=update_fields)

    audit_record(
        action=ActionType.CREDENTIAL_UPDATE,
        resource_type="DoctorCredential",
        actor=user,
        tenant=credential.tenant,
        resource_id=credential.id,
        resource_repr=f"[{credential.kind}] {credential.title}",
        metadata={"doctor_id": str(credential.doctor_id), "fields": update_fields},
    )
    # Si la edición la regresó a "pendiente", avisar de nuevo a los administradores.
    if academic_changed:
        _notify_credential_pending(credential, user)
    return credential


def doctor_credential_set_validation(
    *,
    credential: DoctorCredential,
    user: "User",
    status: str,
    note: str = "",
) -> DoctorCredential:
    """Valida o rechaza una credencial del médico (acción administrativa).

    Flujo híbrido: el médico captura sus credenciales (pendientes) y un owner/admin
    las revisa aquí. Solo las 'validada' aparecen en la receta. El 'rechazada' guarda
    el motivo en `validation_note`. La vista controla que solo owner/admin invoque.

    Args:
        credential: Credencial a validar/rechazar.
        user:       Administrador que realiza la acción (auditoría).
        status:     'validada' o 'rechazada'.
        note:       Motivo/observación (recomendado al rechazar).

    Returns:
        La credencial actualizada.

    Raises:
        ValidationError: si el estado no es 'validada' ni 'rechazada'.
    """
    allowed = {
        CredentialValidationStatus.VALIDADA.value,
        CredentialValidationStatus.RECHAZADA.value,
    }
    if status not in allowed:
        raise ValidationError("El estado de validación debe ser 'validada' o 'rechazada'.")

    credential.validation_status = status
    credential.validation_note = (note or "").strip()
    credential.save(update_fields=["validation_status", "validation_note", "updated_at"])

    audit_record(
        action=ActionType.CREDENTIAL_VALIDATE,
        resource_type="DoctorCredential",
        actor=user,
        tenant=credential.tenant,
        resource_id=credential.id,
        resource_repr=f"[{credential.kind}] {credential.title} → {status}",
        metadata={"doctor_id": str(credential.doctor_id), "status": status},
    )
    _notify_credential_result(credential, user, status)
    return credential


def doctor_credential_delete(
    *,
    credential: DoctorCredential,
    user: "User",
) -> None:
    """Da de baja lógica una credencial del médico (is_active=False).

    A diferencia de DoctorUniversity, las credenciales son documentos con
    implicaciones legales (COFEPRIS): se conservan en BD con baja lógica para
    auditoría histórica. No se borran físicamente.

    Args:
        credential: Instancia DoctorCredential a dar de baja.
        user:       Usuario que realiza la acción.
    """
    doctor_id = credential.doctor_id
    credential_id = credential.id
    credential_repr = f"[{credential.kind}] {credential.title}"
    tenant = credential.tenant

    credential.is_active = False
    credential.save(update_fields=["is_active", "updated_at"])

    audit_record(
        action=ActionType.CREDENTIAL_DELETE,
        resource_type="DoctorCredential",
        actor=user,
        tenant=tenant,
        resource_id=credential_id,
        resource_repr=f"{credential_repr} dado de baja",
        metadata={"doctor_id": str(doctor_id)},
    )


# ---------------------------------------------------------------------------
# ClinicTeamMember — equipo/departamentos de la clínica (Fase 4)
# ---------------------------------------------------------------------------

_TEAM_MEMBER_IMMUTABLE: frozenset[str] = frozenset(
    {"id", "tenant", "tenant_id", "created_at", "updated_at", "deleted_at", "is_active"}
)


def clinic_team_member_create(
    *,
    tenant: "Tenant",
    user: "User",
    departamento: str,
    nombre: str,
    order: int = 0,
    is_active: bool = True,
) -> ClinicTeamMember:
    """Crea un miembro del equipo de la clínica.

    Args:
        tenant:       Clínica a la que pertenece el miembro.
        user:         Usuario que crea el registro.
        departamento: Departamento o área del equipo.
        nombre:       Nombre de la persona.
        order:        Posición de aparición (0 = primero).
        is_active:    True = visible en el catálogo (default).

    Returns:
        Instancia ClinicTeamMember recién creada.
    """
    member = ClinicTeamMember.objects.create(
        tenant=tenant,
        created_by=user,
        departamento=departamento,
        nombre=nombre,
        order=order,
        is_active=is_active,
    )
    audit_record(
        action=ActionType.CLINIC_TEAM_MEMBER_CREATE,
        resource_type="ClinicTeamMember",
        actor=user,
        tenant=tenant,
        resource_id=member.id,
        resource_repr=str(member),
    )
    return member


def clinic_team_member_update(
    *,
    member: ClinicTeamMember,
    user: "User",
    **fields: Any,
) -> ClinicTeamMember:
    """Actualiza campos permitidos de un miembro del equipo.

    No permite modificar is_active (solo vía clinic_team_member_activate/
    deactivate) ni campos de identidad.

    Raises:
        ValidationError: si se intenta modificar un campo inmutable.
    """
    bad = _TEAM_MEMBER_IMMUTABLE & set(fields)
    if bad:
        raise ValidationError(f"No se pueden modificar los campos: {', '.join(sorted(bad))}.")

    for field_name, value in fields.items():
        setattr(member, field_name, value)

    update_fields = [*fields.keys(), "updated_at"]
    member.save(update_fields=update_fields)

    audit_record(
        action=ActionType.CLINIC_TEAM_MEMBER_UPDATE,
        resource_type="ClinicTeamMember",
        actor=user,
        tenant=member.tenant,
        resource_id=member.id,
        resource_repr=str(member),
    )
    return member


def clinic_team_member_activate(*, member: ClinicTeamMember, user: "User") -> ClinicTeamMember:
    """Reactiva un miembro del equipo (is_active=True)."""
    member.is_active = True
    member.save(update_fields=["is_active", "updated_at"])
    audit_record(
        action=ActionType.CLINIC_TEAM_MEMBER_UPDATE,
        resource_type="ClinicTeamMember",
        actor=user,
        tenant=member.tenant,
        resource_id=member.id,
        resource_repr=str(member),
    )
    return member


def clinic_team_member_deactivate(*, member: ClinicTeamMember, user: "User") -> ClinicTeamMember:
    """Oculta un miembro del equipo del catálogo (is_active=False)."""
    member.is_active = False
    member.save(update_fields=["is_active", "updated_at"])
    audit_record(
        action=ActionType.CLINIC_TEAM_MEMBER_UPDATE,
        resource_type="ClinicTeamMember",
        actor=user,
        tenant=member.tenant,
        resource_id=member.id,
        resource_repr=str(member),
    )
    return member


def clinic_team_member_delete(*, member: ClinicTeamMember, user: "User") -> None:
    """Baja lógica (deleted_at) de un miembro del equipo — no borra físicamente."""
    member.deleted_at = timezone.now()
    member.save(update_fields=["deleted_at", "updated_at"])
    audit_record(
        action=ActionType.CLINIC_TEAM_MEMBER_DELETE,
        resource_type="ClinicTeamMember",
        actor=user,
        tenant=member.tenant,
        resource_id=member.id,
        resource_repr=str(member),
    )


# ---------------------------------------------------------------------------
# Sucursal — multi-sede (Fase 1)
# ---------------------------------------------------------------------------
#
# is_active e is_default NUNCA se exponen en el PATCH genérico (regla de
# campos sensibles del proyecto): viven en _SUCURSAL_IMMUTABLE y solo se
# cambian vía sucursal_activate / sucursal_deactivate / sucursal_set_default.

_SUCURSAL_IMMUTABLE: frozenset[str] = frozenset(
    {
        "id",
        "tenant",
        "tenant_id",
        "created_at",
        "updated_at",
        "deleted_at",
        "is_active",
        "is_default",
    }
)


def sucursal_create(
    *,
    tenant: "Tenant",
    user: "User",
    name: str,
    address: str = "",
    phone: str = "",
    color_hex: str = "",
    is_default: bool = False,
) -> Sucursal:
    """Crea una sucursal para el tenant.

    Valida que el nombre sea único en el tenant. Si `is_default=True`, marca
    la nueva sucursal como predeterminada (desmarcando cualquier otra) vía
    `sucursal_set_default` DESPUÉS de crearla, en la misma transacción.

    Args:
        tenant:     Clínica (negocio) a la que pertenece la sucursal.
        user:       Usuario que crea el registro (auditoría).
        name:       Nombre de la sucursal. Único por tenant.
        address:    Dirección física (opcional).
        phone:      Teléfono de contacto (opcional).
        color_hex:  Color #RRGGBB para la agenda (opcional, uso futuro Fase 2).
        is_default: Si True, la marca como predeterminada del tenant.

    Returns:
        Instancia Sucursal recién creada.

    Raises:
        ValidationError: si ya existe una sucursal con ese nombre en el tenant.
    """
    if Sucursal.all_objects.filter(tenant=tenant, name=name, deleted_at__isnull=True).exists():
        raise ValidationError(f"Ya existe una sucursal con el nombre '{name}' en esta clínica.")

    with transaction.atomic():
        sucursal = Sucursal(
            tenant=tenant,
            created_by=user,
            name=name,
            address=address,
            phone=phone,
            color_hex=color_hex,
            is_active=True,
            is_default=False,
        )
        sucursal.full_clean(exclude=["tenant", "created_by"])
        sucursal.save()

        audit_record(
            action=ActionType.SUCURSAL_CREATE,
            resource_type="Sucursal",
            actor=user,
            tenant=tenant,
            resource_id=sucursal.id,
            resource_repr=sucursal.name,
        )

        if is_default:
            sucursal = sucursal_set_default(sucursal=sucursal, user=user)

    return sucursal


def sucursal_update(
    *,
    sucursal: Sucursal,
    user: "User",
    **fields: Any,
) -> Sucursal:
    """Actualiza campos permitidos de una sucursal existente.

    No permite modificar is_active ni is_default (solo vía sucursal_activate/
    deactivate/set_default), ni campos de identidad. Si se cambia `name`,
    revalida unicidad dentro del tenant.

    Args:
        sucursal: Instancia Sucursal a actualizar.
        user:     Usuario que realiza el cambio (auditoría).
        **fields: Campos a actualizar (name, address, phone, color_hex).

    Returns:
        La instancia Sucursal actualizada.

    Raises:
        ValidationError: si se intenta modificar un campo inmutable, o si el
                         nuevo nombre ya existe en el tenant.
    """
    bad = _SUCURSAL_IMMUTABLE & set(fields)
    if bad:
        raise ValidationError(f"No se pueden modificar los campos: {', '.join(sorted(bad))}.")

    new_name = fields.get("name")
    if new_name is not None and new_name != sucursal.name:
        duplicate_exists = (
            Sucursal.all_objects.filter(
                tenant=sucursal.tenant, name=new_name, deleted_at__isnull=True
            )
            .exclude(id=sucursal.id)
            .exists()
        )
        if duplicate_exists:
            raise ValidationError(
                f"Ya existe una sucursal con el nombre '{new_name}' en esta clínica."
            )

    for field_name, value in fields.items():
        setattr(sucursal, field_name, value)

    update_fields = [*fields.keys(), "updated_at"]
    sucursal.full_clean(exclude=["tenant", "created_by"])
    sucursal.save(update_fields=update_fields)

    audit_record(
        action=ActionType.SUCURSAL_UPDATE,
        resource_type="Sucursal",
        actor=user,
        tenant=sucursal.tenant,
        resource_id=sucursal.id,
        resource_repr=sucursal.name,
        metadata={"changed_fields": sorted(fields.keys())},
    )
    return sucursal


def sucursal_activate(*, sucursal: Sucursal, user: "User") -> Sucursal:
    """Reactiva una sucursal desactivada (is_active=True)."""
    sucursal.is_active = True
    sucursal.save(update_fields=["is_active", "updated_at"])
    audit_record(
        action=ActionType.SUCURSAL_ACTIVATE,
        resource_type="Sucursal",
        actor=user,
        tenant=sucursal.tenant,
        resource_id=sucursal.id,
        resource_repr=sucursal.name,
    )
    return sucursal


def sucursal_deactivate(*, sucursal: Sucursal, user: "User") -> Sucursal:
    """Desactiva una sucursal (soft — is_active=False, no borra el registro).

    Regla de negocio: la sucursal predeterminada del tenant NO se puede
    desactivar directamente (un tenant siempre debe tener una sede activa por
    defecto). Hay que marcar otra como predeterminada primero.

    Raises:
        ValidationError: si `sucursal` es la predeterminada del tenant.
    """
    if sucursal.is_default:
        raise ValidationError(
            "No se puede desactivar la sucursal predeterminada. "
            "Marca otra sucursal como predeterminada primero."
        )

    sucursal.is_active = False
    sucursal.save(update_fields=["is_active", "updated_at"])
    audit_record(
        action=ActionType.SUCURSAL_DEACTIVATE,
        resource_type="Sucursal",
        actor=user,
        tenant=sucursal.tenant,
        resource_id=sucursal.id,
        resource_repr=sucursal.name,
    )
    return sucursal


def sucursal_set_default(*, sucursal: Sucursal, user: "User") -> Sucursal:
    """Marca `sucursal` como la predeterminada del tenant; desmarca cualquier otra.

    Solo una sucursal por tenant puede tener is_default=True (constraint
    `sucursal_tenant_one_default_uniq`). Se desmarca la anterior ANTES de
    marcar la nueva, dentro de la misma transacción, para nunca violar el
    índice único parcial.

    Raises:
        ValidationError: si la sucursal está desactivada (no puede ser
                         predeterminada una sede que no opera).
    """
    if not sucursal.is_active:
        raise ValidationError("No se puede marcar como predeterminada una sucursal inactiva.")

    with transaction.atomic():
        Sucursal.all_objects.filter(tenant_id=sucursal.tenant_id, is_default=True).exclude(
            id=sucursal.id
        ).update(is_default=False, updated_at=timezone.now())

        sucursal.is_default = True
        sucursal.save(update_fields=["is_default", "updated_at"])

    audit_record(
        action=ActionType.SUCURSAL_SET_DEFAULT,
        resource_type="Sucursal",
        actor=user,
        tenant=sucursal.tenant,
        resource_id=sucursal.id,
        resource_repr=sucursal.name,
    )
    return sucursal


# ---------------------------------------------------------------------------
# MembershipSucursal — asignación de sedes a un miembro (Fase 4)
# ---------------------------------------------------------------------------
#
# Este es el service que HABILITA crear un "administrador de sucursal" desde
# la app: asignarle a un admin solo la sede Centro lo acota a operar/ver
# SOLO Centro (apps.clinica.sucursal_scope.allowed_sucursales); asignarle
# TODAS las sedes activas del tenant lo convierte en "admin de negocio".
#
# Autorización — SEGURIDAD (cierre de escalada de privilegios):
#   La vista (MembershipSucursalPermission) solo gatea por ROL: únicamente
#   owner y admin pueden llegar aquí. La granularidad fina —qué sede puede
#   tocar CADA admin— es lógica de negocio y vive en este service, no en la
#   vista ni en el permiso DRF (mismo principio que
#   sucursal_scope.resolve_write_sucursal, que también autoriza en la capa
#   de servicio en vez de en el permiso method-aware):
#     - owner: sin restricción adicional (más allá de que la sucursal sea del
#       mismo tenant): puede otorgar/quitar CUALQUIER sede a cualquier miembro.
#     - admin (no owner): solo puede TOCAR (otorgar U quitar) sucursales que
#       él mismo tiene en su propio `allowed_sucursales`. Se calcula la
#       diferencia simétrica entre el conjunto actual y el solicitado — las
#       sedes que NO cambian no se validan (un admin de Centro puede dejar
#       intacta una asignación a Norte que ya existía, hecha por el owner;
#       lo que no puede es AGREGAR Norte ni QUITAR Norte).

_MEMBERSHIP_SUCURSAL_ANTI_LOCKOUT_OWNER = (
    "No se puede dejar al dueño de la clínica sin sucursales asignadas."
)
_MEMBERSHIP_SUCURSAL_ANTI_LOCKOUT_SELF_ADMIN = (
    "No puedes quitarte a ti mismo todas las sucursales asignadas: perderías acceso a la sede."
)


def membership_sucursales_set(
    *,
    tenant: "Tenant",
    actor: "User",
    membership: TenantMembership,
    sucursal_ids: list[uuid.UUID],
) -> TenantMembership:
    """Reemplaza el conjunto COMPLETO de sucursales asignadas a una membresía.

    Es el service que permite crear un "administrador de sucursal": una
    membresía con rol admin y UNA sola fila de MembershipSucursal queda
    acotada a esa sede vía `apps.clinica.sucursal_scope.allowed_sucursales`.

    Autorización (ver bloque de comentarios arriba en el módulo):
        - `actor` debe tener una membresía activa en `tenant` (owner o admin;
          cualquier otro rol ya fue rechazado por
          `MembershipSucursalPermission` antes de llegar aquí, pero se
          revalida — defensa en profundidad).
        - Si `actor` es owner: sin restricción adicional sobre qué sedes toca.
        - Si `actor` es admin (no owner): la diferencia simétrica entre el
          conjunto ACTUAL y el conjunto NUEVO (`sucursal_ids`) —es decir, lo
          que se agrega MÁS lo que se quita— debe estar contenida en
          `allowed_sucursales(user=actor, tenant=tenant)`. Si el actor
          intenta tocar una sede fuera de su alcance (otorgarla o quitarla),
          se rechaza con un mensaje claro.

    Validaciones de datos:
        - `membership` debe pertenecer a `tenant` (defensa en profundidad;
          la vista ya la resuelve tenant-scoped vía `membership_get`).
        - Cada id de `sucursal_ids` debe existir, pertenecer a `tenant` y
          estar activo.

    Anti-lockout:
        - Si `membership` es la del OWNER del tenant: `sucursal_ids` no puede
          quedar vacío (el owner igual ve todas las sedes por rol —
          `allowed_sucursales` no depende de MembershipSucursal para el
          owner— pero se rechaza el intento explícito de vaciarlo).
        - Si `actor` es admin y `membership` ES la propia membresía del
          actor: `sucursal_ids` no puede quedar vacío (un admin SÍ depende
          de MembershipSucursal para su alcance; vaciarlo lo autobloquearía
          de operar cualquier sede).

    Args:
        tenant:       Tenant (negocio) de la membresía y de las sucursales.
        actor:        Usuario que realiza la asignación (auditoría + autorización).
        membership:   TenantMembership objetivo a la que se le fija el conjunto
                      de sedes (ya resuelta tenant-scoped por el caller).
        sucursal_ids: Conjunto COMPLETO de sucursales a dejar asignadas
                      (reemplaza, no añade). Puede ser una lista vacía.

    Returns:
        La misma instancia TenantMembership (sin recargar; el caller relee
        sus sucursales con `membership_sucursales_list`).

    Raises:
        ValidationError: membership de otro tenant, sucursal_ids con ids que
            no existen/no son del tenant/están inactivos, un admin tocando
            una sede fuera de su alcance, o violación de una regla anti-lockout.
    """
    if membership.tenant_id != tenant.id:
        raise ValidationError("La membresía no pertenece a esta clínica.")

    unique_ids: set[uuid.UUID] = set(sucursal_ids)

    if unique_ids:
        sucursales = list(
            Sucursal.all_objects.filter(
                id__in=unique_ids, tenant_id=tenant.id, deleted_at__isnull=True
            )
        )
        found_ids = {s.id for s in sucursales}
        missing = unique_ids - found_ids
        if missing:
            raise ValidationError(
                "Una o más sucursales no existen en esta clínica: "
                f"{', '.join(str(i) for i in sorted(missing, key=str))}."
            )
        inactive = [s for s in sucursales if not s.is_active]
        if inactive:
            names = ", ".join(s.name for s in inactive)
            raise ValidationError(f"Las siguientes sucursales están inactivas: {names}.")

    actor_membership = (
        TenantMembership.objects.filter(
            user=actor, tenant=tenant, is_active=True, deleted_at__isnull=True
        )
        .order_by("created_at")
        .first()
    )
    if actor_membership is None:
        raise ValidationError("No tienes una membresía activa en esta clínica.")

    current_ids: set[uuid.UUID] = set(
        MembershipSucursal.all_objects.filter(
            tenant_id=tenant.id, membership=membership
        ).values_list("sucursal_id", flat=True)
    )

    if actor_membership.role != TenantMembership.Role.OWNER:
        admin_allowed_ids: set[uuid.UUID] = set(
            allowed_sucursales(user=actor, tenant=tenant).values_list("id", flat=True)
        )
        touched = unique_ids.symmetric_difference(current_ids)
        forbidden = touched - admin_allowed_ids
        if forbidden:
            raise ValidationError(
                "No puedes otorgar ni quitar acceso a sucursales que tú mismo no tienes "
                "asignadas."
            )

    if membership.role == TenantMembership.Role.OWNER and not unique_ids:
        raise ValidationError(_MEMBERSHIP_SUCURSAL_ANTI_LOCKOUT_OWNER)

    if (
        actor_membership.role != TenantMembership.Role.OWNER
        and membership.id == actor_membership.id
        and not unique_ids
    ):
        raise ValidationError(_MEMBERSHIP_SUCURSAL_ANTI_LOCKOUT_SELF_ADMIN)

    with transaction.atomic():
        MembershipSucursal.all_objects.filter(tenant_id=tenant.id, membership=membership).exclude(
            sucursal_id__in=unique_ids
        ).delete()

        existing_ids: set[uuid.UUID] = set(
            MembershipSucursal.all_objects.filter(
                tenant_id=tenant.id, membership=membership
            ).values_list("sucursal_id", flat=True)
        )
        to_create = [
            MembershipSucursal(
                tenant=tenant,
                created_by=actor,
                membership=membership,
                sucursal_id=sucursal_id,
            )
            for sucursal_id in unique_ids - existing_ids
        ]
        if to_create:
            MembershipSucursal.all_objects.bulk_create(to_create)

    audit_record(
        action=ActionType.MEMBERSHIP_SUCURSALES_SET,
        resource_type="TenantMembership",
        actor=actor,
        tenant=tenant,
        resource_id=membership.id,
        resource_repr=str(membership.id),
        metadata={"sucursal_ids": [str(i) for i in sorted(unique_ids, key=str)]},
    )
    return membership
