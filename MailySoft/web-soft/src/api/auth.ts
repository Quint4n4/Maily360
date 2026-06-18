/**
<<<<<<< Updated upstream
=======
<<<<<<< HEAD
 * Autenticación: login JWT + perfil /me/.
 *
 * El refresh token vive en cookie httpOnly (maily_refresh); el access en memoria
 * (tokenStore). Login y refresh usan fetch directo porque aún no hay token.
 */

import { http } from '../lib/http'
import { clearAuth, getAccessToken, setAccessToken, setActiveRole } from '../lib/tokenStore'
import type { Role } from '../auth/permisos'

const API_BASE: string =
  (import.meta as { env?: Record<string, string> }).env?.VITE_API_URL ??
  'http://localhost:8000'

const API_PREFIX = '/api/v1'

export interface MeProfile {
  id: string
  email: string
  first_name: string
  last_name: string
  full_name: string
  active_role: Role | null
  active_role_display: string | null
  active_tenant: { id: string; name: string; slug: string } | null
}

export async function login(email: string, password: string): Promise<MeProfile> {
  const response = await fetch(`${API_BASE}${API_PREFIX}/auth/login/`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })

  if (!response.ok) {
    let message = 'Correo o contraseña incorrectos.'
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (body.detail) {
        message = Array.isArray(body.detail) ? body.detail.join(' ') : String(body.detail)
      }
    } catch {
      /* sin cuerpo JSON */
    }
    throw new Error(message)
  }

  const data = (await response.json()) as { access?: string }
  if (!data.access) throw new Error('El servidor no devolvió un token de acceso.')
  setAccessToken(data.access)

  const me = await fetchMe()
  if (me.active_role) setActiveRole(me.active_role)
  return me
}

export async function fetchMe(): Promise<MeProfile> {
  return http.get<MeProfile>('/me/')
}

/** Intenta restaurar sesión vía cookie de refresh (útil tras F5). */
export async function tryRestoreSession(): Promise<MeProfile | null> {
  if (getAccessToken()) {
    try {
      const me = await fetchMe()
      if (me.active_role) setActiveRole(me.active_role)
      return me
    } catch {
      clearAuth()
    }
  }

  try {
    const response = await fetch(`${API_BASE}${API_PREFIX}/auth/refresh/`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
    })
    if (!response.ok) return null
    const data = (await response.json()) as { access?: string }
    if (!data.access) return null
    setAccessToken(data.access)
    const me = await fetchMe()
    if (me.active_role) setActiveRole(me.active_role)
    return me
  } catch {
    return null
  }
}

export function logout(): void {
  clearAuth()
=======
>>>>>>> Stashed changes
 * api/auth — funciones de autenticación. Envuelven el cliente http central.
 *
 * Patrón híbrido:
 *   - login()   → devuelve {access} y lo deja en el tokenStore (memoria); el
 *                 refresh queda en cookie httpOnly (no lo vemos desde JS).
 *   - refresh() → renueva el access leyendo la cookie; el propio http.ts ya lo
 *                 usa para re-login silencioso, pero se expone para el bootstrap.
 *   - me()      → perfil + rol REAL (autoridad del backend).
 *   - logout()  → invalida el refresh y borra la cookie.
 *
 * tokenStore (memoria) es el ÚNICO dueño del access token; estas funciones
 * escriben ahí para que la siguiente petición ya lleve el Bearer.
 */

import { request } from '../lib/http'
import { setAccessToken } from '../lib/tokenStore'
import type { LoginResponse, Me, RefreshResponse } from '../types/api'

export interface LoginInput {
  email: string
  password: string
}

/** POST /auth/login/ — devuelve el access token; setea cookies httpOnly + csrftoken. */
export async function login(input: LoginInput): Promise<LoginResponse> {
  const data = await request<LoginResponse>('/auth/login/', {
    method: 'POST',
    body: { email: input.email, password: input.password },
  })
  setAccessToken(data.access)
  return data
}

/** POST /auth/refresh/ — renueva el access usando la cookie de refresh. */
export async function refresh(): Promise<RefreshResponse> {
  const data = await request<RefreshResponse>('/auth/refresh/', { method: 'POST' })
  if (data?.access) setAccessToken(data.access)
  return data
}

/** GET /me/ — perfil del usuario autenticado con su rol REAL. */
export async function me(): Promise<Me> {
  return request<Me>('/me/')
}

/** POST /auth/logout/ — invalida el refresh y borra la cookie. 205 sin cuerpo. */
export async function logout(): Promise<void> {
  await request<void>('/auth/logout/', { method: 'POST' })
<<<<<<< Updated upstream
=======
>>>>>>> 9f3cd4149619be4d5c604a117d939f7904aad547
>>>>>>> Stashed changes
}
