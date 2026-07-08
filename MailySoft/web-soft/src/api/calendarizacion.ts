/**
 * api/calendarizacion — Calendarización de tratamientos (Fase 1) contra el
 * backend real. Todo pasa por el cliente http central (Bearer + CSRF + refresh).
 *
 * Permisos backend: owner/admin/doctor. Un 403 se propaga para que la UI lo
 * refleje (el backend es la autoridad).
 */

import { request } from '../lib/http'
import { pdfJobBlob } from './pdfs'
import type { Paginated } from '../types/paciente'
import type {
  AgendarSesionInput,
  Calendarizacion,
  CalendarizacionCreateInput,
  CalendarizacionDesdePaqueteInput,
  CalendarizacionResumen,
  CalendarizacionUpdateInput,
  GenerarCotizacionResult,
  TreatmentSession,
} from '../types/calendarizacion'

/** GET /expediente/<patient_id>/calendarizaciones/ — planes del paciente (paginado). */
export async function listCalendarizaciones(
  patientId: string,
): Promise<Paginated<CalendarizacionResumen>> {
  return request<Paginated<CalendarizacionResumen>>(
    `/expediente/${patientId}/calendarizaciones/`,
  )
}

/** GET /expediente/calendarizaciones/<plan_id>/ — detalle del plan. */
export async function getCalendarizacion(planId: string): Promise<Calendarizacion> {
  return request<Calendarizacion>(`/expediente/calendarizaciones/${planId}/`)
}

/** POST /expediente/<patient_id>/calendarizaciones/ — crea un plan (201). */
export async function crearCalendarizacion(
  patientId: string,
  body: CalendarizacionCreateInput,
): Promise<Calendarizacion> {
  return request<Calendarizacion>(`/expediente/${patientId}/calendarizaciones/`, {
    method: 'POST',
    body,
  })
}

/**
 * PUT /expediente/calendarizaciones/<plan_id>/ — reemplaza el contenido del plan
 * (se manda SIEMPRE el estado completo con las fechas y estados). Devuelve el
 * detalle actualizado (200).
 */
export async function guardarCalendarizacion(
  planId: string,
  body: CalendarizacionUpdateInput,
): Promise<Calendarizacion> {
  return request<Calendarizacion>(`/expediente/calendarizaciones/${planId}/`, {
    method: 'PUT',
    body,
  })
}

/**
 * POST /expediente/calendarizaciones/sesiones/<session_id>/agendar/ — crea o
 * reprograma la cita real de una sesión. Devuelve la SESIÓN actualizada (con su
 * `appointment` embebido). Un empalme de horario responde 400 `{ detail }` que se
 * propaga como ApiError para mostrarlo en la UI.
 */
export async function agendarSesion(
  sessionId: string,
  body: AgendarSesionInput,
): Promise<TreatmentSession> {
  return request<TreatmentSession>(
    `/expediente/calendarizaciones/sesiones/${sessionId}/agendar/`,
    { method: 'POST', body },
  )
}

/**
 * DELETE /expediente/calendarizaciones/sesiones/<session_id>/agendar/ — quita la
 * cita de la agenda. Devuelve la sesión actualizada (appointment = null).
 */
export async function quitarAgendaSesion(sessionId: string): Promise<TreatmentSession> {
  return request<TreatmentSession>(
    `/expediente/calendarizaciones/sesiones/${sessionId}/agendar/`,
    { method: 'DELETE' },
  )
}

/** DELETE /expediente/calendarizaciones/<plan_id>/ — elimina el plan (204). */
export async function eliminarCalendarizacion(planId: string): Promise<void> {
  await request<void>(`/expediente/calendarizaciones/${planId}/`, { method: 'DELETE' })
}

/**
 * POST /expediente/calendarizaciones/<plan_id>/cotizacion/ — genera una cotización
 * (borrador) a partir del contenido del plan (Fase 2). Devuelve el id/estado/total
 * de la cotización creada (201). Tras esto, el detalle del plan trae `quote_id`.
 */
export async function generarCotizacion(planId: string): Promise<GenerarCotizacionResult> {
  return request<GenerarCotizacionResult>(
    `/expediente/calendarizaciones/${planId}/cotizacion/`,
    { method: 'POST' },
  )
}

/**
 * POST /expediente/<patient_id>/calendarizaciones/desde-paquete/ — crea una nueva
 * calendarización expandiendo un paquete reutilizable (Fase 3c). Devuelve el detalle
 * de la calendarización creada (201, misma forma que getCalendarizacion).
 */
export async function crearCalendarizacionDesdePaquete(
  patientId: string,
  body: CalendarizacionDesdePaqueteInput,
): Promise<Calendarizacion> {
  return request<Calendarizacion>(
    `/expediente/${patientId}/calendarizaciones/desde-paquete/`,
    { method: 'POST', body },
  )
}

/**
 * GET /expediente/calendarizaciones/<plan_id>/pdf/ — PDF del plan como Blob.
 * Flujo asíncrono (Celery): el endpoint ENCOLA y `pdfJobBlob` hace el polling y
 * la descarga por dentro. El token nunca va en la URL. Lo consume VisorPdf.
 */
export async function getCalendarizacionPdf(planId: string): Promise<Blob> {
  return pdfJobBlob(`/expediente/calendarizaciones/${planId}/pdf/`)
}
