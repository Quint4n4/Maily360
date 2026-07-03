/**
 * Tipos del panel interno de plataforma (equipo Maily).
 *
 * FASE 5 — ADOPCIÓN DE TIPOS OPENAPI:
 * Los tipos de SALIDA de la API ahora DERIVAN del esquema OpenAPI autogenerado
 * (`src/types/openapi.d.ts`, generado con `npm run types:api`). En vez de
 * duplicar a mano la forma de cada respuesta, tomamos `components['schemas'][…]`.
 * Un cambio en un serializer del backend se propaga al regenerar el esquema y,
 * si algo deja de cuadrar, el frontend deja de compilar.
 *
 * Regla de derivación aplicada:
 *   - Los OUTPUT que calzan 1:1 se re-exportan tal cual del esquema.
 *   - Donde el backend documenta un campo como `CharField` genérico (string)
 *     pero el frontend depende de un ENUM estrecho para la UX (indexar
 *     ESTADO_CLINICA[…], ALERTA_SUSCRIPCION[…], etc.), ESTRECHAMOS el campo con
 *     `Omit<…> & { campo: EnumEstrecho }`. Esto NO es una discrepancia de
 *     contrato: el backend devuelve exactamente esos valores; el serializer solo
 *     no los declara como choices, así que el esquema pierde el enum. El
 *     estrechamiento es deliberado y del lado del cliente.
 *   - Los INPUT (formularios) se mantienen a mano: el esquema los expone como
 *     `…Request` con campos opcionales-por-default que ensucian los formularios;
 *     documentado abajo endpoint por endpoint.
 */

import type { components } from './openapi'

import type { EstadoClinica } from '../data/clinicas'

export type { EstadoClinica }

/** Atajo al mapa de esquemas OpenAPI. */
type Schemas = components['schemas']

/** Rol del equipo interno de Maily. */
export type PlatformRoleApi = 'super_admin' | 'sales' | 'engineering' | ''

/**
 * Una clínica (Tenant) vista desde la plataforma, con conteos.
 * DERIVADO de `ClinicaOutput`; solo se estrecha `status` (el backend lo
 * documenta como string, pero siempre es un EstadoClinica y la UI lo indexa).
 */
export type ClinicaPlat = Omit<Schemas['ClinicaOutput'], 'status'> & {
  status: EstadoClinica
}

/**
 * Resumen de una clínica reciente (para el dashboard).
 * DERIVADO de `UltimaClinicaOutput`; se estrecha `status` a EstadoClinica.
 */
export type UltimaClinica = Omit<Schemas['UltimaClinicaOutput'], 'status'> & {
  status: EstadoClinica
}

/**
 * Métricas globales del dashboard de plataforma.
 * DERIVADO de `DashboardMetricsOutput`. `clinicas_por_estado` se estrecha de
 * `{ [k: string]: number }` a `Partial<Record<EstadoClinica, number>>`, y
 * `ultimas_clinicas` a nuestro `UltimaClinica` estrechado.
 */
export type DashboardMetrics = Omit<
  Schemas['DashboardMetricsOutput'],
  'clinicas_por_estado' | 'ultimas_clinicas'
> & {
  clinicas_por_estado: Partial<Record<EstadoClinica, number>>
  ultimas_clinicas: UltimaClinica[]
}

/**
 * Un usuario del equipo interno de Maily.
 * DERIVADO de `PlatformStaffOutput`; se estrecha `platform_role` (el backend
 * lo documenta como string; siempre es un PlatformRoleApi).
 */
export type PlatformStaff = Omit<Schemas['PlatformStaffOutput'], 'platform_role'> & {
  platform_role: PlatformRoleApi
}

/** Rol asignable a un miembro del equipo (sin la variante vacía de lectura). */
export type PlatformRoleAsignable = Exclude<PlatformRoleApi, ''>

/** Cuerpo para dar de alta a un miembro del equipo (POST /plataforma/usuarios/). */
export interface StaffFormInput {
  email: string
  first_name: string
  last_name: string
  platform_role: PlatformRoleAsignable
}

/**
 * Cuerpo para editar a un miembro (PATCH /plataforma/usuarios/<user_id>/).
 * Subconjunto: solo se mandan los campos que cambian. El backend responde 400
 * si intentas cambiar tu PROPIO is_active o platform_role.
 */
export interface StaffUpdateInput {
  first_name?: string
  last_name?: string
  platform_role?: PlatformRoleAsignable
  is_active?: boolean
}

/**
 * Resultado del alta de un miembro: incluye la contraseña temporal.
 * Se muestra UNA sola vez; ninguna otra respuesta la vuelve a incluir.
 * DERIVADO de `StaffCreateOutput` (se estrecha `platform_role`, igual que
 * PlatformStaff).
 */
export type StaffCreateResult = Omit<Schemas['StaffCreateOutput'], 'platform_role'> & {
  platform_role: PlatformRoleApi
}

/**
 * Respuesta de POST /plataforma/usuarios/<user_id>/reset-password/ (mostrar UNA vez).
 * DERIVADO de `StaffPasswordResetOutput` (calza 1:1).
 */
export type StaffResetPasswordResult = Schemas['StaffPasswordResetOutput']

/** Cuerpo para dar de alta una clínica nueva (POST /plataforma/clinicas/). */
export interface ClinicaCreateInput {
  name: string
  owner_email: string
  owner_first_name: string
  owner_last_name: string
  timezone?: string
  trial_days?: number
}

/**
 * Resultado del alta: incluye la contraseña temporal (mostrar UNA sola vez).
 * DERIVADO de `ClinicaCreateOutput`; se estrecha `tenant` a nuestro ClinicaPlat
 * (que a su vez estrecha `status`).
 */
export type ClinicaCreateResult = Omit<Schemas['ClinicaCreateOutput'], 'tenant'> & {
  tenant: ClinicaPlat
}

/**
 * Un miembro de la clínica (dentro de la ficha).
 * DERIVADO de `ClinicaMemberOutput` (calza 1:1).
 */
export type ClinicaMember = Schemas['ClinicaMemberOutput']

/**
 * Un evento del log de auditoría cross-tenant (GET /plataforma/auditoria/).
 * DERIVADO de `AuditLogOutput`.
 *
 * DISCREPANCIA de contrato detectada (ver reporte): el frontend asumía a mano
 * `actor_role: string | null` y `resource_type: string | null`, pero el esquema
 * los declara como `string` NO nullable (el serializer usa
 * `CharField(read_only=True)` sin `allow_null=True`, aunque el modelo AuditLog
 * SÍ permite null en esas columnas). Se conserva el comportamiento previo del
 * frontend (los trata como nullable) estrechándolos localmente a `| null`, para
 * no romper el manejo defensivo existente. `metadata` se estrecha de `unknown`
 * (JSONField) al `Record<string, unknown>` que la UI ya esperaba.
 */
export type AuditoriaEvento = Omit<
  Schemas['AuditLogOutput'],
  'actor_role' | 'resource_type' | 'metadata'
> & {
  actor_role: string | null
  resource_type: string | null
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
  // Suscripciones
  { value: 'SUBSCRIPTION_CHANGE',    label: 'Cambio de suscripción' },
  { value: 'TRIAL_EXPIRED',          label: 'Prueba vencida' },
  { value: 'SUBSCRIPTION_EXPIRED',   label: 'Suscripción vencida' },
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

/* ── Suscripciones (Fase 3) ─────────────────────────────────────────────── */

/**
 * Un plan comercial de la plataforma (GET /plataforma/planes/; array SIN paginar).
 * DERIVADO de `PlanOutput` (calza 1:1; price_monthly es decimal como string).
 */
export type PlanPlataforma = Schemas['PlanOutput']

/**
 * Cuerpo para crear/editar un plan (POST /plataforma/planes/ y
 * PATCH /plataforma/planes/<id>/; solo super_admin). El slug lo genera
 * el backend a partir del nombre y NUNCA se manda ni cambia.
 * En PATCH se envía un subconjunto (todos los campos son opcionales ahí).
 */
export interface PlanFormInput {
  name: string
  price_monthly: string // decimal como string, p. ej. "1500.00"
  description?: string
  is_featured?: boolean
  features?: string[]
  is_active?: boolean
  order?: number
}

/** Ciclo de cobro de una suscripción. */
export type BillingCycle = 'monthly' | 'annual'

/** Alerta de vencimiento calculada por el backend (solo aviso; la suspensión es manual). */
export type AlertaSuscripcion =
  | 'trial_vencido'
  | 'trial_por_vencer'
  | 'periodo_vencido'
  | 'periodo_por_vencer'

/** Etiqueta + badge por tipo de alerta (mismo lenguaje visual que ESTADO_CLINICA). */
export const ALERTA_SUSCRIPCION: Record<AlertaSuscripcion, { label: string; badge: string }> = {
  trial_vencido:      { label: 'Prueba vencida',     badge: 'badge-danger' },
  trial_por_vencer:   { label: 'Prueba por vencer',  badge: 'badge-warning' },
  periodo_vencido:    { label: 'Periodo vencido',    badge: 'badge-danger' },
  periodo_por_vencer: { label: 'Periodo por vencer', badge: 'badge-warning' },
}

/**
 * Una clínica con su plan (item de GET /plataforma/suscripciones/).
 * DERIVADO de `SubscriptionRowOutput`. Se estrechan a enums los campos que el
 * backend documenta como string genérico pero que la UI indexa/compara:
 * `tenant_status` (EstadoClinica), `billing_cycle` (BillingCycle) y `alerta`
 * (AlertaSuscripcion, indexa ALERTA_SUSCRIPCION[…]).
 */
export type SuscripcionRow = Omit<
  Schemas['SubscriptionRowOutput'],
  'tenant_status' | 'billing_cycle' | 'alerta'
> & {
  tenant_status: EstadoClinica
  billing_cycle: BillingCycle | null
  alerta: AlertaSuscripcion | null
}

/** Filtros de la lista de suscripciones (query params del endpoint). */
export interface SuscripcionesFiltros {
  search?: string
  plan_id?: string
  alerta?: 'vencidas' | 'por_vencer'
  page?: number
  page_size?: number
}

/**
 * Respuesta de GET /plataforma/suscripciones/resumen/.
 * DERIVADO de `SubscripcionesResumenOutput` (calza 1:1; incluye los sub-objetos
 * `por_plan` y `alertas` derivados de sus propios componentes).
 */
export type SuscripcionesResumen = Schemas['SubscripcionesResumenOutput']

/** Cuerpo de POST /plataforma/clinicas/<tenant_id>/suscripcion/. */
export interface SuscripcionAsignarInput {
  plan_id: string
  billing_cycle: BillingCycle
  current_period_end: string // YYYY-MM-DD
}

/** Estado de salud de un servicio o del sistema completo. */
export type SistemaEstado = 'operational' | 'degraded' | 'down'

/**
 * Un servicio monitoreado (PostgreSQL, Redis, worker Celery…).
 * DERIVADO de `SystemServiceOutput`; se estrecha `status` a SistemaEstado.
 */
export type SistemaServicio = Omit<Schemas['SystemServiceOutput'], 'status'> & {
  status: SistemaEstado
}

/**
 * Versión desplegada del backend.
 * DERIVADO de `SystemVersionOutput` (calza 1:1).
 */
export type SistemaVersion = Schemas['SystemVersionOutput']

/**
 * Estado de la cola de PDFs (Celery).
 * DERIVADO de `SystemPdfQueueOutput` (calza 1:1).
 */
export type SistemaPdfQueue = Schemas['SystemPdfQueueOutput']

/**
 * Respuesta de GET /plataforma/sistema/ — salud del sistema (super_admin / engineering).
 * DERIVADO de `SystemHealthOutput`; se estrechan `overall_status` a
 * SistemaEstado y `services` a nuestro SistemaServicio (que estrecha su status).
 */
export type SistemaSalud = Omit<
  Schemas['SystemHealthOutput'],
  'overall_status' | 'services'
> & {
  overall_status: SistemaEstado
  services: SistemaServicio[]
}

/**
 * Ficha de detalle de una clínica.
 * DERIVADO de `ClinicaDetailOutput`; se estrecha `status` a EstadoClinica y
 * `members` a nuestro ClinicaMember.
 */
export type ClinicaDetail = Omit<
  Schemas['ClinicaDetailOutput'],
  'status' | 'members'
> & {
  status: EstadoClinica
  members: ClinicaMember[]
}
