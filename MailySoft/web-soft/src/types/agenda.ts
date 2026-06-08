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

export interface ConsultorioRef {
  id: string
  name: string
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
  starts_at: string // ISO UTC
  ends_at?: string | null
  reason: string
  specialty?: string
  notes?: string
}
