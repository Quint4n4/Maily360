# Plan de implementación — Planes, módulos y entitlements

> 2026-07-24. Plan de construcción por fases. Basado en
> `planes-modulos-entitlements-analisis.md` (el concepto) y
> `planes-modulos-mapa-dependencias.md` (el mapa verificado).
>
> **Todo se trabaja en local.** Nada se sube hasta que cada fase esté probada.

---

## Empaquetado aprobado

Se venden **4 planes**. `Solo` queda construido pero apagado (`is_active=False`) — ver
decisión 3 al final.

| | Básico $1,500 | Pro $4,500 | Premium $8,900 | Enterprise | ~~Solo~~ (apagado) |
|---|---|---|---|---|---|
| **Clínico** (agenda, recordatorios, expediente, recetas, notas) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Servicios, cotizaciones, paquetes, cobranza | — | ✅ | ✅ | ✅ | — |
| Facturación CFDI | — | — | ✅ | ✅ | — |
| Calendarización de tratamientos | — | — | — | override | — |
| Sucursales | 1 | 1 | ilim. | ilim. | 1 |
| Consultorios | 1 | 5 | ilim. | ilim. | 1 |
| Usuarios | 3 | ilim. | ilim. | ilim. | 1 |
| Roles | dueño, médico, enfermería, recepción | + admin, finanzas, solo lectura | todos | todos | dueño |

**Add-ons** sobre cualquier plan: sede adicional · CFDI · usuarios extra · consultorio extra ·
módulo suelto (override).

**Principio:** lo clínico completo desde el primer plan. Lo que se compra al subir no es
"poder trabajar", es "poder cobrar".

---

# FASE 0 — Arreglar lo que ya está roto ✅ BACKEND HECHO (2026-07-24)

> Backend completo y probado: **3,285 pruebas verdes**. Falta la parte de frontend
> (§2.2: selector de plan y cédula en el modal de alta), que va en la Fase 2.
>
> Qué se hizo:
> - `ROLES_QUE_PUEDEN_EJERCER = {owner, admin, doctor}` en `apps/personal/services.py`.
>   `doctor_create` acepta esos tres; la cédula sigue siendo la autoridad para recetar.
> - `tenant_and_owner_create` acepta `owner_cedula`, `owner_specialty`, `plan_id` y
>   `billing_cycle`; crea el perfil de médico del dueño y la suscripción **en la misma
>   transacción**. El primer periodo termina junto con el trial.
> - Devuelve `needs_doctor` para que la UI avise cuando la clínica no puede agendar.
> - Pruebas nuevas: `apps/personal/tests/test_owner_puede_ejercer.py` (4) y 5 casos
>   en `apps/plataforma/tests/test_clinica_create.py`.


> Estos NO son requisitos del futuro: son bugs de hoy, verificados en el código. Sin ellos el
> plan Solo es invendible y el alta de clínicas nace coja.

## 0.1 — El dueño no puede ejercer como médico

**Evidencia:**
```
apps/personal/services.py:93   if membership.role != Role.DOCTOR: raise ValidationError
apps/tenancy/models.py:157     UniqueConstraint(user, tenant)   → un usuario = UN rol
apps/recetas/models.py:420     Prescription.doctor  PROTECT, sin null
apps/agenda/models.py:331      Appointment.doctor   PROTECT, sin null
```

Un usuario con rol `owner` no puede tener perfil `Doctor`. Sin perfil `Doctor` **no puede
emitir recetas ni recibir citas**. El consultorio individual —dueño que atiende— no cabe.

**Causa de fondo:** Maily mezcla **cargo administrativo** (dueño, administrador) con
**profesión** (médico, enfermería) en un solo campo con restricción de unicidad.

**Arreglo:** relajar `doctor_create` para aceptar membresías con rol `owner` (y decidir sobre
`admin`, ver §0.4). El perfil profesional pasa a ser un atributo —cédula + especialidad— no
un rol excluyente.

- `apps/personal/services.py` — validación de rol permitido.
- Revisar `doctor_get_for_user` (no cambia: busca por membresía, funcionará solo).
- Revisar `permisos.ts` — `puedeEmitirReceta` ya incluye `owner`; el front ya estaba listo,
  el backend era el que bloqueaba.
- Tests: dueño con cédula emite receta y recibe cita; dueño SIN cédula no puede (debe seguir
  bloqueado — la receta es un documento legal).

## 0.2 — Una clínica nueva nace sin médicos

**Evidencia:** `tenant_and_owner_create` (`apps/plataforma/services.py:166`) crea dueño +
1 consultorio + 3 tipos de cita + categorías. **Ningún `Doctor`.**

Resultado: clínica recién creada **no puede agendar ni una cita** hasta dar de alta a otro
usuario con rol médico.

**Arreglo:** en el alta, pedir opcionalmente la **cédula profesional del dueño**. Si viene, se
le crea su perfil `Doctor` y la clínica queda operativa desde el minuto uno. Si no viene, se
muestra un aviso claro de que falta dar de alta un médico para poder agendar.

## 0.3 — Verificar en el piloto

Antes de tocar nada: dar de alta una clínica de prueba en Railway con un solo dueño e intentar
agendar. Confirma el bug en producción y sirve de prueba de regresión.

## 0.4 — El rol `admin` también puede ejercer  *(decidido 2026-07-24)*

Igual que el dueño: un `admin` con cédula registrada puede tener perfil `Doctor`, emitir
recetas y recibir citas. Sin cédula, no.

`doctor_create` acepta membresías con rol `owner`, `admin` o `doctor`. La regla real no es el
rol, es **tener cédula**.

**Salida de la fase:** un dueño con cédula agenda y receta. Tests verdes. Sin esto no se avanza.

---

# FASE 1 — Modelo de entitlements ✅ HECHA (2026-07-24)

> **3,353 pruebas verdes** (45 nuevas). Migración verificada sobre los datos reales
> de dev: 44 clínicas, ninguna perdió módulos. Reversible (probada de ida y vuelta).
>
> Archivos: `apps/core/modules.py` · `apps/tenancy/entitlements.py` ·
> `apps/tenancy/migrations/0006_*` y `0007_entitlements_legacy_full.py` ·
> `apps/tenancy/management/commands/seed_planes.py`
>
> **Hallazgo durante la construcción:** `0005_seed_plans` ya creaba Básico/Pro/Premium.
> Si la migración les daba todos los módulos "por seguridad", el empaquetado real no
> llegaría nunca a una instalación nueva. Se corrigió la regla:
>   - Plan CON clínicas suscritas → conserva todo (no se interrumpe el servicio).
>   - Plan SIN suscriptores → queda vacío y `seed_planes` le pone el empaquetado.
>   - `seed_planes` completa planes vacíos, pero NO reescribe los que ya tienen
>     módulos salvo `--actualizar`.
>
> Verificado en dev: `pro` (10 clínicas) conservó sus 12 módulos; `basico`,
> `premium`, `enterprise` y `solo` (sin clientes) recibieron el empaquetado real.


## 1.1 Catálogo de módulos (código, no base de datos)

Los módulos los define el código; los planes solo los referencian. Nuevo
`apps/core/modules.py`:

```
Module(TextChoices):
  AGENDA, RECORDATORIOS, EXPEDIENTE, RECETAS, NOTAS,
  SERVICIOS, PAQUETES, COTIZACIONES, COBRANZA, CFDI,
  CALENDARIZACION, PERSONAL, MULTISEDE

MODULE_REQUIRES = {
  RECORDATORIOS:   {AGENDA},
  PAQUETES:        {SERVICIOS},
  COTIZACIONES:    {SERVICIOS},
  CFDI:            {COBRANZA},
  CALENDARIZACION: {SERVICIOS, COTIZACIONES, EXPEDIENTE},
}

ROLE_REQUIRES = {
  DOCTOR: {EXPEDIENTE}, NURSE: {EXPEDIENTE},
  RECEPTION: {AGENDA},  FINANCE: {COBRANZA},
  OWNER: set(), ADMIN: set(), READONLY: set(),
}
```

Más dos funciones puras, fáciles de testear:
`expandir_dependencias(modules)` y `roles_disponibles(modules)`.

## 1.2 `Plan` estructurado

`apps/tenancy/models.py` — el `Plan` gana:
- `modules` JSON — lista de slugs del catálogo.
- `max_sucursales`, `max_consultorios`, `max_usuarios` — enteros, `null` = ilimitado.
- `features` (texto de marketing) **se conserva**: es lo que se muestra en la vitrina.

## 1.3 Overrides por clínica

Nuevo `TenantEntitlements` (OneToOne con `Tenant`):
- `modules_on` / `modules_off` — lo que se concede o revoca sobre el plan.
- `max_*` — overrides de límite, `null` = usa el del plan.
- `notes` — por qué se dio el trato especial (auditoría comercial).

**Efectivo = plan + overrides**, resuelto en un solo selector
`entitlements_for_tenant(tenant)` con caché por request.

## 1.4 Migración de datos (crítica)

Todas las clínicas existentes → plan **"Legacy full"**: todos los módulos, todos los límites
ilimitados. **Nadie debe notar el cambio.** Una clínica que despierte con módulos apagados es
una interrupción de servicio.

## 1.5 Seed de los 5 planes

Comando `seed_planes` que crea Solo / Básico / Pro / Premium / Enterprise con los módulos y
límites de la tabla de arriba. Idempotente (se puede correr dos veces).

**Salida:** modelos + migraciones + seed. Sin efecto visible todavía.

---

# FASE 2 — Alta de clínicas con plan ✅ HECHA (2026-07-24)

> Backend: `Plan` expone y acepta `modules` + límites; `roles` se devuelve derivado.
> Frontend: `EditorModulos` (casillas con dependencias en vivo, límites con
> "ilimitado", roles calculados) dentro de `PlanFormModal`; `NuevaClinicaModal` gana
> selector de plan, cédula del dueño y aviso `needs_doctor`.
> Espejo del catálogo en `web-soft/src/lib/modulos.ts`. OpenAPI regenerado.

# FASE 3 — Backend como autoridad ✅ HECHA (2026-07-24)

> **3,375 pruebas verdes.** `apps/core/entitlement_guards.py`:
> - `RequiresModule` (12 guards) conectado a **91 vistas**: agenda, expediente
>   (11 archivos), recetas, notas, personal y finanzas.
> - **Finanzas se gateó por CAPACIDAD, no por app**: sus 23 vistas se repartieron
>   entre servicios / paquetes / cotizaciones / cobranza / CFDI. Gatearla por app
>   habría apagado el catálogo al apagar la caja. Hay un test que lo vigila.
> - Un módulo no contratado responde **404, no 403**: un 403 delata el catálogo.
> - Límites aplicados en `sucursal_create`, `consultorio_create` y `member_create`.
> - `member_create` rechaza roles que el plan no incluye.
> - Bajar de plan **no borra a nadie**: bloquea altas y conserva lo existente (test).
>
> `TenantFactory` ahora crea la suscripción por defecto (refleja producción tras la
> migración 0007). `TenantFactory(sin_plan=True)` para probar el gating.

# FASE 2 (detalle original)

## 2.1 Backend

`tenant_and_owner_create` gana dos parámetros:
- `plan_id` — opcional; si viene, crea la `TenantSubscription` en la misma transacción.
- `owner_cedula` — opcional; si viene, crea el perfil `Doctor` del dueño (Fase 0.2).

Todo atómico: o se crea clínica + dueño + plan + médico, o no se crea nada.

## 2.2 Frontend — portal de plataforma

`ClinicasPage` → modal de alta: se agrega **selector de plan** (tarjetas con nombre, precio y
qué incluye) y campo opcional de cédula. Al elegir plan se previsualizan módulos y límites.

## 2.3 Editor de planes

Sobre el modal "Editar plan" que ya existe, tres bloques nuevos:
- **Módulos** agrupados (clínico / comercial / operación) con casillas.
- **Límites** con casilla "ilimitado".
- **Roles disponibles** — solo lectura, calculados de los módulos, explicando cuál falta y por qué.

Las dependencias se aplican **en vivo**: desmarcar "Servicios" desmarca Paquetes y
Cotizaciones explicando el motivo. Es lo que impide guardar un plan roto.

**Salida:** ya puedes dar de alta clínicas con plan desde el portal. Todavía sin gating —
pero **no es una regresión**: hoy tampoco hay gating.

---

# FASE 3 — Backend como autoridad

Sin esta fase, todo lo anterior es cosmético: cualquiera con la URL entra.

## 3.1 Guard de módulos
`HasModule("recetas")` (clase de permiso DRF) + `require_module(tenant, MODULE)` para
services. Responde **404**, no 403: un módulo no contratado no debe ni delatar que existe.

Aplicar por **capacidad, no por app** — recordar que `finanzas` contiene cinco módulos
distintos (servicios, paquetes, cotizaciones, cobranza, CFDI).

## 3.2 Guard de límites
`assert_within_limit(tenant, "usuarios")` en `member_create`, `consultorio_create`,
`sucursal_create`. Mensaje de error accionable: *"Tu plan permite 3 usuarios. Contacta a
soporte para ampliar."*

## 3.3 Roles derivados
`member_create` rechaza roles fuera de `roles_disponibles(módulos del tenant)`.

## 3.4 Bajar de plan estando por encima del límite
**Nunca borrar datos.** Se bloquean altas nuevas y se avisa. Una clínica con 8 usuarios que
baja a un tope de 3 conserva sus 8; simplemente no puede agregar el 9º.

**Salida:** tests de que un endpoint de módulo apagado devuelve 404 y que los límites frenan.

---

# FASE 4 — Frontend consistente ✅ HECHA (2026-07-24)

> `/me/` devuelve `capabilities` (módulos, límites, roles derivados, `sede_unica`).
> Una sola fuente para todo el front; el backend bloquea con la misma.
> - `AuthContext` expone `capabilities` y `tieneModulo()`.
> - `Topbar` filtra por rol Y módulo. Rutas (`ClinicRoute requiere=…`) validan el
>   módulo. **`/paquetes` corregido**: era la única ruta sin gating.
> - Expediente: índice de secciones, paso ③ Receta y "Mi Consultorio" se pintan por
>   módulo. Aquí aterriza el caso dental.
> - `NuevoMiembroDrawer` ofrece solo los roles del plan.
> - Espejo del catálogo en `lib/modulos.ts`.
>
> **Bug de Fase 0 corregido de paso:** `/me/` resolvía `doctor_id` solo si el rol era
> exactamente 'doctor'. El dueño-médico no lo recibía → el front creía que no podía
> recetar. Ahora usa `ROLES_QUE_PUEDEN_EJERCER`. Test de regresión incluido.

# FASE 5 — Modo sede única ✅ HECHA (2026-07-24)

> Con `max_sucursales = 1` desaparece la UI de sucursales: sección de Mi Consultorio
> y asignación de sedes por miembro (`SucursalesMiembro` se auto-oculta). Al subir de
> plan reaparece sin migrar nada — la sede principal ya existe.

# FASE 4 (detalle original)

## 4.1 `GET /me/capabilities/`
Devuelve módulos efectivos, límites, consumo actual y roles disponibles. Una sola fuente para
todo el front.

## 4.2 Menú y rutas
`Topbar` filtra por `rol Y módulo`. `ClinicRoute` valida el módulo.
**Corregir `/paquetes`**, la única ruta sin gating de módulo (hoy solo `RequireAuth`).

## 4.3 Dentro del expediente
El paso ③ Receta y las secciones del índice (recetas, estado de cuenta, calendarización) se
pintan según módulo. Aquí se aterriza tu caso dental.

## 4.4 Selector de roles
Al invitar un miembro, solo se ofrecen los roles disponibles del plan.

---

# FASE 5 — Modo sede única

Con `max_sucursales = 1` desaparece **toda** la UI de sucursales: selector del encabezado,
sección de Mi Consultorio, casillas de sede en servicios/paquetes, columnas y filtros en
personal/agenda/finanzas/avisos.

**No se agrega un flag `multi_sucursal`**: sería una segunda fuente de verdad que puede
contradecir al límite. El límite lo dice todo.

Al subir de plan, todo aparece sin migrar nada: la sede principal ya existe por el backfill.

---

# FASE 6 — Cierre comercial ✅ HECHA (2026-07-24)

> - `TenantEntitlements` + `tenant_entitlements_set` (solo super_admin) + endpoint
>   `POST /clinicas/<id>/entitlements/`. Nueva acción de auditoría
>   `TENANT_ENTITLEMENTS_SET` (migración audit 0048).
> - La ficha de clínica (`platform_clinica_detail`) devuelve entitlements efectivos +
>   **consumo vs límite** (usuarios 6/8…) para detectar upsell.
> - Frontend: bloque de plan/consumo/módulos en `ClinicaDetailDrawer` +
>   `AjustesClinicaModal` para encender/apagar módulos por clínica con motivo
>   obligatorio.
> - **Caso dental verificado de punta a punta**: `modules_off=[recetas]` apaga
>   recetas y conserva expediente (9 tests + prueba en Demo Vitalis con rollback).
>
> **Add-ons** = overrides con motivo etiquetado (misma maquinaria). No se construyó
> UI de catálogo de add-ons aparte: el modal de ajustes ya los cubre.

# FASE 6 (detalle original)

- **Overrides por clínica** en la ficha del portal (encender módulo suelto, subir límite),
  con motivo obligatorio para auditoría. **Sin esto no se puede vender el caso dental.**
- **Vista de consumo** (usuarios 6/8, sucursales 2/3) para detectar upsell.
- **Add-ons** como overrides con etiqueta comercial.

---

## Orden y por qué

```
F0  bugs           ← bloqueante: sin esto el plan Solo no existe
F1  modelo         ← sin efecto visible
F2  alta con plan  ← primer valor visible; probable de inmediato
F3  autoridad      ← la seguridad real
F4  frontend       ← lo que ve el cliente
F5  sede única     ← lo más vistoso para el cliente chico
F6  comercial      ← cierra tratos a la medida
```

F2 antes que F3 es deliberado: te deja probar el alta de clínicas pronto, y **no abre ningún
hueco** porque hoy no existe gating alguno. Aun así, **no vender planes restringidos hasta
tener F3**: hasta entonces el plan es una etiqueta, no un candado.

## Riesgos

1. **La migración de F1.4 es la más delicada.** Verificar en local con copia de datos reales
   antes de tocar el piloto.
2. **Dos capas, una fuente.** Backend y frontend deben leer del mismo selector o se
   contradicen.
3. **No romper el piloto.** Todo local hasta que cada fase pase sus pruebas.

---

## Decisiones tomadas (2026-07-24)

**1. `admin` puede ejercer con cédula.** Ver §0.4. La regla es tener cédula, no el rol.

**2. Calendarización de tratamientos = módulo aparte, apagado por defecto.**
Nació de un requerimiento de un negocio específico, no es función general. Se suma al catálogo
como `CALENDARIZACION` con dependencia dura de `SERVICIOS` + `COTIZACIONES` (por eso solo puede
encenderse de Pro en adelante). No entra en ningún plan estándar: se concede por **override**
a quien lo pida. Consecuencia: en el índice del expediente la sección solo aparece con el
módulo encendido.

**3. Se arranca con 4 planes; `Solo` se construye pero nace apagado.**
Se crea en el seed con `is_active=False` (el campo ya existe: *"plan retirado del catálogo, no
asignable a nuevas suscripciones"*). Razones:
- El tope de 1 usuario deja fuera a casi todo médico que tenga quien le conteste el teléfono.
- Sostener un plan de $900 cuesta lo mismo que uno de $4,500, y aún no hay clínicas reales.
- El precio ancla al cliente: es más fácil descubrirlo vendiendo Básicos con descuento que
  lanzar $900 y tener que subirlo.
- Agregar un plan después es trivial; retirar uno con clientes encima, no.

Mientras tanto, al médico solo se le vende **Básico con descuento** + override de límite. Se
enciende `Solo` cuando haya media docena de casos reales que digan el precio correcto.

## Decisiones pendientes

Ninguna. El plan está listo para ejecutarse.

---

# FASE 7 — Roles por plan y dueño único ✅ HECHA (2026-07-24)

> Salió al probar: la pantalla de Equipo mostraba los 7 roles en todos los planes.
> El empaquetado decía que admin/finanzas/solo-lectura son de Pro+, pero como
> admin y readonly no dependen de ningún módulo, aparecían en Básico.

- `Plan.roles` (allow-list, migración 0008/0009). Los roles efectivos = módulos ∩
  roles del plan: la primera capa quita finanzas sin cobranza, la segunda es la
  decisión comercial (Básico = dueño/médico/enfermería/recepción). Vacío = sin
  restricción extra, para no cambiar los planes existentes.
- Configurable desde el super-admin: en el editor de plan los roles son casillas
  (dentro de lo que los módulos permiten); el dueño siempre va y no se desmarca.
- **Un dueño por clínica:** `member_create` rechaza un segundo owner; la UI ya no
  lo ofrece. El grid de Equipo y el botón "Nuevo miembro" se ocultan según el plan
  y el tope de usuarios ("lo que ya no se puede agregar, que no aparezca").

---

## Nota de estado — EN PRODUCCIÓN (2026-07-27)

**Implementado, probado y desplegado.** Ya NO es un plan: es lo que corre en
producción.

- **~80 tests nuevos**, suite completa en verde (3,397 al momento del merge).
- Rama `feat/planes-entitlements` → merge `--no-ff` a `main` → deploy en Railway
  (proyecto just-beauty, servicio Maily360).
- **5 migraciones aplicadas** en producción, incluida `0007_entitlements_legacy_full`:
  las clínicas existentes quedaron con acceso completo — nadie perdió funciones.
- `seed_planes` corrido en producción: los 5 planes (Básico/Pro/Premium/Enterprise
  activos, Solo inactivo) existen.
- App verificada arriba (HTTP 200) tras el deploy.

**Aprendizaje del deploy:** el primer build falló por 3 errores de TypeScript que la
verificación local no cachó (se usó `tsc -p tsconfig.json`, config-solución que no
revisa archivos = falso verde). Verificar el front con `npm run build` / `tsc -b`.
