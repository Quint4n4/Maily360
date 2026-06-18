/**
 * Helpers para mapear errores de la API (ApiError de DRF) a mensajes legibles.
 *
 * DRF devuelve:
 *   - {detail: "..."}           → error general / 403 / 404
 *   - {campo: ["error", ...]}   → errores de validación 400 por campo
 *
 * El backend es la autoridad de permisos: un 403 SIEMPRE se muestra como
 * "No tienes permiso…", no rompe la pantalla.
 */

import { ApiError } from './http'

/** Lista plana de mensajes de error para mostrar en una alerta. */
export function erroresDe(err: unknown): string[] {
  if (!(err instanceof ApiError)) return ['Ocurrió un error inesperado.']
  if (err.isNetwork) return ['No se pudo conectar con el servidor.']
  if (err.status === 403) return ['No tienes permiso para esta acción.']
  const body = err.body
  if (!body) return [`Error ${err.status}.`]
  const msgs: string[] = []
  for (const [campo, valor] of Object.entries(body)) {
    const txt = Array.isArray(valor) ? valor.join(' ') : String(valor)
    msgs.push(campo === 'detail' ? txt : `${campo}: ${txt}`)
  }
  return msgs.length ? msgs : [`Error ${err.status}.`]
}

/** Un único mensaje de error (junta los de erroresDe). */
export function errorMsg(err: unknown): string {
  return erroresDe(err).join(' ')
}

/** Mapa campo → primer mensaje, para resaltar inputs concretos en un form. */
export type FieldErrors = Record<string, string>

/** Extrae errores por campo de un ApiError de DRF (ignora `detail`). */
export function erroresPorCampo(err: unknown): FieldErrors {
  const out: FieldErrors = {}
  if (!(err instanceof ApiError) || !err.body) return out
  for (const [campo, valor] of Object.entries(err.body)) {
    if (campo === 'detail' || valor === undefined) continue
    const txt = Array.isArray(valor) ? valor.join(' ') : String(valor)
    if (txt) out[campo] = txt
  }
  return out
}

/** true si el error es un 403 (sin permiso). El backend es la autoridad. */
export function esSinPermiso(err: unknown): boolean {
  return err instanceof ApiError && err.status === 403
}
