import { createContext, useContext, ReactNode } from 'react'
import { ClinicRole } from './permisos'
import { useAuth } from './AuthContext'

interface RoleCtx {
  role: ClinicRole
}

const Ctx = createContext<RoleCtx>({ role: 'readonly' })

export function RoleProvider({ children }: { children: ReactNode }) {
  // El rol REAL viene del backend (/me/ → active_role) vía AuthContext.
  // Fallback 'readonly' = mínimo privilegio mientras carga o si no hay membresía.
  const { clinicRole } = useAuth()
  const role: ClinicRole = clinicRole ?? 'readonly'

  return <Ctx.Provider value={{ role }}>{children}</Ctx.Provider>
}

export const useRole = () => useContext(Ctx)
