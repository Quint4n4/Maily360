/**
 * api/recetas — Recetas médicas contra el backend real (B1.1–B1.3).
 * Todo pasa por el cliente http central (Bearer + CSRF + refresh automático).
 *
 * Endpoints (apps/recetas/urls.py, prefijo /api/v1/):
 *   B1.1 — Catálogo de medicamentos
 *     GET  recetas/medicamentos/buscar/?q=<texto>&limit=25  → autocompletado (lista)
 *     POST recetas/medicamentos/                            → crea medicamento custom (201)
 *   B1.2 — Recetas
 *     GET  expediente/<patient_id>/recetas/[?page=]         → historial PAGINADO (.results)
 *     POST expediente/<patient_id>/recetas/                 → emite receta (201, detalle)
 *     GET  recetas/<prescription_id>/                       → detalle completo (para "copiar de previa")
 *     POST recetas/<prescription_id>/anular/                → anula con motivo (200, detalle)
 *   B1.3 — PDF
 *     GET  recetas/<prescription_id>/pdf/                   → application/pdf (Bearer, vía blob)
 */

import { request, requestBlob } from '../lib/http'
import type { Paginated } from '../types/paciente'
import type {
  MedicationCreateInput,
  MedicationCreated,
  MedicationSearchResult,
  PrescriptionCancelInput,
  PrescriptionCreateInput,
  PrescriptionDetail,
  PrescriptionListItem,
} from '../types/recetas'

// ── B1.1 — Catálogo de medicamentos ───────────────────────────────────────────

/**
 * GET recetas/medicamentos/buscar/ — autocompletado (catálogo global + custom).
 * Respuesta: lista directa (no paginada). `q` vacío devuelve [].
 * `limit` lo clampa el backend entre 1 y 50 (default 25).
 */
export async function searchMedications(
  q: string,
  limit = 25,
  signal?: AbortSignal,
): Promise<MedicationSearchResult[]> {
  const qs = new URLSearchParams({ q, limit: String(limit) })
  return request<MedicationSearchResult[]>(`/recetas/medicamentos/buscar/?${qs.toString()}`, {
    signal,
  })
}

/** POST recetas/medicamentos/ — crea un medicamento custom del tenant (201). */
export async function createMedication(
  input: MedicationCreateInput,
): Promise<MedicationCreated> {
  return request<MedicationCreated>('/recetas/medicamentos/', { method: 'POST', body: input })
}

// ── B1.2 — Recetas ─────────────────────────────────────────────────────────────

/** GET expediente/<patient_id>/recetas/ — historial paginado (-issued_at). */
export async function listPrescriptions(
  patientId: string,
  page?: number,
): Promise<Paginated<PrescriptionListItem>> {
  const suffix = page ? `?page=${page}` : ''
  return request<Paginated<PrescriptionListItem>>(`/expediente/${patientId}/recetas/${suffix}`)
}

/**
 * POST expediente/<patient_id>/recetas/ — emite una receta nueva (201).
 * El médico se infiere en el backend; NO se manda doctor_id.
 */
export async function createPrescription(
  patientId: string,
  input: PrescriptionCreateInput,
): Promise<PrescriptionDetail> {
  return request<PrescriptionDetail>(`/expediente/${patientId}/recetas/`, {
    method: 'POST',
    body: input,
  })
}

/** GET recetas/<prescription_id>/ — detalle completo (para "copiar de previa"). */
export async function getPrescription(prescriptionId: string): Promise<PrescriptionDetail> {
  return request<PrescriptionDetail>(`/recetas/${prescriptionId}/`)
}

/** POST recetas/<prescription_id>/anular/ — anula la receta con motivo (200). */
export async function cancelPrescription(
  prescriptionId: string,
  input: PrescriptionCancelInput,
): Promise<PrescriptionDetail> {
  return request<PrescriptionDetail>(`/recetas/${prescriptionId}/anular/`, {
    method: 'POST',
    body: input,
  })
}

// ── B1.3 — PDF (descarga vía blob con Bearer) ──────────────────────────────────

/**
 * GET recetas/<prescription_id>/pdf/ — descarga el PDF como Blob.
 * El endpoint exige Authorization Bearer (token en memoria), por eso NO se puede
 * usar un <a href> directo: se obtiene el blob por el cliente central y el caller
 * crea un object URL temporal para abrirlo/descargarlo.
 */
export async function getPrescriptionPdf(prescriptionId: string): Promise<Blob> {
  return requestBlob(`/recetas/${prescriptionId}/pdf/`, {
    headers: { Accept: 'application/pdf' },
  })
}
