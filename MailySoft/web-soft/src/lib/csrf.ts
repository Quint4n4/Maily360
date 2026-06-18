/**
 * csrf — lee la cookie `csrftoken` que Django expone a JS (CSRF_COOKIE_HTTPONLY=False).
 *
 * Patrón double-submit: el backend exige la cabecera `X-CSRFToken` en las
 * mutaciones sensibles (/auth/refresh/, /auth/logout/) y la compara contra el
 * valor de la cookie `csrftoken`. Aquí solo extraemos ese valor.
 */

const CSRF_COOKIE_NAME = 'csrftoken'

export function getCsrfToken(): string | null {
  const cookies = document.cookie ? document.cookie.split('; ') : []
  for (const cookie of cookies) {
    const sep = cookie.indexOf('=')
    if (sep === -1) continue
    const name = cookie.slice(0, sep)
    if (name === CSRF_COOKIE_NAME) {
      return decodeURIComponent(cookie.slice(sep + 1))
    }
  }
  return null
}
