"""
Generación de PDF del Libro Clínico del Paciente — Fase 3.

Librería: WeasyPrint (misma infraestructura que apps/recetas/pdf.py).

Seguridad:
  Reusa `_secure_fetcher` de apps/recetas/pdf.py: SOLO permite data URIs.
  Las imágenes (logo de clínica, imágenes de evolución) se incrustan como
  data-URI base64 ANTES del render. WeasyPrint nunca lee files ni HTTP.

Modos (D-LIB-5):
  completo — portada + HC viva + TODOS los capítulos (más reciente primero).
  hc       — portada + HC viva + alergias (sin capítulos de evolución).
  ultimo   — portada + último capítulo + sus recetas.

Imágenes (D-LIB-2):
  imagenes=True  — incluye imágenes de las evoluciones (default).
  imagenes=False — omite imágenes (PDF más ligero para impresión rápida).
  Todas las imágenes se redimensionan con Pillow a un máximo de
  MAX_IMAGE_W_PT × MAX_IMAGE_H_PT para evitar PDFs gigantes (el proyecto
  ya tuvo un caso de imagen de 58 MP).

Bitácora (D-LIB-4 / NOM-024):
  La bitácora la registra la VISTA; este módulo solo genera el PDF.

Fase 2 — unificación de diseño:
  _build_libro_context usa build_brand_context (apps.core.pdf.branding)
  en lugar de _image_box de recetas. El contexto incluye brand_color y
  watermark_b64 para que el template libro.html aplique el color de marca
  dinámico de la clínica en portada, títulos de sección y encabezados de
  capítulo. Los colores SOAP (S/O/A/P) se conservan intactos.
"""

import base64
import logging
import mimetypes
from io import BytesIO
from typing import Any, Literal

from django.template.loader import render_to_string
from django.utils import timezone
from PIL import Image

from apps.core.pdf.branding import build_brand_context

logger = logging.getLogger("apps.expediente.pdf")

# Modo de impresión válidos (D-LIB-5).
BookMode = Literal["completo", "hc", "ultimo"]
VALID_BOOK_MODES: frozenset[str] = frozenset({"completo", "hc", "ultimo"})

# Etiquetas legibles por modo (para la portada).
_MODO_LABELS: dict[str, str] = {
    "completo": "Libro Completo",
    "hc": "Solo Historia Clínica",
    "ultimo": "Último Capítulo",
}

# Cota de imagen para el PDF (en puntos tipográficos, 1 pt = 1/72 pulgada).
# Estas cotas evitan el problema de imágenes de 58 MP que generaban PDFs de GB.
MAX_IMAGE_W_PT: float = 180.0  # ≈ 6.3 cm — 3 columnas en página carta
MAX_IMAGE_H_PT: float = 200.0  # ≈ 7 cm
MAX_IMAGE_BYTES: int = 8 * 1024 * 1024  # 8 MB como tope de lectura de cada imagen


def _image_field_to_data_uri(
    field: Any,
    *,
    max_w_pt: float = MAX_IMAGE_W_PT,
    max_h_pt: float = MAX_IMAGE_H_PT,
) -> dict[str, Any]:
    """Convierte un ImageField a un dict listo para el template (data-URI + dimensiones).

    Aplica redimensionado proporcional con Pillow para acotar el tamaño de
    las imágenes en el PDF. Límite: MAX_IMAGE_BYTES de lectura por imagen.

    Args:
        field:     ImageField de Django (local o S3).
        max_w_pt:  Ancho máximo en puntos tipográficos.
        max_h_pt:  Alto máximo en puntos tipográficos.

    Returns:
        Dict con keys: b64 (str), mime (str), w (int), h (int).
        Todos vacíos/cero si la imagen no se puede leer.
    """
    empty: dict[str, Any] = {"b64": "", "mime": "", "w": 0, "h": 0}

    if not field:
        return empty

    try:
        name: str = getattr(field, "name", "") or ""
        if not name:
            return empty

        mime_full, _ = mimetypes.guess_type(name)
        mime_sub = mime_full.split("/")[-1] if mime_full and "/" in mime_full else "png"

        with field.open("rb") as fobj:
            raw: bytes = fobj.read(MAX_IMAGE_BYTES + 1)

        if len(raw) > MAX_IMAGE_BYTES:
            logger.warning(
                "pdf._image_field_to_data_uri: imagen '%s' excede %d bytes — "
                "se omite del PDF del libro.",
                name,
                MAX_IMAGE_BYTES,
            )
            return empty

        # Redimensionar con Pillow para acotar tamaño en el PDF.
        with Image.open(BytesIO(raw)) as img:
            w_px, h_px = img.size
            if w_px <= 0 or h_px <= 0:
                return empty

            # Calcular escala para caber dentro de max_w_pt × max_h_pt.
            scale = min(max_w_pt / w_px, max_h_pt / h_px, 1.0)
            new_w = max(1, int(w_px * scale))
            new_h = max(1, int(h_px * scale))

            # Solo redimensionar si la imagen es más grande que el límite.
            if scale < 1.0:
                img_resized = img.resize((new_w, new_h), Image.LANCZOS)
            else:
                img_resized = img
                new_w = w_px
                new_h = h_px

            # Guardar como PNG para uniformidad (independiente del formato original).
            buf = BytesIO()
            img_resized.convert("RGBA").save(buf, format="PNG")
            raw_out = buf.getvalue()

        encoded = base64.b64encode(raw_out).decode("ascii")
        return {
            "b64": encoded,
            "mime": "png",
            "w": new_w,
            "h": new_h,
        }

    except Exception:  # noqa: BLE001
        logger.warning(
            "pdf._image_field_to_data_uri: no se pudo procesar la imagen '%s'. "
            "El PDF se generará sin ella.",
            getattr(field, "name", "<desconocido>"),
        )
        return empty


def _build_libro_context(
    *,
    patient: Any,
    clinic_settings: Any | None,
    medical_history: Any | None,
    allergies: Any,
    capitulos: list[Any],
    capitulos_count: int,
    modo: str,
    incluir_imagenes: bool,
) -> dict[str, Any]:
    """Construye el contexto completo para el template libro.html.

    No hace queries; todo ya fue precargado por book_build_all.
    Las imágenes se convierten a data-URI aquí (antes del render).

    Args:
        patient:           Instancia de Patient.
        clinic_settings:   ClinicSettings del tenant o None.
        medical_history:   MedicalHistory del paciente o None.
        allergies:         QuerySet/lista de Allergy activas.
        capitulos:         Lista de EvolutionNote precargadas.
        capitulos_count:   Total de capítulos del paciente.
        modo:              "completo" | "hc" | "ultimo".
        incluir_imagenes:  True = incluir imágenes de evoluciones en el PDF.

    Returns:
        Diccionario de contexto para render_to_string.
    """
    # --- Contexto de marca (logo, color, datos de contacto) via base común ---
    brand: dict[str, Any] = build_brand_context(
        clinic_settings=clinic_settings,
        logo_max_w_pt=160,
        logo_max_h_pt=80,
    )
    logo_box: dict[str, Any] = {
        "b64": brand["logo_b64"],
        "mime": brand["logo_mime"],
        "w": brand["logo_w"],
        "h": brand["logo_h"],
    }
    brand_color: str = brand["brand_color"]
    watermark_b64: str = brand["watermark_b64"]

    # --- Datos de la clínica ---
    clinica_nombre: str = brand["clinic_name"]
    clinica_direccion: str = brand["address"]
    clinica_telefono: str = brand["phone"] or brand["mobile"]

    if not clinica_nombre:
        # Fallback: nombre del tenant (no siempre está en ClinicSettings).
        clinica_nombre = getattr(patient, "tenant", None)
        clinica_nombre = getattr(clinica_nombre, "name", "") if clinica_nombre else ""

    # --- Datos del paciente ---
    patient_nombre: str = ""
    try:
        patient_nombre = patient.full_name
    except AttributeError:
        patient_nombre = str(patient.id)

    dob = getattr(patient, "date_of_birth", None)
    fecha_nac_display: str = dob.strftime("%d/%m/%Y") if dob else ""

    # Edad + sexo.
    edad_sexo: str = ""
    if dob is not None:
        today = timezone.localdate()
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        edad_sexo = f"{age} años"
    sex_val: str = getattr(patient, "sex", "") or ""
    if sex_val:
        edad_sexo = f"{edad_sexo} / {sex_val}".strip(" /")

    curp: str = getattr(patient, "curp", "") or ""
    record_number: str = getattr(patient, "record_number", "") or ""

    # --- Fecha de generación ---
    fecha_generacion: str = timezone.localtime(timezone.now()).strftime("%d/%m/%Y %H:%M")

    # --- Modo y flags ---
    modo_label: str = _MODO_LABELS.get(modo, modo)
    mostrar_hc: bool = modo in ("completo", "hc")

    # --- Capítulos: construir lista de dicts para el template ---
    cap_total = capitulos_count
    cap_dicts: list[dict[str, Any]] = []

    for idx, nota in enumerate(capitulos, start=1):
        # El número de capítulo en modo completo: el más reciente es cap_total,
        # el siguiente es cap_total-1, etc. (los capítulos vienen -created_at).
        # En modo "ultimo" solo hay 1 capítulo: lo numeramos con el total.
        cap_numero = cap_total - (idx - 1)

        # Fecha del capítulo (usar created_at de la nota).
        nota_created = getattr(nota, "created_at", None)
        if nota_created is not None:
            fecha_display = timezone.localtime(nota_created).strftime("%d/%m/%Y %H:%M")
        else:
            fecha_display = ""

        # Médico.
        doctor_nombre: str = ""
        doctor_cedulas: str = ""
        try:
            doctor_nombre = nota.doctor.full_name
        except Exception:  # noqa: BLE001
            doctor_nombre = "Médico no disponible"
        try:
            # Cédulas VALIDADAS por el admin (DoctorCredential), como en recetas y
            # el visor del libro. No se usa el campo legacy `cedula_profesional`.
            cedulas = [
                c
                for c in nota.doctor.credentials.filter(
                    validation_status="validada",
                    is_active=True,
                    deleted_at__isnull=True,
                ).values_list("credential_number", flat=True)
                if c
            ]
            doctor_cedulas = " · ".join(cedulas)
        except Exception:  # noqa: BLE001
            doctor_cedulas = ""

        # Signos vitales (FK a VitalSignsRecord, puede ser None).
        signos_dict: dict[str, Any] | None = None
        vs = getattr(nota, "vital_signs", None)
        if vs is not None:
            # Calcular IMC si hay peso y talla.
            imc_val: str | None = None
            w_kg = getattr(vs, "weight_kg", None)
            h_m = getattr(vs, "height_m", None)
            if w_kg is not None and h_m is not None and float(h_m) > 0:
                imc_raw = float(w_kg) / (float(h_m) ** 2)
                imc_val = f"{imc_raw:.1f}"
            signos_dict = {
                "weight_kg": getattr(vs, "weight_kg", None),
                "height_m": getattr(vs, "height_m", None),
                "heart_rate": getattr(vs, "heart_rate", None),
                "resp_rate": getattr(vs, "resp_rate", None),
                "systolic": getattr(vs, "systolic", None),
                "diastolic": getattr(vs, "diastolic", None),
                "temperature_c": getattr(vs, "temperature_c", None),
                "oxygen_saturation": getattr(vs, "oxygen_saturation", None),
                "glucose": getattr(vs, "glucose", None),
                "imc": imc_val,
            }

        # SOAP — campos de texto clínico de la nota.
        # S = antecedentes + interrogatorio (subjetivo).
        subjetivo_parts = [
            getattr(nota, "antecedentes", "") or "",
            getattr(nota, "interrogatorio", "") or "",
        ]
        subjetivo = "\n\n".join(p for p in subjetivo_parts if p)

        # O = estudios (objetivo).
        objetivo = getattr(nota, "estudios", "") or ""

        # A = diagnósticos_texto.
        analisis = getattr(nota, "diagnosticos_texto", "") or ""

        # P = tratamiento + plan_recomendaciones + indicaciones_enfermeria.
        plan_parts = [
            getattr(nota, "tratamiento", "") or "",
            getattr(nota, "plan_recomendaciones", "") or "",
            getattr(nota, "indicaciones_enfermeria", "") or "",
        ]
        plan = "\n\n".join(p for p in plan_parts if p)

        # Exploración física (JSONField).
        exploracion: list[dict[str, Any]] = []
        exp_raw = getattr(nota, "exploracion_fisica", None) or {}
        if isinstance(exp_raw, dict):
            for sistema, datos in exp_raw.items():
                if isinstance(datos, dict):
                    exploracion.append(
                        {
                            "sistema": sistema,
                            "estado": datos.get("estado", "no_evaluado"),
                            "detalle": datos.get("detalle", "") or "",
                        }
                    )

        # Imágenes de la evolución (solo si incluir_imagenes=True).
        imagenes_caps: list[dict[str, Any]] = []
        if incluir_imagenes:
            imgs_qs = nota.images.all()  # precargado con prefetch_related
            for img_obj in imgs_qs:
                img_data = _image_field_to_data_uri(
                    img_obj.image if hasattr(img_obj, "image") else None,
                    max_w_pt=MAX_IMAGE_W_PT,
                    max_h_pt=MAX_IMAGE_H_PT,
                )
                imagenes_caps.append(
                    {
                        **img_data,
                        "caption": getattr(img_obj, "caption", "") or "",
                    }
                )

        # Diagnósticos estructurados.
        diagnosticos_caps: list[dict[str, Any]] = []
        for dx in nota.diagnoses.all():  # precargado
            diagnosticos_caps.append(
                {
                    "description": getattr(dx, "description", "") or "",
                    "cie_code": getattr(dx, "cie_code", "") or "",
                    "resuelto": getattr(dx, "status", "") == "resuelto",
                }
            )

        # Recetas (resumen ligero).
        recetas_caps: list[dict[str, Any]] = []
        for rx in nota.prescriptions.all():  # precargado
            medicamentos_rx: list[str] = []
            for item in rx.items.all():
                med_name = getattr(item, "medication_name", "") or ""
                dose = getattr(item, "dose", "") or ""
                freq = getattr(item, "frequency", "") or ""
                parts = [p for p in [med_name, dose, freq] if p]
                if parts:
                    medicamentos_rx.append(" — ".join(parts))

            folio_rx = getattr(rx, "folio", "") or ""
            status_rx = getattr(rx, "status", "") or ""
            recetas_caps.append(
                {
                    "folio": folio_rx,
                    "estado_display": status_rx,
                    "medicamentos": medicamentos_rx,
                }
            )

        # Addenda.
        addenda_caps: list[dict[str, Any]] = []
        for ad in nota.addenda.all():  # precargado con author
            ad_autor = ""
            try:
                ad_autor = ad.author.full_name  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                ad_autor = "Desconocido"
            ad_fecha = ""
            ad_created = getattr(ad, "created_at", None)
            if ad_created is not None:
                ad_fecha = timezone.localtime(ad_created).strftime("%d/%m/%Y %H:%M")
            addenda_caps.append(
                {
                    "fecha": ad_fecha,
                    "autor": ad_autor,
                    "body": getattr(ad, "body", "") or "",
                }
            )

        cap_dicts.append(
            {
                "numero": cap_numero,
                "fecha_display": fecha_display,
                "doctor_nombre": doctor_nombre,
                "doctor_cedulas": doctor_cedulas,
                "signos": signos_dict,
                "subjetivo": subjetivo,
                "objetivo": objetivo,
                "analisis": analisis,
                "plan": plan,
                "exploracion": exploracion,
                "imagenes": imagenes_caps,
                "diagnosticos": diagnosticos_caps,
                "recetas": recetas_caps,
                "addenda": addenda_caps,
            }
        )

    return {
        # Portada: logo
        "logo_b64": logo_box["b64"],
        "logo_mime": logo_box["mime"],
        "logo_w": logo_box["w"],
        "logo_h": logo_box["h"],
        # Marca: color dinámico y marca de agua (Fase 2)
        "brand_color": brand_color,
        "watermark_b64": watermark_b64,
        # Portada: clínica
        "clinica_nombre": clinica_nombre,
        "clinica_direccion": clinica_direccion,
        "clinica_telefono": clinica_telefono,
        # Portada: paciente
        "paciente_nombre": patient_nombre,
        "paciente_record_number": record_number,
        "paciente_fecha_nacimiento": fecha_nac_display,
        "paciente_edad_sexo": edad_sexo,
        "paciente_curp": curp,
        # Portada: metadatos
        "capitulos_count": capitulos_count,
        "fecha_generacion": fecha_generacion,
        "modo_label": modo_label,
        "sin_imagenes": not incluir_imagenes,
        # Historia Clínica
        "mostrar_hc": mostrar_hc,
        "historia_clinica": medical_history,
        "alergias": list(allergies),
        # Capítulos
        "capitulos": cap_dicts,
    }


def libro_pdf_build(
    *,
    patient: Any,
    clinic_settings: Any | None,
    medical_history: Any | None,
    allergies: Any,
    capitulos: list[Any],
    capitulos_count: int,
    modo: str = "completo",
    incluir_imagenes: bool = True,
) -> bytes:
    """Genera los bytes del PDF del libro clínico del paciente.

    Construye el contexto del template, renderiza libro.html con Django
    template engine, y convierte a PDF con WeasyPrint usando el fetcher
    seguro (solo data URIs — bloquea LFI/SSRF).

    Todos los datos ya vienen precargados (el selector book_build_all
    hizo los prefetch). Este módulo no ejecuta ninguna query adicional.

    Args:
        patient:           Instancia de Patient.
        clinic_settings:   ClinicSettings o None.
        medical_history:   MedicalHistory o None.
        allergies:         Iterable de Allergy activas.
        capitulos:         Lista de EvolutionNote precargadas.
        capitulos_count:   Número total de capítulos del paciente.
        modo:              "completo" | "hc" | "ultimo".
        incluir_imagenes:  True = incluir imágenes en el PDF.

    Returns:
        Bytes del PDF generado.

    Raises:
        RuntimeError: si WeasyPrint falla o el PDF queda vacío.
    """
    from weasyprint import HTML  # import tardío — facilita mocking en tests  # noqa: PLC0415

    from apps.recetas.pdf import _secure_fetcher  # noqa: PLC0415

    context = _build_libro_context(
        patient=patient,
        clinic_settings=clinic_settings,
        medical_history=medical_history,
        allergies=allergies,
        capitulos=capitulos,
        capitulos_count=capitulos_count,
        modo=modo,
        incluir_imagenes=incluir_imagenes,
    )

    html_str: str = render_to_string("expediente/libro.html", context)

    try:
        pdf_bytes: bytes = HTML(
            string=html_str,
            base_url=None,
            url_fetcher=_secure_fetcher,
        ).write_pdf()
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "libro_pdf_build: WeasyPrint falló al generar PDF " "para paciente=%s modo=%s — %s",
            getattr(patient, "id", "?"),
            modo,
            exc,
        )
        raise RuntimeError(
            f"Error al generar el PDF del libro clínico "
            f"(paciente={getattr(patient, 'id', '?')}, modo={modo}): {exc}"
        ) from exc

    if not pdf_bytes:
        raise RuntimeError(
            f"El PDF del libro clínico está vacío "
            f"(paciente={getattr(patient, 'id', '?')}, modo={modo})."
        )

    return pdf_bytes


# ---------------------------------------------------------------------------
# PDF del Resumen Clínico por consulta (documento entregable al paciente)
# ---------------------------------------------------------------------------


def _build_resumen_clinico_context(*, summary: Any, clinic_settings: Any | None) -> dict[str, Any]:
    """Construye el contexto para el template resumen_clinico.html.

    No hace queries adicionales: `summary` ya viene precargado por el
    selector clinical_summary_get (patient, evolution, evolution__vital_signs,
    evolution__appointment, doctor, doctor__membership__user).

    Args:
        summary:         Instancia de ClinicalSummary.
        clinic_settings: ClinicSettings del tenant o None.

    Returns:
        Diccionario de contexto para render_to_string.
    """
    patient = summary.patient
    evolution = summary.evolution
    doctor = summary.doctor
    vital_signs = getattr(evolution, "vital_signs", None)

    brand: dict[str, Any] = build_brand_context(clinic_settings=clinic_settings)

    # --- Fecha de la consulta (fecha del appointment; fallback: created_at) ---
    appointment = getattr(evolution, "appointment", None)
    fecha_ref = (
        timezone.localtime(appointment.starts_at)
        if appointment is not None
        else timezone.localtime(summary.created_at)
    )
    fecha_display = fecha_ref.strftime("%d/%m/%Y")

    # --- Datos del paciente: nombre, edad (a la fecha de la consulta), sexo ---
    patient_nombre: str = getattr(patient, "full_name", "") or str(patient.id)
    dob = getattr(patient, "date_of_birth", None)
    edad: int | None = None
    if dob is not None:
        ref_date = fecha_ref.date()
        edad = ref_date.year - dob.year - ((ref_date.month, ref_date.day) < (dob.month, dob.day))
    sex_val: str = getattr(patient, "sex", "") or ""
    sex_labels = {"M": "Masculino", "F": "Femenino", "X": "Otro"}
    sexo_display = sex_labels.get(sex_val, sex_val)

    # --- Signos vitales de la consulta (pueden faltar) ---
    signos: dict[str, Any] | None = None
    if vital_signs is not None:
        imc_val: str | None = None
        w_kg = getattr(vital_signs, "weight_kg", None)
        h_m = getattr(vital_signs, "height_m", None)
        if w_kg is not None and h_m is not None and float(h_m) > 0:
            imc_val = f"{float(w_kg) / (float(h_m) ** 2):.1f}"
        ta_val: str | None = None
        if vital_signs.systolic is not None and vital_signs.diastolic is not None:
            ta_val = f"{vital_signs.systolic}/{vital_signs.diastolic}"
        signos = {
            "weight_kg": w_kg,
            "height_m": h_m,
            "ta": ta_val,
            "fc": vital_signs.heart_rate,
            "fr": vital_signs.resp_rate,
            "temp_c": vital_signs.temperature_c,
            "imc": imc_val,
        }

    # --- Médico y cédula (misma fuente de verdad que libro.html: credenciales validadas) ---
    doctor_nombre: str = ""
    doctor_cedula: str = ""
    if doctor is not None:
        try:
            doctor_nombre = doctor.full_name
        except Exception:  # noqa: BLE001
            doctor_nombre = "Médico no disponible"
        try:
            cedulas = list(
                doctor.credentials.filter(
                    validation_status="validada",
                    is_active=True,
                    deleted_at__isnull=True,
                ).values_list("credential_number", flat=True)
            )
            doctor_cedula = " · ".join(c for c in cedulas if c)
        except Exception:  # noqa: BLE001
            doctor_cedula = ""
        if not doctor_cedula:
            doctor_cedula = getattr(doctor, "cedula_profesional", "") or ""

    # --- Indicaciones como lista (una entrada por línea no vacía) ---
    indicaciones_lines: list[str] = [
        line.strip() for line in (summary.indicaciones or "").splitlines() if line.strip()
    ]

    return {
        **brand,
        "fecha_generacion": timezone.localtime(timezone.now()).strftime("%d/%m/%Y %H:%M"),
        "fecha_consulta": fecha_display,
        "paciente_nombre": patient_nombre,
        "paciente_edad": edad,
        "paciente_sexo": sexo_display,
        "paciente_record_number": getattr(patient, "record_number", "") or "",
        "signos": signos,
        "doctor_nombre": doctor_nombre,
        "doctor_cedula": doctor_cedula,
        "identificacion": summary.identificacion,
        "antecedentes": summary.antecedentes,
        "padecimiento_actual": summary.padecimiento_actual,
        "exploracion_fisica": summary.exploracion_fisica,
        "diagnostico_manejo": summary.diagnostico_manejo,
        "indicaciones_lines": indicaciones_lines,
    }


def resumen_clinico_pdf_build(*, summary: Any, clinic_settings: Any | None) -> bytes:
    """Genera los bytes del PDF del Resumen Clínico de una consulta.

    Documento SINTÉTICO entregable al paciente (a diferencia del libro clínico,
    de uso interno). Usa el mismo membrete de marca que el resto de los PDFs
    de Maily (build_brand_context + clinic_header.html + brand_background.html).

    Seguridad: usa secure_fetcher (apps.core.pdf.fetchers) — SOLO data URIs,
    bloquea LFI/SSRF.

    Args:
        summary:         Instancia de ClinicalSummary (precargada por el selector).
        clinic_settings: ClinicSettings del tenant o None.

    Returns:
        Bytes del PDF generado.

    Raises:
        RuntimeError: si WeasyPrint falla o el PDF queda vacío.
    """
    from weasyprint import HTML  # import tardío — facilita mocking en tests  # noqa: PLC0415

    from apps.core.pdf.fetchers import secure_fetcher  # noqa: PLC0415

    context = _build_resumen_clinico_context(summary=summary, clinic_settings=clinic_settings)
    html_str: str = render_to_string("expediente/resumen_clinico.html", context)

    try:
        pdf_bytes: bytes = HTML(
            string=html_str,
            base_url=None,
            url_fetcher=secure_fetcher,
        ).write_pdf()
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "resumen_clinico_pdf_build: WeasyPrint falló al generar PDF " "para resumen=%s — %s",
            getattr(summary, "id", "?"),
            exc,
        )
        raise RuntimeError(
            f"Error al generar el PDF del resumen clínico "
            f"(resumen={getattr(summary, 'id', '?')}): {exc}"
        ) from exc

    if not pdf_bytes:
        raise RuntimeError(
            f"El PDF del resumen clínico está vacío (resumen={getattr(summary, 'id', '?')})."
        )

    return pdf_bytes


# ---------------------------------------------------------------------------
# PDF de la Calendarización de tratamientos (esquema de protocolos — Fase 1)
# ---------------------------------------------------------------------------


def _treatment_plan_session_lines(*, sessions: list[Any], quantity: int, field: str) -> list[str]:
    """Arma las líneas de una columna de fecha (programada o aplicación).

    Si `quantity` > 1, cada línea se numera "N.- <fecha o vacío>" (una por
    sesión, en orden). Si `quantity` == 1, se devuelve una sola línea sin
    numerar (la fecha, o vacía).

    Fase 4 — Calendarización: cuando `field="scheduled_date"` y la sesión
    tiene `scheduled_time`, la hora se agrega junto a la fecha
    ("09/07/2026 10:30"). Sin hora, se muestra solo la fecha (igual que
    antes de la Fase 4).

    Args:
        sessions: Lista de TreatmentSession (ya precargadas, orden por number).
        quantity: Número de sesiones del tratamiento (item.quantity).
        field:    "scheduled_date" o "applied_date".

    Returns:
        Lista de strings, una por sesión (o una sola si quantity == 1).
    """
    lines: list[str] = []
    for session in sessions:
        value = getattr(session, field, None)
        fecha = value.strftime("%d/%m/%Y") if value else ""
        if fecha and field == "scheduled_date" and getattr(session, "scheduled_time", None):
            fecha = f"{fecha} {session.scheduled_time.strftime('%H:%M')}"
        if quantity > 1:
            lines.append(f"{session.number}.- {fecha}" if fecha else f"{session.number}.-")
        else:
            lines.append(fecha)
    return lines


def _build_treatment_plan_context(*, plan: Any, clinic_settings: Any | None) -> dict[str, Any]:
    """Construye el contexto para el template expediente/calendarizacion.html.

    No hace queries adicionales sobre `plan`/items/sessions: ya vienen
    precargados por el selector treatment_plan_get (select_related +
    prefetch_related). Solo la consulta de cédulas del doctor es una query
    adicional (igual que resumen_clinico y libro.html) — aceptable porque el
    PDF corre en background (Celery), no en el request-response de la API.

    Args:
        plan:            Instancia de TreatmentPlan (precargada por el selector).
        clinic_settings: ClinicSettings del tenant o None.

    Returns:
        Diccionario de contexto para render_to_string.
    """
    patient = plan.patient
    doctor = plan.doctor

    brand: dict[str, Any] = build_brand_context(clinic_settings=clinic_settings)

    # --- Paciente ---
    paciente_nombre: str = getattr(patient, "full_name", "") or str(patient.id)
    paciente_record_number: str = getattr(patient, "record_number", "") or ""

    # --- Médico y cédula: mismos nombres de variable que espera
    # core/pdf/clinic_header.html (doctor_name/doctor_specialty/cedula_profesional),
    # misma fuente de verdad de cédulas validadas que libro.html/resumen_clinico.html.
    doctor_name: str = ""
    doctor_specialty: str = ""
    cedula_profesional: str = ""
    if doctor is not None:
        try:
            doctor_name = doctor.full_name
        except Exception:  # noqa: BLE001
            doctor_name = "Médico no disponible"
        doctor_specialty = getattr(doctor, "specialty", "") or ""
        try:
            cedulas = list(
                doctor.credentials.filter(
                    validation_status="validada",
                    is_active=True,
                    deleted_at__isnull=True,
                ).values_list("credential_number", flat=True)
            )
            cedula_profesional = " · ".join(c for c in cedulas if c)
        except Exception:  # noqa: BLE001
            cedula_profesional = ""
        if not cedula_profesional:
            cedula_profesional = getattr(doctor, "cedula_profesional", "") or ""

    # --- Filas de la tabla: una por TreatmentPlanItem ---
    filas: list[dict[str, Any]] = []
    for item in plan.items.all():
        sessions = list(item.sessions.all())
        filas.append(
            {
                "quantity": item.quantity,
                "description": item.description,
                "scheduled_lines": _treatment_plan_session_lines(
                    sessions=sessions, quantity=item.quantity, field="scheduled_date"
                ),
                "applied_lines": _treatment_plan_session_lines(
                    sessions=sessions, quantity=item.quantity, field="applied_date"
                ),
            }
        )

    return {
        **brand,
        "fecha_generacion": timezone.localtime(timezone.now()).strftime("%d/%m/%Y %H:%M"),
        "titulo": plan.title,
        "paciente_nombre": paciente_nombre,
        "paciente_record_number": paciente_record_number,
        "doctor_name": doctor_name,
        "doctor_specialty": doctor_specialty,
        "cedula_profesional": cedula_profesional,
        "filas": filas,
    }


def treatment_plan_pdf_build(*, plan: Any, clinic_settings: Any | None) -> bytes:
    """Genera los bytes del PDF de la Calendarización de tratamientos.

    Documento con membrete de la clínica y tabla de tratamientos/sesiones
    con columnas de firma FÍSICA (doctor/paciente) — celdas siempre vacías,
    nunca se persisten en BD.

    Seguridad: usa secure_fetcher (apps.core.pdf.fetchers) — SOLO data URIs,
    bloquea LFI/SSRF.

    Args:
        plan:            Instancia de TreatmentPlan (precargada por el selector
                         treatment_plan_get).
        clinic_settings: ClinicSettings del tenant o None.

    Returns:
        Bytes del PDF generado.

    Raises:
        RuntimeError: si WeasyPrint falla o el PDF queda vacío.
    """
    from weasyprint import HTML  # import tardío — facilita mocking en tests  # noqa: PLC0415

    from apps.core.pdf.fetchers import secure_fetcher  # noqa: PLC0415

    context = _build_treatment_plan_context(plan=plan, clinic_settings=clinic_settings)
    html_str: str = render_to_string("expediente/calendarizacion.html", context)

    try:
        pdf_bytes: bytes = HTML(
            string=html_str,
            base_url=None,
            url_fetcher=secure_fetcher,
        ).write_pdf()
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "treatment_plan_pdf_build: WeasyPrint falló al generar PDF " "para esquema=%s — %s",
            getattr(plan, "id", "?"),
            exc,
        )
        raise RuntimeError(
            f"Error al generar el PDF de la calendarización de tratamientos "
            f"(esquema={getattr(plan, 'id', '?')}): {exc}"
        ) from exc

    if not pdf_bytes:
        raise RuntimeError(
            f"El PDF de la calendarización de tratamientos está vacío "
            f"(esquema={getattr(plan, 'id', '?')})."
        )

    return pdf_bytes
