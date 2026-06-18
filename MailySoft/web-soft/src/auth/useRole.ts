/**
 * Hook de rol activo para gating de UX.
 *
 * NOTA: el plumbing de autenticación real (rol derivado del JWT/membresía) aún
 * no existe en web-soft. Mientras tanto, este hook persiste un rol "demo" en
 * localStorage para poder validar la matriz de permisos en la UI. Cuando exista
 * el contexto de auth real, reemplazar la fuente del rol por la membresía activa.
 *
 * IMPORTANTE: esto es solo UX. El backend sigue siendo la autoridad de permisos.
 */

import { useCallback, useEffect, useState } from 'react'

import { getActiveRole } from '../lib/tokenStore'
import type { Role } from './permisos'

const STORAGE_KEY = 'maily_demo_role'
const DEFAULT_ROLE: Role = 'owner'

export const ALL_ROLES: Role[] = [
  'owner',
  'admin',
  'finance',
  'reception',
  'doctor',
  'nurse',
  'readonly',
]

function readRole(): Role {
  if (typeof window === 'undefined') return DEFAULT_ROLE
  // Rol real de la sesión (derivado de /me/ tras login).
  const sessionRole = getActiveRole() as Role | null
  if (sessionRole && ALL_ROLES.includes(sessionRole)) return sessionRole
  // Override manual para probar la matriz UX (selector en FinanzasPage).
  const stored = window.localStorage.getItem(STORAGE_KEY) as Role | null
  return stored && ALL_ROLES.includes(stored) ? stored : DEFAULT_ROLE
}

export function useRole(): { role: Role; setRole: (role: Role) => void } {
  const [role, setRoleState] = useState<Role>(readRole)

  useEffect(() => {
    const onStorage = () => setRoleState(readRole())
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const setRole = useCallback((next: Role) => {
    window.localStorage.setItem(STORAGE_KEY, next)
    setRoleState(next)
  }, [])

  return { role, setRole }
}
