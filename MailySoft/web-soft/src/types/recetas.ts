/**
 * Tipos del dominio Recetas — reflejan EXACTAMENTE el backend
 * (apps/recetas/serializers.py y apps/recetas/models.py).
 *
 * Sub-fases:
 *   B1.1 — Catálogo de medicamentos (global + custom) y autocompletado.
 *   B1.2 — Receta médica inmutable (historial, detalle, alta, anulación).
 *   B1.3 — PDF de la receta (descarga vía blob con Bearer).
 *
 * Regla: nada de `any`. Los choices son whitelists del backend.
 */

// ───────────────────────────────────────────────────────────────────────────
// B1.1 — Catálogo de medicamentos
// ───────────────────────────────────────────────────────────────────────────

/** Forma farmacéutica (models.MedicationForm.choices). */
export type MedicationFormValue =
  | 'tableta'
  | 'capsula'
  | 'jarabe'
  | 'suspension'
  | 'solucion'
  | 'solucion_inyectable'
  | 'crema'
  | 'unguento'
  | 'gel'
  | 'gotas'
  | 'ovulo'
  | 'supositorio'
  | 'parche'
  | 'aerosol'
  | 'polvo'
  | 'otro'

/** Origen del medicamento en el autocompletado. */
export type MedicationSource = 'global' | 'custom'

/**
 * Tipo de ítem de tratamiento (models.ItemKind.choices) — COFEPRIS F2.
 * Para `medicamento` el renglón estructurado (dose/frequency/route/duration) es
 * obligatorio; para `suero`/`terapia` esos campos son opcionales.
 */
export type ItemKind = 'medicamento' | 'suero' | 'terapia'

/** Grupo de medicamento controlado (models.ControlledGroup.choices). */
export type ControlledGroup = 'none' | 'I' | 'II' | 'III' | 'IV' | 'V'

/** Etiqueta legible del grupo controlado (para el aviso de receta especial). */
export function controlledGroupLabel(group: ControlledGroup): string {
  return group === 'none' ? '' : `Grupo ${group}`
}

/**
 * Vía de administración (models.RouteOfAdministration.choices) — COFEPRIS F2.
 * Cadena vacía = "no especificada" (permitida para suero/terapia).
 */
export type RouteOfAdministration =
  | 'oral'
  | 'sublingual'
  | 'intravenosa'
  | 'intramuscular'
  | 'subcutanea'
  | 'topica'
  | 'oftalmica'
  | 'otica'
  | 'nasal'
  | 'rectal'
  | 'vaginal'
  | 'inhalada'
  | 'transdermica'
  | 'otra'

/**
 * Ítem del autocompletado de medicamentos
 * (MedicationSearchOutputSerializer). `id` es CharField (puede ser UUID o id
 * sintético del catálogo global), por eso string.
 * COFEPRIS F2: incluye `kind` y `controlled_group`.
 */
export interface MedicationSearchResult {
  id: string
  generic_name: string
  commercial_name: string
  form: string
  concentration: string
  presentation: string
  source: MedicationSource
  kind: ItemKind
  controlled_group: ControlledGroup
}

/** Cuerpo para crear un medicamento custom (MedicationCreateInputSerializer). */
export interface MedicationCreateInput {
  generic_name: string
  form: MedicationFormValue
  commercial_name?: string
  concentration?: string
  presentation?: string
  /** Tipo de ítem (COFEPRIS F2). Default backend: 'medicamento'. */
  kind?: ItemKind
}

/** Salida de un medicamento custom recién creado (MedicationCreateOutputSerializer). */
export interface MedicationCreated {
  id: string
  generic_name: string
  commercial_name: string
  form: string
  concentration: string
  presentation: string
  kind: ItemKind
  controlled_group: ControlledGroup
  is_active: boolean
  created_at: string
}

// ───────────────────────────────────────────────────────────────────────────
// B1.2 — Receta médica
// ───────────────────────────────────────────────────────────────────────────

/** Estado de la receta (models.PrescriptionStatus). */
export type PrescriptionStatus = 'active' | 'cancelled'

/** Datos mínimos del médico en una receta (_DoctorBriefSerializer). */
export interface PrescriptionDoctor {
  id: string
  full_name: string
  cedula_profesional: string
  specialty: string
}

/** Renglón de tratamiento en salida (PrescriptionItemOutputSerializer). */
export interface PrescriptionItem {
  id: string
  order: number
  /** Tipo de ítem (COFEPRIS F2). */
  kind: ItemKind
  medication_name: string
  medication_presentation: string
  medication_form: string
  medication_concentration: string
  /** Renglón estructurado COFEPRIS F2 (cadena vacía si no aplica). */
  dose: string
  frequency: string
  route: RouteOfAdministration | ''
  duration: string
  /** Nota/observación adicional (opcional; antes era la indicación completa). */
  indication: string
  quantity: string
  global_medication_id: string | null
  medication_id: string | null
}

/**
 * Receta en el historial (PrescriptionListOutputSerializer). Sin items completos
 * ni snapshot — respuesta liviana del listado paginado.
 */
export interface PrescriptionListItem {
  id: string
  folio: number
  issued_at: string
  status: PrescriptionStatus
  /** Diagnóstico del paciente (COFEPRIS F2; cadena vacía si no se capturó). */
  diagnosis: string
  recommendations: string
  doctor: PrescriptionDoctor
  items_count: number
  cancelled_at: string | null
  cancellation_reason: string
}

/**
 * Snapshot de signos vitales congelado al crear la receta (DR-7). Es un JSON
 * libre del backend; todos los campos son opcionales y pueden venir nulos.
 */
export interface PrescriptionVitalsSnapshot {
  weight_kg?: number | string | null
  height_m?: number | string | null
  imc?: number | string | null
  heart_rate?: number | null
  resp_rate?: number | null
  systolic?: number | null
  diastolic?: number | null
  temperature_c?: number | string | null
  oxygen_saturation?: number | null
  glucose?: number | null
  measured_at?: string | null
}

/**
 * Detalle completo de una receta (PrescriptionDetailOutputSerializer).
 * Se usa para "copiar de previa": GET detalle → prellenar el formulario nuevo.
 */
export interface PrescriptionDetail {
  id: string
  folio: number
  issued_at: string
  status: PrescriptionStatus
  /** Diagnóstico del paciente (COFEPRIS F2; cadena vacía si no se capturó). */
  diagnosis: string
  recommendations: string
  vitals_snapshot: PrescriptionVitalsSnapshot | null
  doctor: PrescriptionDoctor
  patient_id: string
  appointment_id: string | null
  evolution_note_id: string | null
  items: PrescriptionItem[]
  cancelled_at: string | null
  cancelled_by_id: string | null
  cancellation_reason: string
  created_at: string
}

/**
 * Renglón de tratamiento al crear (PrescriptionItemInputSerializer).
 * COFEPRIS F2: cuando `kind === 'medicamento'`, dose/frequency/route/duration son
 * obligatorios (el backend valida). `indication` ahora es una nota opcional.
 */
export interface PrescriptionItemInput {
  /** Tipo de ítem. Default backend: 'medicamento'. */
  kind?: ItemKind
  medication_name: string
  /** Renglón estructurado COFEPRIS F2. */
  dose?: string
  frequency?: string
  route?: RouteOfAdministration | ''
  duration?: string
  /** Nota/observación adicional (opcional). */
  indication?: string
  medication_presentation?: string
  medication_form?: string
  medication_concentration?: string
  quantity?: string
  /** Trazabilidad opcional al catálogo global (no obligatorio). */
  global_medication_id?: string | null
  /** Trazabilidad opcional al medicamento custom del tenant (no obligatorio). */
  medication_id?: string | null
}

/**
 * Signos vitales capturados por el médico al emitir la receta
 * (VitalsInPrescriptionSerializer). Todas las claves son opcionales y numéricas.
 * El backend valida rangos fisiológicos y rechaza (400) cualquier clave fuera de
 * estas 9. `measured_at` NO se envía: el backend lo genera al momento de emitir.
 * Si no se envía `vitals` (o todas las claves vacías), el backend cae a la última
 * toma de Enfermería. El IMC lo deriva el backend (peso / talla²); aquí no se envía.
 */
export interface PrescriptionVitalsInput {
  weight_kg?: number
  height_m?: number
  heart_rate?: number
  resp_rate?: number
  systolic?: number
  diastolic?: number
  temperature_c?: number
  oxygen_saturation?: number
  glucose?: number
}

/**
 * Cuerpo para crear una receta (PrescriptionCreateInputSerializer).
 * NO se envía doctor_id: el backend lo infiere del perfil activo del usuario.
 */
export interface PrescriptionCreateInput {
  items: PrescriptionItemInput[]
  /** Diagnóstico del paciente (recomendado, COFEPRIS F2). */
  diagnosis?: string
  recommendations?: string
  appointment_id?: string | null
  evolution_note_id?: string | null
  /**
   * Folio del recetario especial COFEPRIS (F6). REQUERIDO por el backend cuando
   * la receta contiene medicamentos controlados (grupo I–V); si falta, devuelve
   * 400. Para recetas sin controlados se omite.
   */
  controlled_folio?: string
  /**
   * Signos vitales capturados por el médico (opcional). Solo claves con valor; si
   * se omite por completo, el backend usa la última toma de Enfermería.
   */
  vitals?: PrescriptionVitalsInput
}

/** Cuerpo para anular una receta (PrescriptionCancelInputSerializer). */
export interface PrescriptionCancelInput {
  reason: string
}

// ───────────────────────────────────────────────────────────────────────────
// Catálogos para selects (whitelists del backend — etiquetas en español)
// ───────────────────────────────────────────────────────────────────────────

/** Opciones de tipo de ítem (ItemKind.choices). */
export const ITEM_KIND_OPTIONS: { value: ItemKind; label: string }[] = [
  { value: 'medicamento', label: 'Medicamento' },
  { value: 'suero', label: 'Suero / solución parenteral' },
  { value: 'terapia', label: 'Terapia / procedimiento' },
]

/** Opciones de vía de administración (RouteOfAdministration.choices). */
export const ROUTE_OPTIONS: { value: RouteOfAdministration; label: string }[] = [
  { value: 'oral', label: 'Oral' },
  { value: 'sublingual', label: 'Sublingual' },
  { value: 'intravenosa', label: 'Intravenosa' },
  { value: 'intramuscular', label: 'Intramuscular' },
  { value: 'subcutanea', label: 'Subcutánea' },
  { value: 'topica', label: 'Tópica' },
  { value: 'oftalmica', label: 'Oftálmica' },
  { value: 'otica', label: 'Ótica' },
  { value: 'nasal', label: 'Nasal' },
  { value: 'rectal', label: 'Rectal' },
  { value: 'vaginal', label: 'Vaginal' },
  { value: 'inhalada', label: 'Inhalada' },
  { value: 'transdermica', label: 'Transdérmica' },
  { value: 'otra', label: 'Otra' },
]

/** Etiqueta legible de una vía (o '—' si vacía / desconocida). */
export function routeLabel(route: string): string {
  if (!route) return '—'
  return ROUTE_OPTIONS.find((o) => o.value === route)?.label ?? route
}

// ───────────────────────────────────────────────────────────────────────────
// F3 — PrescriptionFormat (galería de formatos de receta)
// ───────────────────────────────────────────────────────────────────────────

/** Plantilla base del PDF (PrescriptionFormat.BaseLayout.choices). */
export type PrescriptionBaseLayout = 'standard' | 'compact' | 'digital'

/** Tipografía del PDF (PrescriptionFormat.FontChoice.choices). */
export type PrescriptionFont = 'helvetica' | 'times'

/** Modo de membrete (PrescriptionFormat.LetterheadMode.choices). */
export type LetterheadMode = 'digital' | 'preprinted'

/** Claves de secciones opcionales del formato (SECTIONS_KEYS del backend). */
export type FormatSectionKey =
  | 'signos'
  | 'diagnostico'
  | 'sueros'
  | 'terapias'
  | 'indicaciones'

/** Flags booleanos por sección (JSON `sections`). */
export type FormatSections = Partial<Record<FormatSectionKey, boolean>>

/** Salida de un PrescriptionFormat (PrescriptionFormatOutputSerializer). */
export interface PrescriptionFormatOut {
  id: string
  name: string
  base_layout: PrescriptionBaseLayout
  /** Color de acento en #RRGGBB. */
  accent_color: string
  font: PrescriptionFont
  sections: FormatSections
  letterhead_mode: LetterheadMode
  is_default: boolean
  is_authorized: boolean
  is_active: boolean
  doctor_id: string | null
  created_at: string
  updated_at: string
}

/** Cuerpo para crear un formato (PrescriptionFormatCreateInputSerializer). */
export interface PrescriptionFormatCreateInput {
  name: string
  base_layout?: PrescriptionBaseLayout
  accent_color?: string
  font?: PrescriptionFont
  sections?: FormatSections
  letterhead_mode?: LetterheadMode
  is_default?: boolean
  doctor_id?: string | null
}

/**
 * Cuerpo para actualizar un formato (PrescriptionFormatUpdateInputSerializer).
 * Todos los campos opcionales (PATCH parcial). `is_authorized` solo lo aplica
 * el backend si el usuario es admin; la UI no lo expone a no-admin.
 */
export interface PrescriptionFormatUpdateInput {
  name?: string
  base_layout?: PrescriptionBaseLayout
  accent_color?: string
  font?: PrescriptionFont
  sections?: FormatSections
  letterhead_mode?: LetterheadMode
  is_default?: boolean
  doctor_id?: string | null
  is_authorized?: boolean
}

/** Opciones de plantilla base con descripción (para el editor con mini-preview). */
export const BASE_LAYOUT_OPTIONS: {
  value: PrescriptionBaseLayout
  label: string
  description: string
}[] = [
  {
    value: 'standard',
    label: 'Estándar',
    description: 'Carta vertical. Formato clásico para imprimir en hoja completa.',
  },
  {
    value: 'compact',
    label: 'Compacta',
    description: 'Media carta horizontal. Ahorra papel; ideal para recetarios cortos.',
  },
  {
    value: 'digital',
    label: 'Digital',
    description: 'Pensada para el paciente: más legible en pantalla y para compartir.',
  },
]

/** Opciones de tipografía. */
export const FONT_OPTIONS: { value: PrescriptionFont; label: string }[] = [
  { value: 'helvetica', label: 'Helvetica / Arial (sans-serif)' },
  { value: 'times', label: 'Times New Roman (serif)' },
]

/** Opciones de modo de membrete. */
export const LETTERHEAD_MODE_OPTIONS: { value: LetterheadMode; label: string }[] = [
  { value: 'digital', label: 'Digital (el sistema imprime el encabezado)' },
  { value: 'preprinted', label: 'Pre-impreso (deja espacio superior en blanco)' },
]

/** Secciones configurables con su etiqueta (orden de presentación en el editor). */
export const SECTION_OPTIONS: { key: FormatSectionKey; label: string }[] = [
  { key: 'signos', label: 'Signos vitales' },
  { key: 'diagnostico', label: 'Diagnóstico' },
  { key: 'sueros', label: 'Sueros' },
  { key: 'terapias', label: 'Terapias' },
  { key: 'indicaciones', label: 'Indicaciones / recomendaciones' },
]
