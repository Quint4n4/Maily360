/**
 * api/clinica — "Mi Consultorio": configuración, plantillas, categorías y
 * perfil del médico. Todo pasa por el cliente http central (Bearer + CSRF +
 * refresh automático + multipart con boundary correcto).
 *
 * Endpoints (apps/clinica/urls.py):
 *   GET    /clinica/configuracion/                       → ClinicSettings (o null si no existe)
 *   PUT    /clinica/configuracion/        (multipart)    → upsert parcial
 *   GET    /clinica/plantillas/?kind=                    → lista paginada
 *   POST   /clinica/plantillas/                          → alta (201)
 *   GET    /clinica/plantillas/<id>/                     → detalle
 *   PATCH  /clinica/plantillas/<id>/                     → actualización parcial
 *   DELETE /clinica/plantillas/<id>/                     → baja lógica (204)
 *   GET    /clinica/categorias/                          → lista paginada
 *   POST   /clinica/categorias/                          → alta (201)
 *   DELETE /clinica/categorias/<id>/                     → baja lógica (204)
 *   PATCH  /clinica/doctores/<id>/perfil/ (multipart)    → sello/foto/cédulas
 *   GET    /clinica/doctores/<id>/universidades/         → lista (array directo)
 *   POST   /clinica/doctores/<id>/universidades/ (mp)    → alta (201)
 *   DELETE /clinica/universidades/<id>/                  → borra (204)
 */

import { request } from '../lib/http'
import type {
  ClinicSettingsFields,
  ClinicSettingsOut,
  ClinicSettingsUpdateInput,
  ClinicTemplateCreateInput,
  ClinicTemplateOut,
  ClinicTemplateUpdateInput,
  DoctorProfileOut,
  DoctorProfileUpdateInput,
  DoctorUniversityCreateInput,
  DoctorUniversityOut,
  Paginated,
  PatientCategoryCreateInput,
  PatientCategoryOut,
  TemplateKind,
} from '../types/clinica'
import type {
  DoctorCredentialCreateInput,
  DoctorCredentialOut,
  DoctorCredentialUpdateInput,
} from '../types/credenciales'

/* ─── Configuración de la clínica ─────────────────────────────────────────── */

/**
 * GET /clinica/configuracion/ — config actual de la clínica.
 * El backend responde 204 cuando aún no existe; aquí se normaliza a null.
 */
export async function getClinicSettings(): Promise<ClinicSettingsOut | null> {
  const data = await request<ClinicSettingsOut | undefined>('/clinica/configuracion/')
  return data ?? null
}

/**
 * PUT /clinica/configuracion/ — upsert parcial.
 *
 * Elige el formato según el payload:
 *  - Si hay imágenes (logo/membretes) → multipart. En este modo NO se envían
 *    campos estructurados (la lista de contactos), porque el MultiPartParser
 *    de DRF no reconstruye un ListField de objetos. Las imágenes se suben en
 *    un PUT propio (la UI lo hace por imagen).
 *  - Si no hay imágenes → JSON (texto, números, booleano y la lista de
 *    contactos viajan correctamente tipados).
 * El PUT es un upsert parcial: solo se mandan los campos presentes.
 */
export async function updateClinicSettings(
  input: ClinicSettingsUpdateInput,
): Promise<ClinicSettingsOut> {
  const { logo, letterhead_full, letterhead_half, ...rest } = input
  const tieneImagen = Boolean(logo || letterhead_full || letterhead_half)

  if (tieneImagen) {
    const fd = new FormData()
    if (logo) fd.append('logo', logo)
    if (letterhead_full) fd.append('letterhead_full', letterhead_full)
    if (letterhead_half) fd.append('letterhead_half', letterhead_half)
    // Campos escalares acompañantes (texto/número/booleano) sí viajan en multipart.
    for (const [key, value] of Object.entries(rest)) {
      if (value === undefined) continue
      if (typeof value === 'boolean') fd.append(key, value ? 'true' : 'false')
      else fd.append(key, String(value))
    }
    return request<ClinicSettingsOut>('/clinica/configuracion/', { method: 'PUT', body: fd })
  }

  // Sin imágenes: JSON puro (la lista de contactos se serializa bien).
  const body: ClinicSettingsFields = rest
  return request<ClinicSettingsOut>('/clinica/configuracion/', { method: 'PUT', body })
}

/* ─── Plantillas ──────────────────────────────────────────────────────────── */

/** GET /clinica/plantillas/?kind= — lista paginada de plantillas activas. */
export async function listTemplates(kind?: TemplateKind): Promise<Paginated<ClinicTemplateOut>> {
  const qs = kind ? `?kind=${encodeURIComponent(kind)}` : ''
  return request<Paginated<ClinicTemplateOut>>(`/clinica/plantillas/${qs}`)
}

/** POST /clinica/plantillas/ — crea una plantilla. */
export async function createTemplate(
  input: ClinicTemplateCreateInput,
): Promise<ClinicTemplateOut> {
  return request<ClinicTemplateOut>('/clinica/plantillas/', { method: 'POST', body: input })
}

/** PATCH /clinica/plantillas/<id>/ — actualización parcial. */
export async function updateTemplate(
  id: string,
  input: ClinicTemplateUpdateInput,
): Promise<ClinicTemplateOut> {
  return request<ClinicTemplateOut>(`/clinica/plantillas/${id}/`, { method: 'PATCH', body: input })
}

/** DELETE /clinica/plantillas/<id>/ — baja lógica. */
export async function deleteTemplate(id: string): Promise<void> {
  await request<void>(`/clinica/plantillas/${id}/`, { method: 'DELETE' })
}

/* ─── Categorías de paciente ──────────────────────────────────────────────── */

/** GET /clinica/categorias/ — lista paginada de categorías activas. */
export async function listCategories(): Promise<Paginated<PatientCategoryOut>> {
  return request<Paginated<PatientCategoryOut>>('/clinica/categorias/')
}

/** POST /clinica/categorias/ — crea una categoría. */
export async function createCategory(
  input: PatientCategoryCreateInput,
): Promise<PatientCategoryOut> {
  return request<PatientCategoryOut>('/clinica/categorias/', { method: 'POST', body: input })
}

/** DELETE /clinica/categorias/<id>/ — baja lógica. */
export async function deleteCategory(id: string): Promise<void> {
  await request<void>(`/clinica/categorias/${id}/`, { method: 'DELETE' })
}

/* ─── Perfil del médico ───────────────────────────────────────────────────── */

/** PATCH /clinica/doctores/<doctorId>/perfil/ — sello/foto/cédulas (multipart). */
export async function updateDoctorProfile(
  doctorId: string,
  input: DoctorProfileUpdateInput,
): Promise<DoctorProfileOut> {
  const fd = new FormData()
  if (input.sello) fd.append('sello', input.sello)
  if (input.foto) fd.append('foto', input.foto)
  if (input.cedulas_adicionales !== undefined)
    fd.append('cedulas_adicionales', input.cedulas_adicionales)
  return request<DoctorProfileOut>(`/clinica/doctores/${doctorId}/perfil/`, {
    method: 'PATCH',
    body: fd,
  })
}

/* ─── Universidades del médico ────────────────────────────────────────────── */

/** GET /clinica/doctores/<doctorId>/universidades/ — array directo (sin paginar). */
export async function listUniversities(doctorId: string): Promise<DoctorUniversityOut[]> {
  return request<DoctorUniversityOut[]>(`/clinica/doctores/${doctorId}/universidades/`)
}

/** POST /clinica/doctores/<doctorId>/universidades/ — agrega un logo (multipart). */
export async function createUniversity(
  doctorId: string,
  input: DoctorUniversityCreateInput,
): Promise<DoctorUniversityOut> {
  const fd = new FormData()
  fd.append('logo', input.logo)
  if (input.name !== undefined) fd.append('name', input.name)
  return request<DoctorUniversityOut>(`/clinica/doctores/${doctorId}/universidades/`, {
    method: 'POST',
    body: fd,
  })
}

/** DELETE /clinica/universidades/<id>/ — elimina un logo de universidad. */
export async function deleteUniversity(universityId: string): Promise<void> {
  await request<void>(`/clinica/universidades/${universityId}/`, { method: 'DELETE' })
}

/* ─── Credenciales del médico (COFEPRIS F2) ───────────────────────────────── */

/** GET /clinica/doctores/<doctorId>/credenciales/ — array directo (sin paginar). */
export async function listCredentials(doctorId: string): Promise<DoctorCredentialOut[]> {
  return request<DoctorCredentialOut[]>(`/clinica/doctores/${doctorId}/credenciales/`)
}

/** POST /clinica/doctores/<doctorId>/credenciales/ — crea una credencial (201).
 *  Multipart: el logo de la institución (opcional) viaja junto con la credencial. */
export async function createCredential(
  doctorId: string,
  input: DoctorCredentialCreateInput,
): Promise<DoctorCredentialOut> {
  const fd = new FormData()
  fd.append('title', input.title)
  fd.append('institution', input.institution)
  fd.append('kind', input.kind)
  if (input.credential_number !== undefined) fd.append('credential_number', input.credential_number)
  if (input.order !== undefined) fd.append('order', String(input.order))
  if (input.logo) fd.append('logo', input.logo)
  return request<DoctorCredentialOut>(`/clinica/doctores/${doctorId}/credenciales/`, {
    method: 'POST',
    body: fd,
  })
}

/** PATCH /clinica/credenciales/<id>/ — edita la credencial (incl. logo, multipart). */
export async function updateCredential(
  credentialId: string,
  input: DoctorCredentialUpdateInput,
): Promise<DoctorCredentialOut> {
  const fd = new FormData()
  if (input.title !== undefined) fd.append('title', input.title)
  if (input.institution !== undefined) fd.append('institution', input.institution)
  if (input.kind !== undefined) fd.append('kind', input.kind)
  if (input.credential_number !== undefined) fd.append('credential_number', input.credential_number)
  if (input.order !== undefined) fd.append('order', String(input.order))
  if (input.logo) fd.append('logo', input.logo)
  return request<DoctorCredentialOut>(`/clinica/credenciales/${credentialId}/`, {
    method: 'PATCH',
    body: fd,
  })
}

/** DELETE /clinica/credenciales/<id>/ — baja lógica de la credencial (204). */
export async function deleteCredential(credentialId: string): Promise<void> {
  await request<void>(`/clinica/credenciales/${credentialId}/`, { method: 'DELETE' })
}
