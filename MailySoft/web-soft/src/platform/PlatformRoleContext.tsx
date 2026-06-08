import { createContext, useContext, useState, ReactNode } from 'react'
import { PlatformRole } from './permisos'

interface PlatformRoleCtx {
  role: PlatformRole
  setRole: (r: PlatformRole) => void
}

const Ctx = createContext<PlatformRoleCtx>({ role: 'super_admin', setRole: () => {} })

export function PlatformRoleProvider({ children }: { children: ReactNode }) {
  const [role, setRole] = useState<PlatformRole>('super_admin')
  return <Ctx.Provider value={{ role, setRole }}>{children}</Ctx.Provider>
}

export const usePlatformRole = () => useContext(Ctx)
