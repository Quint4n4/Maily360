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
  ItemKind,
  MedicationCreateInput,
  MedicationCreated,
  MedicationSearchResult,
  PrescriptionCancelInput,
  PrescriptionCreateInput,
  PrescriptionDetail,
  PrescriptionFormatCreateInput,
  PrescriptionFormatOut,
  PrescriptionFormatUpdateInput,
  PrescriptionListItem,
} from '../types/recetas'

// ── B1.1 — Catálogo de medicamentos ───────────────────────────────────────────

/**
 * GET recetas/medicamentos/buscar/ — autocompletado (catálogo global + custom).
 * Respuesta: lista directa (no paginada). `q` vacío devuelve [].
 * `limit` lo clampa el backend entre 1 y 50 (default 25).
 * `kind` (COFEPRIS F2): filtra por tipo de ítem (medicamento/suero/terapia).
 */
export async function searchMedications(
  q: string,
  limit = 25,
  signal?: AbortSignal,
  kind?: ItemKind,
): Promise<MedicationSearchResult[]> {
  const qs = new URLSearchParams({ q, limit: String(limit) })
  if (kind) qs.set('kind', kind)
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

// ── B1.3 — PDF asíncrono (Celery): encolar → polling → descargar como Blob ──────

const _sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms))

/** Referencia a un trabajo de PDF que devuelve el backend. */
interface PdfJobRef {
  job_id: string
  status: 'pending' | 'processing' | 'done' | 'failed'
}

/**
 * Flujo asíncrono del PDF de receta. Transparente para el caller: devuelve un
 * Promise<Blob> (como antes), pero por dentro:
 *   1. GET /recetas/<id>/pdf/<qs>  → encola (o reusa caché): { job_id, status }.
 *   2. Polling de GET /recetas/pdf-job/<job_id>/ cada 2 s hasta status="done".
 *   3. GET /recetas/pdf-job/<job_id>/file/ → descarga el PDF (Bearer).
 * El PDF se genera en Celery, así que la API no se bloquea (riesgo P0).
 */
async function _prescriptionPdfBlob(prescriptionId: string, qs: string): Promise<Blob> {
  const job = await request<PdfJobRef>(`/recetas/${prescriptionId}/pdf/${qs}`)

  let status = job.status
  const MAX_TRIES = 30 // ~60 s de espera máxima
  for (let i = 0; status !== 'done' && i < MAX_TRIES; i++) {
    if (status === 'failed') throw new Error('No se pudo generar el PDF. Intenta de nuevo.')
    await _sleep(2000)
    const s = await request<PdfJobRef>(`/recetas/pdf-job/${job.job_id}/`)
    status = s.status
  }
  if (status !== 'done') {
    throw new Error('La generación del PDF está tardando demasiado. Intenta de nuevo.')
  }

  return requestBlob(`/recetas/pdf-job/${job.job_id}/file/`, {
    headers: { Accept: 'application/pdf' },
  })
}

/**
 * Descarga el PDF de una receta como Blob (flujo asíncrono interno).
 * El endpoint exige Authorization Bearer (token en memoria), por eso NO se puede
 * usar un <a href> directo: el caller crea un object URL temporal para abrirlo.
 */
export async function getPrescriptionPdf(prescriptionId: string): Promise<Blob> {
  return _prescriptionPdfBlob(prescriptionId, '')
}

/**
 * PDF con override de formato (galería / vista previa). `formato` fuerza el layout
 * por nombre (standard/compact/digital); `formatId` aplica un PrescriptionFormat
 * persistido por UUID.
 */
export async function getPrescriptionPdfWithFormat(
  prescriptionId: string,
  override: { formato?: string; formatId?: string },
): Promise<Blob> {
  const qs = new URLSearchParams()
  if (override.formatId) qs.set('format_id', override.formatId)
  else if (override.formato) qs.set('formato', override.formato)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return _prescriptionPdfBlob(prescriptionId, suffix)
}

// ── F5 — Verificación pública de autenticidad (QR) ─────────────────────────────

/** Resultado del endpoint público de verificación (SIN PII del paciente). */
export interface PrescriptionVerifyResult {
  folio: number
  estado: 'vigente' | 'anulada'
  fecha_emision: string // YYYY-MM-DD
  medico: { nombre: string; cedula_profesional: string }
  clinica: string
  controlado: boolean
  vigencia: string | null // ISO datetime o null
}

/**
 * GET verificar-receta/<id>/?sig=<token> — endpoint PÚBLICO (sin sesión).
 * Confirma la autenticidad de una receta al escanear su QR; devuelve solo datos
 * no sensibles. Firma inválida o receta inexistente → 404 (ApiError).
 */
export async function verificarReceta(
  prescriptionId: string,
  sig: string,
): Promise<PrescriptionVerifyResult> {
  const qs = new URLSearchParams({ sig }).toString()
  return request<PrescriptionVerifyResult>(`/verificar-receta/${prescriptionId}/?${qs}`)
}

// ── F3 — PrescriptionFormat (galería de formatos) ──────────────────────────────

/** GET recetas/formatos/ — formatos del tenant (array directo, no paginado). */
export async function listPrescriptionFormats(): Promise<PrescriptionFormatOut[]> {
  return request<PrescriptionFormatOut[]>('/recetas/formatos/')
}

/** POST recetas/formatos/ — crea un formato (201). */
export async function createPrescriptionFormat(
  input: PrescriptionFormatCreateInput,
): Promise<PrescriptionFormatOut> {
  return request<PrescriptionFormatOut>('/recetas/formatos/', { method: 'POST', body: input })
}

/** GET recetas/formatos/<id>/ — detalle de un formato. */
export async function getPrescriptionFormat(formatId: string): Promise<PrescriptionFormatOut> {
  return request<PrescriptionFormatOut>(`/recetas/formatos/${formatId}/`)
}

/** PATCH recetas/formatos/<id>/ — actualización parcial. */
export async function updatePrescriptionFormat(
  formatId: string,
  input: PrescriptionFormatUpdateInput,
): Promise<PrescriptionFormatOut> {
  return request<PrescriptionFormatOut>(`/recetas/formatos/${formatId}/`, {
    method: 'PATCH',
    body: input,
  })
}

/** DELETE recetas/formatos/<id>/ — baja del formato (204). */
export async function deletePrescriptionFormat(formatId: string): Promise<void> {
  await request<void>(`/recetas/formatos/${formatId}/`, { method: 'DELETE' })
}
