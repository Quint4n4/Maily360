/** api/personal — doctores y consultorios (catálogos + CRUD). */

import { request } from '../lib/http'
import type { Paginated } from '../types/paciente'
import type {
  Consultorio,
  ConsultorioCreateInput,
  ConsultorioUpdateInput,
  Doctor,
  DoctorCreateInput,
  DoctorUpdateInput,
} from '../types/personal'

// ── Doctores ───────────────────────────────────────────────────────────────

/** GET /personal/doctores/ — lista de doctores del tenant. */
export async function listDoctors(onlyActive = true): Promise<Paginated<Doctor>> {
  const qs = onlyActive ? '' : '?only_active=false'
  return request<Paginated<Doctor>>(`/personal/doctores/${qs}`)
}

/** POST /personal/doctores/ — crea el perfil médico para una membresía con rol doctor. */
export async function createDoctor(input: DoctorCreateInput): Promise<Doctor> {
  return request<Doctor>('/personal/doctores/', { method: 'POST', body: input })
}

/** PATCH /personal/doctores/<id>/ — actualiza datos del doctor. */
export async function updateDoctor(id: string, input: DoctorUpdateInput): Promise<Doctor> {
  return request<Doctor>(`/personal/doctores/${id}/`, { method: 'PATCH', body: input })
}

/** DELETE /personal/doctores/<id>/ — desactiva (soft) al doctor. */
export async function deactivateDoctor(id: string): Promise<void> {
  await request<void>(`/personal/doctores/${id}/`, { method: 'DELETE' })
}

// ── Consultorios ─────────────────────────────────────────────────────────────

/** GET /personal/consultorios/ — lista de consultorios (todos si onlyActive=false). */
export async function listConsultorios(onlyActive = true): Promise<Paginated<Consultorio>> {
  const qs = onlyActive ? '' : '?only_active=false'
  return request<Paginated<Consultorio>>(`/personal/consultorios/${qs}`)
}

/** POST /personal/consultorios/ — crea un consultorio. */
export async function createConsultorio(input: ConsultorioCreateInput): Promise<Consultorio> {
  return request<Consultorio>('/personal/consultorios/', { method: 'POST', body: input })
}

/** PATCH /personal/consultorios/<id>/ — actualización parcial. */
export async function updateConsultorio(id: string, input: ConsultorioUpdateInput): Promise<Consultorio> {
  return request<Consultorio>(`/personal/consultorios/${id}/`, { method: 'PATCH', body: input })
}

/** DELETE /personal/consultorios/<id>/ — desactiva (soft). */
export async function deactivateConsultorio(id: string): Promise<void> {
  await request<void>(`/personal/consultorios/${id}/`, { method: 'DELETE' })
}
