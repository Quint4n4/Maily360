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
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
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
    PatientCategory,
)
from apps.clinica.selectors import clinic_settings_get

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
