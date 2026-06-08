/**
 * RequireAuth — guard de autenticación para rutas protegidas.
 *
 * - status 'loading'      → muestra un loader (aún bootstrapeando la sesión).
 * - status 'anonymous'    → redirige a /login, recordando a dónde iba (state.from).
 * - status 'authenticated'→ renderiza la ruta.
 *
 * NO decide permisos por módulo: de eso se encarga el <Guard> de rol. Aquí solo
 * se garantiza que haya una sesión válida antes de pintar cualquier vista privada.
 */

import type { ReactElement } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext'

function FullScreenLoader(): ReactElement {
  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        color: '#9a7b2e',
        fontFamily: 'system-ui, sans-serif',
      }}
    >
      Cargando…
    </div>
  )
}

export function RequireAuth({ children }: { children: ReactElement }): ReactElement {
  const { status } = useAuth()
  const location = useLocation()

  if (status === 'loading') return <FullScreenLoader />
  if (status === 'anonymous') {
    return <Navigate to="/login" state={{ from: location }} replace />
  }
  return children
}
