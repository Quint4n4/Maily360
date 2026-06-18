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
 * Ítem del autocompletado de medicamentos
 * (MedicationSearchOutputSerializer). `id` es CharField (puede ser UUID o id
 * sintético del catálogo global), por eso string.
 */
export interface MedicationSearchResult {
  id: string
  generic_name: string
  commercial_name: string
  form: string
  concentration: string
  presentation: string
  source: MedicationSource
}

/** Cuerpo para crear un medicamento custom (MedicationCreateInputSerializer). */
export interface MedicationCreateInput {
  generic_name: string
  form: MedicationFormValue
  commercial_name?: string
  concentration?: string
  presentation?: string
}

/** Salida de un medicamento custom recién creado (MedicationCreateOutputSerializer). */
export interface MedicationCreated {
  id: string
  generic_name: string
  commercial_name: string
  form: string
  concentration: string
  presentation: string
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
  medication_name: string
  medication_presentation: string
  medication_form: string
  medication_concentration: string
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

/** Renglón de tratamiento al crear (PrescriptionItemInputSerializer). */
export interface PrescriptionItemInput {
  medication_name: string
  indication: string
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
 * Cuerpo para crear una receta (PrescriptionCreateInputSerializer).
 * NO se envía doctor_id: el backend lo infiere del perfil activo del usuario.
 */
export interface PrescriptionCreateInput {
  items: PrescriptionItemInput[]
  recommendations?: string
  appointment_id?: string | null
  evolution_note_id?: string | null
}

/** Cuerpo para anular una receta (PrescriptionCancelInputSerializer). */
export interface PrescriptionCancelInput {
  reason: string
}
