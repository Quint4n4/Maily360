/** Tipos del dominio Agenda (citas), reflejan apps/agenda/serializers.py. */

export type AppointmentStatus =
  | 'scheduled'
  | 'confirmed'
  | 'arrived'
  | 'in_progress'
  | 'attended'
  | 'cancelled'
  | 'no_show'

export interface AppointmentRef {
  id: string
  full_name: string
}

/** Modalidad de la cita (dónde/cómo se realiza). */
export type AppointmentModality = 'office' | 'phone' | 'video' | 'offsite'

export interface ConsultorioRef {
  id: string
  name: string
}

/** Referencia mínima del tipo de cita dentro de una cita. */
export interface AppointmentTypeRef {
  id: string
  name: string
  color_hex: string
}

/** Tipo de cita configurable (catálogo). */
export interface AppointmentType {
  id: string
  name: string
  color_hex: string
  is_active: boolean
  created_at: string
}

export interface AppointmentTypeCreateInput {
  name: string
  color_hex?: string
}

export type AppointmentTypeUpdateInput = Partial<AppointmentTypeCreateInput>

// ── Eventos de agenda (reuniones / bloqueos) ────────────────────────────────

export type AgendaBlockKind = 'meeting' | 'block'

export interface AgendaBlock {
  id: string
  kind: AgendaBlockKind
  kind_display: string
  title: string
  doctor: AppointmentRef | null
  consultorio: ConsultorioRef | null
  starts_at: string // ISO UTC
  ends_at: string // ISO UTC
  all_day: boolean
  notes: string
  created_at: string
}

export interface AgendaBlockCreateInput {
  kind: AgendaBlockKind
  title?: string
  doctor_id?: string | null
  consultorio_id?: string | null
  starts_at: string
  ends_at: string
  all_day?: boolean
  notes?: string
}

export interface AgendaBlockUpdateInput {
  title?: string
  starts_at?: string
  ends_at?: string
  all_day?: boolean
  notes?: string
}

export interface AgendaItemNoteAuthor {
  id: string
  full_name: string
  avatar: string | null
}

/** Nota colaborativa (hilo) pegada a una cita o evento. */
export interface AgendaItemNote {
  id: string
  author: AgendaItemNoteAuthor
  body: string
  created_at: string
}

export interface AppointmentReminder {
  id: string
  channel: string
  channel_display: string
  scheduled_at: string
  sent_at: string | null
  status: string
  status_display: string
}

/**
 * Cotización vinculada a la cita (resumen). El serializer de la cita devuelve este
 * objeto o `null`. `status` es el QuoteStatus del backend; `status_display` ya viene
 * traducido. El `total` puede llegar como string decimal o number desde DRF.
 */
export interface AppointmentQuoteRef {
  id: string
  total: number | string
  status: string
  status_display: string
}

export interface Appointment {
  id: string
  patient: AppointmentRef
  doctor: AppointmentRef
  consultorio: ConsultorioRef | null
  appointment_type: AppointmentTypeRef | null
  modality: AppointmentModality
  modality_display: string
  starts_at: string // ISO UTC
  ends_at: string // ISO UTC
  status: AppointmentStatus
  status_display: string
  reason: string
  specialty: string
  notes: string
  reminders: AppointmentReminder[]
  /** Cotización vinculada (aceptada) o null si la cita no tiene cotización. */
  quote: AppointmentQuoteRef | null
  created_at: string
}

/** Cuerpo para crear una cita (POST). El estado inicial siempre es 'scheduled'. */
/** Paciente nuevo (provisional) creado junto con la cita, en una sola transacción. */
export interface NewPatientInline {
  first_name: string
  paternal_surname: string
  maternal_surname?: string
  phone?: string
}

export interface CreateAppointmentInput {
  /** Paciente existente (uno de patient_id o new_patient, no ambos). */
  patient_id?: string
  /** Paciente nuevo provisional (se crea atómicamente con la cita). */
  new_patient?: NewPatientInline
  doctor_id: string
  consultorio_id?: string | null
  appointment_type_id?: string | null
  modality?: AppointmentModality
  starts_at: string // ISO UTC
  ends_at?: string | null
  reason?: string
  specialty?: string
  notes?: string
  /** Cotización ACEPTADA a vincular (opcional). El backend valida mismo paciente + estado accepted. */
  quote_id?: string | null
}

/** Frecuencia de una serie de citas recurrentes. */
export type SeriesFrequency = 'weekly' | 'biweekly' | 'monthly' | 'custom'

/** Crear una SERIE de citas (multi-cita). ends_at es obligatorio (deriva la duración).
 *  Dos modos: regla (frequency + count|until) o lista explícita (explicit_starts). */
export interface CreateAppointmentSeriesInput extends Omit<CreateAppointmentInput, 'ends_at'> {
  ends_at: string // ISO UTC
  frequency?: SeriesFrequency // modo regla
  count?: number | null // tope por número de citas (XOR until)
  until?: string | null // tope por fecha 'yyyy-mm-dd' (XOR count)
  explicit_starts?: string[] // modo lista explícita: fechas+horas ISO UTC
}

export interface AppointmentSeriesSkipped {
  starts_at: string // ISO UTC de la cita que NO se pudo crear
  error: string
}

export interface AppointmentSeriesResult {
  series_id: string
  created_count: number
  created: Appointment[]
  skipped_count: number
  skipped: AppointmentSeriesSkipped[]
}

/** Un intervalo ocupado (cita activa o bloqueo) — para pintar disponibilidad. */
export interface BusyInterval {
  start: string // ISO UTC
  end: string // ISO UTC
}

export interface AgendaDisponibilidad {
  busy: BusyInterval[]
}
