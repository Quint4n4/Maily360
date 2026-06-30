import { defineConfig, devices } from '@playwright/test'

/**
 * Pruebas E2E (extremo a extremo) con Playwright: manejan un navegador real contra
 * la app corriendo, probando los flujos completos front + back.
 *
 * Requisitos para correrlas (`npm run test:e2e`):
 *   1. El BACKEND corriendo (Docker, :8000) — el proxy de Vite reenvía /api ahí.
 *   2. Los usuarios demo sembrados:
 *        docker compose exec backend python manage.py seed_finanzas
 *   3. Playwright levanta el FRONTEND solo (npm run dev); si ya corre, lo reusa.
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: 'list',
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
