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
  created_at: string
}

/** Cuerpo para crear una cita (POST). El estado inicial siempre es 'scheduled'. */
export interface CreateAppointmentInput {
  patient_id: string
  doctor_id: string
  consultorio_id?: string | null
  appointment_type_id?: string | null
  modality?: AppointmentModality
  starts_at: string // ISO UTC
  ends_at?: string | null
  reason?: string
  specialty?: string
  notes?: string
}
