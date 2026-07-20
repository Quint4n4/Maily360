/**
 * Tipos del dominio "Sucursales" (multi-sede, Fase 1) — reflejan EXACTO el
 * contrato del backend Django/DRF (apps/clinica):
 *
 *   GET    /clinica/sucursales/        → Paginated<Sucursal>  (solo las PERMITIDAS del usuario)
 *   POST   /clinica/sucursales/        → Sucursal (201)       (owner/admin)
 *   GET    /clinica/sucursales/<id>/
 *   PATCH  /clinica/sucursales/<id>/   → Sucursal (200)       (owner/admin)
 *   DELETE /clinica/sucursales/<id>/   → 204                  (owner/admin)
 *
 * La sucursal activa se envía en el header `X-Sucursal-Id` en todas las
 * peticiones (ver src/lib/http.ts); el backend la usa para filtrar personal y
 * consultorios. El backend sigue siendo la autoridad de permisos.
 */

/**
 * Referencia mínima a la sede DONDE se generó un movimiento (Fase 3, finanzas):
 * `Charge`, `Payment` y `Quote` la traen anidada (`sucursal: {id, name} | null`).
 * Es null cuando el movimiento se creó antes de las sucursales (histórico).
 */
export interface SucursalRef {
  id: string
  name: string
}

/** Una sucursal (sede) de la clínica. */
export interface Sucursal {
  id: string
  name: string
  address: string
  phone: string
  /** Color de la sede (formato #RRGGBB), usado en la agenda a futuro. */
  color_hex: string
  is_active: boolean
  /** true = sucursal principal del tenant (una sola por clínica). */
  is_default: boolean
}

/**
 * Representación compacta de una sucursal, tal como llega en /me
 * (`sucursales: [{id, name, is_default}]`) — las permitidas del usuario.
 */
export interface SucursalBrief {
  id: string
  name: string
  is_default: boolean
}

/**
 * Sucursales ASIGNADAS a un miembro de la clínica (multi-sede, Fase 4).
 *
 *   GET /clinica/membresias/<membership_id>/sucursales/
 *   PUT /clinica/membresias/<membership_id>/sucursales/   body {sucursal_ids: [...]}
 *
 * Asignar sedes a una membresía es lo que acota qué puede ver y operar ese
 * usuario: un admin con UNA sola sede asignada = "administrador de sucursal".
 * El owner ve todas las sedes siempre. El backend es la autoridad: un admin
 * solo puede otorgar/quitar sedes que él mismo tiene permitidas (si no → 400/403).
 */
export interface MembershipSucursales {
  membership_id: string
  sucursales: SucursalBrief[]
}

/** Cuerpo del PUT: conjunto COMPLETO de sedes a dejar asignadas (reemplaza, no añade). */
export interface MembershipSucursalesInput {
  sucursal_ids: string[]
}

/** Cuerpo del POST (crear sucursal). Solo owner/admin. */
export interface SucursalCreateInput {
  name: string
  address?: string
  phone?: string
  /** Formato #RRGGBB; vacío permitido. */
  color_hex?: string
}

/**
 * Cuerpo del PATCH (actualización parcial). En Fase 1 solo se editan
 * nombre/dirección/teléfono/color; is_active/is_default se cambian por acciones
 * dedicadas del backend, no por este PATCH.
 */
export type SucursalUpdateInput = Partial<SucursalCreateInput>
