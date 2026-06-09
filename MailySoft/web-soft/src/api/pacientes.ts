/**
 * api/pacientes — CRUD de pacientes contra el backend real.
 * Todo pasa por el cliente http central (Bearer + CSRF + refresh automático).
 *
 * Endpoints (apps/pacientes/urls.py):
 *   GET    /pacientes/?search=&page=   → lista paginada (solo activos)
 *   POST   /pacientes/                 → alta (201)
 *   GET    /pacientes/<id>/            → detalle
 *   PATCH  /pacientes/<id>/            → actualización parcial
 *   DELETE /pacientes/<id>/            → baja lógica (204)
 */

import { request } from '../lib/http'
import type {
  Paginated,
  PatientCreateInput,
  PatientOut,
  PatientQuickCreateInput,
  PatientUpdateInput,
} from '../types/paciente'

export interface ListPatientsParams {
  search?: string
  page?: number
}

/** GET /pacientes/ — lista paginada de pacientes activos del tenant. */
export async function listPatients(params: ListPatientsParams = {}): Promise<Paginated<PatientOut>> {
  const qs = new URLSearchParams()
  if (params.search) qs.set('search', params.search)
  if (params.page) qs.set('page', String(params.page))
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request<Paginated<PatientOut>>(`/pacientes/${suffix}`)
}

/** GET /pacientes/<id>/ — detalle de un paciente. */
export async function getPatient(id: string): Promise<PatientOut> {
  return request<PatientOut>(`/pacientes/${id}/`)
}

/** POST /pacientes/ — crea un paciente. El número de expediente lo asigna el backend. */
export async function createPatient(input: PatientCreateInput): Promise<PatientOut> {
  return request<PatientOut>('/pacientes/', { method: 'POST', body: input })
}

/** POST /pacientes/rapido/ — alta provisional con datos mínimos (desde la agenda). */
export async function createPatientQuick(input: PatientQuickCreateInput): Promise<PatientOut> {
  return request<PatientOut>('/pacientes/rapido/', { method: 'POST', body: input })
}

/** PATCH /pacientes/<id>/ — actualización parcial. */
export async function updatePatient(id: string, input: PatientUpdateInput): Promise<PatientOut> {
  return request<PatientOut>(`/pacientes/${id}/`, { method: 'PATCH', body: input })
}

/** DELETE /pacientes/<id>/ — baja lógica (no borra de la BD). */
export async function deactivatePatient(id: string): Promise<void> {
  await request<void>(`/pacientes/${id}/`, { method: 'DELETE' })
}

/** POST /pacientes/<id>/avatar/ — sube/reemplaza la foto del paciente (multipart). */
export async function uploadPatientAvatar(id: string, file: File): Promise<PatientOut> {
  const fd = new FormData()
  fd.append('avatar', file)
  return request<PatientOut>(`/pacientes/${id}/avatar/`, { method: 'POST', body: fd })
}
