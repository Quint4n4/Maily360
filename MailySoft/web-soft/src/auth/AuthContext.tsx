/**
 * AuthContext — único dueño del estado de sesión en el frontend.
 *
 * Estado:
 *   - status: 'loading' | 'authenticated' | 'anonymous'
 *   - user:   perfil de /me/ (incluye el rol REAL) o null
 *
 * Flujo:
 *   1. Al montar (bootstrap): intenta /auth/refresh/ usando la cookie httpOnly.
 *      Si renueva, pide /me/ y queda autenticado. Si no, queda anónimo.
 *      Esto recupera la sesión tras recargar la página, aunque el access token
 *      (que vive solo en memoria) se haya perdido.
 *   2. login(): POST /auth/login/ → guarda access en memoria → /me/.
 *   3. logout(): POST /auth/logout/ → limpia token y estado.
 *
 * El rol que consume la UI sale de aquí (user.active_role). El backend sigue
 * siendo la autoridad: la UI solo refleja permisos, nunca los concede.
 */

import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import * as authApi from '../api/auth'
import type { LoginInput } from '../api/auth'
import { getCsrfToken } from '../lib/csrf'
import { queryClient } from '../lib/queryClient'
import { clearAccessToken, onAccessTokenChange } from '../lib/tokenStore'
import type { ClinicRole } from './permisos'
import type { Me } from '../types/api'

export type AuthStatus = 'loading' | 'authenticated' | 'anonymous'

interface AuthContextValue {
  status: AuthStatus
  user: Me | null
  /** Rol clínico real del usuario en su tenant activo (null si no aplica). */
  clinicRole: ClinicRole | null
  /** true si el usuario es staff de la plataforma Maily (panel interno). */
  isPlatformStaff: boolean
  login: (input: LoginInput) => Promise<Me>
  logout: () => Promise<void>
  /** Re-consulta /me/ (útil tras cambiar de clínica a futuro). */
  reloadMe: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('loading')
  const [user, setUser] = useState<Me | null>(null)
  const bootstrapped = useRef(false)

  // Bootstrap: recuperar sesión al cargar la app.
  // El ref garantiza que corra UNA sola vez aunque StrictMode monte/desmonte/monte
  // en dev. NO usamos bandera `cancelled`: el desmontaje intermedio de StrictMode
  // la activaría y dejaría el estado pegado en 'loading' para siempre. Un setState
  // tras el re-montaje (mismo componente) es inofensivo.
  useEffect(() => {
    if (bootstrapped.current) return
    bootstrapped.current = true

    // Sin cookie csrftoken nunca hubo login en este navegador → anónimo directo,
    // sin pegarle a /auth/refresh/ (evita un 403 ruidoso en la consola).
    if (!getCsrfToken()) {
      setStatus('anonymous')
      return
    }

    void (async () => {
      try {
        await authApi.refresh()
        const profile = await authApi.me()
        setUser(profile)
        setStatus('authenticated')
      } catch {
        clearAccessToken()
        setUser(null)
        setStatus('anonymous')
      }
    })()
  }, [])

  // Si el token se limpia desde fuera (refresh silencioso fallido en http.ts),
  // sincronizamos el estado a anónimo para que la UI reaccione.
  useEffect(() => {
    return onAccessTokenChange((token) => {
      if (token === null) {
        // Sesión expirada/perdida: vaciar el caché para no dejar datos de la
        // clínica anterior en memoria (privacidad multi-tenant).
        queryClient.clear()
        setUser(null)
        setStatus('anonymous')
      }
    })
  }, [])

  const login = useCallback(async (input: LoginInput): Promise<Me> => {
    // Arrancar SIEMPRE con el caché limpio: si en este mismo navegador hubo
    // otra sesión (otra clínica) cuyos datos quedaron en memoria, se descartan
    // antes de cargar los del nuevo usuario. Evita ver datos de otra clínica.
    queryClient.clear()
    await authApi.login(input)
    const profile = await authApi.me()
    setUser(profile)
    setStatus('authenticated')
    return profile
  }, [])

  const logout = useCallback(async (): Promise<void> => {
    try {
      await authApi.logout()
    } finally {
      clearAccessToken()
      // Vaciar el caché de datos (TanStack Query): sin esto, los pacientes/citas
      // de la clínica recién cerrada quedan en memoria y podrían mostrarse un
      // instante si otra cuenta entra en la misma pestaña sin recargar.
      queryClient.clear()
      setUser(null)
      setStatus('anonymous')
    }
  }, [])

  const reloadMe = useCallback(async (): Promise<void> => {
    const profile = await authApi.me()
    setUser(profile)
    setStatus('authenticated')
  }, [])

  const value: AuthContextValue = {
    status,
    user,
    clinicRole: user?.active_role ?? null,
    isPlatformStaff: user?.is_platform_staff ?? false,
    login,
    logout,
    reloadMe,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (ctx === null) throw new Error('useAuth debe usarse dentro de <AuthProvider>')
  return ctx
}
