# Tablero de trabajo — módulos

> El plan dividido en piezas de una sesión. **Uno a la vez**, cada uno con su rama, su prueba a mano
> y su PR. No se empieza el siguiente sin cerrar el anterior.
>
> Los otros tres documentos siguen sirviendo: `00-plan-explicado.md` para entender qué se rompe,
> `00-plan-de-ataque.md` para el orden y la deuda aceptada, `00-deuda.md` para el detalle completo.
> **Este es el que se marca.**

## Cómo se trabaja cada módulo

Siempre igual, seis pasos:

1. **Lees el módulo aquí** y entiendes qué se está arreglando. Si algo no se entiende, se para y se
   explica — no se avanza a ciegas.
2. **Rama nueva:** `git checkout -b fix/<nombre-del-modulo>`
3. **Ves el problema con tus ojos** (la "prueba antes"). Esto no es opcional: si no viste el error,
   no vas a saber si lo arreglaste o si solo cambiaste código.
4. **Sesión de Claude Code** con el prompt del módulo. Una sesión, un módulo.
5. **Vuelves a probar a mano** (la "prueba después") y compruebas que cambió lo que debía.
6. **PR y merge.** Se marca aquí y se pasa al siguiente.

---

# M0 · Encender los instrumentos

**Estado:** 🟡 en curso — M0.1 y M0.3 cerrados, M0.2 aplazado, M0.4 siguiente · **Riesgo:** ninguno

Va primero por una razón concreta: **sin esto no puedes saber si los arreglos siguientes
funcionaron.** Y además Sentry te va a mostrar si el problema de M1 está ocurriendo en producción
ahora mismo — cuando la bitácora falla, el código escribe un error, y Sentry recoge esos errores.

## M0.1 · Sentry — sin código, solo Railway

**Qué haces:** crear la cuenta (el plan gratis alcanza de sobra), crear un proyecto de tipo Django,
y copiar la dirección que te da — se llama DSN y se ve como una URL larga.

En Railway, en **los dos servicios** (`Maily360` y `intuitive-nurturing`), agregas:

```
SENTRY_DSN            = <la URL que te dio Sentry>
SENTRY_ENVIRONMENT    = production
```

Redespliegas.

> ⚠️ **Dos trampas, las dos ya vividas.** Revisa que el **nombre** de la variable no lleve espacios
> —al pegar es fácil que quede `SENTRY_DSN `, y entonces el código nunca la encuentra— y que el
> **valor** del DSN esté completo y sin comillas ni saltos de línea. Un DSN mal formado **impide que
> la aplicación arranque**, porque Sentry se inicializa durante el arranque de Django.

**Prueba a mano.** Entra a la consola de Railway del servicio `Maily360` —la misma donde corriste
`check_db_role`— y provoca un error de verdad:

```bash
python manage.py shell -c "
import sentry_sdk
try:
    1/0
except ZeroDivisionError:
    sentry_sdk.capture_exception()
sentry_sdk.flush(timeout=5)
"
```

El `flush` obliga a que se envíe antes de que el proceso termine; sin él, un comando de una línea
puede morir antes de alcanzar a mandarlo.

Abre Sentry → **Errors & Outages**, y **limpia los filtros de la barra de búsqueda** (las ✕ de
`is unresolved` y de `issue.category is error`). Ese `ZeroDivisionError` tiene que aparecer en menos
de un minuto. Si no aparece, no sigas hasta verlo.

**Pendiente de este módulo: el Sentry del frontend.** No basta con agregar `VITE_SENTRY_DSN` en
Railway. El `Dockerfile` compila el frontend **dentro de la imagen**, y las variables `VITE_*` tienen
que existir en el momento de la compilación, no cuando el contenedor ya corre. Hoy el `Dockerfile` no
tiene ningún `ARG` para recibirla, así que ponerla no haría nada — sin fallar. Requiere tocar el
`Dockerfile`; va como pieza aparte.

**Lo que probablemente pase después:** en las siguientes horas van a empezar a caer errores reales
que llevaban meses ocurriendo sin que nadie los viera. **Eso es bueno.** No los arregles todavía:
anótalos y revísalos cuando cierres M1. Ver todo junto por primera vez impresiona; casi nada de eso
es urgente.

## M0.2 · Correo — sin código, solo Railway

Hoy todo correo que el sistema manda se imprime en el registro de Railway y nadie lo recibe.

Elige proveedor (Resend o Amazon SES; **nunca** el SMTP de Gmail en producción), y agrega en Railway
las variables del proveedor que elijas más `DJANGO_EMAIL_BACKEND`.

> **Antes de configurarlo, una pregunta que vale la pena:** ¿qué correos manda hoy el sistema? Si la
> respuesta es "ninguno importante todavía", esto puede esperar a que exista el primero. Vale la pena
> revisarlo antes de pagar un servicio que nadie usa. Lo que **no** puede quedarse así es la
> ilusión: hoy el código cree que manda correos.

## M0.3 · Las variables obligatorias — este sí toca código

Hoy el sistema arranca aunque falten configuraciones que deciden cosas serias. Se trata de que
**cuatro de ellas se vuelvan obligatorias**: si faltan, el sistema no arranca y te enteras en el
despliegue.

**Ya verifiqué que las cuatro están puestas en los dos servicios de Railway**, así que poner el
candado no va a tumbar tu producción. Si no lo hubiera verificado, este cambio sería peligroso —
tenlo presente para la próxima: *primero se comprueba que la puerta está cerrada, después se pone la
alarma.*

Y de paso, dos cosas más que salieron de un incidente real (ver abajo):

- **Que el guión de arranque muestre el error real.** Hoy la comprobación de arranque intenta levantar
  Django y conectarse a la base, y **si algo falla tira el error a la basura** y siempre imprime el
  mismo mensaje: *"PostgreSQL no disponible"*. Entonces cualquier fallo de arranque —una variable mal
  escrita, una dependencia rota, un valor inválido— se disfraza de problema de base de datos. Son dos
  caracteres: quitar el `2>/dev/null`.
- **Que el despliegue verifique solo el rol de la base de datos.** Ese comando que corriste a mano
  existe justo para eso y no lo ejecuta nadie.

> ### Incidente del 2026-08-13, y por qué estos dos puntos existen
>
> Al configurar Sentry, el valor del DSN quedó mal formado en el servicio del worker. Sentry se
> inicializa mientras Django arranca, así que un DSN inválido **impide que la aplicación levante**.
> El worker entró en bucle de arranque durante 20 minutos.
>
> Y en todo ese tiempo el registro decía **"PostgreSQL no disponible"**. La base de datos estaba
> perfecta, corriendo sin interrupción desde el 19 de julio. El diagnóstico correcto salió de comparar
> los dos servicios —el web arrancaba, el worker no, mismo código, misma base— no del mensaje de error,
> que apuntaba al lugar equivocado.
>
> **Lo que hay que llevarse:** un mensaje de error genérico no es un detalle de estilo. Cuesta horas
> de buscar en el sitio equivocado, y las cuesta el día que hay algo caído.
>
> En el mismo episodio, en el otro servicio, las variables se habían guardado con un **espacio al final
> del nombre** (`SENTRY_DSN `), así que el código nunca las encontró y Sentry siguió apagado sin una
> sola señal. Dos formas distintas del mismo problema: configuración que se ve puesta y no lo está.

**Prueba a mano.** En tu computadora, con el proyecto local:

1. Borra temporalmente una de esas cuatro variables de tu `.env` y levanta el backend **con la
   configuración de producción**.
2. Tiene que **negarse a arrancar**, con un mensaje que diga exactamente qué variable falta.
3. La devuelves, vuelve a arrancar. Listo.

Si arranca sin la variable, el candado no quedó.

### Cómo quedó · cerrado el 2026-08-13

Rama `fix/arranque-variables-obligatorias`. Lo que cambió:

- **`config/settings/production.py`** exige las cuatro sin default. Las valida **juntas**: un
  servicio mal configurado las reporta todas en un solo arranque, en vez de una por ciclo de
  despliegue. Un valor en blanco cuenta como ausente — en el panel de Railway `REDIS_URL=` se ve
  puesta y no lo está.
- **`entrypoint.sh`** ya no manda el error a `/dev/null`. Cada reintento imprime la última línea del
  error real y el traceback completo sale al agotarse los intentos. Ese bloque levanta Django
  entero, así que falla por cualquier cosa que impida arrancar; el mensaje fijo "PostgreSQL no
  disponible" mandaba a buscar al lugar equivocado.
- **`entrypoint.sh`** corre `check_db_role` al arrancar. Aborta **solo en producción**: el Postgres
  de `docker-compose` y el de CI corren como superuser a propósito, y bloquear ahí rompería
  `docker compose up` sin decir nada de producción. `REQUIRE_DB_ROLE_RLS=false` desactiva el candado
  para no bloquear el rollback de `deploy-rol-app-nosuperuser.md`.
- **`apps/core/tests/test_production_settings.py`** — 21 tests. Verificados por mutación:
  revirtiendo `production.py`, 17 fallan.
- **`docs/DEPLOY-RAILWAY.md`** — bloque de variables al día, con las cuatro, las dos de Sentry y
  `MIGRATION_DATABASE_URL`.

Prueba a mano hecha el 2026-08-13, cinco casos: falta una variable → no arranca y la nombra; las
cuatro puestas → arranca; DSN de Sentry inválido → se ve `BadDsn` en vez de "PostgreSQL no
disponible"; rol superuser en producción → no arranca; el mismo rol en desarrollo → advierte y sigue.

**Dos pendientes que salieron de aquí, no bloquean el cierre:**

1. `deploy-rol-app-nosuperuser.md:3` dice que el rol NOSUPERUSER no está aplicado en Railway.
   `00-plan-de-ataque.md:22`, verificado contra el panel, dice que sí. Corregir esa línea.
2. `.env.production.example` no tiene `MIGRATION_DATABASE_URL` y su `DATABASE_URL` apunta al rol
   superuser. Copiarlo tal cual para un servicio nuevo ahora falla por el candado del rol.

### Prompt para la sesión

```
Módulo M0.3 del plan. Lee CLAUDE.md y MailySoft/docs/00-plan-de-ataque.md §1.3.

Haz que production.py exija estas cuatro variables al arrancar, con el mismo patrón
que ya usa para las cinco actuales y con un mensaje que diga cuál falta:
DJANGO_DEFAULT_FILE_STORAGE, PRESCRIPTION_VERIFY_SECRET, PRESCRIPTION_VERIFY_BASE_URL
y REDIS_URL.

Agrega también la verificación del rol de base de datos al arranque o al pipeline de
CI: el comando check_db_role ya existe y devuelve código 1 si el rol evade RLS.

Actualiza el bloque de variables de docs/DEPLOY-RAILWAY.md, al que le faltan estas
cuatro y las dos de Sentry.

No toques nada más. Al terminar, dime cómo probarlo en local y qué esperar ver.
```

---

# M1 · La nota que se guarda y no existe

**Estado:** ⬜ pendiente · **Tiempo:** una tarde · **Riesgo:** bajo · **Es el P0 más grave**

La escena completa está en `00-plan-explicado.md §1.1`. Resumen de una línea: la Dra. Ana guarda una
nota, la pantalla dice "listo", y la nota no existe.

## Lo que se hace

Dos cosas independientes, las dos necesarias:

1. **Cortar a 64 caracteres** ese folio que llega del navegador, antes de guardarlo. En tres lugares.
   Es una línea en cada uno.
2. **Aislar la anotación de bitácora** para que si falla, falle sola y no arrastre lo demás.

## La prueba antes — y esta es la parte importante

**No arregles nada todavía.** Primero vas a ver el error con tus ojos, en tu computadora, con la base
de datos local. Nunca en producción.

Le vas a pedir a la sesión que primero escriba un guioncito de reproducción: algo que guarde una nota
y a la vez fuerce el fallo de bitácora, y luego te diga si la nota quedó guardada.

**Hoy va a decir que la nota NO existe, sin haber lanzado ningún error.** Ese momento —ver que el
sistema dice que todo salió bien y el dato no está— es lo que hace que entiendas el problema de
verdad. Vale más que cualquier explicación mía.

Después se arregla, corres el mismo guión, y ahora dice que la nota **sí** existe.

## Cómo sabes que quedó

Tres cosas, y las tres tienen que cumplirse:

- El guión de reproducción, que antes decía que no, ahora dice que sí.
- Existe una **prueba automática** que hace lo mismo, para que nadie lo deshaga sin enterarse.
- En Sentry (ya encendido en M0) dejan de aparecer esos errores de bitácora, si es que aparecían.

### Prompt para la sesión

```
Módulo M1 del plan, causa raíz CR-19. Lee CLAUDE.md, MailySoft/docs/00-plan-explicado.md
§1.1 y la sección CR-19 de MailySoft/docs/00-deuda.md.

Trabaja en tres pasos y PARA después de cada uno para que yo lo vea:

PASO 1 — Reprodúcelo antes de tocar nada. Escríbeme un script o un test que, contra la
base de datos LOCAL, haga una escritura de negocio dentro de una transacción y a la vez
fuerce el fallo del INSERT de auditoría tal como ocurre hoy (con un request_id más largo
de 64 caracteres). Que imprima al final si la escritura de negocio quedó guardada.
Córrelo y muéstrame la salida. Espero ver que NO quedó guardada y que no se lanzó ninguna
excepción hacia afuera. No sigas hasta que yo confirme que lo vi.

PASO 2 — El arreglo. Trunca el request_id a 64 caracteres en los tres puntos donde se lee
del header X-Request-Id, y dale a la escritura de auditoría su propio transaction.atomic()
para que un fallo suyo no marque la transacción del caller. Explícame por qué el savepoint
resuelve esto, con el ejemplo del script del paso 1.

PASO 3 — Verifica. Corre otra vez el script del paso 1: ahora la escritura debe quedar
guardada. Y convierte esa reproducción en un test automático permanente que pegue al
endpoint real de crear una nota de evolución con un header X-Request-Id de 200 caracteres
y compruebe que la nota existe en la base después del 201.

No arregles nada más de lo que dice este módulo, aunque veas otras cosas: anótalas y me
las dices al final.
```

---

# Los siguientes, en orden

Se detallan cuando lleguemos a cada uno. No los leas todavía.

| # | Módulo | De dónde sale | Tamaño |
|---|---|---|---|
| **M2** | Las llaves de la demo en la puerta de producción | `explicado §1.2` · CR-16 | 1 sesión corta |
| **M3** | Doble clic, doble deuda — y los otros tres puntos de dinero | `explicado §2.1` · CR-20 | 1 sesión |
| **M4** | Los procesos de segundo plano declaran su clínica | `explicado §2.2` · CR-24 | 1 sesión |
| **M5** | Cerrar el hueco de la base de datos — **solo después de M4** | `explicado §2.2` · CR-01 | 1 sesión |
| **M6** | El módulo grande: sede en el detalle + permisos por objeto | `explicado §3.1 y §3.2` · CR-04, CR-03 | Módulo completo, con contrato |

Y en paralelo, cuando quieras y sin prisa técnica: las **tres decisiones de negocio** de
`00-plan-de-ataque.md` — el CFDI de Premium, las capacidades sin pantalla, y la lista de precios.

---

# Tablero

| Módulo | Estado | Rama | PR | Cerrado |
|---|---|---|---|---|
| M0.1 · Sentry (backend) | ✅ **cerrado 2026-08-13** — `ZeroDivisionError` recibido | — | sin código | 2026-08-13 |
| M0.2 · Correo | ⏸️ aplazado — el sistema no manda ningún correo hoy | — | — | |
| M0.3 · Variables obligatorias | ✅ **cerrado 2026-08-13** — candado puesto, error real visible, rol verificado | `fix/arranque-variables-obligatorias` | [#2](https://github.com/Quint4n4/Maily360/pull/2) | 2026-08-13 |
| M1 · La nota que no existe | ⬜ | — | — | |
| M0.4 · Sentry del frontend (requiere `ARG` en el Dockerfile) | ⬜ | — | — | |
| M2 | ⬜ | — | — | |
| M3 | ⬜ | — | — | |
| M4 | ⬜ | — | — | |
| M5 | ⬜ | — | — | |
| M6 | ⬜ | — | — | |

**Regla:** un módulo no se marca cerrado sin su prueba automática. Sin ella no está arreglado — está
bien por hoy.
