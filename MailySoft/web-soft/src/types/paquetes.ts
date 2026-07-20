/**
 * Tipos del dominio "Paquetes de tratamiento" (Fase 3).
 *
 * Un paquete es un conjunto REUTILIZABLE de tratamientos (conceptos del catálogo),
 * cada uno con un nº de sesiones. Se usa para: (a) agregarlo como renglones a una
 * cotización, y (b) generar una calendarización nueva desde él.
 *
 * Reflejan EXACTO el contrato del backend (apps/finanzas — paquetes):
 *   - Los montos (unit_price, price) viajan como STRING decimal desde/hacia DRF;
 *     se convierten a number SOLO para calcular en la UI.
 *
 * Endpoints (prefijo /api/v1/):
 *   GET    /finanzas/paquetes/?only_active=true → Paginated<PackageListItem>
 *   POST   /finanzas/paquetes/                  → PackageDetail (201)
 *   GET    /finanzas/paquetes/<id>/             → PackageDetail
 *   PATCH  /finanzas/paquetes/<id>/             → PackageDetail (200)
 *   DELETE /finanzas/paquetes/<id>/             → 204
 */

import type { SucursalRef } from './sucursal'

/** Fila de la lista (resumen liviano de cada paquete). */
export interface PackageListItem {
  id: string
  name: string
  description: string
  is_active: boolean
  /** Nº de tratamientos (renglones) del paquete. */
  items_count: number
  /** Suma de sesiones de todos los tratamientos. */
  sessions_total: number
  /** Precio total del paquete como string decimal (ej. "3500.00"). */
  price: string
  /**
   * Sedes DONDE está disponible el paquete (multi-sede). **`[]` = todas las
   * sedes.** El precio es el mismo en todas (no hay precio por sede).
   */
  sucursales: SucursalRef[]
}

/** Un tratamiento (renglón) del paquete (detalle). */
export interface PackageItem {
  /** Concepto del catálogo de servicios ligado a este renglón. */
  concept_id: string
  description: string
  /** Precio unitario como string decimal (viene del concepto). */
  unit_price: string
  sessions: number
  order: number
}

/** Detalle completo de un paquete. */
export interface PackageDetail {
  id: string
  name: string
  description: string
  is_active: boolean
  /** Precio total del paquete como string decimal. */
  price: string
  items: PackageItem[]
  /**
   * Sedes DONDE está disponible el paquete (multi-sede). **`[]` = todas las sedes.**
   */
  sucursales: SucursalRef[]
}

/* ── Inputs (cuerpos de POST / PATCH) ───────────────────────────────────────── */

/** Renglón en el cuerpo del POST/PATCH: el backend rellena descripción y precio. */
export interface PackageItemInput {
  concept_id: string
  sessions: number
  order?: number
}

/** Cuerpo del POST (crear paquete). */
export interface PackageCreateInput {
  name: string
  description?: string
  is_active?: boolean
  items: PackageItemInput[]
  /** Sedes donde queda disponible. **`[]` = todas las sedes.** Solo el dueño. */
  sucursal_ids?: string[]
}

/** Cuerpo del PATCH (actualizar paquete): todos los campos opcionales. */
export interface PackageUpdateInput {
  name?: string
  description?: string
  is_active?: boolean
  items?: PackageItemInput[]
  /**
   * Sedes donde queda disponible. **`[]` = todas las sedes.** Omitirlo = no tocar
   * la asignación actual. Solo el dueño puede enviarlo.
   */
  sucursal_ids?: string[]
}
