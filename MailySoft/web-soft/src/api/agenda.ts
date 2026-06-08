/** api/agenda — citas. Todo pasa por el cliente http central. */

import { request } from '../lib/http'
import type { Paginated } from '../types/paciente'
import type { Appointment, AppointmentStatus, CreateAppointmentInput } from '../types/agenda'

export interface ListAppointmentsParams {
  date_from?: string // ISO UTC
  date_to?: string // ISO UTC
  doctor_id?: string
  consultorio_id?: string
  patient_id?: string
}

/** GET /agenda/citas/ — citas del tenant con filtros (rango de fechas, etc.). */
export async function listAppointments(params: ListAppointmentsParams = {}): Promise<Paginated<Appointment>> {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v) qs.set(k, v)
  }
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request<Paginated<Appointment>>(`/agenda/citas/${suffix}`)
}

/** POST /agenda/citas/ — crea una cita. */
export async function createAppointment(input: CreateAppointmentInput): Promise<Appointment> {
  return request<Appointment>('/agenda/citas/', { method: 'POST', body: input })
}

/** POST /agenda/citas/<id>/estado/ — cambia el estado (valida la transición en backend). */
export async function changeAppointmentStatus(
  id: string,
  status: AppointmentStatus,
  reason = '',
): Promise<Appointment> {
  return request<Appointment>(`/agenda/citas/${id}/estado/`, {
    method: 'POST',
    body: { status, reason },
  })
}
