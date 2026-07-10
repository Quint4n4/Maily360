/**
 * api/analitos — Catálogo de analitos de laboratorio (Fase 3) contra el backend
 * real. Todo pasa por el cliente http central (Bearer + CSRF + refresh).
 *
 * Permisos backend: gestión (crear/editar/eliminar) owner/admin; un 403 se propaga
 * para que la UI lo refleje (el backend es la autoridad).
 */

import { http } from '../lib/http'
import type { Paginated } from '../types/paciente'
import type {
  Analito,
  AnalitoCreateInput,
  AnalitoUpdateInput,
} from '../types/analitos'

/**
 * GET /expediente/analitos/ — analitos (paginado). Por defecto solo los activos
 * (para el picker de laboratorio del Plan Integral); `onlyActive: false` trae todos
 * (para la página de gestión, donde se ven y reactivan los inactivos).
 */
export function listAnalitos(
  opts: { onlyActive?: boolean } = {},
): Promise<Paginated<Analito>> {
  const onlyActive = opts.onlyActive ?? true
  return http.get<Paginated<Analito>>(
    '/expediente/analitos/',
    onlyActive ? { only_active: 'true' } : {},
  )
}

/** GET /expediente/analitos/<id>/ — detalle de un analito. */
export function getAnalito(id: string): Promise<Analito> {
  return http.get<Analito>(`/expediente/analitos/${id}/`)
}

/** POST /expediente/analitos/ — crea un analito (201). */
export function createAnalito(input: AnalitoCreateInput): Promise<Analito> {
  return http.post<Analito>('/expediente/analitos/', input)
}

/** PATCH /expediente/analitos/<id>/ — actualización parcial (200). */
export function updateAnalito(id: string, input: AnalitoUpdateInput): Promise<Analito> {
  return http.patch<Analito>(`/expediente/analitos/${id}/`, input)
}

/** DELETE /expediente/analitos/<id>/ — elimina el analito (204). */
export function deleteAnalito(id: string): Promise<void> {
  return http.delete<void>(`/expediente/analitos/${id}/`)
}
