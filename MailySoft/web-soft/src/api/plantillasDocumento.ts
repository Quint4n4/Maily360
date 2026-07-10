/**
 * api/plantillasDocumento — Catálogo de "Plantillas de documento" (Fase 2) contra
 * el backend real. Todo pasa por el cliente http central (Bearer + CSRF + refresh).
 *
 * Permisos backend: gestión (crear/editar/eliminar) owner/admin; un 403 se propaga
 * para que la UI lo refleje (el backend es la autoridad).
 */

import { http } from '../lib/http'
import type { Paginated } from '../types/paciente'
import type {
  PlantillaDocumento,
  PlantillaDocumentoCreateInput,
  PlantillaDocumentoSection,
  PlantillaDocumentoUpdateInput,
} from '../types/plantillasDocumento'

/**
 * GET /expediente/plantillas-documento/ — plantillas (paginado). `section` filtra
 * por sección (para el picker "Insertar plantilla" de cada sección del Plan
 * Integral). Por defecto solo activas; `onlyActive: false` trae todas (gestión).
 */
export function listPlantillasDocumento(
  opts: { section?: PlantillaDocumentoSection; onlyActive?: boolean } = {},
): Promise<Paginated<PlantillaDocumento>> {
  const onlyActive = opts.onlyActive ?? true
  return http.get<Paginated<PlantillaDocumento>>('/expediente/plantillas-documento/', {
    ...(opts.section ? { section: opts.section } : {}),
    ...(onlyActive ? { only_active: 'true' } : {}),
  })
}

/** GET /expediente/plantillas-documento/<id>/ — detalle de una plantilla. */
export function getPlantillaDocumento(id: string): Promise<PlantillaDocumento> {
  return http.get<PlantillaDocumento>(`/expediente/plantillas-documento/${id}/`)
}

/** POST /expediente/plantillas-documento/ — crea una plantilla (201). */
export function createPlantillaDocumento(
  input: PlantillaDocumentoCreateInput,
): Promise<PlantillaDocumento> {
  return http.post<PlantillaDocumento>('/expediente/plantillas-documento/', input)
}

/** PATCH /expediente/plantillas-documento/<id>/ — actualización parcial (200). */
export function updatePlantillaDocumento(
  id: string,
  input: PlantillaDocumentoUpdateInput,
): Promise<PlantillaDocumento> {
  return http.patch<PlantillaDocumento>(`/expediente/plantillas-documento/${id}/`, input)
}

/** DELETE /expediente/plantillas-documento/<id>/ — elimina la plantilla (204). */
export function deletePlantillaDocumento(id: string): Promise<void> {
  return http.delete<void>(`/expediente/plantillas-documento/${id}/`)
}
