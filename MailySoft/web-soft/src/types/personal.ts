/** Tipos del dominio Personal (doctores y consultorios), reflejan el backend. */

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
