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

/* Capacidades finas del EXPEDIENTE CLÍNICO (deben reflejar el backend).
   Solo son UX: ocultan botones. El backend es la autoridad (devuelve 403). */

/** Editar HC, crear evoluciones/addenda y diagnósticos → owner/admin/doctor. */
export const puedeEditarClinico = (role: ClinicRole): boolean =>
  role === 'owner' || role === 'admin' || role === 'doctor'

/** Capturar signos vitales → owner/admin/doctor/nurse (enfermería incluida). */
export const puedeCapturarSignos = (role: ClinicRole): boolean =>
  role === 'owner' || role === 'admin' || role === 'doctor' || role === 'nurse'

/* Capacidades finas de la AGENDA (deben reflejar el backend):
   - Agendar/reagendar/cancelar-reserva → recepción + clínicos, NO enfermería.
   - Cambiar el estado de una cita (En sala, En consulta…) → incluye enfermería. */
export const puedeAgendar = (role: ClinicRole): boolean =>
  role === 'owner' || role === 'admin' || role === 'doctor' || role === 'reception'

export const puedeCambiarEstadoCita = (role: ClinicRole): boolean =>
  role === 'owner' || role === 'admin' || role === 'doctor' || role === 'nurse' || role === 'reception'

/** Cancelar una cita → owner/admin/doctor/recepción. Enfermería NO (el backend también lo bloquea). */
export const puedeCancelarCita = (role: ClinicRole): boolean =>
  role === 'owner' || role === 'admin' || role === 'doctor' || role === 'reception'

/** Ruta de inicio según el rol (a dónde llega al entrar / cambiar de rol). */
export const inicioDeRol = (role: ClinicRole): string =>
  role === 'finance' ? '/finanzas' : '/agenda'

/* ─── "Mi Consultorio" (apps/clinica) ──────────────────────────────────────
   Solo UX: ocultan/deshabilitan botones. El backend es la autoridad (403).
   Reflejan EXACTO apps/clinica/permissions.py. */

/** Acceder a la página /mi-consultorio → owner/admin/doctor. */
export const puedeAccederConsultorio = (role: ClinicRole): boolean =>
  role === 'owner' || role === 'admin' || role === 'doctor'

/** Editar configuración / membrete / recetas / categorías → solo owner/admin. */
export const puedeGestionarConsultorio = (role: ClinicRole): boolean =>
  role === 'owner' || role === 'admin'

/** Crear/editar/borrar plantillas → owner/admin/doctor. */
export const puedeEditarPlantillas = (role: ClinicRole): boolean =>
  role === 'owner' || role === 'admin' || role === 'doctor'

/** Gestionar el perfil médico (sello/foto/cédulas/universidades) → owner/admin/doctor
 *  (el backend valida además que un doctor solo toque su propio perfil). */
export const puedeGestionarPerfilMedico = (role: ClinicRole): boolean =>
  role === 'owner' || role === 'admin' || role === 'doctor'

/* ─── Recetas (apps/recetas) ────────────────────────────────────────────────
   Solo UX: ocultan/deshabilitan botones. El backend es la autoridad (403).
   Reflejan apps/core/permissions.py (MedicationPermission / PrescriptionPermission)
   + la validación fina del service (solo perfil Doctor emite; emisor/admin/owner anula). */

/**
 * Mostrar el botón "Nueva receta" y "Nuevo medicamento" → owner/admin/doctor.
 * OJO: el backend exige además un perfil de Doctor activo para EMITIR (no solo el
 * rol). Si owner/admin sin perfil médico intentan crear, el backend responde 403;
 * la UI debe mostrar ese mensaje claro, no romperse.
 */
export const puedeEmitirReceta = (role: ClinicRole): boolean =>
  role === 'owner' || role === 'admin' || role === 'doctor'

/** Anular una receta → owner/admin/doctor (el backend exige ser emisor o owner/admin). */
export const puedeAnularReceta = (role: ClinicRole): boolean =>
  role === 'owner' || role === 'admin' || role === 'doctor'
