# Pruebas E2E con Playwright

> Estado: **montado y en verde** · 2026-06-29
>
> Las pruebas E2E (extremo a extremo) manejan un **navegador real** contra la app
> corriendo, probando los flujos completos **frontend + backend** (lo que los tests
> de Python no cubren). Viven en `web-soft/e2e/`.

## Cómo correrlas

**Requisitos:**
1. El **backend** corriendo (Docker, `:8000`) — el proxy de Vite reenvía `/api` ahí.
2. Datos demo + usuario E2E sembrados (una sola vez):
   ```bash
   docker compose exec backend python manage.py seed_finanzas    # crea clinica-demo
   docker compose exec backend python manage.py seed_e2e_user    # crea e2e@maily.local
   ```
3. Playwright levanta el **frontend** solo (`npm run dev`); si ya corre, lo reusa.

**Correr:**
```bash
cd web-soft
npm run test:e2e            # todas
npx playwright test --ui    # modo interactivo (ver el navegador paso a paso)
npx playwright show-report  # reporte HTML de la última corrida
```

## Qué cubre hoy

`e2e/login.spec.ts`:
- La pantalla de login carga con sus campos.
- Login **exitoso** entra al sistema (front + back real).
- Credenciales inválidas muestran error y no entra (401).

## Cómo agregar más flujos

Crea un archivo `e2e/<flujo>.spec.ts`. Para flujos autenticados, primero haz login
(o extrae un helper de login). Próximos candidatos de alto valor:
- Crear paciente → emitir receta → **descargar el PDF** (toca el flujo async que migramos).
- Agendar una cita.
- Cobrar / generar una cotización.

Selectores recomendados (estables): `getByRole`, `getByPlaceholder`, `getByText`.
Evitar selectores por clases de Tailwind (cambian).

## Usuario de pruebas

`seed_e2e_user` crea **`e2e@maily.local` / `Demo1234!`** (rol owner en `clinica-demo`),
dedicado a E2E — no toca usuarios reales. Es idempotente; re-córrelo si hace falta.

## Pendiente (futuro)

Correr el E2E **en CI** requiere levantar todo el stack (backend + BD + seed) en el
runner de GitHub. Es un paso aparte; por ahora el E2E se corre en local.
