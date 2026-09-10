import { test, expect } from '@playwright/test'
import { login, TIMEOUT_CON_LOGIN_MS } from './helpers'

// Usuario E2E dedicado, creado por `manage.py seed_e2e_user` (rol owner, tenant demo).
const DEMO_EMAIL = 'e2e@maily.local'
const DEMO_PASSWORD = 'Demo1234!'

test.describe('Login (E2E)', () => {
  test('la pantalla de login carga con sus campos', async ({ page }) => {
    await page.goto('/login')
    // Por etiqueta, no por placeholder — ver la nota de selectores en helpers.ts.
    await expect(page.getByLabel('Correo electrónico')).toBeVisible()
    await expect(page.getByLabel('Contraseña', { exact: true })).toBeVisible()
    await expect(page.locator('button[type="submit"]')).toBeVisible()
  })

  test('credenciales inválidas muestran error y no entra', async ({ page }) => {
    // Gasta un intento del throttle de /auth/login/ como cualquier otro: usa el
    // mismo helper con reintento, para no confundir un 429 con un 401.
    test.setTimeout(TIMEOUT_CON_LOGIN_MS)
    await login(page, 'noexiste@demo.maily.mx', 'contrasena-incorrecta')
    // El backend responde 401 → el frontend muestra el mensaje y NO redirige.
    await expect(page.getByText(/correo o contraseña incorrectos/i)).toBeVisible()
    await expect(page).toHaveURL(/\/login/)
  })

  test('login exitoso entra al sistema', async ({ page }) => {
    test.setTimeout(TIMEOUT_CON_LOGIN_MS)
    await login(page, DEMO_EMAIL, DEMO_PASSWORD)
    // Tras el login, la URL deja de ser /login (redirige al inicio del rol).
    await expect(page).not.toHaveURL(/\/login/, { timeout: 15_000 })
  })
})
