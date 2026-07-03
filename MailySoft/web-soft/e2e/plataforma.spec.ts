import { test, expect, Page } from '@playwright/test'

/**
 * E2E del PORTAL DE PLATAFORMA (panel interno de Maily, /plataforma/*).
 *
 * Usuario staff dedicado, creado por `manage.py seed_e2e_user --platform`:
 *   e2e-admin@maily.local / Demo1234!  (is_platform_staff=True, platform_role=super_admin,
 *   must_change_password=False explícito — si no, el login cae en /cambiar-contrasena).
 *
 * Requiere además el usuario/tenant de clínica de `manage.py seed_e2e_user` (sin --platform)
 * para el flujo de oro (paso "Cambio de contraseña forzado"), que crea su PROPIA clínica
 * vía el modal "Nueva clínica" — no reutiliza el tenant demo.
 *
 * Login del staff se hace UNA sola vez (beforeAll) y sus cookies se reinyectan en cada
 * test (beforeEach): el endpoint /auth/login/ tiene throttle estricto (5/minuto, ver
 * DRF_THROTTLE_LOGIN en backend/config/settings/base.py) para protegerse de fuerza bruta,
 * y loguear en cada test agotaría el límite. El "flujo de oro" (logout del staff + login
 * real del dueño con contraseña temporal) es el único paso destructivo de la sesión de
 * staff, así que corre AL FINAL del describe (serial) — todo lo demás va antes.
 */

const STAFF_EMAIL = 'e2e-admin@maily.local'
const STAFF_PASSWORD = 'Demo1234!'

/**
 * Login genérico reutilizable — misma pantalla /login para staff y dueños de clínica.
 *
 * Con reintento ante el 429 de /auth/login/ (throttle real de 5/minuto — protección
 * contra fuerza bruta, no se debilita en test): si este spec corre en paralelo con
 * login.spec.ts (otro archivo que también hace login real), pueden agotar juntos el
 * límite. En vez de servir peor seguridad, el test espera y reintenta.
 */
async function login(page: Page, email: string, password: string) {
  const intentosMax = 4
  for (let intento = 1; intento <= intentosMax; intento++) {
    await page.goto('/login')
    await page.getByPlaceholder('Correo electrónico').fill(email)
    await page.getByPlaceholder('Contraseña').fill(password)
    await page.locator('button[type="submit"]').click()

    const bloqueado = page.getByText(/Demasiados intentos/i)
    const huboLimite = await bloqueado.isVisible({ timeout: 3_000 }).catch(() => false)
    if (!huboLimite) return
    if (intento === intentosMax) return // se deja fallar la aserción del caller con el mensaje real
    await page.waitForTimeout(15_000)
  }
}

/** Cierra sesión desde el menú del topbar de plataforma (avatar arriba a la derecha).
 *  El botón muestra full_name ("E2E Admin", del seed_e2e_user --platform) o, si
 *  estuviera vacío, el fallback "Equipo Maily" — se cubren ambos casos. */
async function logoutDesdePlataforma(page: Page) {
  await page.getByRole('button', { name: /Equipo Maily|E2E Admin/i }).click()
  await page.getByRole('button', { name: /Cerrar sesión/i }).click()
  await expect(page).toHaveURL(/\/login/, { timeout: 15_000 })
}

test.describe('Portal de plataforma (E2E)', () => {
  test.describe.configure({ mode: 'serial' })

  // Nombre único de clínica para todo el describe (timestamp del test run).
  const nombreClinica = `E2E Clínica ${Date.now()}`
  const dueñoEmail = `dueno.e2e.${Date.now()}@maily.local`
  let passwordTemporal = ''
  let staffCookies: Awaited<ReturnType<import('@playwright/test').BrowserContext['cookies']>> = []

  test.beforeAll(async ({ browser }) => {
    // Login del staff UNA sola vez; las cookies de sesión (refresh httpOnly) se
    // reutilizan en el resto de los tests para no chocar con el throttle de
    // /auth/login/ (5/minuto — ver DRF_THROTTLE_LOGIN en backend/config/settings/base.py).
    const context = await browser.newContext()
    const page = await context.newPage()
    await login(page, STAFF_EMAIL, STAFF_PASSWORD)
    await expect(page).toHaveURL(/\/plataforma\/dashboard/, { timeout: 15_000 })
    staffCookies = await context.cookies()
    await context.close()
  })

  test.beforeEach(async ({ context }) => {
    // Cada test arranca con la sesión del staff ya autenticada (excepto el
    // "flujo de oro", que la sobreescribe explícitamente con logout + login del dueño).
    await context.addCookies(staffCookies)
  })

  test('login del staff entra al dashboard con métricas y actividad reciente', async ({ page }) => {
    await page.goto('/plataforma/dashboard')
    await expect(page).toHaveURL(/\/plataforma\/dashboard/, { timeout: 15_000 })

    // Tarjetas de métricas (números) — "Clínicas activas" siempre está en el set fijo.
    await expect(page.getByText('Clínicas activas')).toBeVisible()
    await expect(page.getByText('Pacientes totales')).toBeVisible()
    await expect(page.getByText('Usuarios totales')).toBeVisible()

    // Bloque de actividad reciente (super_admin tiene acceso a auditoría).
    await expect(page.getByText('Actividad reciente')).toBeVisible()
  })

  test('Clínicas: buscar, crear una nueva y verla en el listado', async ({ page }) => {
    await page.goto('/plataforma/clinicas')
    await expect(page.getByRole('heading', { name: 'Clínicas' })).toBeVisible()

    // Buscar algo que no existe → lista vacía (ejercita el buscador antes de crear).
    await page.getByPlaceholder('Buscar por nombre o slug').fill('clinica-que-no-existe-e2e')
    await expect(page.getByText('No hay clínicas con ese criterio.')).toBeVisible({ timeout: 10_000 })
    await page.getByPlaceholder('Buscar por nombre o slug').fill('')

    // Abrir el modal "Nueva clínica" y llenarlo.
    await page.getByRole('button', { name: 'Nueva clínica' }).click()
    await expect(page.getByRole('heading', { name: 'Nueva clínica' })).toBeVisible()

    await page.getByPlaceholder('Ej. Clínica San José').fill(nombreClinica)
    await page.getByPlaceholder('Juan').fill('Dueño')
    await page.getByPlaceholder('Pérez').fill('E2E')
    await page.getByPlaceholder('dueno@clinica.mx').fill(dueñoEmail)

    await page.getByRole('button', { name: 'Crear clínica' }).click()

    // Éxito: se muestra la contraseña temporal UNA SOLA VEZ — capturarla.
    await expect(page.getByRole('heading', { name: '¡Clínica creada!' })).toBeVisible({ timeout: 15_000 })
    const passwordCode = page.locator('code').first()
    await expect(passwordCode).toBeVisible()
    passwordTemporal = (await passwordCode.textContent())?.trim() ?? ''
    expect(passwordTemporal.length).toBeGreaterThanOrEqual(10)

    await page.getByRole('button', { name: 'Listo' }).click()

    // La clínica creada aparece en el listado (buscándola por nombre).
    await page.getByPlaceholder('Buscar por nombre o slug').fill(nombreClinica)
    await expect(page.getByText(nombreClinica)).toBeVisible({ timeout: 10_000 })
  })

  test('Auditoría: aparece el evento de creación de la clínica', async ({ page }) => {
    test.skip(!passwordTemporal, 'Depende de que el test de creación de clínica haya corrido antes.')

    await page.goto('/plataforma/auditoria')
    await expect(page.getByRole('heading', { name: 'Auditoría' })).toBeVisible()

    await page.getByPlaceholder('Buscar por actor o descripción').fill(nombreClinica)
    // La fila trae dos variantes (tarjeta móvil oculta con CSS + fila de escritorio visible
    // en este viewport); ':visible' descarta la copia oculta (evita el falso "hidden").
    const filaEvento = page.locator('p:visible, span:visible').filter({ hasText: nombreClinica }).first()
    await expect(filaEvento).toBeVisible({ timeout: 10_000 })
    // El badge de acción es un <span> (el <select> de filtro también tiene un <option>
    // con el mismo texto, oculto): ':visible' se queda solo con el badge real.
    await expect(page.locator('span:visible').filter({ hasText: 'Crear clínica nueva' }).first()).toBeVisible()
  })

  test('Suscripciones: cargan los 3 planes reales y se asigna un plan a la clínica creada', async ({ page }) => {
    test.skip(!passwordTemporal, 'Depende de que el test de creación de clínica haya corrido antes.')

    await page.goto('/plataforma/suscripciones')
    await expect(page.getByRole('heading', { name: 'Suscripciones' })).toBeVisible()

    // Los 3 planes del catálogo (sembrados por la migración de datos 0005_seed_plans).
    await expect(page.getByRole('heading', { name: 'Básico' })).toBeVisible({ timeout: 10_000 })
    await expect(page.getByRole('heading', { name: 'Pro' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Premium' })).toBeVisible()

    // KPIs del resumen.
    await expect(page.getByText('Clínicas totales')).toBeVisible()
    await expect(page.getByText('MRR estimado')).toBeVisible()

    // Buscar la clínica creada — la búsqueda filtra el listado a solo esa fila
    // (evita el "strict mode violation" de Playwright por los ~38 botones
    // "Asignar plan" del listado completo, uno por cada variante móvil/escritorio).
    await page.getByPlaceholder('Buscar por nombre o slug').fill(nombreClinica)
    // ':visible' evita la copia oculta por CSS (tarjeta móvil vs. fila de escritorio:
    // ambas están en el DOM, Tailwind solo oculta una según el viewport).
    await expect(page.locator(`:visible:has-text("${nombreClinica}")`).first()).toBeVisible({ timeout: 10_000 })
    await page.locator('button:visible', { hasText: 'Asignar plan' }).first().click()

    await expect(page.getByRole('heading', { name: 'Asignar plan' })).toBeVisible()
    await page.locator('#susc-plan').selectOption({ label: 'Pro' })

    // Fecha de fin de periodo: hoy + 30 días (formato YYYY-MM-DD para <input type="date">).
    const fechaFin = new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10)
    await page.locator('#susc-fin').fill(fechaFin)

    await page.getByRole('button', { name: 'Guardar suscripción' }).click()

    // El modal se cierra y aparece el aviso de éxito; luego la fila muestra el plan asignado
    // (el botón pasa de "Asignar plan" a "Cambiar plan" porque la clínica ya tiene plan_id).
    await expect(page.getByRole('heading', { name: 'Asignar plan' })).not.toBeVisible({ timeout: 10_000 })
    await expect(page.locator(':visible:has-text("Cambiar plan")').first()).toBeVisible({ timeout: 10_000 })
  })

  // NOTA de orden: este test va ANTES del "flujo de oro" porque ese último hace
  // logout REAL del staff (revoca la sesión en el backend) — cualquier test que
  // corra después ya no puede reutilizar `staffCookies`. Todo lo que necesita
  // sesión de staff vive antes; el flujo de oro es el único paso "destructivo".
  test('permisos: "Ver como Ingeniería" oculta Suscripciones en la navegación', async ({ page }) => {
    // No hay forma barata de crear un usuario real con platform_role=engineering desde
    // el frontend (el alta de staff vive en Usuarios y es otro flujo completo). En su
    // lugar se usa el selector "Ver como" del propio topbar: es un preview LOCAL de
    // permisos (PlatformRoleContext) que reutiliza la misma tabla PERMISOS_PLAT que
    // decide qué módulos se ven — sirve para verificar la lógica de visibilidad del
    // menú, aunque no reemplaza un 403 real del backend (eso ya lo cubre
    // apps/plataforma/tests/test_security.py en el backend).
    await page.goto('/plataforma/dashboard')
    await expect(page.getByRole('button', { name: 'Suscripciones' })).toBeVisible()

    await page.getByRole('button', { name: /Equipo Maily|E2E Admin/i }).click()
    await page.getByRole('button', { name: 'Ingeniería' }).click()

    await expect(page).toHaveURL(/\/plataforma\/sistema/, { timeout: 10_000 })
    await expect(page.getByRole('button', { name: 'Suscripciones' })).not.toBeVisible()
  })

  test('flujo de oro: cambio de contraseña forzado del dueño con la contraseña temporal', async ({ page }) => {
    test.skip(!passwordTemporal, 'Depende de que el test de creación de clínica haya capturado la contraseña.')

    // 1) Logout del staff (la sesión venía precargada por beforeEach).
    await page.goto('/plataforma/dashboard')
    await logoutDesdePlataforma(page)

    // 2) Login como el dueño de la clínica creada, con la contraseña temporal.
    await login(page, dueñoEmail, passwordTemporal)

    // 3) must_change_password=True → redirige a /cambiar-contrasena (sin navegación de app).
    await expect(page).toHaveURL(/\/cambiar-contrasena/, { timeout: 15_000 })
    await expect(page.getByText('Crea una nueva contraseña')).toBeVisible()

    // 4) Cambiar la contraseña por una válida.
    const nuevaPassword = 'NuevaClave2026!'
    await page.locator('#password-actual').fill(passwordTemporal)
    await page.locator('#password-nueva').fill(nuevaPassword)
    await page.locator('#password-confirmar').fill(nuevaPassword)
    await page.getByRole('button', { name: 'Cambiar contraseña' }).click()

    // 5) Aterriza en la app de clínica (dueño → no es staff de plataforma).
    await expect(page).not.toHaveURL(/\/cambiar-contrasena/, { timeout: 15_000 })
    await expect(page).not.toHaveURL(/\/login/)
    await expect(page).not.toHaveURL(/\/plataforma/)
  })
})
