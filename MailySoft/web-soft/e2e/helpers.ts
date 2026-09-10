import { expect, Page } from '@playwright/test'

/**
 * Utilidades compartidas por los specs E2E.
 *
 * SELECTORES DEL LOGIN: se buscan por ETIQUETA (`getByLabel`), no por placeholder.
 * La pantalla tiene `<label htmlFor="email">Correo electrónico</label>` y el placeholder
 * es decorativo ("tucorreo@clinica.com"). Buscar por etiqueta es lo correcto: es el
 * mismo texto que anuncia un lector de pantalla, y sobrevive a un cambio de placeholder.
 * `{ exact: true }` en Contraseña es obligatorio: el botón del ojo tiene
 * `aria-label="Mostrar contraseña"`, que en modo subcadena también haría match.
 */

/** Tope de tiempo para un test que hace login real y puede topar con el throttle.
 *  Peor caso: dos esperas de hasta ~61 s (la ventana completa del límite) más los
 *  intentos. Solo se acerca a ese tope si se corre la suite dos veces en el mismo
 *  minuto sin haber subido `DRF_THROTTLE_LOGIN` en el entorno local. */
export const TIMEOUT_CON_LOGIN_MS = 200_000

/**
 * Llena y envía /login una vez, leyendo el STATUS REAL de la respuesta.
 *
 * Devuelve `null` si el intento llegó al backend, o los segundos que hay que esperar si
 * lo frenó el límite de intentos (429).
 *
 * Se mira la respuesta HTTP y no el mensaje de la pantalla a propósito: la versión
 * anterior comprobaba `locator.isVisible({ timeout })` sobre el texto "Demasiados
 * intentos", y `isVisible` NO espera — devuelve el estado del instante en que se llama,
 * así que se evaluaba antes de que la respuesta llegara y daba `false` con el límite
 * agotado. El reintento existía y nunca se activaba. `waitForResponse` sí espera, y el
 * código 429 es un hecho del backend, no un texto de UI que se pueda mover.
 */
async function enviarLogin(page: Page, email: string, password: string): Promise<number | null> {
  await page.goto('/login')
  await page.getByLabel('Correo electrónico').fill(email)
  await page.getByLabel('Contraseña', { exact: true }).fill(password)

  const respuestaDelLogin = page.waitForResponse(
    r => r.url().includes('/auth/login/') && r.request().method() === 'POST',
    { timeout: 30_000 },
  )
  await page.locator('button[type="submit"]').click()
  const respuesta = await respuestaDelLogin

  if (respuesta.status() !== 429) return null
  // DRF manda `Retry-After` en segundos junto al 429: se espera lo justo, no un número
  // inventado. El 60 de reserva es la ventana completa del límite, por si falta la cabecera.
  const retryAfter = Number(respuesta.headers()['retry-after'])
  return Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : 60
}

/**
 * Envía el login reintentando si el límite de intentos lo bloquea.
 *
 * `/auth/login/` permite 5 intentos por minuto y por IP (`DRF_THROTTLE_LOGIN` en
 * backend/config/settings/base.py). Es protección real contra fuerza bruta y NO se
 * debilita para que los tests pasen: una corrida completa gasta 4 intentos, así que dos
 * corridas seguidas en el mismo minuto agotan el límite y el test espera a que la ventana
 * se libere.
 *
 * En CI el job sube `DRF_THROTTLE_LOGIN` en su propio contenedor efímero (ver
 * .github/workflows/e2e.yml), así que este reintento no llega a activarse allí.
 *
 * Tres intentos: una corrida completa gasta 4 de los 5 intentos del minuto, así que dos
 * corridas seguidas dejan a varios tests esperando la misma ventana y renovándola entre
 * ellos. Con tres intentos la suite aguanta eso sin tocar la configuración del backend.
 *
 * NO afirma que el login haya tenido éxito: solo garantiza que el intento llegó al
 * backend. La aserción sobre el resultado la hace cada test — por eso sirve igual para
 * el caso de credenciales inválidas.
 *
 * Todo test que llame a esta función debe declarar `test.setTimeout(TIMEOUT_CON_LOGIN_MS)`,
 * o la espera no cabe en el timeout por defecto de 30 s.
 */
export async function login(page: Page, email: string, password: string): Promise<void> {
  const intentosMax = 3
  for (let intento = 1; intento <= intentosMax; intento++) {
    const esperaSegundos = await enviarLogin(page, email, password)
    if (esperaSegundos === null) return
    if (intento === intentosMax) return // se deja fallar la aserción del caller con el mensaje real
    await page.waitForTimeout((esperaSegundos + 1) * 1_000)
  }
}

/** Cierra sesión desde el menú del topbar de plataforma (avatar arriba a la derecha).
 *  El botón muestra full_name ("E2E Admin", del seed_e2e_user --platform) o, si
 *  estuviera vacío, el fallback "Equipo Maily" — se cubren ambos casos. */
export async function logoutDesdePlataforma(page: Page): Promise<void> {
  await page.getByRole('button', { name: /Equipo Maily|E2E Admin/i }).click()
  await page.getByRole('button', { name: /Cerrar sesión/i }).click()
  await expect(page).toHaveURL(/\/login/, { timeout: 15_000 })
}
