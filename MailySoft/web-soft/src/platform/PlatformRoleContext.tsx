import { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import { PlatformRole } from './permisos'
import { useAuth } from '../auth/AuthContext'

interface PlatformRoleCtx {
  role: PlatformRole
  setRole: (r: PlatformRole) => void
}

const Ctx = createContext<PlatformRoleCtx>({ role: 'super_admin', setRole: () => {} })

const ROLES_VALIDOS: PlatformRole[] = ['super_admin', 'sales', 'engineering']

export function PlatformRoleProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  // Default: rol REAL del usuario logueado (de /me/). El selector "Ver como"
  // del topbar puede sobreescribirlo localmente para previsualizar otros roles;
  // el backend sigue siendo la autoridad real de permisos.
  const [role, setRole] = useState<PlatformRole>('super_admin')

  useEffect(() => {
    const real = user?.platform_role
    if (real && (ROLES_VALIDOS as string[]).includes(real)) {
      setRole(real as PlatformRole)
    }
  }, [user?.platform_role])

  return <Ctx.Provider value={{ role, setRole }}>{children}</Ctx.Provider>
}

export const usePlatformRole = () => useContext(Ctx)
