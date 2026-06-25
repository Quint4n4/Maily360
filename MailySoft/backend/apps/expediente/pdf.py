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
"""

import base64
import logging
import mimetypes
from io import BytesIO
from typing import Any, Literal, Optional

from django.template.loader import render_to_string
from django.utils import timezone
from PIL import Image

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
        mime_sub = (mime_full.split("/")[-1] if mime_full and "/" in mime_full else "png")

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
    clinic_settings: Optional[Any],
    medical_history: Optional[Any],
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
    from apps.recetas.pdf import _image_box  # noqa: PLC0415

    # --- Logo de la clínica ---
    logo_box: dict[str, Any] = {"b64": "", "mime": "", "w": 0, "h": 0}
    if clinic_settings is not None and clinic_settings.logo:
        logo_box = _image_box(clinic_settings.logo, max_w_pt=160, max_h_pt=80)

    # --- Datos de la clínica ---
    clinica_nombre: str = ""
    clinica_direccion: str = ""
    clinica_telefono: str = ""
    if clinic_settings is not None:
        clinica_nombre = (
            getattr(clinic_settings, "commercial_name", "") or ""
        ) or getattr(clinic_settings, "name", "") or ""
        clinica_direccion = getattr(clinic_settings, "address", "") or ""
        clinica_telefono = (
            getattr(clinic_settings, "phone", "")
            or getattr(clinic_settings, "mobile", "")
            or ""
        )

    if not clinica_nombre:
        # Fallback: nombre del tenant.
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
    fecha_generacion: str = timezone.localtime(timezone.now()).strftime(
        "%d/%m/%Y %H:%M"
    )

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
            fecha_display = timezone.localtime(nota_created).strftime(
                "%d/%m/%Y %H:%M"
            )
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
        signos_dict: Optional[dict[str, Any]] = None
        vs = getattr(nota, "vital_signs", None)
        if vs is not None:
            # Calcular IMC si hay peso y talla.
            imc_val: Optional[str] = None
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
    clinic_settings: Optional[Any],
    medical_history: Optional[Any],
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
            "libro_pdf_build: WeasyPrint falló al generar PDF "
            "para paciente=%s modo=%s — %s",
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
