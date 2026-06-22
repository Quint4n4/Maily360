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

import uuid
from typing import TYPE_CHECKING, Any, Optional

from django.core.exceptions import ValidationError

from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.clinica.models import ClinicSettings, ClinicTemplate, CredentialKind, DoctorCredential, DoctorUniversity, PatientCategory
from apps.clinica.selectors import clinic_settings_get

if TYPE_CHECKING:
    from apps.authn.models import User
    from apps.personal.models import Doctor
    from apps.tenancy.models import Tenant


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
    letterhead_full_spaces: Optional[int] = None,
    letterhead_half_spaces: Optional[int] = None,
    commercial_name: str = "",
    # Soporte partial update: solo actualiza los campos explícitamente pasados.
    _partial_fields: Optional[frozenset[str]] = None,
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
        description="Configuración de clínica creada." if creating else "Configuración de clínica actualizada.",
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
        raise ValidationError(
            f"No se pueden modificar los campos: {', '.join(sorted(bad))}."
        )

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
        raise ValidationError(
            f"Ya existe una categoría con el nombre '{name}' en esta clínica."
        )

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
    """
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


# ---------------------------------------------------------------------------
# Doctor — ampliaciones (sello, foto, cédulas adicionales)
# ---------------------------------------------------------------------------


def doctor_update_profile_images(
    *,
    doctor: "Doctor",
    user: "User",
    sello: Any = None,
    foto: Any = None,
    cedulas_adicionales: Optional[str] = None,
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
