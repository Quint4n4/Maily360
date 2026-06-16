/**
 * api/plataforma — panel interno de Maily (cross-tenant).
 * Solo accesible para usuarios con is_platform_staff=true; el backend valida el rol.
 *
 * Endpoints (apps/plataforma/urls.py):
 *   GET  /plataforma/metricas/                  → métricas del dashboard
 *   GET  /plataforma/clinicas/?search=&status=  → lista paginada de clínicas
 *   POST /plataforma/clinicas/<id>/estado/      → suspender / reactivar
 *   GET  /plataforma/usuarios/?search=          → equipo interno de Maily
 */

import { request } from '../lib/http'
import type { Paginated } from '../types/paciente'
import type {
  ClinicaCreateInput,
  ClinicaCreateResult,
  ClinicaDetail,
  ClinicaPlat,
  DashboardMetrics,
  EstadoClinica,
  PlatformStaff,
} from '../types/plataforma'

/** GET /plataforma/metricas/ — conteos globales para el dashboard. */
export async function getPlatformMetrics(): Promise<DashboardMetrics> {
  return request<DashboardMetrics>('/plataforma/metricas/')
}

export interface ListClinicasParams {
  search?: string
  status?: EstadoClinica
}

/** GET /plataforma/clinicas/ — todas las clínicas con conteos. */
export async function listPlatformClinicas(params: ListClinicasParams = {}): Promise<Paginated<ClinicaPlat>> {
  const qs = new URLSearchParams()
  if (params.search) qs.set('search', params.search)
  if (params.status) qs.set('status', params.status)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request<Paginated<ClinicaPlat>>(`/plataforma/clinicas/${suffix}`)
}

/** POST /plataforma/clinicas/<id>/estado/ — cambia el estado (active | suspended). */
export async function setClinicaEstado(id: string, status: 'active' | 'suspended'): Promise<ClinicaPlat> {
  return request<ClinicaPlat>(`/plataforma/clinicas/${id}/estado/`, { method: 'POST', body: { status } })
}

/** GET /plataforma/usuarios/ — staff interno de la plataforma. */
export async function listPlatformStaff(params: { search?: string } = {}): Promise<Paginated<PlatformStaff>> {
  const qs = new URLSearchParams()
  if (params.search) qs.set('search', params.search)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request<Paginated<PlatformStaff>>(`/plataforma/usuarios/${suffix}`)
}

/** POST /plataforma/clinicas/ — da de alta una clínica nueva + su dueño. */
export async function createClinica(input: ClinicaCreateInput): Promise<ClinicaCreateResult> {
  return request<ClinicaCreateResult>('/plataforma/clinicas/', { method: 'POST', body: input })
}

/** GET /plataforma/clinicas/<id>/ — ficha de detalle de una clínica. */
export async function getClinicaDetail(id: string): Promise<ClinicaDetail> {
  return request<ClinicaDetail>(`/plataforma/clinicas/${id}/`)
}
