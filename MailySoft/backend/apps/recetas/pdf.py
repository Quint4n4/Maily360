"""
Generación de PDF para recetas médicas — Fase B1.3.

Librería: xhtml2pdf (puro Python/pip, sin dependencias de sistema).
  Nota: Se evaluó WeasyPrint pero requiere libpango/libcairo/libgdk-pixbuf en el
  sistema operativo. El Dockerfile usa python:3.12-slim sin esas libs; instalarlas
  en ambos stages (builder + runtime) implicaría reconstrucción completa del venv
  y +200 MB en la imagen. xhtml2pdf no requiere tocar el Dockerfile y cumple el
  requisito funcional completamente.

Imágenes (logo, membrete, sello):
  Se incrustan como data URI en base64. Esto permite que xhtml2pdf las resuelva
  sin acceso al sistema de archivos real y funciona tanto con FileSystemStorage
  (dev) como con S3 (prod), siempre que el archivo sea legible. Si el archivo no
  existe o falla la lectura, se omite la imagen silenciosamente (no truena el PDF).

Decisión sobre recipe_use_responsible_doctor:
  El modelo ClinicSettings tiene el flag `recipe_use_responsible_doctor` pero no
  existe aún un concepto de "médico responsable de la clínica" como entidad
  separada en el sistema (no hay FK en ClinicSettings a un Doctor). Mientras ese
  concepto no esté implementado, este flag se ignora y se usa siempre el médico
  que emitió la receta (doctor directo de la Prescription). Esta decisión se
  documenta aquí para que el equipo la considere en B2+. Ver `prescription_pdf_build`.
"""

import base64
import logging
import mimetypes
from io import BytesIO
from typing import Any, Optional

from django.template.loader import render_to_string
from PIL import Image

logger = logging.getLogger("apps.recetas.pdf")


def _image_box(field: Any, max_w_pt: float, max_h_pt: float) -> dict[str, Any]:
    """Prepara una imagen (logo/sello) para el PDF con dimensiones proporcionales.

    xhtml2pdf NO respeta `max-width`/`max-height` en CSS: si no se dan dimensiones
    exactas en el tag, la imagen sale a tamaño nativo (gigante) o deformada. Para
    que CUALQUIER logo —cuadrado, horizontal o vertical y de cualquier clínica— se
    vea bien, se lee su tamaño real con Pillow y se calcula (w, h) en pt que encaje
    dentro de la caja `max_w_pt × max_h_pt` MANTENIENDO la proporción.

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
        # Si no se pueden leer dimensiones, devolver la imagen sin tamaño (no truena).
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

    xhtml2pdf.pisa.CreatePDF acepta un ``link_callback`` que se invoca para
    resolver URLs de recursos referenciados en el HTML (imágenes, hojas de
    estilo, etc.). Sin este callback la librería puede intentar resolver rutas
    ``file://`` (LFI) o ``http://`` (SSRF) del sistema de archivos del servidor.

    Política de este callback (defensa en profundidad):
        - URIs ``data:`` → se devuelven tal cual. Son los únicos recursos que
          el módulo usa: imágenes incrustadas como base64 en el template.
        - Cualquier otro esquema (``file://``, ``http://``, ``https://``,
          rutas relativas, etc.) → se devuelve cadena vacía y se registra un
          WARNING. xhtml2pdf omite silenciosamente el recurso sin abortar el
          render del PDF (comportamiento seguro).

    Args:
        uri: URI del recurso tal como aparece en el HTML/CSS.
        rel: Ruta relativa base (ignorada; no se usa resolución relativa).

    Returns:
        La URI original si es ``data:``; cadena vacía en cualquier otro caso.
    """
    if uri.startswith("data:"):
        return uri

    logger.warning(
        "pdf._link_callback: URI bloqueada por política de seguridad — '%s'. "
        "Solo se permiten data URIs en el template de receta.",
        uri[:200],  # truncar para no loguear URLs enormes
    )
    return ""

# Tipos MIME seguros para ImageField (JPEG, PNG, WEBP).
# xhtml2pdf soporta JPEG y PNG nativamente. WEBP: se incluye en el data URI pero
# el soporte puede variar según la versión de ReportLab/xhtml2pdf. En la práctica
# el validador de clinica solo admite JPEG/PNG/WEBP; si hay WEBP sin soporte, el
# PDF muestra el espacio vacío sin error (comportamiento seguro).
_MIME_FALLBACK = "image/png"


def _image_to_data_uri(field: Any) -> tuple[str, str]:
    """Lee un ImageField (local o S3) y devuelve (mime, base64_str).

    Intenta leer el archivo del storage. Si el campo está vacío, el archivo
    no existe o se produce cualquier error de I/O, devuelve ("", "") y loguea
    en WARNING (no Critical: imagen faltante no bloquea la generación del PDF).

    Args:
        field: Un ImageField de Django (puede ser local FileSystemStorage o S3).

    Returns:
        Tupla (mime_type, base64_encoded_bytes) o ("", "") si no aplica.
    """
    if not field:
        return ("", "")

    try:
        name: str = field.name or ""
        if not name:
            return ("", "")

        # Determinar MIME por extensión del nombre de archivo.
        mime, _ = mimetypes.guess_type(name)
        if not mime:
            mime = _MIME_FALLBACK

        # Convertir "image/jpeg" → "jpeg" para el data URI (el tag usa el tipo simple).
        mime_subtype = mime.split("/")[-1] if "/" in mime else mime

        # Abrir el archivo del storage (funciona para FileSystemStorage y S3Boto3Storage).
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


def _build_context(prescription: Any) -> dict[str, Any]:  # noqa: C901
    """Construye el contexto para el template HTML de la receta.

    Carga ClinicSettings y Doctor del tenant de la receta.
    Las imágenes se incrustan como data URI base64.

    Decisión sobre recipe_use_responsible_doctor:
        ClinicSettings.recipe_use_responsible_doctor existe en el modelo pero no
        hay un campo "médico responsable de la clínica" definido. Se usa siempre
        el médico emisor (prescription.doctor) hasta que B2+ implemente esa FK.

    Args:
        prescription: Instancia de Prescription con relaciones precargadas
                      (doctor__membership__user, patient, items).

    Returns:
        Diccionario de contexto para render_to_string del template.
    """
    from apps.clinica.models import ClinicSettings

    tenant = prescription.tenant

    # --- Datos de la clínica (ClinicSettings es opcional por tenant) ---
    try:
        settings_obj: Optional[ClinicSettings] = ClinicSettings.objects.filter(
            tenant=tenant,
            deleted_at__isnull=True,
        ).first()
    except Exception:  # noqa: BLE001
        settings_obj = None

    # Membrete DIGITAL (decisión del dueño, 2026-06-18): el PDF arma su propio
    # encabezado limpio con logo + datos de la clínica + médico. NO se incrusta la
    # imagen de membrete de hoja completa (letterhead_full/half): esa es para papel
    # pre-impreso y, al ser una hoja entera, empujaba el contenido a la 2ª página y
    # duplicaba los campos de paciente. (El modo "papel pre-impreso" queda como
    # mejora futura; los campos letterhead_* siguen guardándose en ClinicSettings.)
    # Logo: encajado proporcionalmente en una caja (xhtml2pdf no respeta max-*).
    logo_box = {"b64": "", "mime": "", "w": 0, "h": 0}

    # Nombre de la clínica: Tenant.name (ClinicSettings no tiene campo de nombre).
    clinic_name: str = getattr(tenant, "name", "") or ""

    if settings_obj is not None and settings_obj.logo:
        logo_box = _image_box(settings_obj.logo, max_w_pt=160, max_h_pt=58)

    # --- Datos del médico ---
    doctor = prescription.doctor
    doctor_name = ""
    try:
        doctor_name = doctor.full_name
    except Exception:  # noqa: BLE001
        doctor_name = str(doctor.id)

    cedula_profesional: str = doctor.cedula_profesional or ""
    cedulas_adicionales: str = doctor.cedulas_adicionales or ""
    doctor_specialty: str = doctor.specialty or ""

    sello_box = {"b64": "", "mime": "", "w": 0, "h": 0}
    if doctor.sello:
        sello_box = _image_box(doctor.sello, max_w_pt=110, max_h_pt=58)

    # --- Datos del paciente ---
    patient = prescription.patient
    patient_name: str = ""
    try:
        patient_name = patient.full_name  # type: ignore[attr-defined]
    except AttributeError:
        patient_name = f"{getattr(patient, 'first_name', '')} {getattr(patient, 'last_name', '')}".strip()
    if not patient_name:
        patient_name = str(patient.id)

    # Edad/sexo opcional (calculada desde date_of_birth).
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

    # --- Ítems de medicamento ---
    items_ctx: list[dict[str, Any]] = []
    for item in prescription.items.all().order_by("order"):
        # Construir la línea de detalle (concentración + forma + presentación).
        detail_parts: list[str] = []
        if item.medication_concentration:
            detail_parts.append(item.medication_concentration)
        if item.medication_form:
            detail_parts.append(item.medication_form)
        if item.medication_presentation:
            detail_parts.append(item.medication_presentation)
        med_detail = " — ".join(detail_parts) if detail_parts else ""

        items_ctx.append(
            {
                "medication_name": item.medication_name,
                "medication_detail": med_detail,
                "indication": item.indication,
            }
        )

    # --- Recomendaciones ---
    recommendations: str = prescription.recommendations or ""

    # --- Estado cancelled ---
    from apps.recetas.models import PrescriptionStatus
    cancelled: bool = prescription.status == PrescriptionStatus.CANCELLED

    # --- Datos de contacto de la clínica ---
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

    return {
        # Encabezado digital (logo + datos de la clínica)
        "logo_b64": logo_box["b64"],
        "logo_mime": logo_box["mime"],
        "logo_w": logo_box["w"],
        "logo_h": logo_box["h"],
        "clinic_name": clinic_name,
        "address": address,
        "address_2": address_2,
        "phone": phone,
        "mobile": mobile,
        "email": email,
        "website": website,
        # Paciente
        "patient_name": patient_name,
        "patient_age_sex": patient_age_sex,
        # Receta
        "folio": prescription.folio,
        "issued_at": issued_at_str,
        "vitals": vitals,
        "items": items_ctx,
        "recommendations": recommendations,
        "cancelled": cancelled,
        # Médico
        "doctor_name": doctor_name,
        "cedula_profesional": cedula_profesional,
        "cedulas_adicionales": cedulas_adicionales,
        "doctor_specialty": doctor_specialty,
        "sello_b64": sello_box["b64"],
        "sello_mime": sello_box["mime"],
        "sello_w": sello_box["w"],
        "sello_h": sello_box["h"],
    }


def prescription_pdf_build(*, prescription: Any) -> bytes:
    """Genera los bytes del PDF de una receta médica.

    Renderiza el template HTML con el contexto de la receta y lo convierte a PDF
    usando xhtml2pdf. Las imágenes (logo, membrete, sello) se incrustan como
    data URI base64 para evitar dependencias de rutas del sistema de archivos.

    Decisión sobre recipe_use_responsible_doctor:
        El flag ClinicSettings.recipe_use_responsible_doctor existe en el modelo
        pero no hay un campo "médico responsable de la clínica" en el esquema.
        Se usa siempre el médico emisor (prescription.doctor) hasta que B2+
        implemente la FK "responsible_doctor" en ClinicSettings.

    Args:
        prescription: Instancia de Prescription con relaciones precargadas:
                      doctor, doctor__membership, doctor__membership__user,
                      patient, items.

    Returns:
        Bytes del PDF generado.

    Raises:
        RuntimeError: si xhtml2pdf no pudo generar el PDF (buffer vacío o error
                      de conversión irrecuperable).
    """
    from xhtml2pdf import pisa  # import late para facilitar mocking en tests

    context = _build_context(prescription)
    html_str: str = render_to_string("recetas/prescription.html", context)

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
            "para receta folio=%s — err_code=%s",
            prescription.folio,
            result.err,
        )
        raise RuntimeError(
            f"Error al generar el PDF de la receta (folio={prescription.folio}). "
            f"Código de error xhtml2pdf: {result.err}"
        )

    pdf_bytes: bytes = buffer.getvalue()
    if not pdf_bytes:
        raise RuntimeError(
            f"El PDF generado está vacío para receta folio={prescription.folio}."
        )

    return pdf_bytes
