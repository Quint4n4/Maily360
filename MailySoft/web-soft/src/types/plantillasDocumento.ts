/**
 * Tipos del dominio "Plantillas de documento" (Fase 2).
 *
 * Una plantilla de documento es un texto REUTILIZABLE que el médico inserta en
 * una sección del Plan Integral (reporte médico, seguimiento, interconsulta,
 * estudios, condiciones a mejorar) o de uso general. La gestiona owner/admin en
 * "Mi Consultorio"; al capturar el Plan Integral se ofrecen las de esa sección.
 *
 * Reflejan EXACTO el contrato del backend (apps/expediente):
 *   GET    /expediente/plantillas-documento/?section=<opt>&only_active=true
 *          → Paginated<PlantillaDocumento>
 *   POST   /expediente/plantillas-documento/            → 201
 *   GET    /expediente/plantillas-documento/<id>/
 *   PATCH  /expediente/plantillas-documento/<id>/
 *   DELETE /expediente/plantillas-documento/<id>/       → 204
 */

/**
 * Sección a la que pertenece una plantilla. Las 5 primeras coinciden con las
 * claves de las secciones editables del Plan Integral; `general` es transversal.
 */
export type PlantillaDocumentoSection =
  | 'reporte_medico'
  | 'seguimiento'
  | 'interconsulta'
  | 'estudios'
  | 'condiciones_mejorar'
  | 'general'

/** Una plantilla de documento (lista y detalle comparten shape). */
export interface PlantillaDocumento {
  id: string
  name: string
  section: PlantillaDocumentoSection
  body: string
  is_active: boolean
}

/** Cuerpo del POST (crear plantilla). `is_active` por defecto true en el backend. */
export interface PlantillaDocumentoCreateInput {
  name: string
  section: PlantillaDocumentoSection
  body: string
  is_active?: boolean
}

/** Cuerpo del PATCH (actualización parcial): todos los campos opcionales. */
export interface PlantillaDocumentoUpdateInput {
  name?: string
  section?: PlantillaDocumentoSection
  body?: string
  is_active?: boolean
}
