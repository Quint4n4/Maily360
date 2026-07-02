/* ─────────────────────────────────────────────────────────────────────────
   Panel interno de Maily (web-platform). Roles del EQUIPO de Maily, distintos
   de los roles de la clínica. Solo frontend / prototipo.
   ──────────────────────────────────────────────────────────────────────── */

export type PlatformRole = 'super_admin' | 'sales' | 'engineering'
export type PlatModulo = 'dashboard' | 'clinicas' | 'suscripciones' | 'planes' | 'usuarios' | 'sistema' | 'auditoria'
export type Acceso = 'edit' | 'view'

export const ROLES_PLAT: { key: PlatformRole; label: string }[] = [
  { key: 'super_admin', label: 'Súper Admin' },
  { key: 'sales',       label: 'Ventas / Éxito de Cliente' },
  { key: 'engineering', label: 'Ingeniería' },
]

export const ROLE_PLAT_LABEL: Record<PlatformRole, string> = {
  super_admin: 'Súper Admin', sales: 'Ventas', engineering: 'Ingeniería',
}

export const PERMISOS_PLAT: Record<PlatformRole, Partial<Record<PlatModulo, Acceso>>> = {
  // `planes` vive dentro de Suscripciones (sin ruta propia): escribir planes es SOLO super_admin (el backend da 403 al resto).
  super_admin: { dashboard: 'edit', clinicas: 'edit', suscripciones: 'edit', planes: 'edit', usuarios: 'edit', sistema: 'view', auditoria: 'view' },
  sales:       { dashboard: 'edit', clinicas: 'edit', suscripciones: 'edit', planes: 'view' },
  engineering: { dashboard: 'view', clinicas: 'view', sistema: 'edit', auditoria: 'view' },
}

export const accesoModuloPlat = (role: PlatformRole, m: PlatModulo): Acceso | undefined => PERMISOS_PLAT[role][m]
export const puedeEditarPlat  = (role: PlatformRole, m: PlatModulo): boolean => PERMISOS_PLAT[role][m] === 'edit'

/** A dónde llega cada rol al entrar / cambiar de rol. */
export const inicioPlat = (role: PlatformRole): string =>
  role === 'engineering' ? '/plataforma/sistema' : '/plataforma/dashboard'
