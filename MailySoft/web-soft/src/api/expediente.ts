/**
 * api/expediente — Expediente Clínico contra el backend real (A1–A4).
 * Todo pasa por el cliente http central (Bearer + CSRF + refresh automático).
 *
 * Endpoints (apps/expediente/urls.py, prefijo /api/v1/):
 *   A1 — Alergias
 *     GET    /expediente/<patient_id>/alergias/[?include_resolved=true]
 *     POST   /expediente/<patient_id>/alergias/
 *     DELETE /expediente/alergias/<id>/                 → resolver (baja lógica, 204)
 *   A2 — Historia clínica
 *     GET    /expediente/<patient_id>/historia/         → HC o documento vacío
 *     PUT    /expediente/<patient_id>/historia/         → upsert
 *   A3 — Signos vitales (append-only)
 *     GET    /expediente/<patient_id>/signos/           → PAGINADO (.results)
 *     POST   /expediente/<patient_id>/signos/
 *     GET    /expediente/<patient_id>/signos/series/[?since=YYYY-MM-DD]
 *   A4 — Evolución / diagnósticos
 *     GET    /expediente/<patient_id>/evoluciones/      → PAGINADO (.results)
 *     POST   /expediente/<patient_id>/evoluciones/
 *     POST   /expediente/evoluciones/<id>/addendum/
 *     GET    /expediente/evoluciones/<id>/imagenes/     → lista de imágenes de la nota
 *     POST   /expediente/evoluciones/<id>/imagenes/     → sube una imagen (multipart, campo `image`)
 *     DELETE /expediente/imagenes/<id>/                 → baja lógica de la imagen (204)
 *     GET    /expediente/<patient_id>/diagnosticos/[?only_active=true] → PAGINADO
 *     POST   /expediente/<patient_id>/diagnosticos/
 *     POST   /expediente/diagnosticos/<id>/resolver/
 */

import { request } from '../lib/http'
import type { Paginated } from '../types/paciente'
import type {
  Addendum,
  AddendumInput,
  Allergy,
  AllergyInput,
  Diagnosis,
  DiagnosisInput,
  EvolutionImage,
  EvolutionNote,
  EvolutionNoteInput,
  MedicalHistory,
  MedicalHistoryInput,
  NursingInstruction,
  VitalSignsInput,
  VitalSignsRecord,
  VitalSignsSeries,
} from '../types/expediente'

// ── A1 — Alergias ───────────────────────────────────────────────────────────

/** GET /expediente/<patient_id>/alergias/ — lista alergias (vigentes por defecto). */
export async function listAllergies(
  patientId: string,
  includeResolved = false,
): Promise<Allergy[]> {
  const suffix = includeResolved ? '?include_resolved=true' : ''
  return request<Allergy[]>(`/expediente/${patientId}/alergias/${suffix}`)
}

/** POST /expediente/<patient_id>/alergias/ — registra una alergia (201). */
export async function createAllergy(patientId: string, input: AllergyInput): Promise<Allergy> {
  return request<Allergy>(`/expediente/${patientId}/alergias/`, { method: 'POST', body: input })
}

/** DELETE /expediente/alergias/<id>/ — resolver (baja lógica clínica, 204). */
export async function resolveAllergy(allergyId: string): Promise<void> {
  await request<void>(`/expediente/alergias/${allergyId}/`, { method: 'DELETE' })
}

// ── A2 — Historia clínica ─────────────────────────────────────────────────────

/** GET /expediente/<patient_id>/historia/ — HC del paciente (o documento vacío). */
export async function getMedicalHistory(patientId: string): Promise<MedicalHistory> {
  return request<MedicalHistory>(`/expediente/${patientId}/historia/`)
}

/** PUT /expediente/<patient_id>/historia/ — upsert de la HC (200). */
export async function upsertMedicalHistory(
  patientId: string,
  input: MedicalHistoryInput,
): Promise<MedicalHistory> {
  return request<MedicalHistory>(`/expediente/${patientId}/historia/`, { method: 'PUT', body: input })
}

// ── A3 — Signos vitales ───────────────────────────────────────────────────────

/** GET /expediente/<patient_id>/signos/ — tomas paginadas (-measured_at). */
export async function listVitalSigns(
  patientId: string,
  page?: number,
): Promise<Paginated<VitalSignsRecord>> {
  const suffix = page ? `?page=${page}` : ''
  return request<Paginated<VitalSignsRecord>>(`/expediente/${patientId}/signos/${suffix}`)
}

/** POST /expediente/<patient_id>/signos/ — registra una toma (201). */
export async function createVitalSigns(
  patientId: string,
  input: VitalSignsInput,
): Promise<VitalSignsRecord> {
  return request<VitalSignsRecord>(`/expediente/${patientId}/signos/`, { method: 'POST', body: input })
}

/** GET /expediente/<patient_id>/signos/series/ — series para gráficas. */
export async function getVitalSignsSeries(
  patientId: string,
  since?: string,
): Promise<VitalSignsSeries> {
  const suffix = since ? `?since=${encodeURIComponent(since)}` : ''
  return request<VitalSignsSeries>(`/expediente/${patientId}/signos/series/${suffix}`)
}

// ── A4 — Notas de evolución ───────────────────────────────────────────────────

/** GET /expediente/<patient_id>/evoluciones/ — notas paginadas (-created_at), con addenda. */
export async function listEvolutionNotes(
  patientId: string,
  page?: number,
): Promise<Paginated<EvolutionNote>> {
  const suffix = page ? `?page=${page}` : ''
  return request<Paginated<EvolutionNote>>(`/expediente/${patientId}/evoluciones/${suffix}`)
}

/** POST /expediente/<patient_id>/evoluciones/ — crea una nota (cita ATTENDED, 201). */
export async function createEvolutionNote(
  patientId: string,
  input: EvolutionNoteInput,
): Promise<EvolutionNote> {
  return request<EvolutionNote>(`/expediente/${patientId}/evoluciones/`, {
    method: 'POST',
    body: input,
  })
}

/** POST /expediente/evoluciones/<id>/addendum/ — agrega un addendum (201). */
export async function createAddendum(
  evolutionId: string,
  input: AddendumInput,
): Promise<Addendum> {
  return request<Addendum>(`/expediente/evoluciones/${evolutionId}/addendum/`, {
    method: 'POST',
    body: input,
  })
}

// ── A4 — Imágenes de la nota de evolución ─────────────────────────────────────

/** GET /expediente/evoluciones/<evolution_id>/imagenes/ — imágenes de la nota. */
export async function getEvolutionImages(evolutionId: string): Promise<EvolutionImage[]> {
  return request<EvolutionImage[]>(`/expediente/evoluciones/${evolutionId}/imagenes/`)
}

/**
 * POST /expediente/evoluciones/<evolution_id>/imagenes/ — sube una imagen (multipart).
 * Campo `image` (el archivo) + `caption` opcional. El backend valida que sea una
 * imagen real (JPG/PNG/WEBP) y limita a 20 por nota (400 si no cumple).
 */
export async function uploadEvolutionImage(
  evolutionId: string,
  file: File,
  caption?: string,
): Promise<EvolutionImage> {
  const fd = new FormData()
  fd.append('image', file)
  if (caption) fd.append('caption', caption)
  return request<EvolutionImage>(`/expediente/evoluciones/${evolutionId}/imagenes/`, {
    method: 'POST',
    body: fd,
  })
}

/** DELETE /expediente/imagenes/<id>/ — baja lógica de una imagen (204). */
export async function deleteEvolutionImage(imageId: string): Promise<void> {
  await request<void>(`/expediente/imagenes/${imageId}/`, { method: 'DELETE' })
}

// ── A4 — Indicaciones para enfermería ─────────────────────────────────────────

/**
 * GET /expediente/<patient_id>/indicaciones-enfermeria/ — lista de indicaciones
 * para enfermería derivadas de las notas de evolución (más recientes primero).
 */
export async function getNursingInstructions(
  patientId: string,
): Promise<NursingInstruction[]> {
  return request<NursingInstruction[]>(`/expediente/${patientId}/indicaciones-enfermeria/`)
}

// ── A4 — Diagnósticos ─────────────────────────────────────────────────────────

/** GET /expediente/<patient_id>/diagnosticos/ — diagnósticos paginados. */
export async function listDiagnoses(
  patientId: string,
  onlyActive = false,
  page?: number,
): Promise<Paginated<Diagnosis>> {
  const qs = new URLSearchParams()
  if (onlyActive) qs.set('only_active', 'true')
  if (page) qs.set('page', String(page))
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request<Paginated<Diagnosis>>(`/expediente/${patientId}/diagnosticos/${suffix}`)
}

/** POST /expediente/<patient_id>/diagnosticos/ — crea un diagnóstico (201). */
export async function createDiagnosis(
  patientId: string,
  input: DiagnosisInput,
): Promise<Diagnosis> {
  return request<Diagnosis>(`/expediente/${patientId}/diagnosticos/`, { method: 'POST', body: input })
}

/** POST /expediente/diagnosticos/<id>/resolver/ — marca como resuelto (200). */
export async function resolveDiagnosis(diagnosisId: string): Promise<Diagnosis> {
  return request<Diagnosis>(`/expediente/diagnosticos/${diagnosisId}/resolver/`, { method: 'POST', body: {} })
}
