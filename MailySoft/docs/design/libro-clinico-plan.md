# Libro clínico del paciente — plan por fases

> Estado: **plan** (2026-06-24). Diseño aprobado con maqueta por el dueño.
> Idea: una "carpeta clínica viva" que **encuaderna** la Historia Clínica + todas las
> evoluciones del paciente en un solo documento navegable e imprimible. Cada visita
> **anexa un capítulo** (signos de enfermería, exploración por aparatos, imágenes,
> SOAP, diagnósticos, tratamiento y recetas). Se entrega impreso al paciente.

## 1. Principio rector: se COMPONE, no se duplica

El libro **no es una tabla nueva**. Es una **vista agregada + un PDF** que junta, en orden,
datos que YA existen en el expediente. Nada se copia ni se desnormaliza.

| Sección del libro | Fuente existente (no crear nada nuevo) |
|---|---|
| Portada | `Patient` + `ClinicSettings` |
| Historia Clínica (viva) | `MedicalHistory` (`medical_history_get_for_patient`) + `Allergy` (`allergy_list`) |
| Capítulo = evolución | `EvolutionNote` (`evolution_note_list`) |
| · signos de enfermería | `VitalSignsRecord` (FK `EvolutionNote.vital_signs` / `vital_signs_latest`) |
| · exploración por aparatos | campos de la propia `EvolutionNote` |
| · imágenes | `EvolutionImage` (`evolution_images_list`) |
| · diagnósticos | `EvolutionNote.diagnosticos_texto` + `Diagnosis` (`diagnosis_list`) |
| · tratamiento / receta | `Prescription` vinculada por `Prescription.evolution_note` |
| · addenda | `Addendum` (`addendum_list`) |

## 2. Decisiones tomadas con el dueño (2026-06-24) — locked

- **D-LIB-1 · Historia Clínica viva.** El libro muestra SIEMPRE la versión actual de la HC.
  Las **evoluciones son inmutables** (ya lo son): la primera evolución queda registrada tal
  cual y se puede consultar navegando al final del libro.
- **D-LIB-2 · Imágenes opcionales al imprimir.** Toggle "con / sin imágenes" en la impresión
  (PDF más ligero sin imágenes). En pantalla siempre se ven.
- **D-LIB-3 · Orden: más reciente primero.** El libro abre en el último capítulo; la
  **paginación** lleva hacia el pasado.
- **D-LIB-4 · Snapshot al imprimir.** Cada PDF generado es una foto del momento; se registra
  en bitácora (NOM-024) quién lo generó y cuándo. El contenido vivo es la pantalla.
- **D-LIB-5 · Tres modos de impresión:** (a) **libro completo**, (b) **solo Historia Clínica**
  (para la 1ª consulta), (c) **solo el último capítulo + sus recetas** (cada visita).
- **D-LIB-6 · Privacidad.** El libro contiene TODO el expediente (PII sensible): acceso solo
  a roles clínicos (mismos permisos que el expediente/recetas — recepción/finanzas NO).
  Nunca expuesto en URL pública; reúsa el patrón de descarga autenticada (Bearer) de recetas.

## 3. Contrato de API (borrador — el backend lo afina)

`GET /api/v1/expediente/<patient_id>/libro/?page=N`  → roles clínicos.

```jsonc
{
  "paciente":  { "id", "full_name", "record_number", "date_of_birth", "sex_display", ... },
  "clinica":   { "name", "logo", "address", "phone" },
  "historia_clinica": { ...MedicalHistoryOutput } | null,   // versión viva
  "alergias":  [ ...AllergyOutput ],
  "capitulos_count": 12,
  "capitulos": [                         // paginado, MÁS RECIENTE PRIMERO
    {
      "id", "fecha", "doctor": { "full_name", "cedulas_validadas" },
      "signos":      { ...VitalSignsOutput } | null,
      "subjetivo":   "interrogatorio + antecedentes",
      "objetivo":    "estudios",
      "exploracion": [ { "sistema", "estado", "detalle" } ],
      "analisis":    { "texto", "diagnosticos": [ ...DiagnosisOutput ] },
      "plan":        { "tratamiento", "recomendaciones", "indicaciones_enfermeria" },
      "imagenes":    [ ...EvolutionImageOutput ],
      "recetas":     [ { "id", "folio", "items_resumen" } ],
      "addenda":     [ ...AddendumOutput ]
    }
  ]
}
```

El **PDF** se genera en `GET /api/v1/expediente/<patient_id>/libro/pdf/?modo=completo|hc|ultimo&imagenes=1|0`
(WeasyPrint, reusando la infraestructura de `apps/recetas/pdf.py`).

## 4. Fases

### Fase 1 — Backend: armador del libro (selector + serializer + endpoint JSON)
- `book_build(*, patient, page, page_size)` en `apps/expediente/selectors.py` (o un `services`/módulo
  `libro.py`): compone portada + HC viva + capítulos paginados (más reciente primero), reusando
  los selectors existentes. Evitar N+1 (prefetch de signos/imágenes/recetas por evolución).
- Serializer de salida `PatientBookSerializer` que ensambla los serializers ya existentes.
- Vista `PatientBookApi` (GET) con permiso clínico (igual que `EvolutionNote`), paginada.
- Bitácora: `PATIENT_BOOK_VIEW`.
- Tests: armado correcto, orden reciente-primero, aislamiento multi-tenant, sin N+1, permisos.

### Fase 2 — Frontend: visor del libro
- Botón **"Ver libro"** en el expediente (`FichaPaciente`/`ExpedienteDrawer`).
- Visor: portada + índice de capítulos + página del capítulo (como la maqueta aprobada) +
  paginación (más reciente primero). Tipos/api/hooks tipados; TanStack Query; lazy-load por página.
- Reusa el estilo dorado+glass; los colores SOAP (S azul, O teal, A morado, P verde).

### Fase 3 — PDF del libro (WeasyPrint)
- Plantilla `templates/expediente/libro.html`: portada con marca + HC + capítulos.
- 3 modos (`completo` / `hc` / `ultimo`) + toggle `imagenes`.
- Descarga autenticada (Bearer) como las recetas; bitácora `PATIENT_BOOK_PDF`.

### Fase 4 — Optimización y pulido
- Compresión/redimensionado de imágenes para el PDF (evitar el problema de imágenes enormes,
  ref. DecompressionBomb del logo); portada/carátula con logo de la clínica; rendimiento.

## 5. Reglas (heredadas del proyecto)
- Arquitectura por capas (thin views → serializers → selectors), tipado mypy, multi-tenant + RLS,
  sin secretos. Las evoluciones y recetas siguen **inmutables**. El PDF nunca en URL pública.
