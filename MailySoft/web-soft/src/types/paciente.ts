/**
 * Tipos del dominio Paciente — reflejan EXACTAMENTE el backend
 * (apps/pacientes/serializers.py y views.py).
 */

/** Sexo según NOM-024 (backend: Sex.choices). Ojo: "Otro" es 'X', no 'O'. */
export type Sex = 'M' | 'F' | 'X'

/** Estado civil NOM-004 (backend: MaritalStatus.choices). '' = sin especificar. */
export type MaritalStatus = 'soltero' | 'casado' | 'union_libre' | 'divorciado' | 'viudo' | 'otro' | ''

/** Escolaridad NOM-004 (backend: Education.choices). '' = sin especificar. */
export type Education =
  | 'ninguna'
  | 'primaria'
  | 'secundaria'
  | 'preparatoria'
  | 'licenciatura'
  | 'posgrado'
  | ''

/** Tipo de sangre NOM-004 (backend: BloodType.choices). '' = sin especificar. */
export type BloodType = 'A+' | 'A-' | 'B+' | 'B-' | 'AB+' | 'AB-' | 'O+' | 'O-' | 'desconocido' | ''

/** Respuesta de lista/detalle (PatientOutputSerializer). */
/** Etiqueta (categoría del catálogo) asignada a un paciente. */
export interface PatientTag {
  id: string
  name: string
}

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
  /** Marcado como favorito (visible para toda la clínica). */
  is_favorite: boolean
  /** Paciente VIP (visible para toda la clínica). */
  is_vip: boolean
  /** Fecha/hora de la última cita ATENDIDA (ISO), o null si nunca ha sido atendido. */
  last_seen_at: string | null
  /** Cuántas citas atendidas tiene en total. */
  attended_count: number | null
  /** Motivo ("¿a qué viene?") de la última cita cancelada/reagendada, o null.
   *  Útil para precargar el motivo al "volver a agendar" a un cliente potencial. */
  last_reason: string | null
  // ── Campos NOM-004 (expediente A1, plan §3.1) ──
  address_street: string
  address_neighborhood: string
  city: string
  state: string
  postal_code: string
  birthplace: string
  marital_status: MaritalStatus
  marital_status_display: string
  education: Education
  education_display: string
  occupation: string
  religion: string
  blood_type: BloodType
  blood_type_display: string
  phone_secondary: string
  phone_label: string
  is_deceased: boolean
  /** ISO yyyy-mm-dd; null si vive. */
  deceased_at: string | null
  /** Tarifa de consulta personalizada (string decimal de DRF) o null. */
  custom_consultation_fee: string | null
  category: string
  /** Etiquetas del catálogo asignadas al paciente (clasificación nueva). */
  categories: PatientTag[]
  created_at: string // ISO datetime
}

/** Segmentos de filtrado de la lista de pacientes (reflejan el selector backend). */
export type PatientSegment =
  | 'all'
  | 'recent'
  | 'week'
  | 'month'
  | 'date'
  | 'potential'
  | 'favorites'
  | 'vip'

/** Cuerpo para marcar/desmarcar favorito y/o VIP (POST /pacientes/<id>/clasificacion/). */
export interface PatientClassifyInput {
  is_favorite?: boolean
  is_vip?: boolean
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

/**
 * Campos NOM-004 editables vía PATCH (expediente A1).
 * Solo existen en el PATCH de Patient, no en el alta (POST). Todos opcionales.
 */
export interface PatientNom004Input {
  address_street?: string
  address_neighborhood?: string
  city?: string
  state?: string
  postal_code?: string
  birthplace?: string
  marital_status?: MaritalStatus
  education?: Education
  occupation?: string
  religion?: string
  blood_type?: BloodType
  phone_secondary?: string
  phone_label?: string
  is_deceased?: boolean
  deceased_at?: string | null
  custom_consultation_fee?: number | null
  category?: string
  /** IDs de las etiquetas del catálogo a asignar (reemplaza el set completo). */
  category_ids?: string[]
}

/** Cuerpo para actualización parcial (PATCH). Sin is_active (solo se da de baja vía DELETE). */
export type PatientUpdateInput = Partial<PatientCreateInput> & PatientNom004Input

/** Envoltura de paginación de DRF (PageNumberPagination). */
export interface Paginated<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}
