/**
 * api/sucursales — Sucursales (sedes) de la clínica (multi-sede, Fase 1) contra
 * el backend real. Todo pasa por el cliente http central (Bearer + CSRF +
 * refresh + header X-Sucursal-Id).
 *
 * Permisos backend: lectura para todos los roles (devuelve solo las sucursales
 * PERMITIDAS del usuario); gestión (crear/editar/eliminar) owner/admin. Un 403
 * se propaga para que la UI lo refleje (el backend es la autoridad).
 */

import { http } from '../lib/http'
import type { Paginated } from '../types/paciente'
import type {
  MembershipSucursales,
  MembershipSucursalesInput,
  Sucursal,
  SucursalCreateInput,
  SucursalUpdateInput,
} from '../types/sucursal'

/** GET /clinica/sucursales/ — sucursales permitidas del usuario (paginado → .results). */
export function listSucursales(): Promise<Paginated<Sucursal>> {
  return http.get<Paginated<Sucursal>>('/clinica/sucursales/')
}

/** GET /clinica/sucursales/<id>/ — detalle de una sucursal. */
export function getSucursal(id: string): Promise<Sucursal> {
  return http.get<Sucursal>(`/clinica/sucursales/${id}/`)
}

/** POST /clinica/sucursales/ — crea una sucursal (201). owner/admin. */
export function createSucursal(input: SucursalCreateInput): Promise<Sucursal> {
  return http.post<Sucursal>('/clinica/sucursales/', input)
}

/** PATCH /clinica/sucursales/<id>/ — actualización parcial (200). owner/admin. */
export function updateSucursal(id: string, input: SucursalUpdateInput): Promise<Sucursal> {
  return http.patch<Sucursal>(`/clinica/sucursales/${id}/`, input)
}

/** DELETE /clinica/sucursales/<id>/ — elimina la sucursal (204). owner/admin. */
export function deleteSucursal(id: string): Promise<void> {
  return http.delete<void>(`/clinica/sucursales/${id}/`)
}

// ── Asignación de sedes por miembro (Fase 4) ─────────────────────────────────

/**
 * GET /clinica/membresias/<membership_id>/sucursales/ — sedes asignadas a un
 * miembro. Solo owner/admin (el backend responde 403 a los demás).
 */
export function getMembershipSucursales(membershipId: string): Promise<MembershipSucursales> {
  return http.get<MembershipSucursales>(`/clinica/membresias/${membershipId}/sucursales/`)
}

/**
 * PUT /clinica/membresias/<membership_id>/sucursales/ — REEMPLAZA el conjunto
 * de sedes asignadas al miembro.
 *
 * owner: cualquier sede. admin: solo las que él mismo tiene permitidas (si
 * intenta otra, el backend responde 400/403 con un mensaje claro que la UI
 * debe mostrar tal cual). El backend es la autoridad.
 */
export function setMembershipSucursales(
  membershipId: string,
  input: MembershipSucursalesInput,
): Promise<MembershipSucursales> {
  return http.put<MembershipSucursales>(
    `/clinica/membresias/${membershipId}/sucursales/`,
    input,
  )
}
