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
  AuditoriaEvento,
  AuditoriaFiltros,
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

/** GET /plataforma/auditoria/ — log de auditoría cross-tenant (super_admin / engineering). */
export async function listPlatformAuditoria(params: AuditoriaFiltros = {}): Promise<Paginated<AuditoriaEvento>> {
  const qs = new URLSearchParams()
  if (params.tenant_id) qs.set('tenant_id', params.tenant_id)
  if (params.action) qs.set('action', params.action)
  if (params.actor_id) qs.set('actor_id', params.actor_id)
  if (params.date_from) qs.set('date_from', params.date_from)
  if (params.date_to) qs.set('date_to', params.date_to)
  if (params.search) qs.set('search', params.search)
  if (params.page) qs.set('page', String(params.page))
  if (params.page_size) qs.set('page_size', String(params.page_size))
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request<Paginated<AuditoriaEvento>>(`/plataforma/auditoria/${suffix}`)
}

/** GET /plataforma/clinicas/<id>/ — ficha de detalle de una clínica. */
export async function getClinicaDetail(id: string): Promise<ClinicaDetail> {
  return request<ClinicaDetail>(`/plataforma/clinicas/${id}/`)
}
