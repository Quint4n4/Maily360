# Análisis: Planes, módulos y "entitlements" por cliente (desde el super-admin)

> 2026-07-16. Análisis de diseño (SIN código todavía). Responde: ¿cómo liberamos módulos y
> roles según lo que cada clínica contrata, incluyendo apagar multi-sucursal, todo desde el
> super-admin? Al final hay una sección de **decisiones que necesito de ti**.

---

## 0. Resumen ejecutivo (TL;DR)
Hoy Maily muestra u oculta cosas **solo por el ROL** del usuario. Lo que pides necesita una
**segunda capa**: lo que la CLÍNICA tiene contratado (su "plan"). La llamo **entitlements**
(derechos/permisos del plan). Un usuario ve algo solo si **su rol lo permite Y su clínica lo tiene
contratado**.

Un entitlement es de 3 tipos:
1. **Módulos** (encendido/apagado): Agenda, Finanzas, Cotizaciones, Recetas, Paquetes, Notas, etc.
2. **Límites** (números): máximo de sucursales, máximo de usuarios.
3. **Flags** (sí/no): p. ej. `multi_sucursal`.

El **plan** define los entitlements por defecto; el **super-admin** puede sobrescribirlos por
clínica para tratos especiales. El **backend es la autoridad** (bloquea de verdad); el **frontend
solo oculta** lo que no aplica.

---

## 1. Qué hay hoy (estado real del código, verificado)
- ✅ Existe `Plan` (slug, nombre, precio, `features`=lista de strings de MARKETING, orden) y
  `TenantSubscription` (tenant 1:1 plan, ciclo, vencimiento, estado TRIAL/ACTIVE/SUSPENDED).
  El super-admin/sales YA los administra desde el portal de plataforma.
- ❌ **`Plan.features` es solo texto comercial** — NO enciende ni apaga nada funcional.
- ❌ **No hay gating por plan** en ningún endpoint. Todo se gatea por ROL (`permisos.ts` +
  `HasClinicRole`) y por aislamiento multi-tenant.
- ❌ **No existe "módulo activable por tenant"** (lo de "especialidades" en el código es otra cosa:
  especialidad médica, no módulo de software).
- ❌ **Multi-sucursal está SIEMPRE encendido** — no hay flag para apagarlo.
- Frontend: el menú superior (`Topbar`) muestra los módulos con `accesoModulo(role, modulo)` — solo
  rol. `/me/` devuelve `active_role`, `memberships`, `sucursales` — **no** devuelve plan ni módulos.

**Conclusión:** la infraestructura de planes existe para COBRAR y MOSTRAR; falta la capa que
CONVIERTE el plan en permisos funcionales. Eso es lo que hay que construir.

---

## 2. El concepto central: la capa de "entitlements"
Un objeto por clínica que responde: **"¿qué tiene contratado esta clínica?"**. Ejemplo conceptual:

```
Clínica "Consultorio Dra. Ana" (plan: Individual)
  módulos:   agenda, pacientes, recetas, notas        (finanzas/cotizaciones/paquetes = OFF)
  límites:   max_sucursales = 1, max_usuarios = 2
  flags:     multi_sucursal = false
  roles:     [owner, doctor, reception]                (admin/finance/readonly no aplican)
```

La **regla de oro** que gobierna toda la app:
> El usuario ve/hace algo solo si **(su rol lo permite) Y (su clínica lo tiene contratado)**.

---

## 3. De dónde salen los entitlements: Plan → (override por tenant)
Dos niveles, para tener planes estándar PERO poder cerrar tratos a la medida:
1. **El Plan trae los entitlements por defecto** (hoy `Plan.features` es texto; se vuelve
   estructurado: qué módulos, qué límites, qué flags). Asignar un plan a una clínica le fija esos
   derechos.
2. **Override por tenant** (opcional): el super-admin puede, para UNA clínica, encender un módulo
   extra o subir un límite sin cambiarle el plan (ej. "el plan Individual no trae Finanzas, pero a
   este cliente se lo regalamos"). Es lo que hace flexible el negocio.

Resultado efectivo = **Plan por defecto + overrides de esa clínica**.

---

## 4. Tus 3 casos, resueltos con este modelo

### 4.a — Clínica de 1–2 personas: liberar solo los roles que necesitan
La lista de 7 roles (dueño/admin/médico/enfermería/recepción/finanzas/solo-lectura) abruma a un
consultorio de una persona. Solución: **el plan define qué roles están disponibles**.
- Plan **Individual** → roles = `[owner]` (o `[owner, reception]`). El dueño es todo: médico,
  recepción y caja a la vez. Al dar de alta un miembro, el selector de rol solo ofrece los del plan.
- Plan **Clínica** → roles = `[owner, admin, doctor, nurse, reception, finance, readonly]` (todos).
- **Importante:** apagar un rol NO cambia lo que el owner ve; simplemente no puede CREAR miembros de
  ese rol. Menos opciones = onboarding más simple.

### 4.b — Sin multi-sucursal / paga por 1 sede: "modo sede única"
Con `multi_sucursal = false` (o `max_sucursales = 1`), la app entra en **modo sede única** y
**desaparece toda la UI de sucursales** — el cliente ni se entera de que existe:
- Se oculta el **selector de sucursal** del encabezado.
- Se oculta la sección **"Sucursales"** de Mi Consultorio y el botón "Agregar sucursal".
- **Servicios/paquetes**: sin las casillas de sede (todo cae en su única sede).
- **Avisos, personal, finanzas, agenda**: sin columnas/badges/filtros de sede.
- **Backend**: todo opera contra la sucursal predeterminada (que ya existe por el backfill), y
  **crear una 2ª sucursal se rechaza** (excede `max_sucursales`).
- Si mañana suben de plan → `multi_sucursal = true` y **aparece todo** sin migrar nada (la sede
  "principal" ya está; solo agregan más). **Ventaja enorme:** el mismo código sirve para el
  consultorio de 1 persona y para la cadena de 10 sucursales — solo cambia el entitlement.

### 4.c — Solo algunos módulos: los demás no aparecen
Cada módulo top-level (Agenda, Finanzas, Cotizaciones, Recetas, Paquetes, Notas, Personal,
Analítica/Reportes) se enciende/apaga por clínica.
- El **menú superior** solo pinta los módulos contratados (además del filtro por rol que ya existe).
- El **backend** responde **403/404** si alguien pega a un endpoint de un módulo que su clínica no
  tiene (no basta ocultarlo en el front: el backend es la autoridad).
- Ejemplo: un consultorio que solo quiere agenda + expediente → no ve Finanzas ni Cotizaciones.

---

## 5. Cómo se APLICA (dos capas — esto es lo no-negociable de seguridad)
1. **Backend = autoridad.** Un chequeo central "¿esta clínica tiene el módulo/flag X?" y
   "¿le queda cupo para otra sucursal/usuario?", aplicado en los permisos y en las creaciones.
   Sin esto, ocultar en el front es cosmético (cualquiera con la URL entra).
2. **Frontend = experiencia.** El endpoint `/me/` (o uno nuevo `/capabilities/`) devuelve los
   entitlements de la clínica; el front oculta menús/botones/opciones que no aplican. Es lo que hace
   que la app se sienta "hecha a su medida".

Ambas capas leen de la MISMA fuente (los entitlements de la clínica), así que nunca se contradicen.

---

## 6. Propuesta de PLANES (ejemplo para arrancar — se ajusta)
| Plan | Para quién | Sucursales | Usuarios | Roles | Módulos |
|---|---|---|---|---|---|
| **Individual** | 1 médico solo | 1 (sede única) | 1–2 | owner (+reception) | Agenda, Pacientes, Expediente, Recetas, Notas |
| **Consultorio** | equipo chico, 1 sede | 1 (sede única) | hasta ~8 | todos | + Finanzas, Cotizaciones, Paquetes |
| **Clínica Multi-sede** | varias sucursales | varias | ilimitado* | todos | todo + Multi-sucursal + Reportes por sede |
| **Enterprise** | cadenas | ilimitado | ilimitado | todos + a medida | todo + soporte/branding/integraciones |

*Con límites "blandos" configurables. Los números y el empaquetado los decides tú (sección 11).

---

## 7. El super-admin: qué controla desde el portal de plataforma
Sobre lo que YA existe (asignar plan a una clínica), se agrega:
- **Al dar de alta / editar una clínica:** elegir su **plan** → fija módulos/límites/roles por defecto.
- **Overrides por clínica:** encender/apagar un módulo suelto, subir/bajar un límite (max sucursales,
  max usuarios), o el flag `multi_sucursal`, para tratos especiales — sin tocar el plan.
- **Catálogo de planes:** definir qué trae cada plan (hoy `Plan.features` texto → editor estructurado
  de módulos/límites). Ya hay permiso separado para editar el catálogo (super_admin) vs asignar
  suscripciones (super_admin/sales).
- **Ver de un vistazo** qué tiene contratado cada clínica y su consumo (cuántas sucursales/usuarios
  usa vs su límite) para upsell.

---

## 8. Roles según tamaño de equipo (detalle de 4.a)
- El **plan define el set de roles disponibles**; el frontend y el backend solo ofrecen/aceptan esos.
- Independiente de multi-sucursal: una clínica de 1 sede puede tener 6 personas con roles, y un
  consultorio individual multi-sede (raro) tendría roles pero pocas personas. Por eso **roles** y
  **sucursales** son entitlements SEPARADOS (no atados entre sí).
- El "administrador de sucursal" solo tiene sentido si hay multi-sucursal; si `multi_sucursal=false`,
  el rol admin sigue existiendo pero como "administrador de la clínica" (sin la dimensión de sede).

---

## 9. Migración de las clínicas que YA existen
- Se crea un plan por defecto (ej. "Clínica" o un "Legacy full") y **todas las clínicas actuales se
  asignan a él con TODOS los módulos y multi_sucursal=ON**, para que nada cambie de golpe.
- A partir de ahí, el super-admin ajusta caso por caso o al renovar. Cero disrupción para los que ya
  usan la app.

---

## 10. Plan de implementación por fases (cuando lo aprobemos)
- **F1 — Modelo de entitlements:** estructurar `Plan` (módulos/límites/flags) + tabla de overrides
  por tenant + endpoint `/capabilities/` (o ampliar `/me/`). Migración: todos los tenants a "full".
- **F2 — Backend autoridad:** un guard central de módulos/límites; aplicarlo en permisos y en las
  creaciones (rechazar 2ª sucursal si `max=1`, etc.). Tests.
- **F3 — Modo sede única:** el frontend oculta TODA la UI de sucursales cuando `multi_sucursal=false`.
  (Es el más visible para el cliente pequeño.)
- **F4 — Módulos por clínica:** menú superior + páginas gated por entitlement (front + back).
- **F5 — Roles por plan:** el selector de roles y las validaciones respetan el set del plan.
- **F6 — Super-admin UI:** editor de planes estructurado + overrides por clínica + vista de consumo.
- **F7 — Vitrina/onboarding:** que al comprar se elija plan y se aplique solo.

Cada fase es probable-y-verificable por separado, como venimos haciendo.

---

## 11. Decisiones que necesito de ti (el dueño de Maily)
1. **Empaquetado de planes:** ¿los 4 de la sección 6 te laten, o tienes otros en mente (nombres,
   precios, qué módulo va en cuál)?
2. **Qué es "core" (siempre incluido) vs "de paga":** ¿Agenda + Pacientes + Expediente son la base
   mínima de todos los planes? ¿Finanzas/Cotizaciones/Paquetes son los "de paga"?
3. **Límites:** ¿pones tope de usuarios y de sucursales por plan, o "ilimitado" con límites blandos?
4. **Multi-sucursal:** ¿es un flag aparte (add-on que se compra) o va implícito en el plan más caro?
5. **Overrides por clínica:** ¿quieres poder hacer tratos a la medida (recomendado), o solo planes fijos?
6. **Roles del plan Individual:** ¿solo `owner`, o `owner + reception` (por si el médico tiene una
   secretaria)?

Con eso, aterrizo el modelo exacto y armamos el plan de construcción.

## Nota de estado
Todo esto es ANÁLISIS. No se ha tocado código. La iniciativa de sucursales (lo que has estado
probando) queda intacta: 3236 tests en verde, local, sin push.
