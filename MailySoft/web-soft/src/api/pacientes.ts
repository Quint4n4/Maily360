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
  PatientClassifyInput,
  PatientCreateInput,
  PatientOut,
  PatientQuickCreateInput,
  PatientSegment,
  PatientUpdateInput,
} from '../types/paciente'

export interface ListPatientsParams {
  search?: string
  page?: number
  /** Segmento de filtrado (recientes, semana, mes, rango, potenciales, favoritos, vip). */
  segment?: PatientSegment
  /** Solo con segment='date': inicio del rango 'yyyy-mm-dd'. */
  date_from?: string
  /** Solo con segment='date': fin del rango 'yyyy-mm-dd' (inclusive). */
  date_to?: string
  /** UUID de una etiqueta del catálogo para filtrar por ella. */
  category?: string
}

/**
 * Vista mínima de paciente para los selectores del módulo finanzas
 * (PatientPicker, estado de cuenta, cobros, CFDI). La gestión completa
 * vive en el módulo Contactos vía PatientOut.
 */
export interface PatientLite {
  id: string
  full_name: string
  record_number: string
  phone: string
}

/** GET /pacientes/?search= — búsqueda ligera para los selectores de finanzas. */
export async function searchPatients(search: string): Promise<Paginated<PatientLite>> {
  const suffix = search ? `?${new URLSearchParams({ search }).toString()}` : ''
  return request<Paginated<PatientLite>>(`/pacientes/${suffix}`)
}

/** GET /pacientes/ — lista paginada de pacientes activos del tenant. */
export async function listPatients(params: ListPatientsParams = {}): Promise<Paginated<PatientOut>> {
  const qs = new URLSearchParams()
  if (params.search) qs.set('search', params.search)
  if (params.page) qs.set('page', String(params.page))
  if (params.segment && params.segment !== 'all') qs.set('segment', params.segment)
  if (params.date_from) qs.set('date_from', params.date_from)
  if (params.date_to) qs.set('date_to', params.date_to)
  if (params.category) qs.set('category', params.category)
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

/** POST /pacientes/<id>/clasificacion/ — marca/desmarca favorito y/o VIP. */
export async function setPatientClassification(
  id: string,
  input: PatientClassifyInput,
): Promise<PatientOut> {
  return request<PatientOut>(`/pacientes/${id}/clasificacion/`, { method: 'POST', body: input })
}
