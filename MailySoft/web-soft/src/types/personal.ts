/** Tipos del dominio Personal (doctores, consultorios y miembros), reflejan el backend. */

import type { ClinicRole } from '../auth/permisos'

/** Usuario detrás de una membresía. */
export interface MemberUser {
  id: string
  email: string
  first_name: string
  last_name: string
  full_name: string
  /** URL de la foto del usuario, o null. */
  avatar: string | null
  /** is_active del usuario; false = cuenta bloqueada. */
  is_active: boolean
}

/** Un miembro de la clínica (TenantMembership + su usuario). */
export interface Member {
  id: string // id de la membresía
  user: MemberUser
  role: ClinicRole
  role_display: string
  is_active: boolean // membresía activa
  is_blocked: boolean // cuenta bloqueada (no puede iniciar sesión)
  created_at: string
}

/** Cuerpo para dar de alta un miembro (POST /miembros/). */
export interface MemberCreateInput {
  email: string
  first_name: string
  last_name: string
  password: string
  role: ClinicRole
}

/** Cuerpo para editar un miembro (PATCH /miembros/<id>/). */
export interface MemberUpdateInput {
  first_name?: string
  last_name?: string
  role?: ClinicRole
  /** Restablecer contraseña (nunca se lee, solo se escribe). */
  password?: string
  blocked?: boolean
}

export interface Doctor {
  id: string
  full_name: string
  user_email: string
  role: string
  cedula_profesional: string
  specialty: string
  default_appointment_duration: number
  bio_short: string
  is_active: boolean
  created_at: string
}

export interface Consultorio {
  id: string
  name: string
  location: string
  color_hex: string
  is_active: boolean
  created_at: string
}

/** Cuerpo para crear un consultorio (POST). */
export interface ConsultorioCreateInput {
  name: string
  location?: string
  /** Formato #RRGGBB; vacío permitido. */
  color_hex?: string
}

/** Cuerpo para actualización parcial de consultorio (PATCH). */
export type ConsultorioUpdateInput = Partial<ConsultorioCreateInput>

/** Cuerpo para actualización parcial de doctor (PATCH). */
export interface DoctorUpdateInput {
  cedula_profesional?: string
  specialty?: string
  default_appointment_duration?: number
  bio_short?: string
}

/** Cuerpo para crear un perfil de médico (POST). Liga a la membresía con rol doctor. */
export interface DoctorCreateInput {
  membership_id: string
  cedula_profesional?: string
  specialty?: string
  default_appointment_duration?: number
  bio_short?: string
}
