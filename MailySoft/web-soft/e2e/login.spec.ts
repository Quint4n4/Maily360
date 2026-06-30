import { test, expect } from '@playwright/test'

// Usuario E2E dedicado, creado por `manage.py seed_e2e_user` (rol owner, clinica-demo).
const DEMO_EMAIL = 'e2e@maily.local'
const DEMO_PASSWORD = 'Demo1234!'

test.describe('Login (E2E)', () => {
  test('la pantalla de login carga con sus campos', async ({ page }) => {
    await page.goto('/login')
    await expect(page.getByPlaceholder('Correo electrónico')).toBeVisible()
    await expect(page.getByPlaceholder('Contraseña')).toBeVisible()
    await expect(page.locator('button[type="submit"]')).toBeVisible()
  })

  test('credenciales inválidas muestran error y no entra', async ({ page }) => {
    await page.goto('/login')
    await page.getByPlaceholder('Correo electrónico').fill('noexiste@demo.maily.mx')
    await page.getByPlaceholder('Contraseña').fill('contrasena-incorrecta')
    await page.locator('button[type="submit"]').click()
    // El backend responde 401 → el frontend muestra el mensaje y NO redirige.
    await expect(page.getByText(/correo o contraseña incorrectos/i)).toBeVisible()
    await expect(page).toHaveURL(/\/login/)
  })

  test('login exitoso entra al sistema', async ({ page }) => {
    await page.goto('/login')
    await page.getByPlaceholder('Correo electrónico').fill(DEMO_EMAIL)
    await page.getByPlaceholder('Contraseña').fill(DEMO_PASSWORD)
    await page.locator('button[type="submit"]').click()
    // Tras el login, la URL deja de ser /login (redirige al inicio del rol).
    await expect(page).not.toHaveURL(/\/login/, { timeout: 15_000 })
  })
})
