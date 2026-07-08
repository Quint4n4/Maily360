/**
 * api/paquetes — Catálogo de paquetes de tratamiento (Fase 3) contra el backend
 * real. Todo pasa por el cliente http central (Bearer + CSRF + refresh).
 *
 * Archivo NUEVO (separado de finanzas.ts) para no chocar con otra sesión en
 * paralelo. Permisos backend: gestión (crear/editar/eliminar) owner/admin; un 403
 * se propaga para que la UI lo refleje (el backend es la autoridad).
 */

import { http } from '../lib/http'
import type { Paginated } from '../types/paciente'
import type {
  PackageCreateInput,
  PackageDetail,
  PackageListItem,
  PackageUpdateInput,
} from '../types/paquetes'

/**
 * GET /finanzas/paquetes/ — paquetes (paginado). Por defecto solo los activos
 * (para los pickers de cotización/calendarización); `onlyActive: false` trae todos
 * (para la página de gestión, donde se ven y reactivan los inactivos).
 */
export function listPaquetes(
  opts: { onlyActive?: boolean } = {},
): Promise<Paginated<PackageListItem>> {
  const onlyActive = opts.onlyActive ?? true
  return http.get<Paginated<PackageListItem>>(
    '/finanzas/paquetes/',
    onlyActive ? { only_active: 'true' } : {},
  )
}

/** GET /finanzas/paquetes/<id>/ — detalle del paquete (con sus items). */
export function getPaquete(id: string): Promise<PackageDetail> {
  return http.get<PackageDetail>(`/finanzas/paquetes/${id}/`)
}

/** POST /finanzas/paquetes/ — crea un paquete (201). */
export function createPaquete(input: PackageCreateInput): Promise<PackageDetail> {
  return http.post<PackageDetail>('/finanzas/paquetes/', input)
}

/** PATCH /finanzas/paquetes/<id>/ — actualiza un paquete (200). */
export function updatePaquete(id: string, input: PackageUpdateInput): Promise<PackageDetail> {
  return http.patch<PackageDetail>(`/finanzas/paquetes/${id}/`, input)
}

/** DELETE /finanzas/paquetes/<id>/ — elimina el paquete (204). */
export function deletePaquete(id: string): Promise<void> {
  return http.delete<void>(`/finanzas/paquetes/${id}/`)
}
