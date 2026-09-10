# Sesiones maestras — camino al MVP vendible

> Decidido el **2026-09-09**. Sustituye al orden de `00-modulos.md` como **prioridad del día a día**,
> sin invalidarlo: los módulos M0–M6 siguen siendo la lista de arreglos, pero ahora entran cuando una
> sesión maestra tropieza con ellos, no en fila por su cuenta.
>
> **Por qué cambió el orden.** El 2026-09-09 se confirmó que el despliegue de Railway **no tiene
> datos reales de ninguna clínica**. Eso baja `proyecto.etapa` a `desarrollo` y quita la urgencia de
> M1: la nota que se pierde no le está borrando el trabajo a ninguna doctora todavía. Manda el MVP.
> **El día que entre la primera clínica de pago, esto se invierte** — ver S5.

---

## Qué es una sesión maestra

Una **conversación larga de Claude Code, en una carpeta, sobre un solo dominio**, que:

1. Carga el contexto completo de ese dominio al abrir (los archivos están listados en cada ficha).
2. Prueba a mano lo que hay, contigo mirando, y anota qué está roto.
3. **Despacha subagentes** a cada arreglo concreto y verifica lo que devuelven.
4. Al cerrar, deja escrito qué quedó y qué falta, para que la siguiente no empiece de cero.

**Por qué subagentes y no hacerlo todo en la misma conversación:** un subagente arranca con el
contexto en blanco, hace una tarea acotada y devuelve el resultado. La sesión maestra no gasta su
memoria en los detalles del arreglo, así que **conserva el hilo del módulo completo** — que es
exactamente lo que se pierde hoy al saltar entre sesiones.

**La contra, y hay que tenerla presente:** el subagente **no ve esta conversación**. Su encargo tiene
que ser autosuficiente: qué archivo, qué comportamiento se espera, cómo se comprueba. Un encargo del
tipo «arregla lo que hablamos» no llega.

### Los cuatro subagentes disponibles

| Subagente | Para qué se despacha |
|---|---|
| `backend` | Implementa un arreglo en Django/DRF, con su test |
| `frontend` | Implementa un arreglo en React/TS |
| `architect` | **Modo inverso**: documenta en `02-contrato.md` lo que el módulo hace hoy |
| `reviewer` | Dictamina con `archivo:línea`. No edita nada |

**Los contratos se escriben así, poco a poco:** cuando una sesión maestra termina de estabilizar un
módulo, despacha `architect` en modo inverso para dejar en el contrato lo que ese módulo **hace de
verdad**. No se detiene el trabajo a escribir contratos por adelantado.

### Una sesión a la vez

Dos sesiones sobre la misma carpeta se pisan los archivos. Para trabajar en paralelo hace falta
`git worktree` — una segunda carpeta atada al mismo repo. **Pídeme que te lo explique el día que lo
necesites**; hasta entonces, de una en una.

---

## El orden

| # | Sesión maestra | Cierra cuando | Tamaño |
|---|---|---|---|
| **S0** | Recuperar el rediseño del frontend | ✅ **cerrada 2026-09-10** — PR #5 en `main` | 1 sesión |
| **S0.5** | Frontend: red de seguridad y pulido | Los e2e corren en CI y las vistas de la lista cumplen los cinco criterios | 1–2 sesiones |
| **S1** | Núcleo clínico de punta a punta | Agendas, atiendes, escribes nota y emites receta sin tocar el código | 2–3 sesiones |
| **S2** | Finanzas terminado | Cobras, cierras caja y sacas el reporte del día | 2 sesiones |
| **S3** | Panel de super administrador | Das de alta una clínica completa desde el panel, sin consola | 1–2 sesiones |
| **S4** | Planes y precios para vender | Existe la lista de precios y el plan que compra una clínica la limita de verdad | 1 sesión + decisiones tuyas |
| **S5** | Endurecer antes de la primera clínica real | M1, M2, M4 y M5 cerrados | 3–4 sesiones |

**S5 no se salta.** Es el candado entre «funciona en mi demo» y «se lo vendo a una clínica que va a
meter pacientes de verdad». El día que firmes la primera, S5 pasa a ser lo único que importa.

---

## S0 · Recuperar el rediseño del frontend

**Verificado el 2026-09-09, antes de empezar:** la rama `wip/frontend-rediseno` (commit `0f31bb0`,
respaldada en GitHub) **compila sin errores**, TypeScript incluido, y **mergea a `main` sin un solo
conflicto**. 48 archivos, +2098/−992. Once son nuevos, entre ellos `MarcaMaily.tsx`,
`TarjetaPacienteHover.tsx`, `BarraAlergias.tsx` y las tres pestañas de finanzas `CajaTab`,
`CobranzaTab` y `ResumenTab`.

**Qué hace la sesión:** levanta la rama en local, la recorres tú pantalla por pantalla, y si se ve
bien entra a `main` por PR. **Sin auditoría de código** — el objetivo es recuperar tu trabajo, no
juzgarlo. Lo que esté mal saldrá en S1 y S2, que son las sesiones que sí revisan esas pantallas.

**No hace:** rediseñar nada nuevo, ni arreglar las 76 brechas de frontend documentadas.

### Cómo quedó · cerrada el 2026-09-10

PR [#5](https://github.com/Quint4n4/Maily360/pull/5), rama `feat/rediseno-frontend`, un commit,
48 archivos, +2098/−992. CI en verde y merge a `main` (`880d732`).

**Recuperó el rediseño íntegro y sin tocarlo:** comparado archivo por archivo contra
`wip/frontend-rediseno`, el frontend es idéntico. Los toques de UI que Emanuel quería dar no se
llegaron a hacer y **pasan a S0.5**, que es donde tienen su lista cerrada.

⚠ El candado bloqueante aprobó este PR corriendo **3.418 tests de backend y cero de frontend**. Las
48 pantallas entraron a `main` sin que ninguna prueba automática las mirara. Eso es lo que S0.5
viene a cerrar.

### Prompt de arranque

```
Sesión maestra S0. Lee CLAUDE.md, .claude/PERFIL-DEL-REPO.md y
MailySoft/docs/00-sesiones-maestras.md §S0.

Objetivo: devolver el rediseño de la rama wip/frontend-rediseno a main.

1. Crea la rama feat/rediseno-frontend desde main y trae ahí wip/frontend-rediseno.
2. Levanta el backend (docker compose) y el frontend en local, y dime la URL.
3. PARA. Yo voy a recorrer las pantallas y te digo qué se ve mal.
4. Con lo que te diga, despacha subagentes `frontend` a los arreglos concretos.
5. Cuando yo dé el visto bueno, abre el PR a main.

No refactorices nada que yo no haya señalado. No corras el auditor de frontend.
```

---

## S0.5 · Frontend: red de seguridad y pulido

Dos objetivos independientes en una sesión. **La red va primero**, porque el pulido consiste en
mover cosas de sitio y hoy nada avisaría si al moverlas se rompe una llamada a la API.

### Parte 1 · Encender los tests que ya existen

**No hay que escribirlos desde cero.** Verificado el 2026-09-10: `MailySoft/web-soft/e2e/` tiene
**10 pruebas de Playwright** ya escritas y `playwright.config.ts` configurado —
`login.spec.ts` (3) y `plataforma.spec.ts` (7: dashboard, alta de clínica, auditoría, asignación de
plan, permisos por rol y el flujo de contraseña temporal del dueño).

**Nunca han corrido en CI.** `.github/workflows/ci.yml` no tiene un solo paso de Node.

Trabajo real de esta parte, en orden:

1. Correrlos en local y ver cuántos pasan hoy. Necesitan el backend en Docker y los usuarios demo
   (`seed_finanzas`). **Ese número es el punto de partida y hay que anotarlo**, pase lo que pase.
2. Arreglar los que fallen — con el rediseño recién mergeado es probable que alguno busque un texto
   o un selector que cambió de sitio.
3. Meterlos en CI como job propio: navegadores de Playwright, backend levantado y semilla.
4. Decidir si bloquea o es informativo. **Recomendación: informativo la primera semana**, porque un
   e2e recién montado da falsos rojos y un candado que falla sin razón se acaba ignorando — y
   entonces no sirve de nada.

### Parte 2 · El pulido, con lista cerrada

**Antes de tocar una vista, escribe aquí la lista de las que vas a mejorar y ciérrala.** Tres a
cinco, con qué le cambias a cada una. Lo que descubras fuera de la lista se anota, no se hace. Sin
esto, «darle más toques» no tiene final: siempre hay una pantalla más.

Los cinco criterios, que son verificables mirando y no son cuestión de gusto:

| # | Criterio | Cómo se comprueba |
|---|---|---|
| 1 | **Jerarquía** | Lo que salva a alguien va primero: nombre, alergias, motivo. Si las alergias se ven igual que el teléfono, está mal |
| 2 | **Consistencia** | La misma acción se ve igual en todas partes. «Guardar» no puede ser un botón sólido aquí y un enlace gris allá |
| 3 | **Los tres estados** | Cargando, vacío y error. Abre cada vista con la base sin datos: la mayoría no tiene estado vacío |
| 4 | **Densidad** | Una recepcionista con quince citas no quiere scroll. Si una lista muestra cuatro filas por pantalla, sobra aire |
| 5 | **Contraste y área clicable** | Gris claro sobre blanco no se lee en una tablet con luz de ventana; un icono de 16px no se atina con prisa |

**Regla de corte mientras recorres:** ¿una doctora usando esto **se atoraría**, o solo lo
encontraría **menos bonito**? Atorarse es bug y se arregla. Menos bonito espera.

### Criterio de cierre

- `npm run test:e2e` pasa entero en local, y se sabe cuántos pasaban al empezar.
- Los e2e corren en CI en cada PR que toque `MailySoft/web-soft/`.
- Las vistas de la lista cerrada cumplen los cinco criterios, comprobado con la app corriendo.
- La lista cerrada quedó escrita aquí, con lo que se hizo en cada vista.

### Prompt para la sesión

```
Sesión maestra S0.5. Lee CLAUDE.md, .claude/PERFIL-DEL-REPO.md y
MailySoft/docs/00-sesiones-maestras.md §S0.5.

PARTE 1 primero, no la saltes.

1. Levanta el backend en Docker, siembra los datos demo y corre los 10 tests e2e
   de MailySoft/web-soft/e2e/. Dime cuántos pasan HOY antes de tocar nada.
2. Arregla los que fallen. Si alguno falla porque el rediseño movió un texto o un
   selector, arregla el test, no la pantalla — salvo que la pantalla esté mal.
3. Agrégalos al CI como job propio de Node, informativo (continue-on-error), que
   corra solo cuando el PR toque MailySoft/web-soft/.

PARA aquí y enséñame el resultado antes de seguir.

PARTE 2 — el pulido. Yo te doy la lista cerrada de vistas. Para cada una aplicas
los cinco criterios de la ficha y me la enseñas corriendo antes de pasar a la
siguiente. No toques ninguna vista que no esté en mi lista.

Despacha subagentes `frontend` para los arreglos concretos, con encargos que se
entiendan sin haber leído esta conversación.
```

---

## S1 · Núcleo clínico de punta a punta

**El recorrido que tiene que funcionar sin tocar código**, y es el criterio de cierre completo:

> Doy de alta una paciente → le agendo una cita → marco que llegó → abro su expediente → escribo la
> nota de evolución → le emito una receta → la receta genera su PDF y su código de verificación.

**Contexto de la sesión:** `apps/pacientes`, `apps/agenda`, `apps/expediente`, `apps/recetas` (27.5k
líneas entre las cuatro) y sus pantallas. Es el módulo más grande del sistema.

**Reglas duras que aquí no se negocian**, aunque estemos en `desarrollo`:
- La nota de evolución y la receta **no se editan ni se borran**. Se corrigen con addendum o se
  anulan con motivo. Si algo pide un `update`, es un bug del diseño, no una comodidad que falta.
- Toda acción sensible se registra con `audit_record`.

**Ojo con M1:** el bug de la nota que se guarda y no existe **vive aquí** (`request_id` de más de 64
caracteres + bitácora sin savepoint). Si aparece durante las pruebas a mano, se arregla en el momento
y se marca M1 como cerrado en `00-modulos.md`. No hace falta una sesión aparte para él.

---

## S2 · Finanzas terminado

**Criterio de cierre:** cobro una consulta, la registro en caja, cierro el día y saco el reporte, y
los números cuadran con lo que cobré.

**Contexto:** `apps/finanzas` (6.7k líneas) más las pestañas que llegan en S0. Aquí también vive
**M3** (doble clic, doble cargo), del plan de ataque.

**Decisión de negocio pendiente que bloquea parte de esto:** el CFDI del plan Premium. Está en
`00-plan-de-ataque.md` y es tuya, no técnica.

---

## S3 · Panel de super administrador

**Criterio de cierre:** doy de alta una clínica nueva, le asigno plan y módulos, creo a su dueño y
la clínica entra a trabajar — todo desde el panel, sin abrir la consola de Django ni Railway.

**Contexto:** `apps/plataforma` (4.2k), `apps/tenancy` (1.9k), `src/pages/plataforma/` y
`src/platform/`.

**Prueba de que quedó bien:** correr `seed_planes` no debería ser necesario para que una clínica
nazca con módulos. Si lo es, el panel todavía no está terminado.

---

## S4 · Planes y precios para vender

Mitad técnica, mitad negocio. **La parte que solo puedes hacer tú:** la lista de precios en pesos.

De `00-plan-de-ataque.md` salen dos decisiones más que llevan meses abiertas: qué hace el CFDI en
Premium, y qué pasa con las capacidades que el backend cobra pero que no tienen pantalla.

**Criterio de cierre:** una clínica en plan Básico intenta usar algo de Premium y **recibe 404, no
403** — no debe enterarse de que existe algo que no compró. Y el límite de usuarios del plan
efectivamente impide crear al usuario de más.

**Recordatorio del perfil, no técnico:** hoy no repercutes infraestructura al cliente. Railway te
cuesta ~40 USD/mes de tu bolsillo. La mensualidad de cada clínica tiene que incluirla más margen.

---

## S5 · Endurecer antes de la primera clínica real

Los módulos del plan de ataque que no se hayan cruzado antes: **M1** (nota que se pierde), **M2**
(llaves de la demo en producción), **M4** (workers de Celery sin tenant) y **M5** (cerrar el fallback
de RLS).

⚠ **M4 va antes que M5, y el orden no es negociable.** Los workers de Celery nunca fijan el tenant y
hoy funcionan gracias al fallback `OR current_tenant_id() IS NULL` de las políticas de RLS. Cerrar
ese fallback antes de arreglar los workers **tumba todos los PDFs asíncronos el mismo día**.

También aquí: el test permanente de revocación de sesión que hoy no existe, y `proyecto.etapa` sube a
`produccion-temprana` en `.claude/PERFIL-DEL-REPO.md`.

---

## Cómo se cierra una sesión maestra

Tres líneas al final de la conversación, escritas **en este archivo**, bajo la ficha de la sesión:

1. Qué quedó funcionando, con la prueba a mano que lo demuestra.
2. Qué quedó roto y a dónde se movió (`00-modulos.md`, o una ficha nueva aquí).
3. Qué se documentó en `02-contrato.md`, si se despachó `architect`.

Sin eso, la siguiente sesión vuelve a descubrir lo mismo. Es el problema que todo este sistema existe
para resolver.
