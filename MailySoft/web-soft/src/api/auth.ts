/**
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
import { clearAccessToken, getAccessToken, setAccessToken } from '../lib/tokenStore'
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
}

/**
 * Intenta restaurar la sesión al arrancar la app (fire-and-forget desde main.tsx).
 *
 * Si ya hay access en memoria, valida con /me/. Si no, intenta renovar con la
 * cookie httpOnly de refresh y luego trae el perfil. Devuelve el perfil o null
 * si no hay sesión viva. No lanza: cualquier fallo limpia el token y resuelve null.
 */
export async function tryRestoreSession(): Promise<Me | null> {
  if (getAccessToken()) {
    try {
      return await me()
    } catch {
      clearAccessToken()
    }
  }

  try {
    const data = await refresh()
    if (!data?.access) return null
    return await me()
  } catch {
    clearAccessToken()
    return null
  }
}
