/**
 * Tipos del dominio Paciente — reflejan EXACTAMENTE el backend
 * (apps/pacientes/serializers.py y views.py).
 */

/** Sexo según NOM-024 (backend: Sex.choices). Ojo: "Otro" es 'X', no 'O'. */
export type Sex = 'M' | 'F' | 'X'

/** Respuesta de lista/detalle (PatientOutputSerializer). */
export interface PatientOut {
  id: string
  full_name: string
  /** URL de la foto del paciente, o null. */
  avatar: string | null
  first_name: string
  paternal_surname: string
  maternal_surname: string
  date_of_birth: string | null // ISO yyyy-mm-dd; null en provisionales
  sex: Sex | '' // '' en provisionales
  sex_display: string
  curp: string
  phone: string
  email: string
  record_number: string
  notes: string
  is_active: boolean
  /** true = expediente provisional creado al vuelo desde la agenda; faltan datos personales. */
  is_provisional: boolean
  created_at: string // ISO datetime
}

/** Cuerpo para el alta rápida/provisional (POST /pacientes/rapido/). */
export interface PatientQuickCreateInput {
  first_name: string
  paternal_surname: string
  maternal_surname?: string
  phone?: string
}

/** Cuerpo para crear un paciente (POST). El expediente lo asigna el backend. */
export interface PatientCreateInput {
  first_name: string
  paternal_surname: string
  maternal_surname?: string
  date_of_birth: string
  sex: Sex
  phone: string
  curp?: string
  email?: string
  notes?: string
}

/** Cuerpo para actualización parcial (PATCH). Sin is_active (solo se da de baja vía DELETE). */
export type PatientUpdateInput = Partial<PatientCreateInput>

/** Envoltura de paginación de DRF (PageNumberPagination). */
export interface Paginated<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}
