/**
 * Tipos del contrato de la API (lo que devuelve el backend Django/DRF).
 *
 * Estos tipos reflejan EXACTAMENTE los serializers del backend
 * (apps/authn/serializers.py). Si el backend cambia el contrato, se actualiza
 * aquí. A futuro pueden autogenerarse desde el esquema OpenAPI (drf-spectacular)
 * con openapi-typescript; por ahora se mantienen a mano y acotados.
 */

import type { ClinicRole } from '../auth/permisos'

/** Estado de una clínica (Tenant.status en el backend). */
export type TenantStatus = 'trial' | 'active' | 'suspended' | 'canceled'

/** Representación compacta de una clínica (_TenantBriefSerializer). */
export interface TenantBrief {
  id: string
  name: string
  slug: string
  status: TenantStatus
}

/** Una membresía del usuario en una clínica (_MembershipSerializer). */
export interface Membership {
  tenant: TenantBrief
  role: ClinicRole
  role_display: string
  is_active: boolean
}

/** Respuesta de GET /api/v1/me/ (MeSerializer). */
export interface Me {
  id: string
  email: string
  first_name: string
  last_name: string
  full_name: string
  /** URL de la foto de perfil del usuario, o null. */
  avatar: string | null
  is_platform_staff: boolean
  platform_role: string
  /** Si el usuario es médico, el id de su perfil Doctor en el tenant activo; null si no. */
  doctor_id: string | null
  active_tenant: TenantBrief | null
  active_role: ClinicRole | null
  active_role_display: string | null
  memberships: Membership[]
}

/** Respuesta de POST /api/v1/auth/login/ (patrón híbrido: solo access en el body). */
export interface LoginResponse {
  access: string
}

/** Respuesta de POST /api/v1/auth/refresh/. */
export interface RefreshResponse {
  access: string
}

/** Forma típica de un error de DRF. */
export interface ApiErrorBody {
  detail?: string
  /** Errores por campo (validación). */
  [field: string]: string | string[] | undefined
}
