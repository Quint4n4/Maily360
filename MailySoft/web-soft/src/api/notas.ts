/** api/notas — Notas y Tareas. Todo pasa por el cliente http central. */

import { request } from '../lib/http'
import type { Paginated } from '../types/paciente'
import type { Note, NoteCreateInput, NoteUpdateInput } from '../types/nota'

/** GET /notas/ — notas visibles para mí (personales + globales dirigidas a mí). */
export async function listNotes(params: { is_task?: boolean; done?: boolean } = {}): Promise<Paginated<Note>> {
  const qs = new URLSearchParams()
  if (params.is_task !== undefined) qs.set('is_task', String(params.is_task))
  if (params.done !== undefined) qs.set('done', String(params.done))
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request<Paginated<Note>>(`/notas/${suffix}`)
}

/** POST /notas/ — crea una nota (personal: cualquiera; global: solo Dueño). */
export async function createNote(input: NoteCreateInput): Promise<Note> {
  return request<Note>('/notas/', { method: 'POST', body: input })
}

/** PATCH /notas/<id>/ — edita una nota (autor / Dueño para globales). */
export async function updateNote(id: string, input: NoteUpdateInput): Promise<Note> {
  return request<Note>(`/notas/${id}/`, { method: 'PATCH', body: input })
}

/** DELETE /notas/<id>/ — elimina (soft) una nota. */
export async function deleteNote(id: string): Promise<void> {
  await request<void>(`/notas/${id}/`, { method: 'DELETE' })
}

/** POST /notas/<id>/done/ — alterna hecho/pendiente (tareas). */
export async function toggleNoteDone(id: string): Promise<Note> {
  return request<Note>(`/notas/${id}/done/`, { method: 'POST' })
}

/** GET /notas/recordatorios/ — mis notas con recordatorio en un rango. */
export async function listReminders(params: { date_from?: string; date_to?: string } = {}): Promise<Paginated<Note>> {
  const qs = new URLSearchParams()
  if (params.date_from) qs.set('date_from', params.date_from)
  if (params.date_to) qs.set('date_to', params.date_to)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request<Paginated<Note>>(`/notas/recordatorios/${suffix}`)
}
