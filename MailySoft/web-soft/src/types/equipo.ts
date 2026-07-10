/**
 * Tipos del dominio "Equipo de la clínica" (Fase 4) — los integrantes por
 * departamento (p. ej. "Nutrición — Dra. Pérez") que se muestran en el Plan
 * Integral. Se gestiona en "Mi Consultorio" (owner/admin); el Plan Integral los
 * snapshotea desde esta configuración.
 *
 * Reflejan EXACTO el contrato del backend (apps/clinica):
 *   GET    /clinica/equipo/          → Paginated<EquipoMiembro>
 *   POST   /clinica/equipo/          → EquipoMiembro (201)
 *   GET    /clinica/equipo/<id>/
 *   PATCH  /clinica/equipo/<id>/     → EquipoMiembro (200)
 *   DELETE /clinica/equipo/<id>/     → 204
 */

/** Un integrante del equipo (departamento + nombre), con orden y estado. */
export interface EquipoMiembro {
  id: string
  departamento: string
  nombre: string
  order: number
  is_active: boolean
}

/** Cuerpo del POST (crear integrante). `is_active` por defecto true en el backend. */
export interface EquipoMiembroCreateInput {
  departamento: string
  nombre: string
  order?: number
  is_active?: boolean
}

/** Cuerpo del PATCH (actualización parcial): todos los campos opcionales. */
export interface EquipoMiembroUpdateInput {
  departamento?: string
  nombre?: string
  order?: number
  is_active?: boolean
}
