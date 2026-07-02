/**
 * RequireAuth — guard de autenticación para rutas protegidas.
 *
 * - status 'loading'      → muestra un loader (aún bootstrapeando la sesión).
 * - status 'anonymous'    → redirige a /login, recordando a dónde iba (state.from).
 * - status 'authenticated'→ renderiza la ruta.
 *
 * Contraseña temporal: si /me/ dice must_change_password=true, CUALQUIER ruta
 * protegida (clínica y plataforma, todas pasan por aquí) redirige a
 * /cambiar-contrasena — el backend además bloquea los endpoints de negocio con
 * 403 password_change_required hasta que la cambie.
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
  const { status, user } = useAuth()
  const location = useLocation()

  if (status === 'loading') return <FullScreenLoader />
  if (status === 'anonymous') {
    return <Navigate to="/login" state={{ from: location }} replace />
  }
  // Contraseña temporal pendiente → forzar el cambio antes de usar la app.
  // (La propia /cambiar-contrasena también pasa por aquí: no redirigir en bucle.)
  if (user?.must_change_password && location.pathname !== '/cambiar-contrasena') {
    return <Navigate to="/cambiar-contrasena" replace />
  }
  return children
}
