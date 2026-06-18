/**
 * tokenStore — guarda el access token JWT SOLO en memoria (variable de módulo).
 *
 * Decisión de seguridad (patrón híbrido):
 *   - access token  → memoria (este módulo). Se pierde al recargar la página;
 *     se recupera en silencio con /auth/refresh/ (la cookie httpOnly viaja sola).
 *   - refresh token → cookie httpOnly `maily_refresh` (JS NO puede leerla).
 *
 * NUNCA guardar el access token en localStorage/sessionStorage: sería legible
 * por cualquier XSS. En memoria, un XSS aún podría usarlo mientras la pestaña
 * vive, pero no queda persistido ni se puede exfiltrar tras recargar.
 */

let accessToken: string | null = null

/** Suscriptores notificados cuando el token cambia (ej. para re-render de auth). */
const listeners = new Set<(token: string | null) => void>()

export function getAccessToken(): string | null {
  return accessToken
}

export function setAccessToken(token: string | null): void {
  accessToken = token
  for (const listener of listeners) listener(token)
}

export function clearAccessToken(): void {
  setAccessToken(null)
}

/** Devuelve una función para cancelar la suscripción. */
export function onAccessTokenChange(listener: (token: string | null) => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}
