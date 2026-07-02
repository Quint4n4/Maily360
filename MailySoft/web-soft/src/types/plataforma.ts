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

/** Un evento del log de auditoría cross-tenant (GET /plataforma/auditoria/). */
export interface AuditoriaEvento {
  id: string
  created_at: string // ISO
  action: string
  action_display: string
  actor_email: string | null
  actor_role: string | null
  tenant_id: string | null
  tenant_name: string | null
  resource_type: string | null
  resource_id: string | null
  description: string
  ip_address: string | null
  metadata: Record<string, unknown>
}

/** Filtros de la lista de auditoría (query params del endpoint). */
export interface AuditoriaFiltros {
  tenant_id?: string
  action?: string
  actor_id?: string
  date_from?: string // YYYY-MM-DD
  date_to?: string // YYYY-MM-DD
  search?: string
  page?: number
  page_size?: number
}

/**
 * Catálogo de acciones para el filtro (subconjunto relevante de
 * apps/audit/models.py::ActionType; value = choice del backend).
 */
export const ACCIONES_AUDITORIA: { value: string; label: string }[] = [
  // Autenticación
  { value: 'LOGIN',                  label: 'Inicio de sesión' },
  { value: 'LOGOUT',                 label: 'Cierre de sesión' },
  { value: 'LOGIN_FAILED',           label: 'Intento de sesión fallido' },
  // Plataforma (cross-tenant)
  { value: 'TENANT_CREATE',          label: 'Crear clínica nueva' },
  { value: 'TENANT_STATUS_CHANGE',   label: 'Cambiar estado de clínica' },
  // Pacientes
  { value: 'PATIENT_CREATE',         label: 'Crear paciente' },
  { value: 'PATIENT_UPDATE',         label: 'Actualizar paciente' },
  { value: 'PATIENT_DEACTIVATE',     label: 'Desactivar paciente' },
  { value: 'PATIENT_BOOK_VIEW',      label: 'Consultar libro clínico' },
  { value: 'PATIENT_BOOK_PDF',       label: 'Generar PDF del libro clínico' },
  // Citas
  { value: 'APPOINTMENT_CREATE',     label: 'Crear cita' },
  { value: 'APPOINTMENT_UPDATE',     label: 'Actualizar cita' },
  { value: 'APPOINTMENT_STATUS',     label: 'Cambiar estado de cita' },
  { value: 'APPOINTMENT_RESCHEDULE', label: 'Reagendar cita' },
  // Miembros de la clínica
  { value: 'MEMBER_CREATE',          label: 'Alta de miembro' },
  { value: 'MEMBER_UPDATE',          label: 'Actualizar miembro' },
  { value: 'MEMBER_BLOCK',           label: 'Bloquear/reactivar miembro' },
  { value: 'MEMBER_PASSWORD',        label: 'Restablecer contraseña' },
  // Recetas
  { value: 'PRESCRIPTION_CREATE',    label: 'Emitir receta médica' },
  { value: 'PRESCRIPTION_CANCEL',    label: 'Anular receta médica' },
  { value: 'PRESCRIPTION_PDF',       label: 'Generar PDF de receta' },
  // Finanzas
  { value: 'QUOTE_CREATE',           label: 'Crear cotización' },
  { value: 'CHARGE_CREATE',          label: 'Crear cargo' },
  { value: 'PAYMENT_REGISTER',       label: 'Registrar pago' },
  // Configuración
  { value: 'CLINIC_SETTINGS_UPDATE', label: 'Actualizar configuración de clínica' },
  { value: 'CONFIG_UPDATE',          label: 'Actualizar configuración de agenda' },
]

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
