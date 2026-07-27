# Mapa de dependencias entre módulos — qué se puede vender por separado

> 2026-07-24. Análisis técnico (SIN código). Complementa
> `planes-modulos-entitlements-analisis.md`, que definió el CONCEPTO de entitlements.
> Este documento responde la pregunta operativa: **¿qué módulo depende de cuál, y cuáles
> se pueden apagar de verdad sin romper la app?**
>
> Todo lo que sigue está verificado contra el código, no supuesto.

---

## 0. Veredicto en una línea

**Sí se puede modular, y la app está mejor preparada de lo esperado.** Los cruces entre
módulos son pocos, están hechos con importes diferidos y **todas las llaves foráneas entre
módulos son opcionales** (`null=True`). Apagar un módulo degrada la app, no la rompe.

La restricción real no es técnica: es **qué tan fino quieres cortar** para vender.

---

## 1. Hallazgo estructural: la app ya está desacoplada

Tres evidencias del código:

**a) Todas las llaves entre módulos son opcionales.**

| Llave | Destino | Obligatoria |
|---|---|---|
| `Appointment.quote` | finanzas | No (`SET_NULL`) |
| `Charge.appointment` | agenda | No (`SET_NULL`) |
| `Prescription.appointment` | agenda | No (`SET_NULL`) |
| `Prescription.evolution_note` | expediente | No (`SET_NULL`) |
| `TreatmentScheme.quote` | finanzas | No (`SET_NULL`) |
| `TreatmentSchemeItem.service_concept` | finanzas | No (`PROTECT`, nullable) |

Significa que un registro de un módulo **puede existir sin el otro módulo**. Una receta no
necesita cita ni evolución; un cargo no necesita cita.

**b) Los importes entre apps son diferidos** (dentro de la función, marcados
`# noqa: PLC0415`). Los únicos cruces reales son:

```
expediente/selectors.py:653  → recetas.Prescription   (listar recetas en el libro clínico)
expediente/selectors.py:820  → recetas.Prescription   (idem)
expediente/pdf.py:496        → recetas.pdf            (reusa el fetcher seguro de imágenes)
agenda/services.py:487       → finanzas.Quote         (vincular cita con cotización aceptada)
```

Cuatro puntos de contacto en toda la aplicación. No hay un enredo que desarmar.

**c) Nada gatea por plan hoy.** `Plan.features` es una lista de strings de marketing. Todo el
control de acceso es por ROL. La capa de entitlements se construye limpia, sin deshacer nada.

---

## 2. El núcleo indivisible (nunca se vende, nunca se apaga)

Estas piezas tienen llaves **obligatorias** desde el resto. Sin ellas no hay aplicación:

| Pieza | Por qué es núcleo |
|---|---|
| `tenancy`, `authn`, `core` | Multi-tenant, RLS, login. Infraestructura. |
| `audit` | Bitácora. Es requisito normativo, no una función vendible. |
| `clinica` | La clínica misma y su configuración. |
| **`pacientes`** | **`Patient` es llave obligatoria en agenda, expediente, recetas y finanzas.** Sin pacientes no hay nada que gestionar. |
| **`personal`** | `Appointment.doctor` y `Prescription.doctor` son obligatorias. El *dato* médico/consultorio debe existir. |

**Matiz importante sobre `personal`:** el DATO es núcleo, pero la PANTALLA de gestión de
personal sí es opcional. Un consultorio de un solo médico no necesita el módulo "Personal"
en el menú — el sistema le crea su médico y su consultorio, y él nunca ve esa sección.

> **Regla general:** "módulo" significa dos cosas distintas — una capacidad de datos y una
> entrada de menú. Se pueden apagar entradas de menú cuyos datos siguen existiendo por debajo.

---

## 3. Catálogo real de módulos vendibles

Aquí está el hallazgo que cambia el empaquetado: **el corte NO es por app de Django.**
La app `finanzas` contiene **cinco capacidades vendibles por separado**:

```
finanzas/models.py
├── ServiceConcept      → "Servicios y precios"      (catálogo)
├── TreatmentPackage    → "Paquetes"
├── Quote + QuoteItem   → "Cotizaciones"
├── Charge + Payment    → "Cobranza y estado de cuenta"
└── CfdiDocument        → "Facturación CFDI"
```

Catálogo completo propuesto:

| # | Módulo vendible | Vive en | Depende de |
|---|---|---|---|
| 1 | **Agenda y citas** | `agenda` | núcleo |
| 2 | **Recordatorios** (WhatsApp) | `agenda` + `notificaciones` | Agenda |
| 3 | **Expediente clínico** | `expediente` | núcleo |
| 4 | **Recetas** | `recetas` | núcleo |
| 5 | **Servicios y precios** | `finanzas` | núcleo |
| 6 | **Paquetes** | `finanzas` | Servicios |
| 7 | **Cotizaciones** | `finanzas` | Servicios |
| 8 | **Cobranza / estado de cuenta** | `finanzas` | núcleo |
| 9 | **Facturación CFDI** | `finanzas` | Cobranza |
| 10 | **Notas y tareas** | `notas` | — (el más independiente) |
| 11 | **Avisos internos** | `notificaciones` | — |
| 12 | **Gestión de personal** | `personal` (UI) | — |
| 13 | **Multi-sucursal** | flag | — |

Dentro del expediente hay sub-capacidades que también podrían venderse aparte, si se quiere
llegar a ese nivel de granularidad: Historia clínica, Signos vitales, Evoluciones/libro
clínico, Diagnósticos, **Calendarización de tratamientos**, Plan Integral, Resumen clínico.

---

## 4. Mapa de dependencias

### 4.a — Dependencias DURAS (no se pueden romper)

Si enciendes el de la izquierda, **debes** encender el de la derecha:

```
Recordatorios          → Agenda
Paquetes               → Servicios y precios
Cotizaciones           → Servicios y precios
Facturación CFDI       → Cobranza
Calendarización        → Servicios y precios + Cotizaciones
(todos)                → Pacientes + Personal (núcleo)
```

El super-admin debe **impedir** combinaciones inválidas: si desmarcas "Servicios", se
desmarcan solos Paquetes y Cotizaciones. Si no, se venden planes rotos.

### 4.b — Dependencias SUAVES (se degradan, no rompen)

Estas son las que hacen que el modelo funcione. Si el módulo destino está apagado, la función
simplemente no aparece:

| Función | Necesita | Si falta |
|---|---|---|
| Vincular cita ↔ cotización | Agenda + Cotizaciones | No se ofrece el vínculo |
| Receta desde una evolución | Recetas + Expediente | La receta se emite suelta |
| Cargo automático desde la cita | Cobranza + Agenda | El cargo se captura a mano |
| Recetas dentro del libro clínico | Expediente + Recetas | El libro no muestra esa sección |
| Estado de cuenta en el expediente | Expediente + Cobranza | No aparece la sección |

**Ninguna de estas rompe nada.** Son enriquecimientos entre módulos.

---

## 5. Tu caso: la clínica dental

> *"Agenda, recordatorios, expedientes; sin recetas ni finanzas."*

| Módulo | Estado | Consecuencia |
|---|---|---|
| Agenda | ON | Completa |
| Recordatorios | ON | Depende de Agenda ✓ |
| Expediente | ON | HC, signos, evoluciones, diagnósticos |
| Recetas | OFF | Sin "Receta" en la visita ni en el libro clínico |
| Servicios/Paquetes/Cotizaciones | OFF | Sin menú Cotizaciones |
| Cobranza / CFDI | OFF | Sin menú Finanzas ni estado de cuenta |
| Notas | a elección | Independiente |

**Qué ve el dentista:** menú con Agenda · Pacientes · (Notas). Dentro del expediente: paso ①
Enfermería y ② Evolución — **sin el paso ③ Receta**. En el índice de secciones: libro
clínico, signos, diagnósticos, citas — **sin recetas, sin estado de cuenta, sin
calendarización** (esta última cae porque depende de Servicios + Cotizaciones).

**Verificado que no rompe:** los 4 puntos de contacto del §1.b son importes diferidos y
llaves nulables. `expediente → recetas` solo se usa para LISTAR recetas; con el módulo
apagado, la lista va vacía y la sección no se pinta.

**El único ajuste real:** hoy la calendarización de tratamientos vive en el expediente pero
depende de finanzas. Hay que decidir si en un plan sin finanzas se apaga (recomendado) o si
se le hace una versión sin precios.

---

## 6. Los roles NO deberían configurarse libres — deberían derivarse

Pediste controlar "cuántos roles va a tener". Aquí una recomendación en contra de la forma
directa, con la razón:

Los 7 roles existen **para repartir módulos**. Si Finanzas está apagado, el rol `finance`
queda con: agenda(ver) + pacientes(ver) + notas. Es decir, **un usuario que no puede hacer su
trabajo**. Lo mismo con `nurse` sin Expediente: enfermería existe para capturar signos.

| Rol | Existe por | Se vuelve inútil si falta |
|---|---|---|
| `owner` | siempre | — |
| `admin` | delegar administración | (equipos chicos no lo necesitan) |
| `doctor` | Expediente + Recetas | Expediente |
| `nurse` | Signos vitales | Expediente |
| `reception` | Agenda | Agenda |
| `finance` | Cobranza | Cobranza |
| `readonly` | consulta/auditoría | — |

**Recomendación:** el super-admin **no elige roles a mano**. El sistema los deriva de los
módulos contratados y el super-admin solo puede **quitar** de esa lista (nunca agregar uno
sin su módulo). Así es imposible vender un plan con un rol que no puede trabajar.

El plan Individual queda `[owner]` no porque alguien lo escribió, sino porque un solo usuario
no necesita repartir nada.

---

## 7. Límites numéricos

Los que ya anuncias en las tarjetas de planes, y dónde se aplicarían:

| Límite | Modelo | Se valida al |
|---|---|---|
| `max_usuarios` | `TenantMembership` | invitar/dar de alta un miembro |
| `max_consultorios` | `personal.Consultorio` | crear consultorio |
| `max_sucursales` | `clinica.Sucursal` | crear sucursal |

`max_sucursales = 1` **es** el "modo sede única": desaparece toda la UI de sucursales.
No hace falta un flag aparte de `multi_sucursal` — el límite lo dice todo. Un flag adicional
sería una segunda fuente de verdad que puede contradecir al límite.

**Ojo con los límites:** hay que decidir qué pasa cuando una clínica **baja** de plan y ya
tiene 8 usuarios con un tope nuevo de 3. Nunca borrar datos. La salida sana es bloquear altas
nuevas y avisar, dejando lo existente en paz.

---

## 8. Empaquetado propuesto (ajustable)

Sobre tus 3 planes actuales (Básico $1,500 · Pro $4,500 · Premium $8,900):

| | Básico | Pro | Premium |
|---|---|---|---|
| Sucursales | 1 | 1 | ilimitadas |
| Consultorios | 1 | 5 | ilimitados |
| Usuarios | 3 | ilimitados | ilimitados |
| Agenda + Recordatorios | ✅ | ✅ | ✅ |
| Pacientes + Expediente | ✅ | ✅ | ✅ |
| Recetas | ✅ | ✅ | ✅ |
| Notas y tareas | ✅ | ✅ | ✅ |
| Servicios y precios | — | ✅ | ✅ |
| Cotizaciones + Paquetes | — | ✅ | ✅ |
| Cobranza / estado de cuenta | — | ✅ | ✅ |
| Facturación CFDI | — | — | ✅ |
| Multi-sucursal | — | — | ✅ |
| Roles disponibles | owner | todos | todos |

**El corte natural del negocio es: lo clínico es la base, lo financiero es el upgrade.**
Coincide con tus tarjetas actuales ("Finanzas y reportes" ya aparece solo en Pro).

**Pero tu caso dental no cabe aquí**, y ese es el punto: un dentista que quiere agenda +
expediente pero NO recetas no encaja en ningún plan fijo. Por eso los **overrides por
clínica** no son un lujo — son lo que hace vendible el producto a clínicas con formas
distintas. El plan es el punto de partida; el override cierra el trato.

---

## 9. Cómo se vería en el super-admin

Sobre el modal "Editar plan" que ya existe (nombre, precio, orden, características, popular,
activo), se agregan tres bloques:

```
┌─ MÓDULOS INCLUIDOS ──────────────────────────┐
│  Clínico                                     │
│   ☑ Agenda y citas                           │
│   ☑ Recordatorios          (requiere Agenda) │
│   ☑ Expediente clínico                       │
│   ☑ Recetas                                  │
│  Comercial                                   │
│   ☐ Servicios y precios                      │
│   ☐ Paquetes            (requiere Servicios) │
│   ☐ Cotizaciones        (requiere Servicios) │
│   ☐ Cobranza                                 │
│   ☐ Facturación CFDI    (requiere Cobranza)  │
│  Operación                                   │
│   ☑ Notas y tareas                           │
│   ☐ Gestión de personal                      │
└──────────────────────────────────────────────┘
┌─ LÍMITES ────────────────────────────────────┐
│  Usuarios     [ 3 ]  ☐ ilimitado             │
│  Consultorios [ 1 ]  ☐ ilimitado             │
│  Sucursales   [ 1 ]  ☐ ilimitado             │
│                 ↑ 1 = modo sede única        │
└──────────────────────────────────────────────┘
┌─ ROLES (derivados de los módulos) ───────────┐
│  Disponibles: Dueño, Médico, Recepción       │
│  Enfermería  — requiere Expediente ✓         │
│  Finanzas    — requiere Cobranza ✗ apagado   │
│  ☐ Restringir más (quitar de la lista)       │
└──────────────────────────────────────────────┘
```

Las dependencias se aplican **en vivo**: desmarcar "Servicios" desmarca Paquetes y
Cotizaciones a la vista, explicando por qué. Es lo que impide vender un plan roto.

Además, en la ficha de cada clínica: los mismos controles como **override**, más un
indicador de consumo real (usuarios 6/8, sucursales 2/3) para detectar upsell.

---

## 10. Riesgos identificados

1. **Las dos capas deben leer la misma fuente.** El backend es la autoridad (403 real); el
   frontend solo oculta. Si se implementa solo el ocultamiento, cualquiera con la URL entra.
2. **Migración de las clínicas actuales.** Todas deben quedar en un plan "Legacy full" con
   todo encendido. Si alguna despierta con módulos apagados, es una interrupción de servicio.
3. **Bajar de plan con datos existentes.** Nunca borrar. Bloquear altas y avisar.
4. **Cotizaciones y Finanzas son el mismo app de Django** pero módulos distintos. El guard
   debe ser por endpoint/capacidad, no por app, o se apagan de más.
5. **Calendarización cruza clínico↔financiero.** Es el único punto donde la separación
   "clínico = base / financiero = upgrade" no es limpia. Requiere decisión.
6. **`/paquetes` no tiene gating de rol en el router del frontend** (solo `RequireAuth`),
   a diferencia del resto de rutas que usan `ClinicRoute modulo=…`. El backend sí lo protege
   (`TreatmentPackagePermission`), así que **no es un hueco de seguridad**, pero al agregar
   entitlements hay que corregirlo o esa página se escapará del gating.

---

## 11. Decisiones que necesito de ti

1. **Granularidad:** ¿el corte de 13 módulos del §3 te sirve, o prefieres menos bloques más
   gruesos (p. ej. "Finanzas" entero en vez de 5 piezas)?
2. **Calendarización de tratamientos** en un plan sin finanzas: ¿se apaga, o versión sin precios?
3. **Roles derivados** (§6): ¿te convence que el sistema los calcule, o los quieres a mano?
4. **Overrides por clínica:** ¿los habilitamos desde el inicio? (Sin ellos, el caso dental no
   se puede vender.)
5. **Bajar de plan** estando por encima del límite: ¿bloquear altas y avisar, o algo distinto?
6. **Empaquetado del §8:** ¿los 3 planes actuales quedan así, o movemos módulos entre ellos?

Con esas respuestas aterrizo el modelo de datos exacto y el plan de construcción por fases.

---

## Nota de estado

Análisis. **No se ha tocado código.** Todo lo afirmado sobre el estado actual fue verificado
leyendo el código en esta sesión (llaves foráneas, importes entre apps, permisos, rutas).
