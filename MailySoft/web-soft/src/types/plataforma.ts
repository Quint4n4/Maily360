/** Tipos del panel interno de plataforma (equipo Maily) — reflejan apps/plataforma/serializers.py. */

import type { EstadoClinica } from '../data/clinicas'

export type { EstadoClinica }

/** Rol del equipo interno de Maily. */
export type PlatformRoleApi = 'super_admin' | 'sales' | 'engineering' | ''

/** Una clínica (Tenant) vista desde la plataforma, con conteos. */
export interface ClinicaPlat {
  id: string
  name: string
  slug: string
  status: EstadoClinica
  status_display: string
  trial_ends_at: string | null // ISO
  created_at: string // ISO
  member_count: number
  patient_count: number
}

/** Resumen de una clínica reciente (para el dashboard). */
export interface UltimaClinica {
  id: string
  name: string
  status: EstadoClinica
  created_at: string
}

/** Métricas globales del dashboard de plataforma. */
export interface DashboardMetrics {
  total_clinicas: number
  clinicas_por_estado: Partial<Record<EstadoClinica, number>>
  total_usuarios: number
  total_platform_staff: number
  total_pacientes: number
  ultimas_clinicas: UltimaClinica[]
}

/** Un usuario del equipo interno de Maily. */
export interface PlatformStaff {
  id: string
  email: string
  full_name: string
  platform_role: PlatformRoleApi
  platform_role_display: string
  is_active: boolean
}

/** Cuerpo para dar de alta una clínica nueva (POST /plataforma/clinicas/). */
export interface ClinicaCreateInput {
  name: string
  owner_email: string
  owner_first_name: string
  owner_last_name: string
  timezone?: string
  trial_days?: number
}

/** Resultado del alta: incluye la contraseña temporal (mostrar UNA sola vez). */
export interface ClinicaCreateResult {
  tenant: ClinicaPlat
  owner_email: string
  temporary_password: string
}

/** Un miembro de la clínica (dentro de la ficha). */
export interface ClinicaMember {
  id: string
  full_name: string
  email: string
  role: string
  role_display: string
  is_active: boolean
}

/** Ficha de detalle de una clínica. */
export interface ClinicaDetail {
  id: string
  name: string
  slug: string
  status: EstadoClinica
  status_display: string
  trial_ends_at: string | null
  created_at: string
  member_count: number
  patient_count: number
  appointment_count: number
  ultima_actividad: string | null
  members: ClinicaMember[]
}
