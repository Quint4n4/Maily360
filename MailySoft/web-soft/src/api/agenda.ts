/** api/agenda — citas. Todo pasa por el cliente http central. */

import { request } from '../lib/http'
import type { Paginated } from '../types/paciente'
import type {
  AgendaBlock,
  AgendaBlockCreateInput,
  AgendaBlockUpdateInput,
  AgendaItemNote,
  Appointment,
  AppointmentStatus,
  AppointmentType,
  AppointmentTypeCreateInput,
  AppointmentTypeUpdateInput,
  CreateAppointmentInput,
} from '../types/agenda'

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

// ── Tipos de cita (catálogo configurable) ──────────────────────────────────

/** GET /agenda/tipos-cita/ — lista de tipos (todos si onlyActive=false). */
export async function listAppointmentTypes(onlyActive = true): Promise<AppointmentType[]> {
  const qs = onlyActive ? '' : '?only_active=false'
  return request<AppointmentType[]>(`/agenda/tipos-cita/${qs}`)
}

/** POST /agenda/tipos-cita/ — crea un tipo de cita. */
export async function createAppointmentType(input: AppointmentTypeCreateInput): Promise<AppointmentType> {
  return request<AppointmentType>('/agenda/tipos-cita/', { method: 'POST', body: input })
}

/** PATCH /agenda/tipos-cita/<id>/ — actualiza nombre/color. */
export async function updateAppointmentType(id: string, input: AppointmentTypeUpdateInput): Promise<AppointmentType> {
  return request<AppointmentType>(`/agenda/tipos-cita/${id}/`, { method: 'PATCH', body: input })
}

/** DELETE /agenda/tipos-cita/<id>/ — desactiva (soft). */
export async function deactivateAppointmentType(id: string): Promise<void> {
  await request<void>(`/agenda/tipos-cita/${id}/`, { method: 'DELETE' })
}

// ── Eventos de agenda (reuniones / bloqueos) ────────────────────────────────

/** GET /agenda/eventos/ — eventos que solapan el rango dado. */
export async function listAgendaBlocks(params: { date_from?: string; date_to?: string } = {}): Promise<AgendaBlock[]> {
  const qs = new URLSearchParams()
  if (params.date_from) qs.set('date_from', params.date_from)
  if (params.date_to) qs.set('date_to', params.date_to)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request<AgendaBlock[]>(`/agenda/eventos/${suffix}`)
}

/** POST /agenda/eventos/ — crea una reunión o bloqueo. */
export async function createAgendaBlock(input: AgendaBlockCreateInput): Promise<AgendaBlock> {
  return request<AgendaBlock>('/agenda/eventos/', { method: 'POST', body: input })
}

/** PATCH /agenda/eventos/<id>/ — edita un evento (título, fecha/hora, notas). */
export async function updateAgendaBlock(id: string, input: AgendaBlockUpdateInput): Promise<AgendaBlock> {
  return request<AgendaBlock>(`/agenda/eventos/${id}/`, { method: 'PATCH', body: input })
}

/** DELETE /agenda/eventos/<id>/ — elimina un evento. */
export async function deleteAgendaBlock(id: string): Promise<void> {
  await request<void>(`/agenda/eventos/${id}/`, { method: 'DELETE' })
}

// ── Notas colaborativas (hilo en cita / evento) ─────────────────────────────

export async function listAppointmentNotes(apptId: string): Promise<AgendaItemNote[]> {
  return request<AgendaItemNote[]>(`/agenda/citas/${apptId}/notas/`)
}
export async function addAppointmentNote(apptId: string, body: string): Promise<AgendaItemNote> {
  return request<AgendaItemNote>(`/agenda/citas/${apptId}/notas/`, { method: 'POST', body: { body } })
}
export async function listBlockNotes(blockId: string): Promise<AgendaItemNote[]> {
  return request<AgendaItemNote[]>(`/agenda/eventos/${blockId}/notas/`)
}
export async function addBlockNote(blockId: string, body: string): Promise<AgendaItemNote> {
  return request<AgendaItemNote>(`/agenda/eventos/${blockId}/notas/`, { method: 'POST', body: { body } })
}
export async function deleteAgendaNote(noteId: string): Promise<void> {
  await request<void>(`/agenda/notas/${noteId}/`, { method: 'DELETE' })
}

/** POST /agenda/citas/<id>/reagendar/ — cambia día/horario (reactiva si estaba cancelada). */
export async function rescheduleAppointment(
  id: string,
  input: { starts_at: string; ends_at?: string | null; consultorio_id?: string | null },
): Promise<Appointment> {
  return request<Appointment>(`/agenda/citas/${id}/reagendar/`, { method: 'POST', body: input })
}

/** POST /agenda/citas/<id>/reactivar/ — reactiva una cita cancelada (mismo horario). */
export async function reactivateAppointment(id: string): Promise<Appointment> {
  return request<Appointment>(`/agenda/citas/${id}/reactivar/`, { method: 'POST' })
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
