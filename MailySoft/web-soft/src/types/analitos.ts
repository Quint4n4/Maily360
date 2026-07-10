/**
 * Tipos del dominio "Analitos" (Fase 3) — el catálogo de parámetros de
 * laboratorio (p. ej. Glucosa, Colesterol) con su unidad y rango de referencia.
 *
 * Se usa al capturar el Plan Integral: el médico elige un analito del catálogo
 * para agregar una fila de laboratorio con su rango; el resultado se pinta en
 * rojo si cae fuera de [ref_low, ref_high].
 *
 * Reflejan EXACTO el contrato del backend (apps/expediente):
 *   - ref_low / ref_high viajan como STRING decimal o null (DRF); se convierten
 *     a number SOLO para comparar en la UI.
 *
 * Endpoints (prefijo /api/v1/):
 *   GET    /expediente/analitos/?only_active=true → Paginated<Analito>
 *   POST   /expediente/analitos/                  → Analito (201)
 *   GET    /expediente/analitos/<id>/
 *   PATCH  /expediente/analitos/<id>/             → Analito (200)
 *   DELETE /expediente/analitos/<id>/             → 204
 */

/** Un analito del catálogo. `unit`/`ref_low`/`ref_high` pueden faltar (null/''). */
export interface Analito {
  id: string
  name: string
  unit: string
  /** Límite inferior de referencia como string decimal, o null si no aplica. */
  ref_low: string | null
  /** Límite superior de referencia como string decimal, o null si no aplica. */
  ref_high: string | null
  is_active: boolean
}

/**
 * Cuerpo del POST (crear analito). Los rangos son opcionales: se envían como
 * string decimal o null. `is_active` por defecto true en el backend.
 */
export interface AnalitoCreateInput {
  name: string
  unit?: string
  ref_low?: string | null
  ref_high?: string | null
  is_active?: boolean
}

/** Cuerpo del PATCH (actualización parcial): todos los campos opcionales. */
export interface AnalitoUpdateInput {
  name?: string
  unit?: string
  ref_low?: string | null
  ref_high?: string | null
  is_active?: boolean
}
