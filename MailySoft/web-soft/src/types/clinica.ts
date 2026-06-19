/**
 * Tipos del dominio Clínica — "Mi Consultorio".
 * Reflejan EXACTAMENTE los serializers del backend (apps/clinica/serializers.py).
 *
 * Imágenes (logo, membretes, sello, foto, logos de universidad): se envían como
 * multipart (igual que el avatar de paciente) y el backend las devuelve como
 * URLs absolutas en la salida.
 */

import type { Paginated } from './paciente'

export type { Paginated }

/* ─────────────────────────────────────────────────────────────────────────
   Configuración de la clínica  (clinica/configuracion/)
   ──────────────────────────────────────────────────────────────────────── */

/** Un contacto de WhatsApp para el envío (simulado) de recetas. */
export interface WhatsAppContact {
  nombre: string
  numero: string
}

/** Salida de ClinicSettings (ClinicSettingsOutputSerializer). */
export interface ClinicSettingsOut {
  id: string
  /** Nombre comercial de la clínica para el membrete (COFEPRIS F2). */
  commercial_name: string
  /** URL absoluta del logo, o null si no hay. */
  logo: string | null
  address: string
  address_2: string
  phone: string
  mobile: string
  email: string
  website: string
  facebook: string
  instagram: string
  youtube: string
  /** URL absoluta del membrete completo, o null. */
  letterhead_full: string | null
  /** URL absoluta del medio membrete, o null. */
  letterhead_half: string | null
  letterhead_full_spaces: number
  letterhead_half_spaces: number
  recipe_use_responsible_doctor: boolean
  recipe_whatsapp_contacts: WhatsAppContact[]
  created_at: string
  updated_at: string
}

/**
 * Campos de texto/numéricos/booleanos editables vía PUT (multipart).
 * Las imágenes se adjuntan aparte como File (ver ClinicSettingsUpdateInput).
 * Todos opcionales: el PUT es un upsert parcial (solo actualiza lo enviado).
 */
export interface ClinicSettingsFields {
  /** Nombre comercial de la clínica para el membrete (COFEPRIS F2). */
  commercial_name?: string
  address?: string
  address_2?: string
  phone?: string
  mobile?: string
  email?: string
  website?: string
  facebook?: string
  instagram?: string
  youtube?: string
  letterhead_full_spaces?: number
  letterhead_half_spaces?: number
  recipe_use_responsible_doctor?: boolean
  recipe_whatsapp_contacts?: WhatsAppContact[]
}

/** Imágenes opcionales para el PUT de configuración. */
export interface ClinicSettingsImages {
  logo?: File
  letterhead_full?: File
  letterhead_half?: File
}

/** Cuerpo combinado para actualizar la configuración (PUT multipart). */
export type ClinicSettingsUpdateInput = ClinicSettingsFields & ClinicSettingsImages

/* ─────────────────────────────────────────────────────────────────────────
   Plantillas clínicas  (clinica/plantillas/)
   ──────────────────────────────────────────────────────────────────────── */

/** Tipo de plantilla (backend: ChoiceField). */
export type TemplateKind = 'recipe' | 'document' | 'consent'

/** Límite de caracteres del cuerpo (backend: max_length=50_000). */
export const TEMPLATE_BODY_MAX = 50_000

/** Salida de ClinicTemplate (ClinicTemplateOutputSerializer). */
export interface ClinicTemplateOut {
  id: string
  kind: TemplateKind
  name: string
  body: string
  group: string
  is_active: boolean
  created_at: string
  updated_at: string
}

/** Cuerpo para crear una plantilla (POST). */
export interface ClinicTemplateCreateInput {
  kind: TemplateKind
  name: string
  body: string
  group?: string
}

/** Cuerpo para actualización parcial (PATCH). Todos opcionales. */
export type ClinicTemplateUpdateInput = Partial<ClinicTemplateCreateInput>

/* ─────────────────────────────────────────────────────────────────────────
   Categorías de paciente  (clinica/categorias/)
   ──────────────────────────────────────────────────────────────────────── */

/** Salida de PatientCategory (PatientCategoryOutputSerializer). */
export interface PatientCategoryOut {
  id: string
  name: string
  is_active: boolean
  created_at: string
}

/** Cuerpo para crear una categoría (POST). */
export interface PatientCategoryCreateInput {
  name: string
}

/* ─────────────────────────────────────────────────────────────────────────
   Perfil ampliado del médico  (clinica/doctores/<id>/...)
   ──────────────────────────────────────────────────────────────────────── */

/**
 * Salida del perfil médico tras el PATCH (DoctorOutputSerializer de personal).
 * Incluye sello/foto (URLs absolutas) y cédulas adicionales.
 */
export interface DoctorProfileOut {
  id: string
  full_name: string
  user_email: string
  role: string
  cedula_profesional: string
  specialty: string
  default_appointment_duration: number
  bio_short: string
  /** URL absoluta del sello, o null. */
  sello: string | null
  /** URL absoluta de la foto, o null. */
  foto: string | null
  /** Cédulas adicionales separadas por coma. */
  cedulas_adicionales: string
  is_active: boolean
  created_at: string
}

/**
 * Cuerpo para el PATCH del perfil médico (multipart).
 * Las imágenes (sello/foto) son File; cedulas_adicionales es texto.
 */
export interface DoctorProfileUpdateInput {
  sello?: File
  foto?: File
  cedulas_adicionales?: string
}

/** Salida de DoctorUniversity (DoctorUniversityOutputSerializer). */
export interface DoctorUniversityOut {
  id: string
  /** URL absoluta del logo. */
  logo: string
  name: string
  created_at: string
}

/** Cuerpo para agregar una universidad (POST multipart). */
export interface DoctorUniversityCreateInput {
  logo: File
  name?: string
}
