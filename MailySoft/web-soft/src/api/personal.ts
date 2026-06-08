/** api/personal — doctores y consultorios (lectura para los selectores de agenda). */

import { request } from '../lib/http'
import type { Paginated } from '../types/paciente'
import type { Consultorio, Doctor } from '../types/personal'

/** GET /personal/doctores/ — lista de doctores del tenant. */
export async function listDoctors(): Promise<Paginated<Doctor>> {
  return request<Paginated<Doctor>>('/personal/doctores/')
}

/** GET /personal/consultorios/ — lista de consultorios del tenant. */
export async function listConsultorios(): Promise<Paginated<Consultorio>> {
  return request<Paginated<Consultorio>>('/personal/consultorios/')
}
