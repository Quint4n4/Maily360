/**
 * nucleoHistoriaClinica — definición COMPARTIDA del núcleo NOM-004 de la
 * Historia Clínica (secciones fijas con sus preguntas).
 *
 * Fuente única de la verdad para:
 *   - HistoriaTab (captura de la HC del paciente): reusa los `*_FIELDS` (clave/label).
 *   - SeccionHistoriaClinica (configurador de preguntas extra): muestra el núcleo a
 *     detalle en un acordeón de solo lectura y ofrece sus títulos en el selector
 *     de "Sección (grupo)".
 *
 * El núcleo NO se edita; estas constantes describen lo que YA viene fijo en cada HC.
 */

import type {
  GinecoObstetricos,
  HabitosAlimenticios,
  HeredoFamiliares,
  NoPatologicos,
  PersonalesPatologicos,
  QuestionFieldType,
} from '../types/expediente'

/** Una pregunta del núcleo: su clave en el bloque JSON y su etiqueta visible. */
export interface NucleoPregunta {
  key: string
  label: string
  /** Tipo de control con que se captura (para mostrarlo en la vista de detalle). */
  field_type: QuestionFieldType
}

/** Una sección del núcleo NOM-004 con su título y sus preguntas. */
export interface NucleoSeccion {
  id: string
  titulo: string
  preguntas: NucleoPregunta[]
}

// ── Campos string de cada bloque (clave → etiqueta) — los reusa HistoriaTab ───

export const AHF_FIELDS: { key: keyof HeredoFamiliares; label: string }[] = [
  { key: 'diabetes', label: 'Diabetes' },
  { key: 'hipertension_arterial', label: 'Hipertensión arterial' },
  { key: 'cardiopatias', label: 'Cardiopatías' },
  { key: 'hepatopatias', label: 'Hepatopatías' },
  { key: 'urologicos', label: 'Urológicos' },
  { key: 'neurologicos', label: 'Neurológicos' },
  { key: 'respiratorias', label: 'Respiratorias' },
  { key: 'cancer', label: 'Cáncer' },
  { key: 'alergicas', label: 'Alérgicas' },
  { key: 'metabolicas', label: 'Metabólicas' },
  { key: 'sanguineas', label: 'Sanguíneas' },
  { key: 'articulares', label: 'Articulares' },
  { key: 'inmunologicas', label: 'Inmunológicas' },
  { key: 'malformaciones', label: 'Malformaciones' },
  { key: 'dermatologicas', label: 'Dermatológicas' },
  { key: 'otros', label: 'Otros' },
]

export const APP_FIELDS: { key: keyof PersonalesPatologicos; label: string }[] = [
  { key: 'enfermedades_infancia', label: 'Enfermedades de la infancia' },
  { key: 'diabetes', label: 'Diabetes' },
  { key: 'hipertension', label: 'Hipertensión' },
  { key: 'respiratorias', label: 'Respiratorias' },
  { key: 'oftalmico', label: 'Oftálmico' },
  { key: 'cardiovasculares', label: 'Cardiovasculares' },
  { key: 'neurologicos', label: 'Neurológicos' },
  { key: 'gastrointestinales', label: 'Gastrointestinales' },
  { key: 'hepatopatias', label: 'Hepatopatías' },
  { key: 'metabolicas', label: 'Metabólicas' },
  { key: 'urologicos', label: 'Urológicos' },
  { key: 'circulatorio', label: 'Circulatorio' },
  { key: 'traumaticas', label: 'Traumáticas' },
  { key: 'articulares', label: 'Articulares' },
  { key: 'dermatologicas', label: 'Dermatológicas' },
  { key: 'quirurgicos', label: 'Quirúrgicos' },
  { key: 'transfusionales', label: 'Transfusionales' },
  { key: 'vectores', label: 'Vectores' },
  { key: 'autoinmunes', label: 'Autoinmunes' },
  { key: 'emocionales', label: 'Emocionales' },
  { key: 'adicciones', label: 'Adicciones' },
  { key: 'hospitalizaciones_previas', label: 'Hospitalizaciones previas' },
  { key: 'pesticidas', label: 'Pesticidas' },
  { key: 'dx_cancer', label: 'Diagnóstico de cáncer' },
  { key: 'otros', label: 'Otros' },
]

export const APNP_FIELDS: { key: keyof NoPatologicos; label: string }[] = [
  { key: 'servicios_basicos', label: 'Servicios básicos' },
  { key: 'actividad_fisica', label: 'Actividad física' },
  { key: 'tabaquismo', label: 'Tabaquismo' },
  { key: 'alcoholismo', label: 'Alcoholismo' },
  { key: 'otras_toxicomanias', label: 'Otras toxicomanías' },
  { key: 'inmunizaciones', label: 'Inmunizaciones' },
  { key: 'ultima_desparasitacion', label: 'Última desparasitación' },
  { key: 'otros', label: 'Otros' },
]

export const HABITOS_FIELDS: { key: keyof HabitosAlimenticios; label: string }[] = [
  { key: 'dieta_especial', label: 'Dieta especial' },
  { key: 'intolerancias_alimentarias', label: 'Intolerancias alimentarias' },
  { key: 'consumo_agua_litros', label: 'Consumo de agua (litros)' },
  { key: 'suplementos', label: 'Suplementos' },
]

export const AGO_FIELDS: { key: keyof GinecoObstetricos; label: string }[] = [
  { key: 'menarca', label: 'Menarca' },
  { key: 'ritmo_menstrual', label: 'Ritmo menstrual' },
  { key: 'alteraciones', label: 'Alteraciones' },
  { key: 'fum', label: 'FUM (última menstruación)' },
  { key: 'ivsa', label: 'IVSA' },
  { key: 'numero_parejas', label: 'Número de parejas' },
  { key: 'gestas', label: 'Gestas' },
  { key: 'abortos', label: 'Abortos' },
  { key: 'partos', label: 'Partos' },
  { key: 'cesareas', label: 'Cesáreas' },
  { key: 'fup', label: 'FUP (último parto)' },
  { key: 'metodo_planificacion', label: 'Método de planificación' },
  { key: 'citologia_vaginal', label: 'Citología vaginal' },
  { key: 'colposcopia', label: 'Colposcopia' },
  { key: 'usg_pelvico', label: 'USG pélvico' },
  { key: 'mastografia', label: 'Mastografía' },
  { key: 'usg_mamas', label: 'USG de mamas' },
  { key: 'menopausia_climaterio', label: 'Menopausia / climaterio' },
  { key: 'tratamientos_hormonales', label: 'Tratamientos hormonales' },
]

// ── Helpers internos para construir la vista de detalle del núcleo ────────────

/** Convierte una lista `{ key, label }` en preguntas del núcleo (texto corto). */
function comoPreguntasTexto(
  fields: { key: string; label: string }[],
): NucleoPregunta[] {
  return fields.map(f => ({ key: f.key, label: f.label, field_type: 'text' }))
}

// ── Estructura del núcleo NOM-004 (secciones + preguntas) ─────────────────────
//
// Los `titulo` deben coincidir EXACTAMENTE con los títulos de los bloques que
// renderiza HistoriaTab y con los valores del selector del configurador: así una
// pregunta extra cuya `section` iguale un título cae dentro de esa sección.

/**
 * Secciones del núcleo NOM-004 con TODAS sus preguntas fijas (label + tipo).
 * Solo lectura: describe lo que ya viene incluido por norma en cada HC.
 */
export const NUCLEO_SECCIONES: NucleoSeccion[] = [
  {
    id: 'ahf',
    titulo: 'Antecedentes heredo-familiares',
    preguntas: [
      { key: 'numero_hermanos', label: 'Número de hermanos', field_type: 'number' },
      ...comoPreguntasTexto(AHF_FIELDS),
    ],
  },
  {
    id: 'app',
    titulo: 'Antecedentes personales patológicos',
    preguntas: comoPreguntasTexto(APP_FIELDS),
  },
  {
    id: 'apnp',
    titulo: 'Antecedentes no patológicos',
    preguntas: [
      { key: 'casa_habitacion', label: 'Casa habitación', field_type: 'select' },
      ...comoPreguntasTexto(APNP_FIELDS),
    ],
  },
  {
    id: 'habitos',
    titulo: 'Hábitos alimenticios',
    preguntas: [
      { key: 'numero_comidas_dia', label: 'Número de comidas al día', field_type: 'number' },
      ...comoPreguntasTexto(HABITOS_FIELDS),
    ],
  },
  {
    id: 'ago',
    titulo: 'Antecedentes gineco-obstétricos',
    preguntas: comoPreguntasTexto(AGO_FIELDS),
  },
  {
    id: 'exploracion',
    titulo: 'Exploración física basal',
    preguntas: [
      { key: 'exploracion_fisica_basal', label: 'Exploración por aparatos y sistemas', field_type: 'textarea' },
    ],
  },
  {
    id: 'padecimiento_actual',
    titulo: 'Padecimiento actual',
    preguntas: [
      { key: 'padecimiento_actual', label: 'Padecimiento actual', field_type: 'textarea' },
    ],
  },
  {
    id: 'antecedentes_importancia',
    titulo: 'Antecedentes de importancia',
    preguntas: [
      { key: 'antecedentes_importancia', label: 'Antecedentes de importancia', field_type: 'textarea' },
    ],
  },
  {
    id: 'tratamientos_actuales',
    titulo: 'Tratamientos actuales',
    preguntas: [
      { key: 'tratamientos_actuales', label: 'Tratamientos actuales', field_type: 'textarea' },
    ],
  },
  {
    id: 'prioridad_analisis',
    titulo: 'Prioridad de análisis',
    preguntas: [
      { key: 'prioridad_analisis', label: 'Prioridad de análisis', field_type: 'textarea' },
    ],
  },
]

/** Solo los títulos del núcleo (para el selector de sección del configurador). */
export const NUCLEO_TITULOS: string[] = NUCLEO_SECCIONES.map(s => s.titulo)

/** Conjunto de títulos del núcleo para chequeos O(1) (¿esta sección es del núcleo?). */
export const NUCLEO_TITULOS_SET: ReadonlySet<string> = new Set(NUCLEO_TITULOS)
