---
name: frontend-audit
description: >
  Checklist falsable para auditar el frontend de Maily360 (web-soft/) contra el contrato del
  backend. Úsala SIEMPRE que se audite, revise en modo gate o cierre un módulo que toque
  web-soft/src, y en cualquier sesión donde se pregunte si el frontend y el backend están
  alineados. Detecta las cinco clases de falla que no se ven leyendo solo el backend: deriva de
  permisos (botón fantasma y función invisible), gating por módulo desalineado, caché de TanStack
  Query que sobrevive al cambio de clínica o de sede, header X-Sucursal-Id ausente, y fugas del
  bundle. Cada punto se responde con evidencia archivo:línea de AMBOS lados o se marca
  NO VERIFICABLE. No opina de diseño ni de estética.
---

# Auditoría de frontend contra el contrato — Maily360

Auditas `MailySoft/web-soft/src` contra `MailySoft/docs/02-contrato.md`. **No es una revisión de
código ni de diseño: es un cruce de dos listas.** Cada punto de abajo se contesta con evidencia de
los dos lados o se marca `NO VERIFICABLE`. Nunca `PASA` sin cita.

## Por qué existe esta skill

El contrato documenta el backend y el backend es la autoridad de permisos. Eso hace creer que el
frontend no puede causar daño. Puede, de cinco formas, y ninguna se ve leyendo el backend.

## Dónde vive cada cosa (verificado 2026-08-12)

| Lado | Archivo |
|---|---|
| Permisos por rol en la UI | `web-soft/src/auth/permisos.ts` (`MATRIX`, `PERMISOS`) |
| Rol y capacidades de la sesión | `web-soft/src/auth/AuthContext.tsx` (`capabilities`, `tieneModulo`) |
| Espejo del catálogo de módulos | `web-soft/src/lib/modulos.ts` (`MODULO_REQUIERE`, `ROL_REQUIERE`, `expandirDependencias`) |
| Rutas y su gating | `web-soft/src/App.tsx` (`ClinicRoute modulo=…`, `PlatformRoute`) |
| Cliente HTTP único | `web-soft/src/lib/http.ts` |
| Token de acceso | `web-soft/src/lib/tokenStore.ts` |
| Sede activa | `web-soft/src/auth/SucursalContext.tsx`, selector en `components/Topbar.tsx` |
| Estado de servidor | `web-soft/src/hooks/*.ts` (20 archivos) |
| Autoridad real | `backend/apps/core/permissions.py`, `backend/apps/core/entitlement_guards.py`, `backend/apps/clinica/sucursal_scope.py` |

## Cruce 1 · Deriva de permisos

Por cada clase de permiso del backend (§1.3.2 del contrato tiene las 50 con su `policy`), encuentra
qué decide el frontend para esa misma acción. Dos fallas, y las dos cuentan:

- **BOTÓN FANTASMA** — el frontend ofrece la acción y el backend responde 403. El usuario cree que el
  sistema está roto y te llama. Es el más caro en soporte.
- **FUNCIÓN INVISIBLE** — el frontend la esconde y el backend la permite. Pagaste por código que
  nadie usa, y a veces es una capacidad que el cliente pidió y cree que no existe.

Entrega una tabla: `acción | roles que permite el backend (archivo:línea) | roles a los que el front
la muestra (archivo:línea) | veredicto`.

**Trampas conocidas de este repo:**

- El rol viene de `/me/` y se persiste en `tokenStore`; una comprobación hecha contra un rol cacheado
  después de cambiar de sesión es una falla real, no teórica.
- Varias reglas del backend **no viven en el permiso sino en el `service`** (el médico solo agenda
  para sí mismo, solo anula su propia receta, solo escribe sobre citas suyas). El frontend no puede
  reflejarlas con una matriz de rol: revisa si las esconde por rol cuando debería hacerlo por
  pertenencia.
- El código de respuesta ante un método no declarado en la `policy` es **403, no 405**, y en varios
  endpoints **depende del rol**. Un manejo de error que asume 405 no se dispara.

## Cruce 2 · Gating por módulo

Cada `<ClinicRoute modulo="X" requiere="Y">` de `App.tsx` contra el `Requires*` de las vistas que esa
pantalla consume. Deben nombrar el mismo módulo.

- Un módulo apagado responde **404, no 403**: si el frontend trata el 404 como "no existe el
  registro" en vez de "no contratado", el usuario ve una pantalla vacía sin explicación.
- `lib/modulos.ts` es un **espejo** del catálogo de `backend/apps/core/modules.py`. Dos fuentes de
  verdad: compara los 12 módulos, sus dependencias duras y los roles que cada módulo habilita. Una
  divergencia aquí hace que el menú ofrezca algo que la API va a negar.
- Verifica también el camino inverso: un módulo activo cuya pantalla no está enrutada.

## Cruce 3 · Caché entre clínicas y entre sedes

**El más grave y el que nadie revisa.** Es una fuga de datos que ocurre en el navegador aunque el
backend esté perfecto.

- ¿Toda clave de query incluye el tenant y, cuando aplica, la sucursal activa? Una clave como
  `['pacientes', filtros]` sirve datos de la clínica anterior al cambiar de sesión.
- Al **cambiar de sede** con el selector: ¿qué se invalida? Lo que no se invalide sigue mostrando la
  sede anterior.
- Al **cerrar sesión o cambiar de usuario**: ¿se vacía el caché de TanStack Query, no solo el token?
- ¿Hay algo del dominio en `localStorage` o `sessionStorage`? Los snooze de recordatorios y las
  pausas de la alerta de seguimiento sí viven ahí: revisa que no lleven PII ni datos de paciente, y
  que estén separados por usuario.

Si encuentras una clave sin tenant o sin sede, es **P0**: escribe el escenario exacto (qué usuario,
qué pantalla, qué dato de qué clínica se ve).

## Cruce 4 · Header `X-Sucursal-Id`

- ¿Sale en toda petición que el backend acota por sede? El backend lo lee en
  `clinica/sucursal_scope.py`; el contrato dice qué endpoints lo usan.
- ¿Qué pasa si falta? Comprueba el fallback del backend y si el frontend depende de él sin saberlo.
- ¿El selector de sede se oculta con una sola sucursal, y el `owner` tiene la opción "todas"?
- **Detalle contra listado:** el backend acota varios listados por sede pero no sus detalles por id.
  El frontend puede estar navegando a un detalle fuera de alcance desde un listado que sí filtró.
  Anota cada caso: es la clase de brecha más repetida del proyecto.

## Cruce 5 · Bundle y XSS

Puntos binarios, se responden con un `grep`:

- Cero `dangerouslySetInnerHTML`.
- Cero `fetch(` o `axios` fuera de `lib/http.ts`.
- El access token **solo en memoria**, nunca en `localStorage` ni `sessionStorage`.
- Cero secretos, llaves o URLs privadas en `src/` ni en `.env` versionado. Solo `VITE_*` públicas.
- El refresh automático ante 401 ocurre **una vez** y no sobre `/auth/refresh/` (bucle infinito).
- Nada de datos de prueba ni arreglos de demostración importados en código de producción.

## Formato del reporte

`MailySoft/docs/00-brechas-frontend.md`, una sección por cruce. Cada hallazgo:

```
### F-<CRUCE>-<NN> · <título en una línea>
**Severidad:** P0 / P1 / P2
**Backend:** <archivo:línea> — qué permite o exige
**Frontend:** <archivo:línea> — qué hace
**Qué ve el usuario:** <escenario concreto: qué rol, en qué pantalla, con qué dato>
**Clase:** botón fantasma / función invisible / caché sucia / alcance de sede / bundle
```

## Reglas de esta auditoría

1. **No corriges código.** Documentas. Si arreglas mientras documentas, el reporte no describe ni el
   sistema viejo ni el nuevo.
2. **Sin evidencia de los dos lados no hay hallazgo.** Una sospecha va como `NO VERIFICABLE` con lo
   que haría falta para confirmarla.
3. **La severidad se justifica con el escenario, no con adjetivos.** "Grave" no es una severidad;
   "la recepcionista de Norte ve el teléfono de un paciente de Centro" sí.
4. **Nada de diseño.** Espaciado, colores y consistencia visual no son esta auditoría.
5. Si el frontend y el backend difieren y **el frontend tiene razón** (el backend es más
   restrictivo de lo que el negocio quiere), dilo: es una brecha de producto, no un bug de UI.
