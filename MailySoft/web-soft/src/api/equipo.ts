/**
 * api/equipo — Equipo / departamentos de la clínica (Fase 4) contra el backend
 * real. Todo pasa por el cliente http central (Bearer + CSRF + refresh).
 *
 * Permisos backend: gestión (crear/editar/eliminar) owner/admin; un 403 se propaga
 * para que la UI lo refleje (el backend es la autoridad).
 */

import { http } from '../lib/http'
import type { Paginated } from '../types/paciente'
import type {
  EquipoMiembro,
  EquipoMiembroCreateInput,
  EquipoMiembroUpdateInput,
} from '../types/equipo'

/**
 * GET /clinica/equipo/ — integrantes del equipo (paginado → usar .results).
 * Por defecto solo activos; `onlyActive: false` trae también los desactivados
 * (para poder reactivarlos desde la gestión).
 */
export function listEquipo(
  opts: { onlyActive?: boolean } = {},
): Promise<Paginated<EquipoMiembro>> {
  const onlyActive = opts.onlyActive ?? true
  return http.get<Paginated<EquipoMiembro>>(
    '/clinica/equipo/',
    onlyActive ? { only_active: 'true' } : {},
  )
}

/** GET /clinica/equipo/<id>/ — detalle de un integrante. */
export function getEquipoMiembro(id: string): Promise<EquipoMiembro> {
  return http.get<EquipoMiembro>(`/clinica/equipo/${id}/`)
}

/** POST /clinica/equipo/ — crea un integrante (201). */
export function createEquipoMiembro(
  input: EquipoMiembroCreateInput,
): Promise<EquipoMiembro> {
  return http.post<EquipoMiembro>('/clinica/equipo/', input)
}

/** PATCH /clinica/equipo/<id>/ — actualización parcial (200). */
export function updateEquipoMiembro(
  id: string,
  input: EquipoMiembroUpdateInput,
): Promise<EquipoMiembro> {
  return http.patch<EquipoMiembro>(`/clinica/equipo/${id}/`, input)
}

/** DELETE /clinica/equipo/<id>/ — elimina el integrante (204). */
export function deleteEquipoMiembro(id: string): Promise<void> {
  return http.delete<void>(`/clinica/equipo/${id}/`)
}
