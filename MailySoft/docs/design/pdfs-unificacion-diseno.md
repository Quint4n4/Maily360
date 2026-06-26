# Plan — Unificar el diseño de TODOS los PDFs bajo la identidad de Recetas

> Estado: PROPUESTA · Fecha: 2026-06-26 · Relacionado: recetas (diseño maestro), `project_maily_recetas`

## 1. Objetivo
Que los 4 PDFs del sistema compartan la MISMA identidad visual (la del PDF de recetas):
encabezado de clínica (logo + nombre + contacto), **color de marca**, tipografía, **fondo de
ondas + logo como marca de agua**, y pie. Hoy cada PDF tiene su propio estilo (recetas dorado
personalizable, libro dorado+SOAP, finanzas azul fijo sin logo).

PDFs: **receta** (maestro), **libro clínico** (expediente), **reporte de periodo** (finanzas),
**cotización** (finanzas).

## 2. Decisiones (AskUserQuestion 2026-06-26)
- **D-1 Color de marca en `ClinicSettings`**: nuevo campo `brand_color` (hex) editable en Mi
  Consultorio. Aplica a TODOS los PDFs. La receta conserva su personalización fina
  (`PrescriptionFormat`) como override propio; si no hay, usa `brand_color`.
- **D-2 Estilo completo en los tabulares**: el reporte y la cotización también llevan el
  **fondo de ondas + marca de agua** (no solo el encabezado), para máxima consistencia.
- **D-3 (técnica) Recetas NO se refactoriza** para no arriesgar el diseño aprobado: se EXTRAE
  su "piel" a una base común (`apps/core/pdf/`) que heredan los otros 3; recetas sigue igual.

## 3. Qué se extrae a una base común (`apps/core/pdf/`)
- **Helpers** (hoy duplicados entre recetas y finanzas): `secure_fetcher` (solo data URIs),
  `image_to_data_uri`, `image_box`, `logo_watermark_b64`.
- **`build_brand_context(clinic_settings)`** → dict con `logo_b64/mime/w/h`, `clinic_name`,
  `address/phone/email/website`, `brand_color`, `watermark_b64`.
- **Templates parciales** en `apps/core/templates/core/pdf/`:
  - `clinic_header.html` (logo + nombre + contacto, con `brand_color`).
  - `brand_background.html` (ondas SVG + marca de agua, con `brand_color`) — extraído de
    `recetas/formats/_theme_bg.html`.
  - CSS base común (paleta neutra + tipografía + página letter + `_secure_fetcher`).

## 4. Fases
### Fase 1 — Base común (sin tocar los PDFs existentes salvo de-duplicar)
- `apps/core/pdf/` con helpers + `build_brand_context`.
- `ClinicSettings.brand_color` (CharField hex, default `#9A7B1E`, validado) + migración +
  exponer en el serializer de config (editable owner/admin).
- Parciales `clinic_header.html` + `brand_background.html` (replican el look de recetas).
- Tests del campo y del builder.

### Fase 2 — Aplicar la base a los 3 PDFs
- **Libro clínico**: encabezado con `brand_color` + ondas + marca de agua. Mantener los
  colores SOAP (legibilidad) salvo el acento del encabezado/títulos.
- **Reporte de periodo**: pasar `ClinicSettings` (hoy solo recibe `clinic_name`); aplicar
  encabezado + `brand_color` (reemplaza el azul fijo) + ondas + marca de agua detrás de las tablas.
- **Cotización**: igual que el reporte.
- Ajustar los builders (`finance_report_pdf_build`, `quote_pdf_build`, libro) para recibir
  `ClinicSettings` y construir el contexto de marca. Actualizar las vistas que los llaman.

### Fase 3 — Frontend
- Campo **"Color de marca"** (color picker) en Mi Consultorio → Datos de la clínica, guardado
  en `ClinicSettings.brand_color`. Solo owner/admin.

## 5. Riesgos / notas
- **No romper recetas** (D-3): recetas queda intacto; solo, si acaso, migra a los helpers de
  `core` sin cambiar su apariencia (verificar generando el PDF y comparándolo).
- **Reporte/cotización son tablas**: las ondas + marca de agua van DETRÁS (como en recetas);
  validar que no estorben la legibilidad (método: generar PDF y leerlo).
- **Pasar `ClinicSettings` a finanzas**: hoy el reporte recibe solo `clinic_name` (string);
  cambiar la firma + las vistas. Cuidado con la sesión paralela (no tocar lo suyo).
- **Default de `brand_color`**: el dorado actual de recetas (`#9A7B1E`) para no cambiar nada
  visible hasta que la clínica elija su color.
- Método de verificación de PDFs: generar el PDF y leerlo con la herramienta de lectura
  (como se hizo con receta/reporte/cotización), para cazar bugs de render (SVG, dobles `$`, etc.).
