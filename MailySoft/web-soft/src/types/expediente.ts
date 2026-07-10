/**
 * Tipos del dominio Expediente Clínico — reflejan EXACTAMENTE el backend
 * (apps/expediente/serializers.py y apps/expediente/validators.py).
 *
 * Sub-fases:
 *   A1 — Alergias (banderas de seguridad).
 *   A2 — Historia clínica (documento vivo, bloques JSON).
 *   A3 — Signos vitales (append-only, con IMC derivado + series).
 *   A4 — Notas de evolución (inmutables), addenda y diagnósticos.
 *
 * Regla: nada de `any`. Las claves de los bloques JSON son whitelists del backend.
 */

// ───────────────────────────────────────────────────────────────────────────
// A1 — Alergias
// ───────────────────────────────────────────────────────────────────────────

/** Severidad de la reacción alérgica (models.Severity). '' = sin especificar. */
export type AllergySeverity = 'leve' | 'moderada' | 'severa' | ''

/** Salida de Allergy (AllergyOutputSerializer). */
export interface Allergy {
  id: string
  patient_id: string
  substance: string
  reaction: string
  severity: AllergySeverity
  severity_display: string
  /** true = vigente; false = resuelta (baja lógica clínica). */
  is_active: boolean
  created_at: string
  updated_at: string
}

/** Cuerpo para registrar una alergia (AllergyInputSerializer). */
export interface AllergyInput {
  substance: string
  reaction?: string
  severity?: AllergySeverity
}

// ───────────────────────────────────────────────────────────────────────────
// A2 — Historia clínica (bloques JSON)
// ───────────────────────────────────────────────────────────────────────────

/** Antecedentes heredo-familiares (AHF). Strings opcionales + numero_hermanos (int). */
export interface HeredoFamiliares {
  numero_hermanos?: number | null
  diabetes?: string | null
  hipertension_arterial?: string | null
  cardiopatias?: string | null
  hepatopatias?: string | null
  urologicos?: string | null
  neurologicos?: string | null
  respiratorias?: string | null
  cancer?: string | null
  alergicas?: string | null
  metabolicas?: string | null
  sanguineas?: string | null
  articulares?: string | null
  inmunologicas?: string | null
  malformaciones?: string | null
  dermatologicas?: string | null
  otros?: string | null
}

/** Antecedentes personales patológicos (APP). Todas strings opcionales. */
export interface PersonalesPatologicos {
  enfermedades_infancia?: string | null
  diabetes?: string | null
  hipertension?: string | null
  respiratorias?: string | null
  oftalmico?: string | null
  cardiovasculares?: string | null
  neurologicos?: string | null
  gastrointestinales?: string | null
  hepatopatias?: string | null
  metabolicas?: string | null
  urologicos?: string | null
  circulatorio?: string | null
  traumaticas?: string | null
  articulares?: string | null
  dermatologicas?: string | null
  quirurgicos?: string | null
  transfusionales?: string | null
  vectores?: string | null
  autoinmunes?: string | null
  emocionales?: string | null
  adicciones?: string | null
  hospitalizaciones_previas?: string | null
  pesticidas?: string | null
  dx_cancer?: string | null
  otros?: string | null
}

/** Choice de tipo de vivienda (validators._VIVIENDA_CHOICES). */
export type ViviendaChoice = 'propia' | 'rentada' | 'prestada' | 'otro'

/** Antecedentes no patológicos (APNP) — núcleo. casa_habitacion es choice. */
export interface NoPatologicos {
  casa_habitacion?: ViviendaChoice | '' | null
  servicios_basicos?: string | null
  actividad_fisica?: string | null
  tabaquismo?: string | null
  alcoholismo?: string | null
  otras_toxicomanias?: string | null
  inmunizaciones?: string | null
  ultima_desparasitacion?: string | null
  otros?: string | null
}

/** Hábitos alimenticios (versión corta). numero_comidas_dia es int. */
export interface HabitosAlimenticios {
  numero_comidas_dia?: number | null
  dieta_especial?: string | null
  intolerancias_alimentarias?: string | null
  consumo_agua_litros?: string | null
  suplementos?: string | null
}

/** Antecedentes gineco-obstétricos (AGO). Solo aplica a sexo F. Strings opcionales. */
export interface GinecoObstetricos {
  menarca?: string | null
  ritmo_menstrual?: string | null
  alteraciones?: string | null
  fum?: string | null
  ivsa?: string | null
  numero_parejas?: string | null
  gestas?: string | null
  abortos?: string | null
  partos?: string | null
  cesareas?: string | null
  fup?: string | null
  metodo_planificacion?: string | null
  citologia_vaginal?: string | null
  colposcopia?: string | null
  usg_pelvico?: string | null
  mastografia?: string | null
  usg_mamas?: string | null
  menopausia_climaterio?: string | null
  tratamientos_hormonales?: string | null
}

/** Sistemas/aparatos de la exploración física (validators._EXPLORACION_SISTEMAS). */
export type ExploracionSistema =
  | 'cerebro'
  | 'sistema_nervioso'
  | 'ocular'
  | 'endocrino'
  | 'corazon'
  | 'circulatorio'
  | 'respiratorio'
  | 'hepatico'
  | 'pancreas'
  | 'renal'
  | 'gastrointestinal'
  | 'osteoarticular'
  | 'tendomuscular'
  | 'reproductor'
  | 'inmunologico'
  | 'extremidades'
  | 'piel_tegumentos'
  | 'otros'

/** Estado de un sistema en la exploración basal (HC). */
export type ExploracionBasalEstado = 'sin_alteraciones' | 'con_alteraciones'

/** Celda de un sistema en la exploración basal. */
export interface ExploracionBasalCelda {
  estado?: ExploracionBasalEstado
  detalle?: string | null
}

/** Exploración física basal por sistema (bloque JSON de la HC). */
export type ExploracionFisicaBasal = Partial<Record<ExploracionSistema, ExploracionBasalCelda>>

// ───────────────────────────────────────────────────────────────────────────
// Fase 2 — Historia clínica CONFIGURABLE (preguntas extra por clínica)
//
// El núcleo NOM-004 de la HC NO se toca; estas preguntas son SOLO adicionales.
// Reflejan EXACTAMENTE el backend (apps/expediente — MedicalHistoryQuestion):
//   GET    /expediente/preguntas-hc/        → lista de preguntas de la clínica
//   POST   /expediente/preguntas-hc/        (owner/admin) → crea
//   PATCH  /expediente/preguntas-hc/<id>/   (owner/admin) → edita
//   DELETE /expediente/preguntas-hc/<id>/   (owner/admin) → baja lógica
// ───────────────────────────────────────────────────────────────────────────

/** Tipo de campo de una pregunta extra de la HC (choices del backend). */
export type QuestionFieldType =
  | 'text'
  | 'textarea'
  | 'boolean'
  | 'select'
  | 'number'
  | 'date'

/** Una pregunta extra de la HC definida por la clínica (MedicalHistoryQuestion). */
export interface MedicalHistoryQuestion {
  id: string
  /** Texto de la pregunta que ve el médico. */
  label: string
  field_type: QuestionFieldType
  /** Opciones del dropdown (solo aplica cuando field_type === 'select'). */
  options: string[]
  /** Agrupador opcional (ej. "Estilo de vida"); '' si no se especificó. */
  section: string
  /** Orden dentro de su sección (ascendente). */
  order: number
  is_required: boolean
  /** false = pregunta dada de baja (baja lógica). */
  is_active: boolean
  created_at: string
  updated_at: string
}

/** Cuerpo para crear una pregunta extra de la HC (POST). */
export interface MedicalHistoryQuestionInput {
  label: string
  field_type: QuestionFieldType
  /** Solo para 'select'. */
  options?: string[]
  section?: string
  order?: number
  is_required?: boolean
}

/** Cuerpo para editar una pregunta extra (PATCH). Todos los campos opcionales. */
export interface MedicalHistoryQuestionUpdateInput {
  label?: string
  field_type?: QuestionFieldType
  options?: string[]
  section?: string
  order?: number
  is_required?: boolean
  is_active?: boolean
}

/**
 * Valor de una respuesta a una pregunta extra. El backend acepta texto, número
 * o booleano según el field_type (las claves inválidas se descartan en el PUT).
 */
export type CustomAnswerValue = string | number | boolean | null

/** Mapa { <question_id>: valor } de las respuestas a preguntas extra. */
export type CustomAnswers = Record<string, CustomAnswerValue>

/** Salida de MedicalHistory (MedicalHistoryOutputSerializer / documento vacío). */
export interface MedicalHistory {
  /** null cuando la HC aún no existe (documento vacío que devuelve el backend). */
  id: string | null
  patient_id: string | null
  heredo_familiares: HeredoFamiliares
  personales_patologicos: PersonalesPatologicos
  no_patologicos: NoPatologicos
  habitos_alimenticios: HabitosAlimenticios
  gineco_obstetricos: GinecoObstetricos
  exploracion_fisica_basal: ExploracionFisicaBasal
  antecedentes_importancia: string
  padecimiento_actual: string
  tratamientos_actuales: string
  prioridad_analisis: string
  /** Respuestas a las preguntas extra de la clínica (Fase 2): { <question_id>: valor }. */
  custom_answers: CustomAnswers
  /** Preguntas extra ACTIVAS de la clínica para renderizar dinámicamente (Fase 2). */
  active_questions: MedicalHistoryQuestion[]
  created_at: string | null
  updated_at: string | null
}

/** Cuerpo del upsert de HC (PUT). Todos los bloques son opcionales (D-EC-8). */
export interface MedicalHistoryInput {
  heredo_familiares?: HeredoFamiliares
  personales_patologicos?: PersonalesPatologicos
  no_patologicos?: NoPatologicos
  habitos_alimenticios?: HabitosAlimenticios
  gineco_obstetricos?: GinecoObstetricos
  exploracion_fisica_basal?: ExploracionFisicaBasal
  antecedentes_importancia?: string
  padecimiento_actual?: string
  tratamientos_actuales?: string
  prioridad_analisis?: string
  /** Respuestas a las preguntas extra (Fase 2). Las claves inválidas se descartan. */
  custom_answers?: CustomAnswers
}

// ───────────────────────────────────────────────────────────────────────────
// A3 — Signos vitales
// ───────────────────────────────────────────────────────────────────────────

/** Claves permitidas en extra_params (models.EXTRA_PARAMS_WHITELIST). */
export type ExtraParamKey = 'colesterol' | 'trigliceridos' | 'urea' | 'creatinina' | 'hemoglobina'

/** Parámetros de laboratorio extensibles del legacy. */
export type ExtraParams = Partial<Record<ExtraParamKey, number>>

/**
 * Salida de una toma de signos vitales (VitalSignsOutputSerializer).
 * Los DecimalField llegan como string en JSON de DRF; los IntegerField como number.
 */
export interface VitalSignsRecord {
  id: string
  patient_id: string
  appointment_id: string | null
  measured_at: string // ISO datetime
  weight_kg: string | null
  height_m: string | null
  heart_rate: number | null
  resp_rate: number | null
  systolic: number | null
  diastolic: number | null
  temperature_c: string | null
  oxygen_saturation: number | null
  glucose: number | null
  extra_params: ExtraParams
  notes: string
  /** IMC derivado (weight_kg / height_m²). null si falta peso o talla. No se almacena. */
  imc: number | null
  created_by_id: string | null
  /** Nombre legible de quien capturó la toma. Cadena vacía si no se puede resolver. */
  created_by_name: string
  created_at: string
}

/** Cuerpo para crear una toma de signos (VitalSignsInputSerializer). Append-only. */
export interface VitalSignsInput {
  /** ISO 8601. Default: ahora. No puede ser futuro. */
  measured_at?: string
  weight_kg?: number | null
  height_m?: number | null
  heart_rate?: number | null
  resp_rate?: number | null
  systolic?: number | null
  diastolic?: number | null
  temperature_c?: number | null
  oxygen_saturation?: number | null
  glucose?: number | null
  extra_params?: ExtraParams
  notes?: string
  appointment_id?: string | null
}

/** Un punto de una serie temporal: {measured_at, value}. */
export interface SeriesPoint {
  measured_at: string // ISO datetime
  value: number
}

/**
 * Series temporales para gráficas (VitalSignsSeriesApi).
 * Una clave por parámetro plano + 'imc' + cada clave de extra_params.
 * (selectors._SERIES_FIELDS + 'imc' + _EXTRA_SERIES_KEYS)
 */
export interface VitalSignsSeries {
  weight_kg: SeriesPoint[]
  heart_rate: SeriesPoint[]
  resp_rate: SeriesPoint[]
  systolic: SeriesPoint[]
  diastolic: SeriesPoint[]
  temperature_c: SeriesPoint[]
  oxygen_saturation: SeriesPoint[]
  glucose: SeriesPoint[]
  imc: SeriesPoint[]
  colesterol: SeriesPoint[]
  trigliceridos: SeriesPoint[]
  urea: SeriesPoint[]
  creatinina: SeriesPoint[]
  hemoglobina: SeriesPoint[]
}

/** Clave de una serie graficable. */
export type SeriesKey = keyof VitalSignsSeries

// ───────────────────────────────────────────────────────────────────────────
// A4 — Notas de evolución, addenda y diagnósticos
// ───────────────────────────────────────────────────────────────────────────

/** Estado del semáforo de la exploración en una nota de evolución. */
export type ExploracionEvolucionEstado = 'no_evaluado' | 'normal' | 'observacion' | 'alterado'

/** Celda de un sistema en la exploración de la nota de evolución. */
export interface ExploracionEvolucionCelda {
  estado?: ExploracionEvolucionEstado
  detalle?: string | null
}

/** Exploración física por sistema en una nota de evolución (bloque JSON). */
export type ExploracionEvolucion = Partial<Record<ExploracionSistema, ExploracionEvolucionCelda>>

/** Salida de un addendum (AddendumOutputSerializer). */
export interface Addendum {
  id: string
  evolution_id: string
  author_id: string
  body: string
  created_at: string
}

/**
 * Imagen adjunta a una nota de evolución (EvolutionImageOutputSerializer).
 * Salida de GET/POST /expediente/evoluciones/<evolution_id>/imagenes/.
 */
export interface EvolutionImage {
  id: string
  /** URL absoluta/relativa servida por el backend para mostrar la imagen. */
  image_url: string
  /** Pie de foto opcional ('' si no se capturó). */
  caption: string
  created_at: string
}

/** Salida de una nota de evolución (EvolutionNoteOutputSerializer). Inmutable. */
export interface EvolutionNote {
  id: string
  patient_id: string
  appointment_id: string
  doctor_id: string
  vital_signs_id: string | null
  antecedentes: string
  interrogatorio: string
  estudios: string
  diagnosticos_texto: string
  tratamiento: string
  plan_recomendaciones: string
  indicaciones_enfermeria: string
  exploracion_fisica: ExploracionEvolucion
  is_locked: boolean
  addenda: Addendum[]
  created_at: string
  updated_at: string
}

/** Cuerpo para crear una nota de evolución (EvolutionNoteInputSerializer). */
export interface EvolutionNoteInput {
  /** Cita ATTENDED del paciente. */
  appointment_id: string
  /** Doctor de la cita (debe ser el doctor del appointment). */
  doctor_id: string
  vital_signs_id?: string | null
  antecedentes?: string
  interrogatorio?: string
  estudios?: string
  diagnosticos_texto?: string
  tratamiento?: string
  plan_recomendaciones?: string
  indicaciones_enfermeria?: string
  exploracion_fisica?: ExploracionEvolucion
}

/** Cuerpo para agregar un addendum (AddendumInputSerializer). */
export interface AddendumInput {
  body: string
}

/**
 * Indicación para enfermería — vista derivada de las notas de evolución.
 * Salida de GET /expediente/<patient_id>/indicaciones-enfermeria/.
 */
export interface NursingInstruction {
  id: string
  /** ISO datetime de la evolución que originó la indicación. */
  fecha: string
  /** Nombre del médico que firmó la evolución. */
  doctor: string
  indicaciones: string
}

/** Tipo de diagnóstico (models.DiagnosisKind). */
export type DiagnosisKind = 'presuntivo' | 'definitivo'

/** Estado del diagnóstico (models.DiagnosisStatus). */
export type DiagnosisStatus = 'activo' | 'resuelto'

/** Salida de un diagnóstico (DiagnosisOutputSerializer). */
export interface Diagnosis {
  id: string
  patient_id: string
  evolution_id: string | null
  cie_code: string
  description: string
  kind: DiagnosisKind
  kind_display: string
  status: DiagnosisStatus
  status_display: string
  created_at: string
  updated_at: string
}

/** Cuerpo para crear un diagnóstico (DiagnosisInputSerializer). */
export interface DiagnosisInput {
  description: string
  cie_code?: string
  kind?: DiagnosisKind
  evolution_id?: string | null
}

// ───────────────────────────────────────────────────────────────────────────
// Fase 2 — Libro clínico (vista agregada, NO crea tablas nuevas)
//
// Refleja EXACTAMENTE el endpoint del backend (Fase 1):
//   GET /api/v1/expediente/<patient_id>/libro/?page=N&page_size=M
// Solo se COMPONE de datos que ya existen (HC viva + alergias + evoluciones).
// Más reciente primero (D-LIB-3).
// ───────────────────────────────────────────────────────────────────────────

/** Datos de la clínica para la portada del libro (subset de ClinicSettings). */
export interface BookClinica {
  name: string
  /** URL del logo de la clínica, o null. */
  logo: string | null
  address: string
  phone: string
}

/** Firma del médico que firmó la evolución (encabezado/pie del capítulo). */
export interface BookDoctor {
  full_name: string
  /** Cédulas profesionales validadas (COFEPRIS), ya filtradas por el backend. */
  cedulas_validadas: string[]
}

/** Una fila de la exploración por aparatos dentro del capítulo. */
export interface BookExploracion {
  sistema: string
  estado: string
  detalle: string
}

/** Bloque "Análisis" (A del SOAP): texto libre + diagnósticos asociados. */
export interface BookAnalisis {
  texto: string
  diagnosticos: Diagnosis[]
}

/** Bloque "Plan" (P del SOAP). */
export interface BookPlan {
  tratamiento: string
  recomendaciones: string
  indicaciones_enfermeria: string
}

/** Resumen de una receta dentro de un capítulo (no el detalle completo). */
export interface BookRecetaResumen {
  id: string
  folio: number
  /** Estado de la receta (models.PrescriptionStatus): 'active' | 'cancelled'. */
  status: string
  /** ISO datetime de emisión. */
  issued_at: string
  /** Líneas resumidas de los ítems (ej. "Paracetamol 500mg · 1 c/8h"). */
  items_resumen: string[]
}

/**
 * Un capítulo del libro = una nota de evolución compuesta (SOAP + signos +
 * exploración + imágenes + diagnósticos + recetas + addenda). Inmutable.
 */
export interface BookCapitulo {
  id: string
  /** ISO datetime (created_at de la evolución). */
  fecha: string
  doctor: BookDoctor
  /** Snapshot de signos de enfermería de la visita, o null. */
  signos: VitalSignsRecord | null
  /** S — subjetivo (interrogatorio + antecedentes). */
  subjetivo: string
  /** O — objetivo (estudios). */
  objetivo: string
  /** Exploración por aparatos (solo los sistemas evaluados). */
  exploracion: BookExploracion[]
  /** A — análisis. */
  analisis: BookAnalisis
  /** P — plan. */
  plan: BookPlan
  imagenes: EvolutionImage[]
  recetas: BookRecetaResumen[]
  addenda: Addendum[]
}

/**
 * Respuesta del armador del libro (PatientBookSerializer).
 * Portada + HC viva + alergias + capítulos paginados (más reciente primero).
 */
export interface PatientBook {
  /** Datos del paciente (mismo serializer que el detalle de paciente). */
  paciente: import('./paciente').PatientOut
  /** Datos de la clínica para la portada, o null si no hay configuración. */
  clinica: BookClinica | null
  /** Historia clínica VIVA (versión actual), o null si aún no existe. */
  historia_clinica: MedicalHistory | null
  alergias: Allergy[]
  /** Total de capítulos (evoluciones) del paciente, sin importar la página. */
  capitulos_count: number
  /** Total de páginas con el page_size actual. */
  total_pages: number
  /** Página actual (1-based). */
  page: number
  page_size: number
  /** Capítulos de esta página, MÁS RECIENTE PRIMERO. */
  capitulos: BookCapitulo[]
}

// ───────────────────────────────────────────────────────────────────────────
// Resumen Clínico — constancia que se entrega al paciente desde una evolución
// ───────────────────────────────────────────────────────────────────────────

/**
 * Las 6 secciones EDITABLES del resumen clínico. Son texto libre; el borrador
 * las trae auto-rellenadas desde la evolución y el médico las ajusta antes de
 * generar la constancia. Mismo shape en el borrador y en el POST de creación.
 */
export interface ResumenSecciones {
  /** Ficha de identificación del paciente. */
  identificacion: string
  /** Antecedentes de importancia. */
  antecedentes: string
  /** Padecimiento actual. */
  padecimiento_actual: string
  /** Exploración física. */
  exploracion_fisica: string
  /** Diagnóstico y manejo. */
  diagnostico_manejo: string
  /** Indicaciones para el paciente. */
  indicaciones: string
}

/**
 * Encabezado NO editable del resumen (datos de la clínica, del paciente y los
 * signos vitales de la visita). Refleja `encabezado` del endpoint de borrador.
 * Los numéricos pueden venir null; los signos como string ya formateado o null.
 */
export interface ResumenEncabezado {
  clinic_name: string
  patient_name: string
  edad: number | null
  /** 'M' | 'F' | 'X' | '' (sin especificar). */
  sexo: 'M' | 'F' | 'X' | ''
  /** Fecha de la consulta (YYYY-MM-DD). */
  fecha: string
  peso_kg: string | null
  talla_m: string | null
  /** Tensión arterial (ej. "120/80"). */
  ta: string | null
  fc: number | null
  fr: number | null
  temp_c: string | null
}

/**
 * Borrador del resumen clínico (GET .../resumen/borrador/): encabezado NO
 * editable + las 6 secciones auto-rellenadas y editables.
 */
export interface ResumenBorrador {
  encabezado: ResumenEncabezado
  secciones: ResumenSecciones
}

/**
 * Constancia de resumen clínico guardada (respuesta del POST y de la lista).
 * El PDF se genera aparte por el flujo async (endpoint /pdf/).
 */
export interface ResumenClinico {
  id: string
  created_at: string
  doctor_name: string
  evolution_id: string
}
