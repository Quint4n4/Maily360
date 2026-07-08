/**
 * Tipos del dominio "Calendarización de tratamientos" (Fase 1).
 *
 * Reflejan EXACTO el contrato del backend (apps/expediente — calendarizaciones):
 *   - Los montos (unit_price, total) viajan como STRING decimal desde/hacia DRF;
 *     se convierten a number SOLO para calcular en la UI (nunca se re-serializan
 *     con pérdida de precisión).
 *   - Las fechas (scheduled_date, applied_date) son 'yyyy-mm-dd' o null.
 *
 * Endpoints (prefijo /api/v1/):
 *   GET    /expediente/<patient_id>/calendarizaciones/         → Paginated<CalendarizacionResumen>
 *   POST   /expediente/<patient_id>/calendarizaciones/         → Calendarizacion (201)
 *   GET    /expediente/calendarizaciones/<plan_id>/            → Calendarizacion
 *   PUT    /expediente/calendarizaciones/<plan_id>/            → Calendarizacion (reemplaza contenido)
 *   DELETE /expediente/calendarizaciones/<plan_id>/            → 204
 *   GET    /expediente/calendarizaciones/<plan_id>/pdf/        → encola PDF (pdfJobBlob)
 */

/** Estado del plan de tratamiento. */
export type PlanStatus = 'borrador' | 'activa' | 'completada'

/** Estado de una sesión individual. */
export type SessionStatus = 'programada' | 'aplicada'

/** Fila de la lista (resumen liviano de cada calendarización del paciente). */
export interface CalendarizacionResumen {
  id: string
  title: string
  status: PlanStatus
  status_display: string
  created_at: string
  doctor_name: string | null
  /** Total del plan como string decimal (ej. "1500.00"). */
  total: string
  sessions_count: number
  applied_count: number
}

/**
 * Cita real (de la agenda) vinculada a una sesión, o null si la sesión aún no se
 * ha agendado. Espejo del bloque `appointment` embebido en cada sesión del detalle.
 */
export interface SessionAppointment {
  id: string
  /** Inicio/fin de la cita en UTC ISO. */
  starts_at: string
  ends_at: string
  status: string
  doctor_id: string
  doctor_name: string
  consultorio_id: string | null
  consultorio_name: string | null
}

/** Una sesión de un tratamiento (detalle). */
export interface TreatmentSession {
  /** Id de la sesión persistida (necesario para agendar / conservar la cita en el PUT). */
  id: string
  number: number
  scheduled_date: string | null
  /** Hora programada "HH:MM[:SS]" o null. */
  scheduled_time: string | null
  /** Duración en minutos de la cita, o null si aún no se define. */
  duration_minutes: number | null
  applied_date: string | null
  status: SessionStatus
  /** Cita real en la agenda, o null si no se ha agendado. */
  appointment: SessionAppointment | null
}

/** Un tratamiento (renglón) del plan, con sus N sesiones (detalle). */
export interface TreatmentItem {
  /** Id del renglón persistido (se reenvía en el PUT para conservar sesiones/citas). */
  id: string
  /** Concepto del catálogo de servicios, o null si es un tratamiento manual. */
  concept_id: string | null
  description: string
  /** Precio unitario como string decimal. */
  unit_price: string
  quantity: number
  order: number
  sessions: TreatmentSession[]
}

/** Detalle completo de una calendarización. */
export interface Calendarizacion {
  id: string
  patient_id: string
  title: string
  notes: string
  status: PlanStatus
  doctor_name: string | null
  /** Médico por defecto del plan (para agendar sus sesiones), o null. */
  doctor_id: string | null
  /** Consultorio por defecto del plan, o null. */
  consultorio_id: string | null
  consultorio_name: string | null
  created_at: string
  /** Total del plan como string decimal. */
  total: string
  /**
   * Id de la cotización (borrador) generada desde este plan, o null si aún no se
   * ha generado ninguna (Fase 2). Al generarla, el detalle vuelve con este campo.
   */
  quote_id: string | null
  items: TreatmentItem[]
}

/**
 * Resultado del POST que genera una cotización (borrador) desde una calendarización
 * (Fase 2). `total` viaja como string decimal (mismo criterio que el resto de montos).
 */
export interface GenerarCotizacionResult {
  quote_id: string
  status: string
  total: string
}

/** Cuerpo del POST para crear una calendarización desde un paquete (Fase 3c). */
export interface CalendarizacionDesdePaqueteInput {
  package_id: string
}

/* ── Inputs (cuerpos de POST / PUT) ─────────────────────────────────────────── */

/** Sesión en el cuerpo del PUT. */
export interface TreatmentSessionInput {
  /** Id de la sesión ya existente (MANDARLO para conservar su cita y estado aplicado). */
  id?: string
  number: number
  scheduled_date?: string | null
  /** Hora programada "HH:MM" o null. */
  scheduled_time?: string | null
  /** Duración en minutos, o null. */
  duration_minutes?: number | null
  applied_date?: string | null
  status: SessionStatus
}

/** Tratamiento en el cuerpo del PUT. */
export interface TreatmentItemInput {
  /** Id del renglón ya existente (MANDARLO para conservar sus sesiones agendadas). */
  id?: string
  concept_id?: string | null
  description: string
  /** Precio unitario como string decimal. */
  unit_price: string
  quantity: number
  sessions: TreatmentSessionInput[]
}

/** Cuerpo del POST (crear): todo opcional; el backend crea un plan vacío. */
export interface CalendarizacionCreateInput {
  title?: string
  notes?: string
  status?: PlanStatus
  items?: TreatmentItemInput[]
}

/**
 * Cuerpo del PUT (guardar): reemplaza el contenido completo. Se envía SIEMPRE el
 * estado completo (todos los tratamientos con sus fechas y estados).
 */
export interface CalendarizacionUpdateInput {
  title: string
  notes: string
  status: PlanStatus
  /** Médico por defecto del plan (para agendar), o null. */
  doctor_id?: string | null
  /** Consultorio por defecto del plan, o null. */
  consultorio_id?: string | null
  items: TreatmentItemInput[]
}

/**
 * Cuerpo del POST de agendar una sesión
 * (`/expediente/calendarizaciones/sesiones/<id>/agendar/`). El backend crea/actualiza
 * la cita real; un empalme responde 400 `{ detail }`.
 */
export interface AgendarSesionInput {
  scheduled_date: string // 'yyyy-mm-dd'
  scheduled_time: string // 'HH:MM'
  starts_at: string // UTC ISO
  ends_at: string // UTC ISO
  duration_minutes: number
  doctor_id: string
  consultorio_id: string | null
}
