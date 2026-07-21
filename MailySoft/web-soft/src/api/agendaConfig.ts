/**
 * api/agendaConfig — Configuración de agenda de la clínica (horario que abarca
 * la agenda, intervalo de la rejilla y duración de consulta por defecto).
 *
 * Permisos backend: LECTURA para el staff (la agenda necesita saber el horario
 * para pintarse); ESCRITURA solo owner/admin. Un 403 se propaga para que la UI
 * lo refleje (el backend es la autoridad).
 */

import { http } from '../lib/http'
import type { AgendaConfig, AgendaConfigUpdateInput } from '../types/agendaConfig'

/** GET /agenda/config/ — configuración vigente de la clínica. */
export function getAgendaConfig(): Promise<AgendaConfig> {
  return http.get<AgendaConfig>('/agenda/config/')
}

/** PATCH /agenda/config/ — actualiza la configuración (solo owner/admin). */
export function updateAgendaConfig(input: AgendaConfigUpdateInput): Promise<AgendaConfig> {
  return http.patch<AgendaConfig>('/agenda/config/', input)
}
