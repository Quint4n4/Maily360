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

/** Ruta de inicio según el rol (a dónde llega al entrar / cambiar de rol). */
export const inicioDeRol = (role: ClinicRole): string =>
  role === 'finance' ? '/finanzas' : '/agenda'
