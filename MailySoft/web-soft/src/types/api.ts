/**
 * Tipos del contrato de la API (lo que devuelve el backend Django/DRF).
 *
 * Estos tipos reflejan EXACTAMENTE los serializers del backend
 * (apps/authn/serializers.py). Si el backend cambia el contrato, se actualiza
 * aquí.
 *
 * PIPELINE OPENAPI (Fase 5): ya existe generación de tipos desde el esquema
 * OpenAPI (drf-spectacular → openapi-typescript). Ver `openapi/README.md` y
 * `src/types/openapi.d.ts`. La ADOPCIÓN es gradual: el portal de plataforma
 * (`src/types/plataforma.ts`) ya deriva sus tipos de salida del esquema; el
 * resto de dominios de este archivo se mantiene a mano por ahora y se migrará
 * endpoint por endpoint.
 */

import type { ClinicRole } from '../auth/permisos'
import type { SucursalBrief } from './sucursal'

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
  /**
   * true si la contraseña es temporal y el backend exige cambiarla antes de
   * usar la app (responde 403 password_change_required en endpoints de negocio).
   */
  must_change_password: boolean
  /** Si el usuario es médico, el id de su perfil Doctor en el tenant activo; null si no. */
  doctor_id: string | null
  active_tenant: TenantBrief | null
  active_role: ClinicRole | null
  active_role_display: string | null
  memberships: Membership[]
  /**
   * Sucursales (sedes) PERMITIDAS del usuario en el tenant activo. Multi-sede
   * (Fase 1): el frontend inicializa la sucursal activa tomando la `is_default`.
   * Puede venir vacío en clínicas aún sin sucursales configuradas.
   */
  sucursales: SucursalBrief[]
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
  /** Código de error de negocio (ej. 'password_change_required' en un 403). */
  code?: string
  /** Errores por campo (validación). */
  [field: string]: string | string[] | undefined
}
