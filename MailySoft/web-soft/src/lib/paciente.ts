/**
 * Helpers de presentación para Paciente (puros, sin lógica de negocio).
 * El nombre completo y la etiqueta de sexo ya vienen del backend
 * (full_name, sex_display); aquí solo lo que el front necesita calcular.
 */

import type { PatientOut, Sex } from '../types/paciente'

export const SEX_LABEL: Record<Sex, string> = {
  M: 'Masculino',
  F: 'Femenino',
  X: 'Otro',
}

/** Iniciales a partir de nombre + apellido paterno. */
export function initialsOf(p: Pick<PatientOut, 'first_name' | 'paternal_surname'>): string {
  const a = p.first_name?.[0] ?? ''
  const b = p.paternal_surname?.[0] ?? ''
  return `${a}${b}`.toUpperCase()
}

/** Edad en años a partir de una fecha ISO yyyy-mm-dd. Devuelve null si la fecha es inválida. */
export function edad(fechaISO: string): number | null {
  const partes = fechaISO?.split('-').map(Number)
  if (!partes || partes.length !== 3 || partes.some(Number.isNaN)) return null
  const [y, m, d] = partes
  const hoy = new Date()
  let e = hoy.getFullYear() - y
  if (hoy.getMonth() + 1 < m || (hoy.getMonth() + 1 === m && hoy.getDate() < d)) e--
  return e
}
