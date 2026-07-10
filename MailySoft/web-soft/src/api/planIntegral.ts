/**
 * api/planIntegral — "Plan Integral de Longevidad y Medicina Regenerativa"
 * contra el backend real. Todo pasa por el cliente http central (Bearer + CSRF
 * + refresh automático). Los componentes NO llaman aquí directamente: lo hacen
 * vía los hooks de src/hooks/planIntegral.ts (TanStack Query).
 *
 * Endpoints (apps/expediente, prefijo /api/v1/):
 *   GET  /expediente/<patient_id>/plan-integral/borrador/?treatment_plan_id=<uuid?>
 *   POST /expediente/<patient_id>/plan-integral/
 *   GET  /expediente/plan-integral/<id>/pdf/     → PDF async (Blob)
 *   GET  /expediente/<patient_id>/plan-integral/ → lista paginada
 *
 * Permiso: roles clínicos (owner/admin/doctor). El backend es la autoridad y
 * responde 403 al resto; el cliente http propaga ese error para que la UI lo
 * refleje sin romperse.
 */

import { request } from '../lib/http'
import { pdfJobBlob } from './pdfs'
import type { Paginated } from '../types/paciente'
import type {
  PlanIntegral,
  PlanIntegralBorrador,
  PlanIntegralInput,
} from '../types/planIntegral'

/**
 * GET /expediente/<patient_id>/plan-integral/borrador/ — borrador del Plan
 * Integral: encabezado NO editable + 8 secciones (4 auto-rellenadas) + esquema
 * del plan elegido + planes disponibles. `treatmentPlanId` opcional: al pasarlo,
 * el backend arma el `esquema` con ese plan de tratamiento.
 */
export async function getPlanIntegralBorrador(
  patientId: string,
  treatmentPlanId?: string,
): Promise<PlanIntegralBorrador> {
  const suffix = treatmentPlanId
    ? `?treatment_plan_id=${encodeURIComponent(treatmentPlanId)}`
    : ''
  return request<PlanIntegralBorrador>(
    `/expediente/${patientId}/plan-integral/borrador/${suffix}`,
  )
}

/**
 * POST /expediente/<patient_id>/plan-integral/ — guarda la constancia con el
 * plan elegido (opcional) y el texto ya editado de las 8 secciones (201).
 * Devuelve el registro (con su id) para luego pedir su PDF.
 */
export async function crearPlanIntegral(
  patientId: string,
  body: PlanIntegralInput,
): Promise<PlanIntegral> {
  return request<PlanIntegral>(`/expediente/${patientId}/plan-integral/`, {
    method: 'POST',
    body,
  })
}

/**
 * GET /expediente/plan-integral/<id>/pdf/ — PDF de la constancia (Blob).
 * Flujo asíncrono unificado: el endpoint ENCOLA y `pdfJobBlob` hace el polling y
 * la descarga por dentro. Descarga autenticada (Bearer); el token no va en la URL.
 */
export async function getPlanIntegralPdf(planId: string): Promise<Blob> {
  return pdfJobBlob(`/expediente/plan-integral/${planId}/pdf/`)
}

/**
 * GET /expediente/<patient_id>/plan-integral/ — constancias de Plan Integral del
 * paciente (paginado, más reciente primero → usar .results).
 */
export async function listPlanesIntegrales(
  patientId: string,
  page?: number,
): Promise<Paginated<PlanIntegral>> {
  const suffix = page ? `?page=${page}` : ''
  return request<Paginated<PlanIntegral>>(
    `/expediente/${patientId}/plan-integral/${suffix}`,
  )
}
