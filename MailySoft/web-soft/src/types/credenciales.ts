/**
 * Tipos del dominio Credenciales del médico (COFEPRIS F2).
 * Reflejan EXACTAMENTE los serializers del backend
 * (apps/clinica/serializers.py — DoctorCredentialInput/OutputSerializer).
 *
 * COFEPRIS exige distinguir la cédula profesional (licenciatura), la cédula de
 * especialidad y los posgrados de forma estructurada (institución + número).
 * Sustituye funcionalmente al texto libre `cedulas_adicionales`.
 */

/** Tipo de credencial académica (models.CredentialKind.choices). */
export type CredentialKind = 'profesional' | 'especialidad' | 'posgrado'

/** Estado de validación de la credencial (flujo híbrido). */
export type CredentialValidationStatus = 'pendiente' | 'validada' | 'rechazada'

/** Salida de DoctorCredential (DoctorCredentialOutputSerializer). */
export interface DoctorCredentialOut {
  id: string
  title: string
  institution: string
  credential_number: string
  kind: CredentialKind
  /** Etiqueta legible del kind (get_kind_display del backend). */
  kind_display: string
  order: number
  is_active: boolean
  created_at: string
  /** URL del logo opcional de la institución que expide la credencial (o null). */
  logo_url: string | null
  /** Estado de validación: solo las 'validada' aparecen en la receta. */
  validation_status: CredentialValidationStatus
  /** Etiqueta legible del estado (get_validation_status_display del backend). */
  validation_status_display: string
  /** Motivo del rechazo / nota de la validación (puede estar vacío). */
  validation_note: string
  /** Id y nombre del médico dueño (útil en la bandeja del administrador). */
  doctor_id: string
  doctor_name: string
}

/** Cuerpo para validar/rechazar una credencial (solo owner/admin). */
export interface CredentialValidationInput {
  status: 'validada' | 'rechazada'
  note?: string
}

/**
 * Cuerpo para crear una credencial (DoctorCredentialInputSerializer).
 * title, institution y kind son obligatorios; el resto opcional.
 */
export interface DoctorCredentialCreateInput {
  title: string
  institution: string
  kind: CredentialKind
  credential_number?: string
  order?: number
  /** Logo opcional de la institución (se sube junto con la credencial, multipart). */
  logo?: File | null
}

/** Cuerpo para editar una credencial (PATCH parcial). Todos los campos opcionales. */
export interface DoctorCredentialUpdateInput {
  title?: string
  institution?: string
  kind?: CredentialKind
  credential_number?: string
  order?: number
  /** Nuevo logo de la institución (reemplaza el actual). Multipart. */
  logo?: File | null
}

/** Opciones de tipo de credencial (etiquetas en español). */
export const CREDENTIAL_KIND_OPTIONS: { value: CredentialKind; label: string }[] = [
  { value: 'profesional', label: 'Cédula profesional' },
  { value: 'especialidad', label: 'Cédula de especialidad' },
  { value: 'posgrado', label: 'Posgrado (maestría / doctorado)' },
]
