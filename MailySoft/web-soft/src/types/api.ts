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
import type { ModuloId } from '../lib/modulos'
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
  /**
   * Id del perfil Doctor del usuario en el tenant activo; null si no ejerce.
   * Incluye a dueño y administrador con cédula: el perfil de médico es una
   * capacidad profesional, no un cargo.
   */
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
  /**
   * Qué tiene CONTRATADA la clínica activa. null si no hay clínica activa.
   *
   * El frontend OCULTA con esto; el backend BLOQUEA con la misma fuente
   * (apps/tenancy/entitlements.py) y responde 404 a un módulo no contratado.
   * Por eso nunca se contradicen: ocultar aquí es experiencia, no seguridad.
   */
  capabilities: Capabilities | null
}

/** Derechos efectivos de una clínica (plan + ajustes a la medida). */
export interface Capabilities {
  plan_slug: string
  plan_name: string
  /** Slugs de apps/core/modules.py Module contratados. */
  modules: ModuloId[]
  /** Roles asignables, derivados de los módulos. */
  roles: ClinicRole[]
  /** null = ilimitado. */
  max_sucursales: number | null
  max_consultorios: number | null
  max_usuarios: number | null
  /** max_sucursales === 1: se oculta TODA la UI de sucursales. */
  sede_unica: boolean
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
