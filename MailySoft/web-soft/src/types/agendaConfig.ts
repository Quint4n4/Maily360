/** Tipos de la configuración de agenda de la clínica (refleja TenantAgendaConfig). */

/** Intervalos permitidos de la rejilla (minutos). Debe coincidir con los choices del backend. */
export const INTERVALOS_REJILLA = [5, 10, 15, 20, 30, 60] as const
export type IntervaloRejilla = (typeof INTERVALOS_REJILLA)[number]

export interface AgendaConfig {
  /** Hora a la que ABRE la agenda (0–23). */
  agenda_start_hour: number
  /** Hora a la que CIERRA (1–24, exclusiva: 18 = la última franja termina a las 18:00). */
  agenda_end_hour: number
  /** Cada cuántos minutos hay una línea en la rejilla. */
  slot_interval_minutes: number
  /** Duración de consulta por defecto de la clínica (el médico puede tener la suya). */
  default_appointment_duration: number
  record_number_format: string
  record_number_reset_yearly: boolean
  reminder_offsets_minutes: number[]
  reminders_enabled: boolean
}

/** Solo lo que edita el dueño/admin desde Mi Consultorio (todo opcional en PATCH). */
export interface AgendaConfigUpdateInput {
  agenda_start_hour?: number
  agenda_end_hour?: number
  slot_interval_minutes?: number
  default_appointment_duration?: number
}
