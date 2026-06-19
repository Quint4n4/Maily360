"""
Generación de PDF para recetas médicas — F1 (multi-formato).

Librería: xhtml2pdf (puro Python/pip, sin dependencias de sistema).
  Nota: Se evaluó WeasyPrint pero requiere libpango/libcairo/libgdk-pixbuf en el
  sistema operativo. El Dockerfile usa python:3.12-slim sin esas libs; instalarlas
  en ambos stages (builder + runtime) implicaría reconstrucción completa del venv
  y +200 MB en la imagen. xhtml2pdf no requiere tocar el Dockerfile y cumple el
  requisito funcional completamente.

Formatos disponibles (F1):
  standard  — Carta vertical, membrete digital limpio. (refactor del original)
  compact   — Media carta horizontal (8.5×5.5 in). Caso Camsa. 2 columnas.
  digital   — Carta vertical amigable para el paciente.

Imágenes (logo, sello):
  Se incrustan como data URI en base64. Funciona con FileSystemStorage (dev)
  y S3Boto3Storage (prod). Si el archivo no existe o falla, se omite silenciosamente.

Decisión sobre recipe_use_responsible_doctor:
  El modelo ClinicSettings tiene el flag `recipe_use_responsible_doctor` pero no
  existe aún un concepto de "médico responsable de la clínica" como entidad
  separada en el sistema (no hay FK en ClinicSettings a un Doctor). Mientras ese
  concepto no esté implementado, este flag se ignora y se usa siempre el médico
  que emitió la receta (doctor directo de la Prescription).
"""

import base64
import logging
import mimetypes
from io import BytesIO
from typing import Any, Literal, Optional

from django.template.loader import render_to_string
from PIL import Image

logger = logging.getLogger("apps.recetas.pdf")

# Formatos soportados (F1). F3 los persistirá en PrescriptionFormat.
BaseLayout = Literal["standard", "compact", "digital"]
VALID_LAYOUTS: frozenset[str] = frozenset({"standard", "compact", "digital"})

# Mapeo layout → template relativo a TEMPLATES dirs.
_TEMPLATE_MAP: dict[str, str] = {
    "standard": "recetas/formats/standard.html",
    "compact": "recetas/formats/compact.html",
    "digital": "recetas/formats/digital.html",
}


def _image_box(field: Any, max_w_pt: float, max_h_pt: float) -> dict[str, Any]:
    """Prepara una imagen (logo/sello) para el PDF con dimensiones proporcionales.

    xhtml2pdf NO respeta `max-width`/`max-height` en CSS: si no se dan dimensiones
    exactas en el tag, la imagen sale a tamaño nativo (gigante) o deformada. Para
    que CUALQUIER logo —cuadrado, horizontal o vertical— se vea bien, se lee su
    tamaño real con Pillow y se calcula (w, h) en pt que encaje dentro de la caja
    `max_w_pt × max_h_pt` MANTENIENDO la proporción.

    Returns:
        dict con `b64`, `mime`, `w`, `h` (w/h en pt; 0 si no hay imagen válida).
    """
    mime, b64 = _image_to_data_uri(field)
    if not b64:
        return {"b64": "", "mime": "", "w": 0, "h": 0}
    try:
        raw = base64.b64decode(b64)
        with Image.open(BytesIO(raw)) as img:
            w_px, h_px = img.size
    except Exception:  # noqa: BLE001
        return {"b64": b64, "mime": mime, "w": 0, "h": 0}
    if w_px <= 0 or h_px <= 0:
        return {"b64": b64, "mime": mime, "w": 0, "h": 0}
    scale = min(max_w_pt / w_px, max_h_pt / h_px)
    return {
        "b64": b64,
        "mime": mime,
        "w": max(1, round(w_px * scale)),
        "h": max(1, round(h_px * scale)),
    }


def _link_callback(uri: str, rel: str) -> str:  # noqa: ARG001
    """Callback de seguridad para xhtml2pdf — bloquea acceso a recursos externos.

    Política:
        - URIs ``data:`` → se devuelven tal cual (son los únicos recursos usados).
        - Cualquier otro esquema (file://, http://, rutas relativas) → cadena vacía
          y WARNING. xhtml2pdf omite el recurso silenciosamente (comportamiento seguro).

    Args:
        uri: URI del recurso tal como aparece en el HTML/CSS.
        rel: Ruta relativa base (ignorada).

    Returns:
        La URI original si es ``data:``; cadena vacía en cualquier otro caso.
    """
    if uri.startswith("data:"):
        return uri

    logger.warning(
        "pdf._link_callback: URI bloqueada por política de seguridad — '%s'. "
        "Solo se permiten data URIs en el template de receta.",
        uri[:200],
    )
    return ""


_MIME_FALLBACK = "image/png"


def _image_to_data_uri(field: Any) -> tuple[str, str]:
    """Lee un ImageField (local o S3) y devuelve (mime, base64_str).

    Args:
        field: Un ImageField de Django.

    Returns:
        Tupla (mime_type, base64_encoded_bytes) o ("", "") si no aplica.
    """
    if not field:
        return ("", "")

    try:
        name: str = field.name or ""
        if not name:
            return ("", "")

        mime, _ = mimetypes.guess_type(name)
        if not mime:
            mime = _MIME_FALLBACK

        mime_subtype = mime.split("/")[-1] if "/" in mime else mime

        with field.open("rb") as f:
            raw: bytes = f.read()

        encoded = base64.b64encode(raw).decode("ascii")
        return (mime_subtype, encoded)

    except Exception:  # noqa: BLE001
        logger.warning(
            "pdf._image_to_data_uri: no se pudo leer la imagen '%s'. "
            "El PDF se generará sin ella.",
            getattr(field, "name", "<desconocido>"),
        )
        return ("", "")


# Etiquetas legibles para la vía de administración (RouteOfAdministration choices).
_ROUTE_LABELS: dict[str, str] = {
    "oral": "Oral",
    "sublingual": "Sublingual",
    "intravenosa": "Intravenosa",
    "intramuscular": "Intramuscular",
    "subcutanea": "Subcutánea",
    "topica": "Tópica",
    "oftalmica": "Oftálmica",
    "otica": "Ótica",
    "nasal": "Nasal",
    "rectal": "Rectal",
    "vaginal": "Vaginal",
    "inhalada": "Inhalada",
    "transdermica": "Transdérmica",
    "otra": "Otra",
}


def _build_context(prescription: Any, fmt: "Any | None" = None) -> dict[str, Any]:  # noqa: C901
    """Construye el contexto completo para los templates HTML de receta (F1+F2+F3).

    Amplía el contexto de B1.3 con los campos de F2:
      - commercial_name (ClinicSettings) → nombre principal del encabezado.
      - credentials: lista de DoctorCredential del médico, por order.
      - items agrupados por kind: medicamentos, sueros, terapias.
      - Cada ítem expone dose, frequency, route (con etiqueta legible), duration, indication.
      - diagnosis (de la receta).

    F3 — formato configurable:
      - accent: color de acento (#RRGGBB) del PrescriptionFormat resuelto.
      - font_family: CSS font-family del formato resuelto.
      - sections: dict de flags booleanos de secciones del formato (completo con defaults).
      - letterhead_mode: "digital" | "preprinted" del formato.

    Carga ClinicSettings y DoctorCredentials del tenant de la receta.
    Las imágenes se incrustan como data URI base64.

    Args:
        prescription: Instancia de Prescription con relaciones precargadas
                      (doctor, doctor__membership__user, patient, items).
        fmt:          PrescriptionFormat resuelto (real o en memoria). None = defaults.

    Returns:
        Diccionario de contexto para render_to_string del template.
    """
    from apps.clinica.models import ClinicSettings, DoctorCredential

    tenant = prescription.tenant

    # --- ClinicSettings (opcional por tenant) ---
    try:
        settings_obj: Optional[ClinicSettings] = ClinicSettings.objects.filter(
            tenant=tenant,
            deleted_at__isnull=True,
        ).first()
    except Exception:  # noqa: BLE001
        settings_obj = None

    # Logo: encajado proporcionalmente en caja.
    logo_box: dict[str, Any] = {"b64": "", "mime": "", "w": 0, "h": 0}
    if settings_obj is not None and settings_obj.logo:
        logo_box = _image_box(settings_obj.logo, max_w_pt=160, max_h_pt=58)

    # Nombre principal del encabezado: commercial_name tiene prioridad sobre Tenant.name.
    commercial_name: str = ""
    if settings_obj is not None:
        commercial_name = settings_obj.commercial_name or ""
    clinic_name: str = commercial_name or getattr(tenant, "name", "") or ""

    # --- Médico ---
    doctor = prescription.doctor
    doctor_name = ""
    try:
        doctor_name = doctor.full_name
    except Exception:  # noqa: BLE001
        doctor_name = str(doctor.id)

    cedula_profesional: str = doctor.cedula_profesional or ""
    cedulas_adicionales: str = doctor.cedulas_adicionales or ""
    doctor_specialty: str = doctor.specialty or ""

    sello_box: dict[str, Any] = {"b64": "", "mime": "", "w": 0, "h": 0}
    if doctor.sello:
        sello_box = _image_box(doctor.sello, max_w_pt=110, max_h_pt=58)

    # Credenciales estructuradas (F2): DoctorCredential ordenadas por `order`.
    credentials: list[dict[str, str]] = []
    try:
        cred_qs = DoctorCredential.objects.filter(
            doctor=doctor,
            is_active=True,
            deleted_at__isnull=True,
        ).order_by("order", "id")
        for cred in cred_qs:
            credentials.append(
                {
                    "title": cred.title,
                    "institution": cred.institution,
                    "credential_number": cred.credential_number,
                    "kind": cred.kind,
                    "kind_display": cred.get_kind_display(),
                }
            )
    except Exception:  # noqa: BLE001
        credentials = []

    # --- Paciente ---
    patient = prescription.patient
    patient_name: str = ""
    try:
        patient_name = patient.full_name  # type: ignore[attr-defined]
    except AttributeError:
        patient_name = (
            f"{getattr(patient, 'first_name', '')} {getattr(patient, 'last_name', '')}".strip()
        )
    if not patient_name:
        patient_name = str(patient.id)

    patient_age_sex = ""
    dob = getattr(patient, "date_of_birth", None)
    sex = getattr(patient, "sex", None) or ""
    if dob is not None:
        from django.utils import timezone as _tz

        today = _tz.localdate()
        age_years = today.year - dob.year - (
            (today.month, today.day) < (dob.month, dob.day)
        )
        patient_age_sex = f"{age_years} años"
    if sex:
        patient_age_sex = f"{patient_age_sex} / {sex}".strip(" /")

    # --- Fecha de emisión ---
    issued_at_str: str = ""
    if prescription.issued_at:
        issued_at_str = prescription.issued_at.strftime("%d/%m/%Y")

    # --- Vitals snapshot ---
    vitals: Optional[dict[str, Any]] = prescription.vitals_snapshot or None

    # --- Diagnóstico (F2) ---
    diagnosis: str = prescription.diagnosis or ""

    # --- Ítems agrupados por kind (F2) ---
    medicamentos: list[dict[str, Any]] = []
    sueros: list[dict[str, Any]] = []
    terapias: list[dict[str, Any]] = []

    from apps.recetas.models import ItemKind

    for item in prescription.items.all().order_by("order"):
        detail_parts: list[str] = []
        if item.medication_concentration:
            detail_parts.append(item.medication_concentration)
        if item.medication_form:
            detail_parts.append(item.medication_form)
        if item.medication_presentation:
            detail_parts.append(item.medication_presentation)
        med_detail = " — ".join(detail_parts) if detail_parts else ""

        route_value: str = item.route or ""
        route_label: str = _ROUTE_LABELS.get(route_value, route_value) if route_value else ""

        item_ctx: dict[str, Any] = {
            "medication_name": item.medication_name,
            "medication_detail": med_detail,
            "dose": item.dose or "",
            "frequency": item.frequency or "",
            "route": route_value,
            "route_label": route_label,
            "duration": item.duration or "",
            "indication": item.indication or "",
            "quantity": item.quantity or "",
            # F6: grupo COFEPRIS del ítem (snapshot — none si no es controlado)
            "controlled_group": getattr(item, "controlled_group", "none") or "none",
        }

        if item.kind == ItemKind.SUERO:
            sueros.append(item_ctx)
        elif item.kind == ItemKind.TERAPIA:
            terapias.append(item_ctx)
        else:
            medicamentos.append(item_ctx)

    # Lista unificada (mantiene compatibilidad con templates que usen {{ items }}).
    items_ctx: list[dict[str, Any]] = medicamentos + sueros + terapias

    # --- Recomendaciones ---
    recommendations: str = prescription.recommendations or ""

    # --- Estado cancelled ---
    from apps.recetas.models import PrescriptionStatus

    cancelled: bool = prescription.status == PrescriptionStatus.CANCELLED

    # --- Contacto de la clínica ---
    address = ""
    address_2 = ""
    phone = ""
    mobile = ""
    email = ""
    website = ""
    if settings_obj is not None:
        address = settings_obj.address or ""
        address_2 = settings_obj.address_2 or ""
        phone = settings_obj.phone or ""
        mobile = settings_obj.mobile or ""
        email = settings_obj.email or ""
        website = settings_obj.website or ""

    # --- F3: variables del PrescriptionFormat resuelto ---
    _DEFAULT_ACCENT = "#9A7B1E"
    _DEFAULT_FONT_FAMILY = "Helvetica, Arial, sans-serif"
    _DEFAULT_SECTIONS: dict[str, bool] = {
        "signos": True,
        "diagnostico": True,
        "sueros": True,
        "terapias": True,
        "indicaciones": True,
    }

    accent: str = _DEFAULT_ACCENT
    font_family: str = _DEFAULT_FONT_FAMILY
    sections_ctx: dict[str, bool] = dict(_DEFAULT_SECTIONS)
    letterhead_mode_ctx: str = "digital"

    if fmt is not None:
        accent = getattr(fmt, "accent_color", _DEFAULT_ACCENT) or _DEFAULT_ACCENT
        # font_family: property del modelo (puede ser objeto en memoria sin property)
        if hasattr(fmt, "font_family"):
            font_family = fmt.font_family
        else:
            _font = getattr(fmt, "font", "helvetica")
            font_family = (
                "Times, serif" if _font == "times" else "Helvetica, Arial, sans-serif"
            )
        # sections: mergeamos con defaults para rellenar flags ausentes
        _sections_raw = getattr(fmt, "sections", {}) or {}
        if hasattr(fmt, "get_sections_full"):
            sections_ctx = fmt.get_sections_full()
        else:
            sections_ctx = dict(_DEFAULT_SECTIONS)
            sections_ctx.update(_sections_raw)
        letterhead_mode_ctx = getattr(fmt, "letterhead_mode", "digital") or "digital"

    # --- F5: QR de verificación ---
    # Se genera en memoria como PNG base64; NO contiene PII del paciente.
    # Si falla (qrcode no instalado, error de I/O), queda ("", "") y el PDF
    # se genera sin el QR (comportamiento seguro — no bloquea el PDF).
    from apps.recetas.verification import prescription_qr_b64 as _qr_b64

    qr_b64, qr_mime = _qr_b64(prescription=prescription)

    # --- F6: datos de medicamento controlado para el template ---
    # is_controlled depende de items (ya precargados con order_by en el loop).
    # Calculamos aquí para no disparar otra query en el template.
    from apps.recetas.models import ControlledGroup as _CG

    controlled_items_groups: list[str] = [
        item_ctx_dict.get("controlled_group", "none")
        for item_ctx_dict in (medicamentos + sueros + terapias)
        if item_ctx_dict.get("controlled_group", "none") != "none"
    ]
    is_controlled_pdf: bool = bool(controlled_items_groups)

    # Grupo más restrictivo (para mostrar en el aviso del PDF).
    _GROUP_ORDER_PDF: list[str] = [
        _CG.I, _CG.II, _CG.III, _CG.IV, _CG.V
    ]
    controlled_group_top_pdf: str = ""
    for _g in _GROUP_ORDER_PDF:
        if _g in controlled_items_groups:
            controlled_group_top_pdf = _g
            break

    # Vigencia y folio oficial (del modelo — ya calculados por el servicio).
    controlled_folio_pdf: str = getattr(prescription, "controlled_folio", "") or ""
    valid_until_pdf = getattr(prescription, "valid_until", None)

    # Formato legible de vigencia para el template.
    valid_until_str: str = ""
    if valid_until_pdf is not None:
        valid_until_str = valid_until_pdf.strftime("%d/%m/%Y %H:%M")

    return {
        # Encabezado digital
        "logo_b64": logo_box["b64"],
        "logo_mime": logo_box["mime"],
        "logo_w": logo_box["w"],
        "logo_h": logo_box["h"],
        "clinic_name": clinic_name,
        "commercial_name": commercial_name,
        "address": address,
        "address_2": address_2,
        "phone": phone,
        "mobile": mobile,
        "email": email,
        "website": website,
        # Médico + credenciales F2
        "doctor_name": doctor_name,
        "cedula_profesional": cedula_profesional,
        "cedulas_adicionales": cedulas_adicionales,
        "doctor_specialty": doctor_specialty,
        "credentials": credentials,
        "sello_b64": sello_box["b64"],
        "sello_mime": sello_box["mime"],
        "sello_w": sello_box["w"],
        "sello_h": sello_box["h"],
        # Paciente
        "patient_name": patient_name,
        "patient_age_sex": patient_age_sex,
        # Receta
        "folio": prescription.folio,
        "issued_at": issued_at_str,
        "diagnosis": diagnosis,
        "vitals": vitals,
        # Ítems: lista unificada + listas por kind (F2).
        "items": items_ctx,
        "medicamentos": medicamentos,
        "sueros": sueros,
        "terapias": terapias,
        "recommendations": recommendations,
        "cancelled": cancelled,
        # F3 — formato configurable
        "accent": accent,
        "font_family": font_family,
        "sections": sections_ctx,
        "letterhead_mode": letterhead_mode_ctx,
        # F5 — QR de verificación de autenticidad (PNG base64, sin PII)
        "qr_b64": qr_b64,
        "qr_mime": qr_mime,
        # F6 — medicamento controlado
        "is_controlled": is_controlled_pdf,
        "controlled_group_top": controlled_group_top_pdf,
        "controlled_folio": controlled_folio_pdf,
        "valid_until": valid_until_str,
    }


def prescription_pdf_build(
    *,
    prescription: Any,
    base_layout: str = "standard",
    format_override: "Any | None" = None,
) -> bytes:
    """Genera los bytes del PDF de una receta médica en el formato resuelto.

    F3: La firma acepta `format_override` (un PrescriptionFormat real o en memoria,
    o None). Si no se provee, resuelve el formato automáticamente con
    `prescription_format_resolve`.

    Compatibilidad hacia atrás: `base_layout` se mantiene como override de layout
    rápido (para el endpoint ?formato=). Cuando se pasa `format_override`, este
    tiene prioridad sobre `base_layout`.

    Args:
        prescription:    Instancia de Prescription con relaciones precargadas:
                         doctor, doctor__membership, doctor__membership__user,
                         patient, items.
        base_layout:     Nombre de layout para override de vista previa (legacy).
                         Válidos: "standard", "compact", "digital".
                         Si es inválido, se usa "standard" (fallback con WARNING).
        format_override: PrescriptionFormat (real o en memoria) o None.
                         Si es None, se resuelve automáticamente. Si viene del
                         endpoint ?formato=, la vista lo construye y lo pasa aquí.

    Returns:
        Bytes del PDF generado.

    Raises:
        RuntimeError: si xhtml2pdf no pudo generar el PDF (buffer vacío o error
                      de conversión irrecuperable).
    """
    from apps.recetas.selectors import prescription_format_resolve
    from xhtml2pdf import pisa  # import late para facilitar mocking en tests

    # Resolver el formato a usar.
    if format_override is not None:
        resolved_fmt = format_override
    else:
        resolved_fmt = prescription_format_resolve(prescription=prescription)

    # Determinar el layout activo (format_override tiene prioridad; fallback base_layout).
    active_layout: str = getattr(resolved_fmt, "base_layout", base_layout) or base_layout
    if active_layout not in VALID_LAYOUTS:
        logger.warning(
            "prescription_pdf_build: base_layout='%s' no es un valor válido. "
            "Se usará 'standard'. Valores válidos: %s.",
            active_layout,
            ", ".join(sorted(VALID_LAYOUTS)),
        )
        active_layout = "standard"

    template_name = _TEMPLATE_MAP[active_layout]
    context = _build_context(prescription, fmt=resolved_fmt)
    html_str: str = render_to_string(template_name, context)

    buffer = BytesIO()
    result = pisa.CreatePDF(
        src=html_str,
        dest=buffer,
        encoding="utf-8",
        link_callback=_link_callback,
    )

    if result.err:
        logger.error(
            "prescription_pdf_build: xhtml2pdf reportó errores al generar PDF "
            "para receta folio=%s layout=%s — err_code=%s",
            prescription.folio,
            base_layout,
            result.err,
        )
        raise RuntimeError(
            f"Error al generar el PDF de la receta (folio={prescription.folio}, "
            f"layout={base_layout}). Código de error xhtml2pdf: {result.err}"
        )

    pdf_bytes: bytes = buffer.getvalue()
    if not pdf_bytes:
        raise RuntimeError(
            f"El PDF generado está vacío para receta folio={prescription.folio} "
            f"layout={base_layout}."
        )

    return pdf_bytes
