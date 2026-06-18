<<<<<<< Updated upstream
=======
<<<<<<< HEAD
/**
 * Matriz de permisos del módulo Finanzas — SOLO para gating de UX.
 *
 * El backend es la autoridad real (apps/core/permissions.py). Esto solo decide
 * qué botones/tabs mostrar para no ofrecer acciones que el backend rechazaría.
 * Refleja la sección 2 del plan (matriz reconciliada).
 */

export type Role =
  | 'owner'
  | 'admin'
  | 'doctor'
  | 'nurse'
  | 'reception'
  | 'finance'
  | 'readonly'

/** Capacidades discretas del módulo finanzas. */
export type FinanceCapability =
  | 'viewDashboard'
  | 'viewModule'
  | 'manageConcepts'
  | 'manageFiscalConfig'
  | 'createQuote'
  | 'createCharge'
  | 'registerPayment'
  | 'issueCfdi'
  | 'viewCfdi'
  | 'viewStatement'

const VIEW_ROLES: Role[] = ['owner', 'admin', 'finance', 'reception', 'readonly']
const DESK_ROLES: Role[] = ['owner', 'admin', 'finance', 'reception']
const CORE_ROLES: Role[] = ['owner', 'admin', 'finance']
const MANAGE_ROLES: Role[] = ['owner', 'admin']
const DASHBOARD_ROLES: Role[] = ['owner', 'admin', 'finance', 'readonly']
const CFDI_VIEW_ROLES: Role[] = ['owner', 'admin', 'finance', 'readonly']

const MATRIX: Record<FinanceCapability, Role[]> = {
  viewModule: VIEW_ROLES,
  viewDashboard: DASHBOARD_ROLES,
  viewStatement: VIEW_ROLES,
  viewCfdi: CFDI_VIEW_ROLES,
  manageConcepts: MANAGE_ROLES,
  manageFiscalConfig: MANAGE_ROLES,
  createQuote: DESK_ROLES,
  createCharge: CORE_ROLES,
  registerPayment: DESK_ROLES,
  issueCfdi: CORE_ROLES,
}

export function can(role: Role | null | undefined, capability: FinanceCapability): boolean {
  if (!role) return false
  return MATRIX[capability].includes(role)
}

/** Roles que NO ven el módulo finanzas (para redirigir o esconder la navegación). */
export function canAccessFinance(role: Role | null | undefined): boolean {
  return can(role, 'viewModule')
}
=======
>>>>>>> Stashed changes
/* ─────────────────────────────────────────────────────────────────────────
   Roles de la clínica y sus permisos (solo frontend / prototipo).
   Cuando se conecte el backend, el rol vendrá del JWT del usuario; aquí lo
   simulamos con un selector para la demo.
   ──────────────────────────────────────────────────────────────────────── */

export type ClinicRole = 'owner' | 'admin' | 'doctor' | 'nurse' | 'reception' | 'finance' | 'readonly'
export type Modulo = 'finanzas' | 'agenda' | 'contactos' | 'personal' | 'notas'
export type Acceso = 'edit' | 'view'

export const ROLES: { key: ClinicRole; label: string }[] = [
  { key: 'owner',     label: 'Dueño' },
  { key: 'admin',     label: 'Administrador' },
  { key: 'doctor',    label: 'Médico' },
  { key: 'nurse',     label: 'Enfermería' },
  { key: 'reception', label: 'Recepción' },
  { key: 'finance',   label: 'Finanzas' },
  { key: 'readonly',  label: 'Solo lectura' },
]

export const ROLE_LABEL: Record<ClinicRole, string> = {
  owner: 'Dueño', admin: 'Administrador', doctor: 'Médico', nurse: 'Enfermería',
  reception: 'Recepción', finance: 'Finanzas', readonly: 'Solo lectura',
}

interface Permisos {
  finanzas?: Acceso
  agenda?: Acceso
  contactos?: Acceso
  personal?: Acceso
  notas?: Acceso
  /** ¿Puede ver el expediente CLÍNICO (historial, notas médicas)? */
  expedienteClinico: boolean
}

/* Matriz de permisos (ver docs/design/plan-paneles-roles.md).
   notas: todos los roles pueden usar el módulo (notas personales). El backend
   restringe internamente quién difunde notas globales (solo Dueño). */
export const PERMISOS: Record<ClinicRole, Permisos> = {
  owner:     { agenda: 'edit', contactos: 'edit', personal: 'edit', finanzas: 'edit', notas: 'edit', expedienteClinico: true },
  admin:     { agenda: 'edit', contactos: 'edit', personal: 'edit', finanzas: 'edit', notas: 'edit', expedienteClinico: true },
  doctor:    { agenda: 'edit', contactos: 'edit', notas: 'edit', expedienteClinico: true },
  nurse:     { agenda: 'edit', contactos: 'view', notas: 'edit', expedienteClinico: true },
  reception: { agenda: 'edit', contactos: 'edit', notas: 'edit', expedienteClinico: false },
  finance:   { agenda: 'view', contactos: 'view', finanzas: 'edit', notas: 'edit', expedienteClinico: false },
  readonly:  { agenda: 'view', contactos: 'view', personal: 'view', finanzas: 'view', notas: 'edit', expedienteClinico: true },
}

/* ─── Helpers ──────────────────────────────────────────────────────────── */
export const accesoModulo = (role: ClinicRole, m: Modulo): Acceso | undefined => PERMISOS[role][m]
export const puedeEditar  = (role: ClinicRole, m: Modulo): boolean => PERMISOS[role][m] === 'edit'
export const puedeVerExpedienteClinico = (role: ClinicRole): boolean => PERMISOS[role].expedienteClinico

/* Capacidades finas de la AGENDA (deben reflejar el backend):
   - Agendar/reagendar/cancelar-reserva → recepción + clínicos, NO enfermería.
   - Cambiar el estado de una cita (En sala, En consulta…) → incluye enfermería. */
export const puedeAgendar = (role: ClinicRole): boolean =>
  role === 'owner' || role === 'admin' || role === 'doctor' || role === 'reception'

export const puedeCambiarEstadoCita = (role: ClinicRole): boolean =>
  role === 'owner' || role === 'admin' || role === 'doctor' || role === 'nurse' || role === 'reception'

/** Ruta de inicio según el rol (a dónde llega al entrar / cambiar de rol). */
export const inicioDeRol = (role: ClinicRole): string =>
  role === 'finance' ? '/finanzas' : '/agenda'
<<<<<<< Updated upstream
=======
>>>>>>> 9f3cd4149619be4d5c604a117d939f7904aad547
>>>>>>> Stashed changes
