# Plan de ataque — decidido en A4

> Cierre de la adopción del modelo de trabajo. **Decidido el 2026-08-13** sobre
> `docs/00-deuda.md` (27 causas raíz, 276 hallazgos).
>
> Esto no es una lista de deseos: es el orden acordado, con lo que se acepta como deuda **a
> conciencia** y bajo qué condición deja de ser aceptable.
>
> **Marco de la decisión:** objetivo de la primera tanda = *que no se pierda nada*. Dedicación real
> = **más de 20 h/semana**, Maily360 es el foco. Los dos arreglos caros (CR-03 y CR-04) entran al
> ciclo normal **como módulo con contrato**, no como parche.

---

## Lo que cambió al mirar Railway (2026-08-13)

Tres P0 dependían de la configuración de producción y no se podían cerrar desde el código. Se
verificaron directamente contra el proyecto `just-beauty`, servicio `Maily360`:

| Verificación | Resultado | Efecto |
|---|---|---|
| Rol de conexión a PostgreSQL | `maily_app` · `SUPERUSER: False` · `BYPASSRLS: False` | **CR-01 se cae.** La segunda barrera está viva |
| `DJANGO_DEFAULT_FILE_STORAGE` + `CLOUDINARY_URL` | Puestas | Los archivos no viven en disco efímero |
| `PRESCRIPTION_VERIFY_SECRET` y `..._BASE_URL` | Puestas | El QR no cae al `SECRET_KEY` ni apunta a localhost |

**Pero los dos P0 que se caen no desaparecen: bajan a P1.** Lo que está bien es la configuración de
hoy, no el código. Nada impide que se rompa: `production.py` no **exige** esas variables, y nada
verifica el rol de base de datos en el despliegue.

### Y tres cosas que solo se veían mirando el panel

1. **Sentry no está encendido en producción.** No existe la variable `SENTRY_DSN`. El código es
   correcto —A2 lo verificó línea por línea— pero sin la variable no se inicializa. Sigues sin ver
   los errores de producción.
2. **El correo va al log.** Falta `DJANGO_EMAIL_BACKEND`, así que todo correo se imprime en la
   consola de Railway y nadie lo recibe. Sin error.
3. **El CFDI real es inalcanzable por código.** `adapters/cfdi.py:187-189` lee
   `FACTURAMA_API_USER`, `FACTURAMA_API_PASSWORD` y `FACTURAMA_BASE_URL`, y **ningún archivo de
   `config/settings/` define esos settings**. Poner las variables en Railway no cambia nada: la
   factory devuelve **siempre** el adaptador simulado. Ver §Decisiones pendientes.

**Recuento final: seis P0 activos**, no ocho: CR-19, CR-20, CR-03, CR-04, CR-05, CR-16.

---

## Tanda 1 · Que no se pierda nada

**Objetivo:** cerrar toda pérdida silenciosa de datos y toda regresión de configuración.
**Plazo: 2026-08-16.** Dos sesiones de trabajo.
**Todo es de pocas líneas.** Ninguno de estos arreglos cambia la forma del sistema.

### 1.1 · CR-19 — la nota clínica que se revierte y responde 201 · **P0**

El arreglo son dos cosas independientes, y hay que hacer **las dos**:

- **Truncar el `request_id`.** `core/views.py:184`, `plataforma/views.py:160` y `authn/views.py:190`
  leen el header `X-Request-Id` y lo pasan sin cortar a un `CharField(max_length=64)`. La línea de
  arriba, el `user_agent`, sí corta con `[:512]`. Es literalmente añadir `[:64]` en tres sitios.
- **Darle savepoint propio a `audit_record`.** El `except Exception` de `audit/services.py` se traga
  el fallo de su propio `INSERT`, pero Django ya marcó la conexión como `needs_rollback`: la
  transacción del service se revierte y la vista responde 201. Envolver el `log.save()` en su propio
  `transaction.atomic()` hace que el fallo se quede dentro del savepoint y no contamine al caller.

**Cómo se verifica que quedó:** un test que mande `X-Request-Id` de 200 caracteres al endpoint de
crear una nota de evolución y compruebe que la nota **existe** en la base después del 201. Sin ese
test no está cerrado.

### 1.2 · CR-16 — los comandos de siembra pueden escribir en producción · **P0**

`seed_e2e_user` y `seed_demo` no comprueban en qué entorno corren, y `DEMO_OWNER_PASSWORD` está
puesta en el servicio de producción. Basta ejecutar el comando equivocado desde la consola de
Railway —la misma que acabas de usar— para que tome la clínica más antigua.

- Guardia de entorno al inicio de los comandos de siembra: si `DJANGO_SETTINGS_MODULE` apunta a
  producción, abortar con mensaje claro.
- Quitar `DEMO_OWNER_PASSWORD` del servicio de producción si no se usa ahí. Si se usa, rotarla.

### 1.3 · CR-02 — que la configuración correcta de hoy no se rompa mañana · **P1** (era P0)

De 53 variables que el código lee, **solo 5 revientan el arranque si faltan**. Las otras 48 tienen
un default pensado para que `docker compose up` funcione sin configurar nada.

Añadir a la lista de obligatorias en `production.py`: `DJANGO_DEFAULT_FILE_STORAGE`,
`PRESCRIPTION_VERIFY_SECRET`, `PRESCRIPTION_VERIFY_BASE_URL` y `REDIS_URL`.

> **Por qué `REDIS_URL` está en la lista y no parece de seguridad:** el límite de intentos de login
> (5 por minuto) lee el historial del caché. Con el caché caído, `cache.get()` devuelve `None` y
> **cada petición pasa**. El límite desaparece sin dejar rastro, justo cuando más falta hace.

Y actualizar el bloque de variables de `DEPLOY-RAILWAY.md`, al que le faltan estas y las de Sentry.

### 1.4 · Encender lo que creías encendido · **P1**

- `SENTRY_DSN` y `SENTRY_ENVIRONMENT` en Railway, en los dos servicios.
- `DJANGO_EMAIL_BACKEND` con un proveedor real (Resend o Amazon SES; nunca SMTP de Gmail).
- `check_db_role` en el arranque o en CI. Devuelve código 1 si el rol evade RLS: hoy la
  verificación existe y **no la corre nadie**. Es la guardia que evita que CR-01 vuelva.

---

## Tanda 2 · El dinero, y una secuencia que no se puede invertir

**Plazo: 2026-08-23.**

### 2.1 · CR-20 — comprobar-luego-actualizar sin lock · **P0**

Cuatro sitios donde la comprobación ocurre fuera de la transacción o sin bloquear la fila:
`payment_register`, `charge_cancel`, `quote_accept` y el folio de receta.

El caso más fácil de provocar: **doble clic en "Aceptar cotización" duplica la deuda del paciente.**
La guarda de idempotencia está *antes* del `atomic()` (`finanzas/services.py:600` vs `:604`) y sin
`select_for_update`. Una cotización de $18,000 con seis renglones produce doce cargos por $36,000. El
docstring promete que es idempotente; no lo es.

### 2.2 · CR-24 antes de tocar las políticas de RLS · **P0 de secuencia**

Esto es lo más importante del plan y no es un arreglo, es un **orden**.

Ahora sabemos que RLS está activo de verdad. Las políticas dicen "si nadie fijó la clínica activa,
deja pasar". Los workers de Celery **nunca fijan la clínica activa**. Es decir: los recordatorios y
los PDFs asíncronos **funcionan hoy gracias a ese hueco**. El hueco es carga estructural.

> **Si cierras el fallback `OR current_tenant_id() IS NULL` antes de arreglar los workers, todos los
> PDFs asíncronos dejan de funcionar el mismo día.**

Orden obligatorio: (1) que cada tarea de Celery fije el tenant explícitamente, (2) que un test lo
exija, (3) recién entonces endurecer las políticas y el test guardián — que hoy **exige** el
fallback y por tanto congela el patrón permisivo.

---

## Tanda 3 · El módulo · CR-03 y CR-04

**Decisión tomada: entran al ciclo normal de seis fases, como un módulo con su contrato.** No se
parchean.

**Arranca el 2026-08-24.** Fase 1 (análisis) y fase 2 (contrato) **antes de la primera línea de
código**, con el gate: nadie escribe nada hasta que el contrato esté leído y aprobado.

- **CR-04 · el alcance de sede** — 34 selectores resuelven por id y **ninguno puede acotar por sede,
  porque la sede no está en la firma de la función**. No es que esté mal usada: no existe el
  parámetro. Por eso es un cambio de forma.
- **CR-03 · permisos por objeto** — **cero `has_object_permission` en todo el backend**. Las reglas
  de pertenencia (el médico solo anula su receta, solo escribe sobre sus citas) viven sueltas dentro
  de los services, y por eso el frontend no puede reflejarlas: solo tiene una matriz de rol.

Van juntos porque atacan la misma pregunta desde dos lados: *¿de quién es este objeto y desde dónde
lo estás pidiendo?* Cierran 32 hallazgos.

**Por qué es el módulo correcto para estrenar el modelo:** es grande, es riesgoso, y toca 34 puntos.
Es exactamente el caso donde el contrato antes del código se paga solo.

---

## Deuda aceptada a conciencia

Lo que sigue **no se arregla ahora**, y eso es una decisión, no un descuido. Cada una lleva la
condición que la vuelve inaceptable. El día que se cumpla la condición, sube a la tanda siguiente.

| Deuda | Por qué se acepta hoy | Deja de ser aceptable cuando… |
|---|---|---|
| **CR-05** · el Django admin es una segunda puerta sin las reglas del producto: se puede editar el propio `is_superuser` y no queda en la bitácora | Hoy el único con acceso al admin eres tú | …exista un segundo usuario de plataforma que no seas tú. Es decir: **antes de contratar o dar acceso a alguien más** |
| **CR-06** · 30 de 31 constraints ignoran el borrado lógico | No produce pérdida de datos, produce colisiones raras al reactivar | …se construya el endpoint de reactivación (CR-07). Van juntos |
| **CR-08** · la bitácora lleva PII y se escribe en modo silencioso | La parte silenciosa se cierra en CR-19 (tanda 1) | …firmes con una clínica que exija cumplimiento por contrato |
| **CR-14** · diez capacidades implementadas y facturadas a las que ningún clic llega | Ver §Decisiones pendientes | …se venda un plan que las incluya |
| **CR-09 a CR-11** · N+1, paginación, filtros que invalidan índices | 1 a 3 usuarios concurrentes por clínica. No sobre-optimizar para escala que no existe | …una clínica pase de ~10 usuarios concurrentes, o un listado tarde más de 2 s |
| **CR-27** · los 20 documentos de `docs/design/` ya no describen el sistema | El contrato los sustituyó como fuente de verdad | …alguien más entre al proyecto. Cierra 61 hallazgos de una sola vez, así que conviene antes de eso |

**Regla que hace honesta esta tabla:** una deuda sin condición de caducidad no es una decisión, es
un olvido con buena redacción.

---

## Decisiones pendientes, y son de negocio

**1. El CFDI del plan Premium.** Vendes Premium a $8,900/mes con facturación CFDI 4.0, y el timbrado
real es inalcanzable por código: el adaptador simulado inventa un UUID y la clínica cree que timbró.
Tres caminos, y hay que elegir **antes de la siguiente venta**:

- Construir la integración real con el PAC (definir los settings que faltan, credenciales, pruebas
  contra el ambiente del proveedor).
- Sacar CFDI del catálogo de planes hasta que funcione, y ajustar el precio de Premium.
- Venderlo diciendo explícitamente que la facturación llega después, con fecha comprometida.

Lo que no es una opción es dejarlo como está: hoy una clínica puede entregar a su paciente un
comprobante que el SAT no conoce.

**2. Las diez capacidades sin pantalla (CR-14).** Están implementadas, probadas y facturadas, y
ninguna interfaz las ofrece. Por cada una: se construye la pantalla o se retira del catálogo. Es
media hora de decisiones y desbloquea CR-14 entero.

**3. Los precios.** El código cobra $1,500 / $4,500 / $8,900. Las presentaciones de `documentacion/`
dicen $13,990, $22,990, $199/mes. **Hay que fijar una sola lista** antes de mandar la siguiente
propuesta.

---

## Qué cambia en el proceso

Tres causas raíz existen porque el `reviewer` no tenía cómo atraparlas. Un incidente que no cambia el
checklist está garantizado que se repite, así que se convierten en puntos fijos:

| Skill | Punto nuevo | Nace de |
|---|---|---|
| `security-checklist` | Toda variable de entorno que decida **dónde viven los datos**, **con qué se firma algo** o **si un efecto externo es real** lleva guardia de arranque en `production.py` | CR-02 |
| `security-checklist` | Ningún `except` alrededor de una escritura a base de datos sin su propio `transaction.atomic()` | CR-19 |
| `db-schema` | Toda `UniqueConstraint` sobre un modelo con borrado lógico lleva `condition=Q(deleted_at__isnull=True)` | CR-06 |
| `django-backend` | Todas las validaciones **antes** de la primera escritura | CR-22 |
| `django-backend` | Una regla de pertenencia se declara en `has_object_permission`, no dentro del service | CR-03 |
| `multitenancy` | Resolver por id sin declarar el alcance de sede es un hallazgo, no un descuido | CR-04 |

---

## Cierre de la adopción

- [x] `docs/02-contrato.md` describe el sistema real
- [x] `docs/00-brechas.md` y `docs/00-brechas-frontend.md` revisados
- [x] `docs/00-deuda.md` priorizado, agrupado por causa raíz
- [x] `CLAUDE.md` del repo escrito y fusionado con el de la plantilla
- [x] Fecha de adopción escrita: **2026-08-11**. Todo commit posterior pasa por el `reviewer` en gate
- [x] Prioridades decididas con plazos — este documento
- [ ] `MEMORIA.md` actualizado
- [ ] Estructura de Notion montada

**A partir de aquí el proyecto opera con las seis fases de `FLUJO-DE-TRABAJO.md`.** Los arreglos de
las tandas 1 y 2 se cierran como módulos normales: rama, arreglo, `reviewer` en modo gate, PR.
