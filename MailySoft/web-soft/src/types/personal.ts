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
  /**
   * Sucursales (sedes) ASIGNADAS al miembro (multi-sede, Fase 4).
   * Definen qué sedes puede ver y operar. Vacío = sin asignación explícita
   * (el owner ve todas; los demás roles caen en la sede por defecto).
   */
  sucursales: SucursalRefMin[]
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

export interface ConsultorioRefMin {
  id: string
  name: string
}

/** Referencia compacta a una sucursal, embebida en consultorios/doctores. */
export interface SucursalRefMin {
  id: string
  name: string
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
  /** URL absoluta del sello del médico, o null (perfil ampliado, apps/clinica). */
  sello: string | null
  /** URL absoluta de la foto del médico, o null. */
  foto: string | null
  /** Cédulas adicionales separadas por coma. */
  cedulas_adicionales: string
  /** Consultorios asignados al médico (vacío = puede usar cualquiera). */
  consultorios: ConsultorioRefMin[]
  /** Sucursales (sedes) donde opera el médico (multi-sede, Fase 1). */
  sucursales: SucursalRefMin[]
  is_active: boolean
  created_at: string
}

export interface Consultorio {
  id: string
  name: string
  location: string
  color_hex: string
  /** Sucursal (sede) a la que pertenece el consultorio, o null (multi-sede, F1). */
  sucursal: SucursalRefMin | null
  is_active: boolean
  created_at: string
}

/** Cuerpo para crear un consultorio (POST). */
export interface ConsultorioCreateInput {
  name: string
  location?: string
  /** Formato #RRGGBB; vacío permitido. */
  color_hex?: string
  /** Id de la sucursal a la que pertenece el consultorio (multi-sede, F1). */
  sucursal_id?: string
}

/** Cuerpo para actualización parcial de consultorio (PATCH). */
export type ConsultorioUpdateInput = Partial<ConsultorioCreateInput>

/** Cuerpo para actualización parcial de doctor (PATCH). */
export interface DoctorUpdateInput {
  cedula_profesional?: string
  specialty?: string
  default_appointment_duration?: number
  bio_short?: string
  /** Lista de ids de consultorios asignados al médico. */
  consultorio_ids?: string[]
  /** Lista de ids de sucursales donde opera el médico (multi-sede, F1). */
  sucursal_ids?: string[]
}

/** Cuerpo para crear un perfil de médico (POST). Liga a la membresía con rol doctor. */
export interface DoctorCreateInput {
  membership_id: string
  cedula_profesional?: string
  specialty?: string
  default_appointment_duration?: number
  bio_short?: string
}

// ── Horarios laborales del médico (DoctorSchedule) ───────────────────────────

/** Día de la semana del backend (Weekday): 0 = Lunes … 6 = Domingo. */
export type Weekday = 0 | 1 | 2 | 3 | 4 | 5 | 6

/**
 * Bloque de horario laboral de un médico. Refleja DoctorScheduleOutputSerializer.
 *
 * Multi-sede (Fase 2): el horario es POR SEDE — un médico puede atender L-V 9-14
 * en la Sucursal Centro y S 9-13 en la Sucursal Norte.
 *
 * OJO (contrato del backend): start_time/end_time están en hora LOCAL del tenant
 * (formato 'HH:MM:SS'), NO en UTC.
 */
export interface DoctorSchedule {
  id: string
  day_of_week: Weekday
  day_of_week_display: string
  start_time: string // 'HH:MM:SS' hora local del tenant
  end_time: string // 'HH:MM:SS' hora local del tenant
  consultorio: ConsultorioRefMin | null
  /** Sucursal (sede) a la que pertenece este horario, o null (multi-sede, F2). */
  sucursal: SucursalRefMin | null
  valid_from: string | null // 'yyyy-mm-dd'
  valid_until: string | null // 'yyyy-mm-dd'
  is_active: boolean
}

/** Cuerpo para crear un horario (POST /personal/doctores/<id>/horarios/). */
export interface DoctorScheduleCreateInput {
  day_of_week: Weekday
  start_time: string // 'HH:MM'
  end_time: string // 'HH:MM'
  consultorio_id?: string | null
  /** Sede del horario (multi-sede, F2). Si no se manda, el backend la deriva. */
  sucursal_id?: string | null
  valid_from?: string | null
  valid_until?: string | null
}
