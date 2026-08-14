# Brechas de frontend — lo que la interfaz promete y lo que el backend concede

> Producido en la sesión A3 de adopción con la skill `frontend-audit`. Cruza
> `MailySoft/web-soft/src` contra `MailySoft/docs/02-contrato.md`. **No es una revisión de código ni
> de diseño: es un cruce de dos listas.** Cada punto se contesta con evidencia `archivo:línea` de los
> dos lados o se marca `NO VERIFICABLE`.

| | |
|---|---|
| Fecha | 2026-08-12 |
| Commit auditado | `a5cd334` |
| Estado del árbol | 39 archivos de `web-soft/src` con cambios sin commitear: **se auditó el árbol de trabajo**, no el commit |
| Contra qué se comparó | `docs/02-contrato.md` rev. 2, y el código de `MailySoft/backend/` cuando el contrato citaba una línea concreta |
| Documento hermano | `docs/00-brechas.md` — las 167 brechas del backend (fase A2) |
| Método | `.claude/skills/frontend-audit/SKILL.md`, sus cinco cruces, uno por subagente (el cruce 1 partido en cuatro por módulo) |

## Por qué existe este documento

El contrato documenta el backend y el backend es la autoridad de permisos. Eso hace creer que el
frontend no puede causar daño. Puede, de cinco formas, y ninguna se ve leyendo el backend: deriva de
permisos, gating por módulo desalineado, caché que sobrevive al cambio de clínica o de sede, header
`X-Sucursal-Id` ausente, y fugas del bundle.

## Qué NO es este documento

**No se corrigió nada de código.** Ni una línea. Documentar y arreglar a la vez produce un reporte
que no describe ni el sistema viejo ni el nuevo.

**No opina de diseño.** Espaciado, colores y consistencia visual quedan fuera por regla de la skill.

## Cómo se leen las severidades

Mismos criterios que `00-brechas.md`, para que las dos listas se puedan ordenar juntas en A4:

| | Criterio |
|---|---|
| **P0** | Fuga de datos entre clínicas o entre sedes visible en pantalla, escalamiento de privilegios, pérdida o corrupción de datos clínicos o de dinero |
| **P1** | El usuario queda bloqueado o el sistema parece roto; PII expuesta de más; promesa comercial sin implementación |
| **P2** | Molestia, capacidad pagada que nadie usa, código muerto, inconsistencias |

La severidad se justifica con el escenario, no con adjetivos.

## Prefijos de identificador

`F-1A` permisos de pacientes y expediente · `F-1B` permisos de agenda, notas y notificaciones ·
`F-1C` permisos de finanzas y recetas · `F-1D` permisos de consultorio, personal, autenticación,
bitácora y plataforma · `F-2` gating por módulo · `F-3` caché · `F-4` alcance por sede ·
`F-5` bundle y XSS.

## Índice

| Cruce | Qué contesta | Sección |
|---|---|---|
| Resumen | el P0, las 29 P1 agrupadas por causa, los defectos del contrato | [§Resumen](#resumen) |
| 1A | ¿el frontend ofrece de pacientes y expediente lo mismo que el backend concede? | [§Cruce 1A](#cruce-1a--pacientes-y-expediente-clínico) |
| 1B | lo mismo para agenda, notas y notificaciones | [§Cruce 1B](#cruce-1b--agenda-notas-y-notificaciones) |
| 1C | lo mismo para finanzas y recetas | [§Cruce 1C](#cruce-1c--finanzas-y-recetas) |
| 1D | lo mismo para consultorio, personal, autenticación, bitácora y plataforma | [§Cruce 1D](#cruce-1d--mi-consultorio-personal-autenticación-bitácora-y-plataforma) |
| 2 | ¿la ruta exige el mismo módulo que exigen sus endpoints? | [§Cruce 2](#cruce-2--gating-por-módulo) |
| 3 | ¿la caché del navegador sobrevive al cambio de clínica o de sede? | [§Cruce 3](#cruce-3--caché-entre-clínicas-y-entre-sedes) |
| 4 | ¿sale `X-Sucursal-Id` donde el backend lo espera? | [§Cruce 4](#cruce-4--header-x-sucursal-id-y-alcance-por-sede) |
| 5 | ¿se escapa algo por el bundle? | [§Cruce 5](#cruce-5--bundle-y-xss) |

Cada cruce abre con su **tabla de cruce completa** —también las filas alineadas, que son la prueba de
cobertura— y sigue con sus hallazgos, sus `NO VERIFICABLE` y los defectos del contrato que encontró.

## Resumen

**76 hallazgos: 1 P0 · 29 P1 · 46 P2.** Se produjeron 83 en bruto; 7 eran el mismo defecto visto
desde dos cruces y se consolidaron (tabla al final de esta sección).

| Cruce | Total | P0 | P1 | P2 |
|---|---:|---:|---:|---:|
| 1A · Permisos: pacientes y expediente | 14 | **1** | 7 | 6 |
| 1B · Permisos: agenda, notas y notificaciones | 11 | 0 | 4 | 7 |
| 1C · Permisos: finanzas y recetas | 14 | 0 | 5 | 9 |
| 1D · Permisos: consultorio, personal, autenticación, bitácora y plataforma | 11 | 0 | 6 | 5 |
| 2 · Gating por módulo | 10 | 0 | 3 | 7 |
| 3 · Caché entre clínicas y entre sedes | 3 | 0 | 1 | 2 |
| 4 · Header `X-Sucursal-Id` y alcance por sede | 10 | 0 | 3 | 7 |
| 5 · Bundle y XSS | 3 | 0 | 0 | 3 |
| **Total** | **76** | **1** | **29** | **46** |

### El resultado más importante: no hay fuga entre clínicas

El cruce 3 es el que la skill declara "el más grave y el que nadie revisa", y salió sin ningún P0.
No por suerte ni por buenas claves de caché —**ninguna `queryKey` lleva el tenant**— sino porque el
escenario no es alcanzable: `X-Tenant-ID` no existe en el código (`02-contrato.md:302-304`), un
usuario con dos membresías siempre opera sobre la más antigua, y el único paso de una clínica a otra
en el mismo navegador es cambiar de usuario, que pasa obligatoriamente por `login()` o `logout()`, y
ambos hacen `queryClient.clear()` (`web-soft/src/auth/AuthContext.tsx:110` y `:129`).

Eso es una **dependencia, no una garantía**: el día que se implemente el cambio de clínica en
caliente (el "Paso 3" que anuncian `apps/core/tests/test_middleware.py:222` y
`apps/tenancy/models.py:29`), las 68 `queryKey` del inventario del cruce 3 se vuelven una fuga entre
clínicas el mismo día. Anotarlo aquí es el objetivo de esta auditoría.

### El P0

| ID | Qué pasa |
|---|---|
| `F-1A-05` | El addendum es el único canal para corregir una nota de evolución firmada, y **no tiene ninguna pantalla alcanzable**: la UI existe en `EvolucionTab.tsx`, un componente sin ningún importador. El expediente real monta `LibroClinico` (`ExpedienteDrawer.tsx:49`), que no lo ofrece. El backend sí expone la ruta (`apps/expediente/urls.py:119`) |

Es la misma forma que `B-REC-01` del backend: una función completa, implementada y facturada, a la
que ningún clic llega. Aquí importa más porque la regla dura nº4 del proyecto ("lo clínico es
inmutable: se corrige con addendum") deja de tener cómo cumplirse. Un error en una nota firmada hoy
no se puede corregir por ningún camino de la aplicación.

### Las 29 P1, agrupadas por causa

No son 29 problemas distintos. Son seis patrones:

| Patrón | Hallazgos | Por qué se repite |
|---|---|---|
| **Autoridad por pertenencia disfrazada de rol** | `F-1A-06` `F-1A-07` `F-1A-08` `F-1B-03` `F-1C-03` | El backend decide por autoría o pertenencia dentro del `service` (el médico solo anula su receta, solo escribe sobre sus citas). El frontend solo tiene una matriz de rol, así que o muestra de más o esconde de más. **Es el hallazgo estructural de esta auditoría** |
| **Botón fantasma por matriz desalineada** | `F-1A-01` `F-1B-01` `F-1B-02` `F-1B-11` `F-1D-02` `F-1D-03` `F-4-01` | `auth/permisos.ts` se escribió contra un plan de diseño, no contra `apps/core/permissions.py` |
| **Función invisible con costo real** | `F-1A-03` `F-1A-04` `F-1C-01` `F-1C-02` | Capacidad implementada y pagada que ninguna pantalla ofrece. `F-1C-02` es comercial: una clínica Premium compra CFDI y **no hay dónde capturar los datos fiscales del emisor**, así que todo timbrado falla |
| **Fallo abierto al arrancar la sesión** | `F-1D-01` `F-1D-06` `F-2-03` | Antes de que `/me/` responda, o cuando no responde nunca, el frontend asume el máximo privilegio en vez del mínimo |
| **La UI promete lo que el backend no cumple** | `F-1D-04` `F-1D-05` `F-1C-13` | Un botón sin endpoint detrás, una regla de contraseña de 8 donde el backend exige 10, y una receta controlada vencida declarada "auténtica y vigente" |
| **Sede** | `F-3-01` `F-4-02` `F-4-04` | `F-4-02` es el de más consecuencia: en modo "Todas las sucursales" no sale el header y **toda escritura cae en la sede predeterminada del tenant** |

### Una asimetría que conviene mirar junta

El contexto de rol de clínica falla a `readonly`, mínimo privilegio (`auth/RoleContext.tsx:15`). El
de plataforma falla a `super_admin`, máximo privilegio (`platform/PlatformRoleContext.tsx:19`). El
guard de módulo falla abierto cuando `capabilities` es `null` (`App.tsx:50`). Y el hook huérfano
`auth/useRole.ts:18` cae a `owner`. Cuatro decisiones del mismo tipo, tres de ellas hacia el lado
inseguro. Ninguna abre datos por sí sola —el backend filtra— pero juntas dicen que no hay un criterio
escrito sobre qué hacer mientras la sesión se resuelve.

### Hallazgos consolidados

Siete hallazgos aparecieron en dos cruces. Se conserva el que tiene el mejor escenario; el otro queda
como referencia cruzada dentro de su cruce, con su ID original para no romper trazabilidad.

| Se conserva | Absorbe | Severidad final | Motivo |
|---|---|---|---|
| `F-5-01` | `F-1A-15`, `F-3-04` | P2 | El mismo hook `useRole` huérfano visto desde tres cruces; el 5 lo verificó contra el bundle |
| `F-1D-01` | `F-5-02` | **P1** | Mismo selector "Ver como (demo)"; el 1D aporta el escenario concreto (ventas navegando como ingeniería) que justifica subirlo de P2 |
| `F-1A-09` | `F-1D-07` | P2 | Idénticos |
| `F-3-01` | `F-4-05` | **P1** | Mismo defecto de recordatorios; el 3 explica por qué la ventana no son 30 s sino indefinida |
| `F-1C-02` | `F-2-01` | P1 | Los datos fiscales del emisor: función invisible (1C) y capacidad comprada e inalcanzable (2) |
| `F-1C-08` | `F-1D-10` | P2 | Idénticos |

### Defectos del contrato detectados

Esta auditoría no debía tocar el contrato, pero verificar los dos lados obligó a leer el código del
backend y aparecieron ocho puntos donde `02-contrato.md` rev. 2 no coincide con `apps/`. **Dos son de
seguridad y no son de frontend**: van al backend en A3, no a esta lista.

| # | Dónde | Qué dice el contrato | Qué hace el código |
|---|---|---|---|
| **D-1** | §8.5 `:6326` | Crear un segundo dueño está bloqueado "incluso para el owner" | La comprobación vive solo en `member_create`; `member_update` (`apps/tenancy/services.py:406-411`) no la tiene. Un `PATCH /miembros/<id>/` deja la clínica con dos dueños, y el frontend ofrece ese camino (`MiembroDetalleDrawer.tsx:85-86`) |
| **D-2** | §8.5 `:6324` | La allow-list de roles del plan se hace valer al gestionar un miembro | Solo en el alta. `member_update` nunca consulta `entitlements_for_tenant`: en plan Básico el alta rechaza `admin` con 400 y el PATCH lo acepta |
| D-3 | §3.5 `:2213-2215` | Sin `agenda` contratada, 404 para los 7 roles | El permiso de rol se evalúa antes del guard de módulo, así que `finance` recibe 403 con o sin módulo. §9.4 `:6744` sí razona bien este caso |
| D-4 | §1.4.1 `:462` | El guard de `recordatorios` no se aplica en ninguna vista | Cierto pero incompleto: la funcionalidad **sí se ejecuta** (`apps/agenda/reminders.py:20`) y el módulo **se factura en los cuatro planes** |
| D-5 | §1.4.3 `:514-515` | Front y backend "no se pueden contradecir" porque comparten el objeto de entitlements | Con `capabilities = null` (usuario sin tenant) el backend es fail-closed y el frontend fail-open |
| D-6 | §1.4.3 `:502` | Documenta la fórmula de overrides | No dice si el resultado pasa por `validar_modulos`; queda sin resolver si el frontend es la única defensa |
| D-7 | §1.5.5 `:608` | Un admin de Norte puede borrar la nota de cita de Centro | §3.4.2 `:2199` precisa que la vista solo implementa `delete`; las dos secciones no dicen lo mismo |
| D-8 | — | — | En dirección contraria: **el contrato tiene razón y el docstring del backend está mal.** `apps/core/permissions.py:748-750` afirma que un PATCH sobre una evolución da 405; el mecanismo real da 403 (`permissions.py:133-135`), como documentan `:361` y `:3072`. Quien escriba el manejo de errores guiándose por el docstring pondrá una rama de 405 que nunca se dispara |

**D-1 y D-2 son escalada de privilegios y hay que tratarlos como tal**: un dueño puede fabricar un
segundo dueño, y cualquiera puede quedar con un rol que su plan no incluye. El frontend los amplifica
pero no los causa; el arreglo va en `apps/tenancy/services.py`.

### Qué se verificó y salió limpio

No todo son hallazgos. Conviene dejar escrito qué se comprobó y está bien, para no volver a auditarlo:

- **El espejo del catálogo de módulos está sincronizado**: los 12 slugs, etiquetas, dependencias
  duras, roles y grupos de `lib/modulos.ts` coinciden con `apps/core/modules.py`.
- **Los siete puntos binarios del bundle pasan**: cero `dangerouslySetInnerHTML`, cero `fetch` fuera
  de `lib/http.ts` (los 21 módulos de `api/` pasan por el cliente central), el access token vive solo
  en memoria y un F5 lo destruye, ningún `.env` versionado ni secreto en `src/`, y el refresh ante
  401 tiene doble candado contra el bucle infinito y una promesa compartida para peticiones
  concurrentes.
- **CSRF y sesión están alineados** con lo que exige el contrato §1.2.
- Ningún subagente encontró un camino por el que una clínica lea datos de otra.

---

## Cruce 1A · Pacientes y expediente clínico

Fuente del rol en la UI (verificado): `RoleContext.tsx:14-15` lee `AuthContext.clinicRole`
(`AuthContext.tsx:152` = `user.active_role` de `/me/`) con *fallback* `'readonly'`. `auth/useRole.ts`
existe pero **ningún archivo lo importa** y `tokenStore.setActiveRole` **nunca se llama**
(`lib/tokenStore.ts:50`), así que la trampa del "rol cacheado" no muerde hoy; ver F-1A-15.

Leyenda de roles: **O** owner · **A** admin · **D** doctor · **N** nurse · **R** reception ·
**F** finance · **L** readonly.

Matriz del frontend, una sola vez (`web-soft/src/auth/permisos.ts`):
`PERMISOS[rol].contactos` (`:105-111`) → O A D R = `edit`; N F L = `view`.
`puedeVerExpedienteClinico` (`:117`) → O A D N L = true; R F = false.
`puedeEditarClinico` (`:123-124`) → O A D. `puedeCapturarSignos` (`:127-128`) → O A D N.
`puedeVerEstadoCuenta` (`:208-215`) → O A F R L siempre + D si `doctors_see_costs`.

---

### Tabla de cruce

| Acción | Backend permite (archivo:línea) | Front la muestra a (archivo:línea) | Veredicto |
|---|---|---|---|
| **PACIENTES** | | | |
| Listar pacientes `GET /pacientes/` | los 7 (`apps/core/permissions.py:155`; contrato:1146, 1434) | los 7 — `/contactos` abierto a todo rol (`auth/permisos.ts:105-111`; `components/Topbar.tsx:45`), listado sin gate (`pages/ContactosPage.tsx:152-159`) | ALINEADO |
| Ver detalle `GET /pacientes/<id>/` | los 7 (`permissions.py:155`; contrato:1149, 1435) | los 7 — la tarjeta/fila abre el drawer sin gate (`ContactosPage.tsx:344`, `:454`, `:531-538`) | ALINEADO |
| Ver `last_reason` | los 6 de `APPOINTMENT_VIEW_ROLES`; F recibe `null` (`permissions.py:75-77`; contrato:1436) | O A D R — solo se pinta en el botón "Reagendar", gateado por `puedeAgendar` (`ContactosPage.tsx:95`, `:410`, `:496`) | ALINEADO |
| Crear paciente `POST /pacientes/` | O A D N R (`permissions.py:156`; contrato:1147, 1437) | O A D R (`ContactosPage.tsx:94`, `:182-189`) | FUNCIÓN INVISIBLE (N) |
| Crear provisional `POST /pacientes/rapido/` | O A D N R (`permissions.py:156`; contrato:1148, 1438) | nadie — cliente sin consumidor (`api/pacientes.ts:79`, `hooks/pacientes.ts:82`; ningún `.tsx` lo llama) | FUNCIÓN INVISIBLE |
| Editar paciente `PATCH /pacientes/<id>/` | O A D N R (`permissions.py:157`; contrato:1150, 1439) | O A D R (`ContactosPage.tsx:94`, `:535`; `components/expediente/FichaPaciente.tsx:264-272`) | FUNCIÓN INVISIBLE (N) |
| Asignar etiquetas (`category_ids` en PATCH) | O A D N R (`permissions.py:157`; contrato:1440) | O A D R (`ContactosPage.tsx:403-405`, `:444-446`; `components/contactos/EtiquetasQuickMenu.tsx:78-84`) | FUNCIÓN INVISIBLE (N) |
| Favorito/VIP `POST .../clasificacion/` | O A D N R (`permissions.py:156`; contrato:1154, 1441) | O A D R (`ContactosPage.tsx:389-402`, `:430-443`) | FUNCIÓN INVISIBLE (N) |
| Subir foto `POST .../avatar/` | O A D N R (`permissions.py:156`; contrato:1152, 1442) | O A D R (`components/contactos/ExpedienteDrawer.tsx:184-191`) | FUNCIÓN INVISIBLE (N) |
| Quitar foto `DELETE .../avatar/` | **O A** (`permissions.py:158`; contrato:1153, 1443) | nadie — sin función en `api/pacientes.ts` y sin botón en `components/common/AvatarUploader.tsx:54-70` | FUNCIÓN INVISIBLE |
| Desactivar `DELETE /pacientes/<id>/` | **O A** (`permissions.py:158`; contrato:1151, 1444) | O A D R (`ExpedienteDrawer.tsx:225-232` con `puedeEditar` = `ContactosPage.tsx:94`) | **BOTÓN FANTASMA (D, R)** |
| Reactivar paciente | n/a (contrato:1445) | no ofrecido | ALINEADO |
| **EXPEDIENTE — alergias** | | | |
| Listar alergias `GET` | **los 7** a propósito (`permissions.py:689-690`; contrato:358, 2736, 3144) | O A D N L (`FichaPaciente.tsx:90` con `verClinico` = `ExpedienteDrawer.tsx:87`) | **FUNCIÓN INVISIBLE (R, F)** |
| Crear alergia `POST` | O A D **N** (`permissions.py:691`; contrato:3145) | O A D (`FichaPaciente.tsx:511-518`, `puedeEditar` = `puedeEditarClinico`, `ExpedienteDrawer.tsx:88`, `:257`) | **FUNCIÓN INVISIBLE (N)** |
| Resolver alergia `DELETE` | O A D **N** (`permissions.py:693`; contrato:3146) | O A D (`FichaPaciente.tsx:547-560`) | **FUNCIÓN INVISIBLE (N)** |
| **EXPEDIENTE — historia clínica** | | | |
| Leer HC `GET` | CLINICAL_READ = O A D N L (`permissions.py:716`; contrato:3147) | O A D N L (`components/expediente/IndiceSecciones.tsx:87`, `:109-117`) | ALINEADO |
| Guardar HC `PUT` | O A D (`permissions.py:717`; contrato:3148) | O A D (`ExpedienteDrawer.tsx:299`; `components/expediente/HistoriaTab.tsx:515`) | ALINEADO |
| **EXPEDIENTE — signos** | | | |
| Leer signos / series `GET` | CLINICAL_READ (`permissions.py:736`; contrato:3149) | O A D N L (`IndiceSecciones.tsx:51-53`, `:88-94`) | ALINEADO |
| Registrar toma `POST` | O A D N (`permissions.py:737`; contrato:3150) | O A D N (`ExpedienteDrawer.tsx:89`, `:305`; `VisitaDeHoy.tsx:95-99`; `SignosTab.tsx:144`) | ALINEADO |
| **EXPEDIENTE — evolución** | | | |
| Leer evoluciones / libro `GET` | CLINICAL_READ (`permissions.py:764`; contrato:3151, 3160) | O A D N L (`IndiceSecciones.tsx:96-101`; `ExpedienteDrawer.tsx:301-303`) | ALINEADO |
| Crear evolución `POST` (rol) | O A D (`permissions.py:765`; contrato:3152) | O A D (`VisitaDeHoy.tsx:107-113`) | ALINEADO |
| Crear evolución `POST` (**pertenencia**: D solo sobre sus citas) | `apps/expediente/services.py:699-709`, `actor_role` real (`views_evoluciones.py:226`, `:240`); contrato:3076 | el selector lista **todas** las citas atendidas, de cualquier médico (`EvolucionSoapStepper.tsx:154-157`, `:253-260`) | **BOTÓN FANTASMA (D)** |
| Editar / borrar evolución | nadie: PATCH/PUT 403, DELETE 405 (`permissions.py:763-767`; contrato:3153) | no ofrecido | ALINEADO |
| Crear addendum `POST` | O A D (`permissions.py:891-893`; contrato:3154) | nadie — única UI en `EvolucionTab.tsx:274-296`, componente **huérfano** (sin ningún import en `src/`) | **FUNCIÓN INVISIBLE** |
| Leer addenda | CLINICAL_READ, anidados en el capítulo (contrato:2823) | O A D N L (`LibroClinico.tsx:847-852`) | ALINEADO |
| **EXPEDIENTE — diagnósticos** | | | |
| Leer diagnósticos `GET` | CLINICAL_READ (`permissions.py:910`; contrato:3155) | O A D N L (`IndiceSecciones.tsx:102-107`) | ALINEADO |
| Crear diagnóstico `POST` | O A D (`permissions.py:911`; contrato:3156) | O A D (`ExpedienteDrawer.tsx:308`; `DiagnosticosTab.tsx:51`) | ALINEADO |
| Resolver diagnóstico `POST` | O A D (`permissions.py:911`; contrato:3156) | O A D (`DiagnosticosTab.tsx:133`) | ALINEADO |
| **EXPEDIENTE — enfermería e imágenes** | | | |
| Leer indicaciones de enfermería `GET` | CLINICAL_READ (`permissions.py:930`; contrato:3157) | O A D N L (`FichaPaciente.tsx:105-107`, `:640-641`) | ALINEADO |
| Listar imágenes de evolución `GET` | CLINICAL_READ (`permissions.py:764`; contrato:3158) | O A D N L en el libro (`LibroClinico.tsx` capítulo) — pero la galería editable solo tras crear (`EvolucionSoapStepper.tsx:628`) | ALINEADO (lectura) |
| Subir imagen `POST` | O A D, sin límite temporal (`permissions.py:765`; contrato:3084, 3159) | O A D **solo en la pantalla de éxito posterior a crear la nota** (`EvolucionSoapStepper.tsx:629`) | FUNCIÓN INVISIBLE (parcial) |
| Borrar imagen `DELETE` | O A D (`permissions.py:766`; contrato:3159) | ídem (`EvolucionSoapStepper.tsx:630`) | FUNCIÓN INVISIBLE (parcial) |
| Pedir PDF del libro | CLINICAL_READ (contrato:3161) | O A D N L (`LibroClinico.tsx:188`, `:229`, `:289-293`) | ALINEADO |
| **EXPEDIENTE — resumen clínico** | | | |
| Borrador de resumen `GET` | O A D (`permissions.py:790`; contrato:3162) | O A D (`LibroClinico.tsx:710`, `:735-745`) | ALINEADO |
| Guardar resumen `POST` (rol) | O A D (`permissions.py:791`; contrato:3163) | O A D (`LibroClinico.tsx:710`) | ALINEADO |
| Guardar resumen `POST` (**pertenencia**: D solo sus consultas) | `services_resumen.py:405-415`, `actor_role` real (`views_resumen.py:131`, `:138`); contrato:3080 | el botón sale en **todos** los capítulos, también los de otro médico (`LibroClinico.tsx:735-745`) | **BOTÓN FANTASMA (D)** |
| Listar resúmenes `GET` | O A D (`permissions.py:790`; contrato:3164) | nadie — `useResumenesClinicos` (`hooks/expediente.ts:376`) sin consumidor | FUNCIÓN INVISIBLE |
| PDF de resumen `GET` | O A D (contrato:3164) | O A D solo en el instante de generarlo (`ResumenClinicoModal.tsx`) | FUNCIÓN INVISIBLE (parcial) |
| **EXPEDIENTE — plan integral** | | | |
| Borrador plan integral `GET` | O A D (`permissions.py:838`; contrato:3165) | O A D (`ExpedienteDrawer.tsx:119`, `:216-224`) | ALINEADO |
| Crear plan integral `POST` | O A D (`permissions.py:839`; contrato:3166) | O A D (`ExpedienteDrawer.tsx:216-224`; `PlanIntegralModal.tsx`) | ALINEADO |
| Listar planes integrales `GET` | O A D (`permissions.py:838`; contrato:3166) | nadie — `usePlanesIntegrales` (`hooks/planIntegral.ts:59`) sin consumidor | FUNCIÓN INVISIBLE |
| **EXPEDIENTE — calendarización** | | | |
| Listar / ver calendarización `GET` | O A D (`permissions.py:812`; contrato:3167) | O A D (`ExpedienteDrawer.tsx:101`, `:321`; `IndiceSecciones.tsx:45`) | ALINEADO |
| Crear / PUT / DELETE calendarización | O A D (`permissions.py:812`; contrato:3168) | O A D (`CalendarizacionTab.tsx:289-291`, `:605`, `:826`, `:863`) | ALINEADO |
| Crear desde paquete `POST` | O A D (contrato:3169) | O A D (`CalendarizacionTab.tsx:593`, `:615`, `:639`) | ALINEADO |
| Generar cotización `POST` | O A D (contrato:3170) | O A D (`CalendarizacionTab.tsx:839-844`) | ALINEADO |
| Agendar sesión `POST` (**pertenencia**) | O A D; D solo para sí mismo (contrato:3171; `services_calendarizacion.py:942-948`) | el médico queda fijado a sí mismo (`AgendarSesionModal.tsx:79`, `:96`; `CalendarizacionTab.tsx:295`, `:314`, `:736-740`) | ALINEADO |
| Desagendar sesión `DELETE` / PUT que borra sesiones (**pertenencia**: D solo sus citas) | `services_calendarizacion.py:201-206`, invocado también desde el PUT (`:322-331`, `:595-605`), `actor_role` real (`views_calendarizacion.py:270`, `:494`); contrato:3081 | "Quitar de agenda" y "Reagendar" salen en cualquier sesión, incluso mostrando el nombre del otro médico (`CalendarizacionTab.tsx:1113`, `:1116-1131`) | **BOTÓN FANTASMA (D)** |
| PDF de calendarización | O A D (contrato:3167) | O A D (`CalendarizacionTab.tsx:835`) | ALINEADO |
| **EXPEDIENTE — catálogos** | | | |
| Leer preguntas de HC `GET` | CLINICAL_READ (`permissions.py:1053`; contrato:3172) | O A ven la pantalla (`pages/MiConsultorioPage.tsx:105-107`, `:117`); D N L las reciben embebidas en la HC (`serializers.py:335-344`, contrato:2768) | ALINEADO |
| Crear / editar / desactivar pregunta | O A (`permissions.py:1054-1056`; contrato:3173) | O A (`MiConsultorioPage.tsx:93` con `gestionable` = `:59`) | ALINEADO |
| Leer plantillas de documento `GET` | O A D (`permissions.py:854`; contrato:3174) | O A en la pantalla de catálogo (`MiConsultorioPage.tsx:87`); D las consume en el plan integral (`PlanIntegralModal.tsx:607`) | ALINEADO |
| Crear / editar / borrar plantilla | O A (`permissions.py:855-857`; contrato:3175) | O A (`MiConsultorioPage.tsx:87`) | ALINEADO |
| Leer analitos `GET` | O A D (`permissions.py:872`; contrato:3174) | O A en el catálogo (`MiConsultorioPage.tsx:89`); D los consume en el plan integral (`PlanIntegralModal.tsx:159`) | ALINEADO |
| Crear / editar / borrar analito | O A (`permissions.py:873-875`; contrato:3175) | O A (`MiConsultorioPage.tsx:89`) | ALINEADO |
| **LLAMADAS QUE HACE EL EXPEDIENTE A OTROS MÓDULOS** | | | |
| `GET /clinica/configuracion/` desde el expediente | CLINICAL_READ (`apps/clinica/permissions.py:37-38`; contrato:413) | los 7 — `useClinicSettings()` incondicional (`ExpedienteDrawer.tsx:94`) | **BOTÓN FANTASMA (R, F)** |
| `GET /agenda/citas/?patient_id=` desde el expediente | O A D N R L, **F excluido** (`permissions.py:192` + `:75-77`; contrato:341) | los 7 — `ProximaConsulta` incondicional (`FichaPaciente.tsx:339`) y sección "Citas" gateada solo por módulo (`IndiceSecciones.tsx:47`, `:56`, `:119-125`) | **BOTÓN FANTASMA (F)** |
| Botón "Agendar" del encabezado del expediente | `POST /agenda/citas/` = O A D R (`permissions.py:193`) | los 7, y además **sin `onClick`** (`ExpedienteDrawer.tsx:211-215`) | **BOTÓN FANTASMA** |
| Estado de cuenta del paciente | O A F R L siempre; D si `doctors_see_costs` (`permissions.py:502-528`; contrato:381) | idéntico (`auth/permisos.ts:208-215`; `ExpedienteDrawer.tsx:96`, `:204`, `:318-320`; `IndiceSecciones.tsx:46`) | ALINEADO |

---

### Hallazgos

### F-1A-01 · "Dar de baja" se ofrece al médico y a recepción; el backend solo deja a dueño y administrador
**Severidad:** P1
**Backend:** `apps/core/permissions.py:158` — `PatientPermission.policy["DELETE"] = MANAGE_ROLES` (owner y admin). Contrato:1151 y matriz contrato:1444: D, N, R, F, L reciben 403.
**Frontend:** `components/contactos/ExpedienteDrawer.tsx:225-232` — el botón se pinta con `puedeEditar && paciente.is_active`, y `puedeEditar` llega desde `pages/ContactosPage.tsx:94` (`puedeEditar(role,'contactos')`), que es `edit` para owner, admin, **doctor y reception** (`auth/permisos.ts:105-109`).
**Qué ve el usuario:** la recepcionista abre el expediente de un paciente activo, ve "Dar de baja" en rojo junto a la foto, confirma en el diálogo ("¿Dar de baja a Ana López? Dejará de aparecer en la lista") y recibe un error genérico; el paciente sigue en la lista. Igual para un médico. Es la clase de fallo que genera una llamada a soporte por paciente.
**Clase:** botón fantasma

### F-1A-02 · Enfermería no puede tocar el directorio de pacientes aunque el backend se lo permite
**Severidad:** P2
**Backend:** `apps/core/permissions.py:156-157` — `POST` y `PATCH` de `PatientPermission` incluyen `Role.NURSE`. Contrato:1147-1154 y matriz contrato:1437-1442: alta, alta rápida, edición, etiquetas, favorito/VIP y foto están abiertos a enfermería.
**Frontend:** `auth/permisos.ts:108` — `nurse: { contactos: 'view' }`, así que `puedeEditar(role,'contactos')` es `false` (`pages/ContactosPage.tsx:94`) y se apagan a la vez: "Nuevo paciente" (`ContactosPage.tsx:182-189`), estrella/corona (`:389-402`, `:430-443`), `EtiquetasQuickMenu` (`:403-405`, `:444-446`), el botón "Editar" de la ficha (`components/expediente/FichaPaciente.tsx:264-272`) y la carga de foto (`ExpedienteDrawer.tsx:188`).
**Qué ve el usuario:** la enfermera hace el ingreso de un paciente provisional creado desde la agenda (sin fecha de nacimiento ni sexo), toma los signos, y no encuentra ningún botón para completar la ficha; la bandera `is_provisional` solo se apaga con un PATCH que el backend le permite y la UI no le ofrece (`apps/pacientes/services.py:346-348`, contrato:1344). Tiene que pedírselo a un médico o a recepción.
**Clase:** función invisible

### F-1A-03 · Las alergias, abiertas a los 7 roles a propósito, se esconden a recepción y a finanzas
**Severidad:** P1
**Backend:** `apps/core/permissions.py:689-690` — `AllergyPermission.policy["GET"] = ALL_ROLES`, con el motivo escrito en el docstring (`:678-680`): *bandera de seguridad que cualquier miembro debe poder ver*. Contrato:358, 2736 y matriz contrato:3144 (los 7 con ✔).
**Frontend:** `components/expediente/FichaPaciente.tsx:90` — `{verClinico && <AlergiasBlock …>}`; `verClinico` es `accesoClinico` (`ExpedienteDrawer.tsx:87`) = `puedeVerExpedienteClinico(role)`, que es `false` para reception y finance (`auth/permisos.ts:109-110`, `:117`).
**Qué ve el usuario:** la recepcionista abre el expediente de un paciente que llama preguntando si puede tomar el antibiótico que le mandaron y no ve el bloque rojo "Alergias (2) · Penicilina"; el backend se lo habría devuelto. La decisión de seguridad tomada en el backend no llega a la única persona que atiende el teléfono. Recepción y finanzas son precisamente los dos roles que no tienen ninguna otra pantalla clínica donde consultarlo.
**Clase:** función invisible

### F-1A-04 · Enfermería no puede registrar ni resolver alergias
**Severidad:** P1
**Backend:** `apps/core/permissions.py:691` y `:693` — `POST` y `DELETE` de `AllergyPermission` incluyen `Role.NURSE`; el docstring lo llama "personal clínico y directivo" (`:684`). Contrato:3145-3146.
**Frontend:** `components/expediente/FichaPaciente.tsx:511-518` (botón "Agregar") y `:547-560` (botón "Resolver") dependen de `puedeEditar`, que es `puedeEditarClinico` (`ExpedienteDrawer.tsx:88`, `:257`) = O A D (`auth/permisos.ts:123-124`). Enfermería queda fuera.
**Qué ve el usuario:** la enfermera hace el interrogatorio de ingreso, el paciente le dice que es alérgico a la penicilina, y en el bloque de Alergias no hay botón "Agregar": solo la lista. La captura de signos de la misma pantalla sí la tiene (`VisitaDeHoy.tsx:95-99`), así que la ausencia parece un fallo del sistema. El dato se queda sin registrar o se registra tarde, cuando pasa el médico.
**Clase:** función invisible

### F-1A-05 · El addendum, único canal de corrección de una nota firmada, no tiene ninguna pantalla alcanzable
**Severidad:** P0
**Backend:** `apps/core/permissions.py:891-893` — `AddendumPermission` permite `POST` a owner, admin y doctor. Contrato:3077 ("Corrección solo por addendum", `services.py:815-888`) y contrato:3154. La nota de evolución nace bloqueada por *CheckConstraint* en la base (`models.py:611-614`, contrato:3071) y no tiene PATCH, PUT ni DELETE (contrato:3072): el addendum es la **única** vía de corrección que existe.
**Frontend:** el formulario de addendum existe en `components/expediente/EvolucionTab.tsx:274-296` (`useCreateAddendum` en `:184`, `:198`), pero **`EvolucionTab` no lo importa ningún archivo de `src/`** (verificado con `grep -rn "EvolucionTab" src/`: solo aparece dentro del propio archivo y en comentarios de `EvolucionSoapStepper.tsx:5` y `LibroClinico.tsx:922`). `ExpedienteDrawer.tsx:301-303` rutea la sección "libro" a `LibroClinico`, que **muestra** los addenda existentes (`LibroClinico.tsx:847-852`) pero no ofrece crearlos.
**Qué ve el usuario:** un médico escribe la nota de la consulta y se da cuenta al día siguiente de que puso "niega alergias" en el paciente equivocado. Abre el libro clínico, ve el capítulo bloqueado, ve que otras notas tienen addenda pintados… y no hay ningún botón para agregar el suyo. La corrección que la NOM-004 exige por addendum no se puede hacer desde el producto; el error queda fijo en el expediente.
**Clase:** función invisible

### F-1A-06 · El selector de citas de la evolución ofrece las citas de los demás médicos
**Severidad:** P1
**Backend:** `apps/expediente/services.py:699-709` — con `actor_role == "doctor"` compara `appointment.doctor.membership.user_id` con `user.pk` y responde 400 "Un médico solo puede crear notas de evolución sobre sus propias citas". El `actor_role` llega de verdad desde HTTP (`apps/expediente/views_evoluciones.py:226`, `:240`), así que la regla está viva. Contrato:3076 y matriz contrato:3152 (celda **propio**).
**Frontend:** `components/expediente/EvolucionSoapStepper.tsx:154-157` filtra **solo** por `status === 'attended'`; el `<select>` de `:253-260` lista todas esas citas e incluso imprime `c.doctor.full_name` — es decir, el frontend sabe que la cita es de otro médico y aun así la ofrece.
**Qué ve el usuario:** el Dr. Pérez abre "Visita de hoy → Escribir evolución" de un paciente compartido, elige en el desplegable "12 ago 10:00 · Dra. Ruiz" porque es la última atendida, recorre los cuatro pasos S-O-A-P escribiendo la nota completa y, al guardar, recibe el 400. El texto no se pierde (hay borrador local, `:125-129`), pero el trabajo sí.
**Clase:** botón fantasma

### F-1A-07 · "Resumen clínico" se ofrece sobre los capítulos escritos por otro médico
**Severidad:** P1
**Backend:** `apps/expediente/services_resumen.py:405-415` — con `actor_role == "doctor"`, si el médico de la evolución no es el usuario, 400 "Un médico solo puede generar el resumen clínico de sus propias consultas". `actor_role` real en `apps/expediente/views_resumen.py:131`, `:138`. Contrato:3080 y matriz contrato:3163 (celda **propio**). El **borrador** (GET) no aplica esa regla (contrato:2905, 2910): carga sin problema.
**Frontend:** `components/expediente/LibroClinico.tsx:710` calcula `puedeResumen` solo por rol (O A D) y `:735-745` pinta el botón en la cabecera de **cada capítulo**, aunque el capítulo lleve arriba el nombre de otro médico (`:733`).
**Qué ve el usuario:** el Dr. Pérez hojea el libro clínico de un paciente, encuentra la consulta de la Dra. Ruiz de la semana pasada, pulsa "Resumen clínico", el modal carga el borrador auto-rellenado con todo el texto clínico, lo edita, pulsa "Generar" y recibe el 400. La constancia que el paciente está esperando en la sala no sale.
**Clase:** botón fantasma

### F-1A-08 · "Quitar de agenda" y "Reagendar" se ofrecen sobre sesiones cuya cita es de otro médico
**Severidad:** P1
**Backend:** `apps/expediente/services_calendarizacion.py:201-206` — con `actor_role == "doctor"`, si `appointment.doctor_id != caller_doctor.id`, 400 "Como médico, solo puedes cancelar o mover tus propias citas". La misma función se invoca desde el PUT de reemplazo del esquema (`:322-331` y `:595-605`), así que también revienta al *guardar* un plan del que se quitó una sesión. `actor_role` real en `apps/expediente/views_calendarizacion.py:270`, `:494`. Contrato:3081, 3171 y contrato:3273.
**Frontend:** `components/expediente/CalendarizacionTab.tsx:1116-1131` — los botones "Reagendar" y "Quitar de agenda" se pintan siempre que la sesión tenga cita, y en la misma línea (`:1113`) se muestra `appt.doctor_name`. El componente sí aplica pertenencia al **crear** (`:295`, `:314`, `:736-740` fijan al médico en sí mismo), pero no a las citas ya existentes.
**Qué ve el usuario:** el Dr. Pérez abre la calendarización de un paciente que también atiende la Dra. Ruiz, ve la sesión 3 marcada "Agendada · 14 ago 11:00 · Dra. Ruiz", pulsa "Quitar de agenda" y recibe el 400. Peor variante: borra una línea de tratamiento cuyas sesiones tenían cita con la otra doctora y **todo el guardado del esquema** falla, sin que la pantalla explique qué línea lo provoca.
**Clase:** botón fantasma

### F-1A-09 · El expediente pide la configuración de la clínica a recepción y a finanzas, que reciben 403
**Severidad:** P2
**Backend:** `apps/clinica/permissions.py:37-38` — `ClinicSettingsPermission.policy["GET"] = CLINICAL_READ` (owner, admin, doctor, nurse, readonly). Recepción y finanzas → 403 (contrato:413).
**Frontend:** `components/contactos/ExpedienteDrawer.tsx:94` — `const clinicSettings = useClinicSettings()` se ejecuta al montar el drawer para cualquier rol; el hook no tiene `enabled` (`hooks/clinica.ts:60-65`).
**Qué ve el usuario:** nada en pantalla, pero cada apertura de un expediente por parte de recepción o de finanzas deja un 403 en la consola y en los logs del backend. Ensucia el diagnóstico de incidentes reales y consume una petición por apertura. El valor que se buscaba (`doctors_see_costs`) solo lo necesita el rol `doctor`, que sí tiene permiso.
**Clase:** botón fantasma

### F-1A-10 · Finanzas ve la sección "Citas" y "Próxima consulta", y el 403 se pinta como "sin citas"
**Severidad:** P1
**Backend:** `apps/core/permissions.py:192` — `AppointmentPermission.policy["GET"] = APPOINTMENT_VIEW_ROLES`, definido en `:75-77` **sin** `Role.FINANCE`, con el comentario explícito de que finanzas no debe ver contenido de agenda. Contrato:341.
**Frontend:** dos puntos. (1) `components/expediente/FichaPaciente.tsx:339` llama `useAppointmentsForPatient(patientId)` sin condición para todo rol que abra el drawer; ante el 403, `data` queda `undefined` y `:367` imprime "Sin cita próxima.". (2) `components/expediente/IndiceSecciones.tsx:47` calcula `verCitas = tieneModulo('agenda')` **solo por módulo, sin rol**, dispara la query en `:56` y ofrece la sección en `:119-125`; `components/expediente/CitasSection.tsx:20` repite la llamada y `:43` / `:51` imprimen "Sin cita próxima." y "Sin citas registradas todavía.".
**Qué ve el usuario:** el usuario de finanzas abre el expediente de un paciente para cobrarle, entra a "Citas" y lee "Sin citas registradas todavía" en un paciente con doce citas atendidas. No es una pantalla vacía: es una afirmación falsa producida por un 403 que la UI no distingue de una lista vacía. Si de ahí sale una decisión de cobro o de reagenda, el dato es simplemente incorrecto.
**Clase:** botón fantasma

### F-1A-11 · El botón "Agendar" del encabezado del expediente no consulta el rol ni tiene manejador
**Severidad:** P2
**Backend:** `apps/core/permissions.py:193` — `POST` de `AppointmentPermission` = owner, admin, doctor, reception; enfermería, finanzas y solo-lectura reciben 403 (contrato:341).
**Frontend:** `components/contactos/ExpedienteDrawer.tsx:211-215` — `<button className="btn-primary">Agendar</button>` sin `onClick` y sin ninguna comprobación de rol, mientras que los botones vecinos sí la tienen (`:216` `puedeVerPlanIntegral`, `:225` `puedeEditar`). El helper `puedeAgendar` existe (`auth/permisos.ts:133-134`) y se usa en la lista (`pages/ContactosPage.tsx:95`), pero no aquí.
**Qué ve el usuario:** cualquiera de los 7 roles ve el botón dorado principal del expediente y al pulsarlo no ocurre absolutamente nada. Para enfermería, finanzas y solo-lectura es además una acción que el backend nunca les habría permitido.
**Clase:** botón fantasma

### F-1A-12 · Las imágenes de una nota solo se pueden adjuntar o quitar en los segundos posteriores a crearla
**Severidad:** P2
**Backend:** `apps/core/permissions.py:765-766` — `POST` y `DELETE` de imágenes de evolución = owner, admin, doctor, **sin restricción temporal**; el contrato lo documenta como decisión consciente (contrato:3084, B-EXP-07: "las imágenes de la nota firmada siguen siendo mutables"), con tope de 20 por nota (contrato:2868).
**Frontend:** los tres hooks (`useEvolutionImages`, `useUploadEvolutionImage`, `useDeleteEvolutionImage`) solo se montan en `components/expediente/EvolucionSoapStepper.tsx:628-630`, dentro de la pantalla de éxito que aparece justo después de guardar la nota. La otra galería editable vive en `EvolucionTab.tsx:328-330`, componente huérfano (ver F-1A-05). En el libro clínico las imágenes son de solo lectura.
**Qué ve el usuario:** el médico guarda la nota, cierra el paso sin adjuntar la foto de la lesión porque aún no la tenía en el equipo, y al volver una hora después no encuentra por dónde subirla. La única salida es crear otra nota — imposible, porque hay una sola nota por cita (contrato:3073).
**Clase:** función invisible

### F-1A-13 · Los listados de constancias emitidas (resúmenes clínicos y planes integrales) no tienen pantalla
**Severidad:** P2
**Backend:** `apps/core/permissions.py:790` (`ClinicalSummaryPermission` GET = O A D) y `:838` (`LongevityPlanPermission` GET = O A D). Endpoints `GET /expediente/<patient_id>/resumenes/` (contrato:2908) y `GET /expediente/<patient_id>/plan-integral/` (contrato:2931), ambos paginados y con su PDF por id (contrato:2907, 2933).
**Frontend:** `hooks/expediente.ts:376` (`useResumenesClinicos`) y `hooks/planIntegral.ts:59` (`usePlanesIntegrales`) están escritos y tipados pero **ningún componente los llama** (verificado por búsqueda en todo `src/`). El único momento en que se ve una constancia es el modal que la acaba de generar.
**Qué ve el usuario:** el paciente vuelve y pide otra copia del resumen que se le entregó el mes pasado. El médico no tiene dónde buscarlo: la única forma de volver a imprimirlo es generar una constancia nueva, lo que **crea un segundo registro** de un documento que el backend trata como append-only (contrato:2920).
**Clase:** función invisible

### F-1A-14 · Dos endpoints de pacientes tienen permiso y cliente pero ningún botón
**Severidad:** P2
**Backend:** `POST /pacientes/rapido/` — `apps/core/permissions.py:156`, abierto a O A D N R (contrato:1148, 1438). `DELETE /pacientes/<id>/avatar/` — `permissions.py:158`, abierto a O A (contrato:1153, 1443; el propio contrato lo marca como endpoint sin consumidor en B-PAC-08, contrato:1156-1158).
**Frontend:** `api/pacientes.ts:79` y `hooks/pacientes.ts:82` definen `createPatientQuick`/`useCreatePatientQuick` y **nada los invoca** (la agenda crea el provisional dentro del payload de la cita, `components/agenda/CrearEventoModal.tsx:382-383`, que pasa por `AppointmentPermission` y deja a enfermería fuera). Para quitar la foto no hay ni función en `api/pacientes.ts` ni botón en `components/common/AvatarUploader.tsx:54-70`: solo se puede reemplazar.
**Qué ve el usuario:** el dueño sube por error la foto de otro paciente y no encuentra cómo borrarla; solo puede sustituirla por otra imagen. Y la única puerta de alta rápida queda condicionada al permiso de agenda, no al de pacientes, lo que cierra esa vía a enfermería por partida doble.
**Clase:** función invisible

### F-1A-15 · Queda en el árbol un hook de rol que cae a `owner` por defecto
> **Consolidado en `F-5-01`.** El mismo defecto lo encontró otro cruce con un escenario mejor. Se conserva aquí la evidencia porque el ángulo es distinto, pero **no cuenta como hallazgo aparte** en el total del resumen.
**Severidad:** P2
**Backend:** `apps/core/permissions.py:129-131` — `active_role is None` → `False`; el backend nunca concede un rol por omisión (fail-closed, contrato:329, 332).
**Frontend:** `auth/useRole.ts:18` — `const DEFAULT_ROLE: Role = 'owner'`; `:30-38` lee primero `getActiveRole()` de `lib/tokenStore.ts:46` y, si es nulo, un `localStorage['maily_demo_role']` y, si tampoco, devuelve `'owner'`. **Hoy no muerde**: ningún archivo importa `auth/useRole.ts` (todo consume `auth/RoleContext.tsx:20`, que cae a `'readonly'` en `:15`) y `setActiveRole` (`tokenStore.ts:50`) no se llama nunca, así que `getActiveRole()` siempre devuelve `null`.
**Qué ve el usuario:** nada, hoy. La consecuencia es futura y concreta: el primer componente que importe `useRole` desde `auth/useRole` en vez de `auth/RoleContext` mostrará la UI completa de dueño a cualquiera —incluido un usuario con `readonly`— y el conflicto solo aparecerá al primer 403. El comentario del archivo (`:2-10`) lo declara como andamio de la demo previa al login real.
**Clase:** botón fantasma (latente)

---

### NO VERIFICABLE

1. **Si `queryClient` conserva alergias o expediente al cambiar de clínica en la misma pestaña.**
   Las claves de expediente son `['expediente', patientId, …]` (`hooks/expediente.ts:52-76`) sin tenant.
   Hay `queryClient.clear()` en login (`AuthContext.tsx:110`) y en logout (`:129`), lo que parece
   cubrirlo. Falta: es Cruce 3, no Cruce 1, y exige recorrer el cambio de sede además del de sesión.
2. **Si el 403 de `GET /clinica/configuracion/` (F-1A-09) degrada algo más que ruido.**
   `hooks/clinica.ts:60-65` no define `retry`, y no leí la configuración global del `QueryClient`.
   Falta: revisar `lib/queryClient.ts` para saber si TanStack reintenta el 403 y multiplica las
   peticiones fallidas.
3. **Si el módulo `expediente` apagado deja a recepción/finanzas sin alergias por 404 en vez de por
   el gate del frontend.** El guard `RequiresExpediente` cubre la ruta de alergias (contrato:2731) y
   devuelve 404. Falta: cruzar `lib/modulos.ts` con `apps/core/modules.py` — es Cruce 2.
4. **Si `EvolucionTab.tsx` está en el árbol a propósito** (pantalla en pausa) **o es residuo de la
   migración al stepper.** La evidencia de que está huérfano es firme; la intención no. Falta:
   preguntarle al autor, o revisar el historial de git del commit que introdujo `VisitaDeHoy`.
5. **Si el `doctor_id` que el frontend fija en calendarización (`user.doctor_id`) coincide siempre
   con el `Doctor` que resuelve el backend** (`doctor_get_for_user`, `services_calendarizacion.py:203`).
   Falta: leer `apps/authn` / `/me/` para confirmar de dónde sale `doctor_id` y qué pasa con un
   médico con dos perfiles o sin perfil.

---

### Defectos del contrato detectados

**Ninguno en el alcance auditado.** Las 50 clases de §1.3, la matriz de §2.4 y la de §4.4 coinciden
con `apps/core/permissions.py` y con los tres services de pertenencia en todo lo que verifiqué.

Una nota que va en dirección contraria y conviene dejar escrita: el **docstring del backend está mal
y el contrato tiene razón**. `apps/core/permissions.py:748-750` afirma que un PATCH o PUT sobre una
nota de evolución produce "405 (método no ruteado)"; el mecanismo real de `HasClinicRole.has_permission`
(`permissions.py:133-135`: método no declarado en la `policy` → `frozenset()` → `False`) responde
**403**, que es exactamente lo que documentan contrato:361 y contrato:3072. Si alguien escribe el
manejo de errores del frontend guiándose por ese docstring, la rama de 405 no se disparará jamás.

---

## Cruce 1B · Agenda, notas y notificaciones

Roles: **O** owner · **A** admin · **D** doctor · **N** nurse · **R** reception · **F** finance ·
**L** readonly. Backend = `MailySoft/backend/`. Frontend = `MailySoft/web-soft/src/`.
El orden de `permission_classes` importa: el permiso de rol va **antes** del guard de módulo
(`apps/agenda/views.py:159`), así que un rol negado recibe 403 aunque falte el módulo.

### Tabla de cruce

| Acción | Roles que permite el backend (archivo:línea) | Roles a los que el front la muestra (archivo:línea) | Veredicto |
|---|---|---|---|
| Ver listado de citas · `GET /agenda/citas/` | O A D N R L — `apps/core/permissions.py:76-78`, `:191-192`; contrato:341, :1751 | los 7: cualquiera que entre a `/agenda` — `auth/permisos.ts:105-111`, `components/Topbar.tsx:44-46`, `pages/AgendaPage.tsx:252` | **BOTÓN FANTASMA** (F-1B-01) |
| Ver la rejilla **completa** de la clínica | todas las citas del alcance de sede para O A D N R L — `apps/core/permissions.py:191-192` | solo las del `doctor_id` del usuario si lo tiene — `pages/AgendaPage.tsx:239`, `:273`, `:265-270`, `:276` | **FUNCIÓN INVISIBLE** (F-1B-03) |
| Ver detalle de cita por id · `GET /agenda/citas/<id>/` | O A D N R L — contrato:1755 | nadie: no existe la función en `api/agenda.ts` (el detalle sale del listado, `pages/AgendaPage.tsx:314`) | FUNCIÓN INVISIBLE (sin impacto) |
| Ver disponibilidad · `GET /agenda/disponibilidad/` | O A D N R L — contrato:1754 | O A D R: solo dentro del modal de agendar — `components/agenda/CrearEventoModal.tsx:301-310` | FUNCIÓN INVISIBLE (sin impacto) |
| Crear cita · `POST /agenda/citas/` | O A D R; D **solo para sí mismo** — `apps/core/permissions.py:193`; `apps/agenda/services.py:417-425` | O A D R — `auth/permisos.ts:133-134`, `pages/AgendaPage.tsx:235`, `:294`; el bloqueo "solo para mí" se aplica por **perfil médico**, no por rol — `components/agenda/CrearEventoModal.tsx:202`, `:611-621` | **FUNCIÓN INVISIBLE** (F-1B-04) |
| Crear cita desde Contactos ("Volver a agendar") | O A D R — `apps/core/permissions.py:193` | O A D **N** R — `pages/ContactosPage.tsx:95`, `:408`, `:492`, `:518`; el modal no tiene gate propio (`components/agenda/CrearEventoModal.tsx:1-16`, cero imports de rol) | **BOTÓN FANTASMA** (F-1B-11) |
| Crear serie · `POST /agenda/citas/serie/` | O A D R, misma regla del médico — contrato:1753 | O A D R — `components/agenda/CrearEventoModal.tsx:186`, `:303` | FUNCIÓN INVISIBLE (F-1B-04, misma causa) |
| Editar cita (`reason`/`specialty`/`notes`) · `PATCH /agenda/citas/<id>/` | O A D R — `apps/core/permissions.py:194`; contrato:1756, :2222 | nadie: no existe la función en `api/agenda.ts`; el modal los pinta como texto — `components/agenda/DetalleCitaModal.tsx:254-261` | **FUNCIÓN INVISIBLE** (F-1B-08) |
| Cancelar por `DELETE /agenda/citas/<id>/` | O A R — `apps/core/permissions.py:195`; contrato:1757, :2225 | nadie: no existe la función en `api/agenda.ts` | FUNCIÓN INVISIBLE (sin impacto: se cancela por `POST /estado/`) |
| Cancelar por `POST /agenda/citas/<id>/estado/` | O A D R (permiso O A D N R + veto explícito a N) — `apps/core/permissions.py:208-210`, `apps/agenda/views.py:594-603` | O A D R — `auth/permisos.ts:140-141`, `components/agenda/DetalleCitaModal.tsx:357-362` | ALINEADO |
| Enviar el **motivo** de cancelación | el endpoint acepta `reason` — `apps/agenda/views.py:585-587`; contrato:1963 | nunca se envía — `api/agenda.ts:145-153`, `pages/AgendaPage.tsx:346-347`, `components/agenda/AlertaCitas.tsx:112-114` | **FUNCIÓN INVISIBLE** (F-1B-09) |
| Otros cambios de estado (confirmar, en sala, en consulta, atendida, no asistió) | O A D N R — `apps/core/permissions.py:208-210` | O A D N R — `auth/permisos.ts:136-137`, `components/agenda/DetalleCitaModal.tsx:364`, `:380` | ALINEADO |
| Reagendar · `POST /agenda/citas/<id>/reagendar/` | O A D R — `apps/core/permissions.py:193`; contrato:1759 | O A D R — `pages/AgendaPage.tsx:811`, `components/agenda/DetalleCitaModal.tsx:334`, `:373` | ALINEADO |
| Reactivar · `POST /agenda/citas/<id>/reactivar/` | O A D R — contrato:1760 | O A D R — `pages/AgendaPage.tsx:810`, `components/agenda/DetalleCitaModal.tsx:341` | ALINEADO |
| Ver config de agenda · `GET /agenda/config/` | los 7 — `apps/core/permissions.py:266`; contrato:345 | los 7 que entren a `/agenda` — `pages/AgendaPage.tsx:109`, `hooks/agendaConfig.ts:16-23` | ALINEADO |
| Editar config de agenda · `PATCH /agenda/config/` | O A — `apps/core/permissions.py:266` | O A — `pages/MiConsultorioPage.tsx:59`, `:77`; `auth/permisos.ts:156-157` | ALINEADO |
| Ver tipos de cita · `GET /agenda/tipos-cita/` | los 7 — `apps/core/permissions.py:242` | O A D R (modal de agendar, `components/agenda/CrearEventoModal.tsx:184`) + O A L (`pages/PersonalPage.tsx:25`, `:130`) | FUNCIÓN INVISIBLE (sin impacto: N y F no tienen pantalla que los use) |
| Crear/editar/desactivar tipo de cita | O A — `apps/core/permissions.py:242` | O A — `pages/PersonalPage.tsx:22`, `:130` (`editar = puedeEditar(role,'personal')`) | ALINEADO |
| Ver eventos · `GET /agenda/eventos/` | O A D N R L — contrato:1767 | los 7 en `/agenda` — `pages/AgendaPage.tsx:254` | **BOTÓN FANTASMA** (F-1B-01, misma causa) |
| Crear evento (bloqueo/reunión) · `POST /agenda/eventos/` | O A D R — contrato:1768, :2233 | O A D R desde la rejilla — `pages/AgendaPage.tsx:294`, `components/agenda/CrearEventoModal.tsx:508-510`; **O A D N R** desde Contactos — `pages/ContactosPage.tsx:95` | **BOTÓN FANTASMA** (F-1B-11) |
| Editar evento · `PATCH /agenda/eventos/<id>/` | O A D R — contrato:1769, :2234 | O A D R — `pages/AgendaPage.tsx:819`, `components/agenda/EventoDetalleModal.tsx:155-159` | ALINEADO |
| Borrar evento · `DELETE /agenda/eventos/<id>/` | O A R — `apps/core/permissions.py:195`; contrato:1770, :2235 | O A **D** R — `pages/AgendaPage.tsx:819`, `components/agenda/EventoDetalleModal.tsx:135`, `:151-154` | **BOTÓN FANTASMA** (F-1B-02) |
| Ver hilo de notas de cita/evento | O A D N R L — `apps/core/permissions.py:628-631` | quien abra el modal — `components/agenda/NotasHilo.tsx:27`, montado en `DetalleCitaModal.tsx:323` y `EventoDetalleModal.tsx:131` | ALINEADO |
| Agregar nota al hilo | O A D N R — `apps/core/permissions.py:632` | O A D N R — `components/agenda/NotasHilo.tsx:23`, `:82` (`puedeEditar(role,'agenda')`) | ALINEADO |
| Borrar nota del hilo · `DELETE /agenda/notas/<id>/` | permiso O A D N R + service: autor u O/A — `apps/agenda/notes.py:32-34`, `:206-223` | autor u O/A — `components/agenda/NotasHilo.tsx:53`, `:70` | ALINEADO |
| Ver notas · `GET /notas/` | los 7 — `apps/core/permissions.py:638`, `:655-660` | los 7 — `auth/permisos.ts:105-111` (`notas:'edit'`), `pages/NotasPage.tsx:35` | ALINEADO |
| Crear nota personal · `POST /notas/` `scope=personal` | los 7 — `apps/notas/services.py:343-345` | los 7 — `components/notas/NuevaNotaModal.tsx:44`, `:71-95` | ALINEADO |
| Crear aviso a un rol · `scope=role` | O A D N R — `apps/notificaciones/recipients.py:32-34`, `apps/notas/services.py:323-326`; contrato:6729 | **O A** — `components/notas/NuevaNotaModal.tsx:34`, `:148` | **FUNCIÓN INVISIBLE** (F-1B-05) |
| Dirigir un aviso **al dueño** (`target_role='owner'`) | permitido — `apps/notas/services.py:68-75`, `:332` | excluido del selector — `components/notas/NuevaNotaModal.tsx:158` | **FUNCIÓN INVISIBLE** (F-1B-10) |
| Crear aviso a toda la clínica · `scope=all` | O A — `apps/notas/services.py:106-108`, `:314-322` | O A — `components/notas/NuevaNotaModal.tsx:34`, `:153` | ALINEADO |
| Marcar un aviso como importante | solo O — `apps/notas/services.py:219-220` | solo O — `components/notas/NuevaNotaModal.tsx:163-172`, `:86-88` | ALINEADO |
| Elegir la sede del aviso | solo O — `apps/notas/services.py:211-228` | solo O — `components/notas/NuevaNotaModal.tsx:163-169`, `:86-88`, `:177-181` | ALINEADO |
| Editar/borrar nota propia · `PATCH`/`DELETE /notas/<id>/` | el autor — `apps/notas/services.py:150-151` | el autor — `pages/NotasPage.tsx:94-95`, `components/notas/NotaCard.tsx:92-103` | ALINEADO |
| Editar/borrar **aviso ajeno** (`role`/`all`) | el owner (supervisión) — `apps/notas/services.py:162-163`; contrato:6734, :6740 | nadie — `pages/NotasPage.tsx:45`, `:114-115` | **FUNCIÓN INVISIBLE** (F-1B-06) |
| Cambiar el `scope` de una nota propia | O A D N R (a `role`) / O A (a `all`) — `apps/notas/services.py:522-535`; contrato:6736-6737 | nadie: el bloque de alcance se oculta al editar — `components/notas/NuevaNotaModal.tsx:148` (`puedeAvisar && !esEdicion`) | FUNCIÓN INVISIBLE (F-1B-05, misma causa) |
| Marcar tarea hecha · `POST /notas/<id>/done/` (pantalla Notas) | **solo el autor** — `apps/notas/services.py:595-596` | solo las propias — `pages/NotasPage.tsx:95`, `:114` (globales sin `onToggleDone`), `components/notas/NotaCard.tsx:110-114` | ALINEADO |
| Marcar tarea hecha (widget de recordatorios) | **solo el autor** — `apps/notas/services.py:595-596` | cualquier tarea visible, incluidos los avisos ajenos — `components/agenda/RecordatoriosWidget.tsx:42-47`, `:55` | **BOTÓN FANTASMA** (F-1B-07) |
| Ver mis recordatorios · `GET /notas/recordatorios/` | los 7 — `apps/core/permissions.py:655` | los 7 — `components/agenda/RecordatoriosWidget.tsx:14`, `components/agenda/LuzRecordatorios.tsx:46` | ALINEADO |
| Listar notificaciones · `GET /notificaciones/` | los 7, solo las propias — `apps/core/permissions.py:1060`; contrato:7044-7046 | los 7, sin gate — `components/Topbar.tsx:103`, `components/CampanaNotificaciones.tsx:63` | ALINEADO |
| Contar no leídas · `GET /notificaciones/conteo/` | los 7 — contrato:7032-7040 | los 7 — `components/CampanaNotificaciones.tsx:62`, `hooks/notificaciones.ts:17-25` | ALINEADO |
| Marcar todas leídas · `POST /notificaciones/leidas/` | los 7 — contrato:7032-7040 | los 7 — `components/CampanaNotificaciones.tsx:112` | ALINEADO |
| Marcar una leída · `POST /notificaciones/<id>/leida/` | los 7, solo las propias — contrato:6959-6964 | los 7, solo las de su propia lista — `components/CampanaNotificaciones.tsx:71` | ALINEADO |
| Crear/editar/borrar notificación por API | no existe; `PUT`/`PATCH`/`DELETE` → 403 — contrato:7048-7050 | el front no lo intenta — `api/notificaciones.ts` (solo GET y POST) | ALINEADO |

---

### Hallazgos

### F-1B-01 · `finance` tiene la Agenda en el menú y la pantalla se rompe con 403
**Severidad:** P1
**Backend:** `MailySoft/backend/apps/core/permissions.py:76-78` define `APPOINTMENT_VIEW_ROLES` **sin** `finance` y `:191-192` lo usa como `policy["GET"]`; `apps/agenda/views.py:159` y `:899` aplican `AppointmentPermission` **antes** que `RequiresAgenda`, así que la negación es 403. Contrato:341, :2242-2244.
**Frontend:** `MailySoft/web-soft/src/auth/permisos.ts:110` le da a `finance` `agenda: 'view'`; `components/Topbar.tsx:44-46` pinta la pestaña "Agenda" porque `accesoModulo` devuelve un valor truthy; `App.tsx:47` deja entrar por la misma razón; `pages/AgendaPage.tsx:252` y `:254` disparan `GET /agenda/citas/` y `GET /agenda/eventos/` sin mirar el rol.
**Qué ve el usuario:** la persona de facturación (rol `finance`) ve "Agenda" en la barra superior junto a Finanzas. Al pulsarla, el encabezado del día, el calendario, "Mis recordatorios" y las columnas de consultorios **sí** cargan (esos endpoints la admiten), pero el cuerpo de la rejilla queda con "No se pudieron cargar las citas." (`pages/AgendaPage.tsx:518-520`) y sin ningún evento. Media pantalla funciona y media no: parece un error del sistema, no una restricción.
**Clase:** botón fantasma

### F-1B-02 · El médico ve "Eliminar" en un evento de agenda y el backend responde 403
**Severidad:** P1
**Backend:** `MailySoft/backend/apps/core/permissions.py:195` — `AppointmentPermission.policy["DELETE"] = {owner, admin, reception}`, sin `doctor`; `apps/agenda/views.py:971` aplica esa clase al `DELETE /agenda/eventos/<id>/`. Contrato:1770, :2235, :2248-2249.
**Frontend:** `MailySoft/web-soft/src/auth/permisos.ts:133-134` — `puedeAgendar` incluye `doctor`; `pages/AgendaPage.tsx:819` pasa `soloLectura={!agendar}`, así que para un médico es `false`; `components/agenda/EventoDetalleModal.tsx:135` monta la barra de acciones y `:151-154` pinta el botón "Eliminar", que llama a `:60-63`.
**Qué ve el usuario:** un médico crea el bloqueo "Vacaciones — semana del 20" desde su agenda (el `POST` sí lo admite: `permissions.py:193`). Al querer quitarlo abre el evento, pulsa "Eliminar", confirma "Sí, eliminar" y recibe el texto genérico "No se pudo guardar." (`EventoDetalleModal.tsx:62`) mientras el bloqueo sigue en la rejilla. El médico puede crear eventos que después no puede borrar, y el mensaje no dice por qué.
**Clase:** botón fantasma

### F-1B-03 · El dueño que también consulta solo ve sus propias citas en la rejilla
**Severidad:** P1
**Backend:** `MailySoft/backend/apps/agenda/services.py:417-425` — la regla "solo puedes agendar para ti" se dispara **únicamente** si `caller_role == Role.DOCTOR`; `apps/personal/services.py:38-44` (`ROLES_QUE_PUEDEN_EJERCER`) permite que `owner` y `admin` tengan perfil de médico, y `apps/authn/views.py:391-409` les devuelve `doctor_id` en `/me/` precisamente por eso. El `GET /agenda/citas/` no filtra por médico: devuelve todas las del alcance de sede (contrato:2219-2220).
**Frontend:** `MailySoft/web-soft/src/pages/AgendaPage.tsx:239` define `soyDoctor = !!user?.doctor_id` **sin mirar el rol**; `:273` filtra las citas a las del `doctor_id`; `:265-270` filtra los eventos; `:276` recorta las columnas a los consultorios asignados a ese médico.
**Qué ve el usuario:** la dueña de una clínica con dos médicos también atiende pacientes, así que tiene perfil de médico. Abre `/agenda` un martes con 14 citas en la clínica y ve 3 (las suyas). Las columnas de los consultorios de sus colegas desaparecen del tablero y el contador del encabezado dice "3 citas". No hay ningún interruptor en la UI para ver la agenda completa: el backend le mandó las 14 en esa misma respuesta y el navegador descartó 11.
**Clase:** función invisible

### F-1B-04 · Dueño o administrador con perfil médico no pueden agendar para otro médico
**Severidad:** P2
**Backend:** `MailySoft/backend/apps/agenda/services.py:417` — la restricción solo aplica al rol `doctor`; para `owner`/`admin` el `doctor_id` del cuerpo es libre. Contrato:2220 (O y A con ✔ sin condición).
**Frontend:** `MailySoft/web-soft/src/components/agenda/CrearEventoModal.tsx:202` usa `soyDoctor = !!user?.doctor_id`; `:611-621` sustituye el `<select>` de doctores por una caja fija con el nombre propio y la etiqueta "Tú". Lo mismo aplica a la serie (`:186`, `:303`).
**Qué ve el usuario:** la misma dueña quiere agendar un paciente con el Dr. Ruiz. Pulsa una casilla libre de la columna de él y el campo "Doctor" aparece bloqueado con su propio nombre. Tiene que pedirle a recepción que lo agende, o cambiar de sesión.
**Clase:** función invisible

### F-1B-05 · Médicos, enfermería y recepción no pueden dirigir un aviso a un rol
**Severidad:** P2
**Backend:** `MailySoft/backend/apps/notificaciones/recipients.py:32-34` — `ROLE_NOTE_SENDERS = {owner, admin, doctor, nurse, reception}`; `apps/notas/services.py:323-326` solo rechaza a quien no esté en ese conjunto (`finance` y `readonly`). Contrato:6685-6687, :6729.
**Frontend:** `MailySoft/web-soft/src/components/notas/NuevaNotaModal.tsx:34` — `puedeAvisar = esOwner || esAdmin`; `:148` envuelve **todo** el bloque "Alcance" en esa condición, así que doctor, enfermería y recepción solo ven el formulario de nota personal. La misma línea añade `&& !esEdicion`, con lo que **nadie** puede convertir una nota personal en aviso por `PATCH`, capacidad que el backend sí permite (`apps/notas/services.py:522-535`, contrato:6736-6737).
**Qué ve el usuario:** un médico quiere avisar a recepción "el lunes no vengo, muevan mis citas de la mañana". Entra a Notas → Nueva nota y solo puede escribir una nota que nadie más verá; no hay selector de alcance ni de rol destino. Acaba escribiéndolo por WhatsApp. El backend habría aceptado su `scope=role, target_role=reception` y habría hecho sonar la campana de las recepcionistas de su sede.
**Clase:** función invisible

### F-1B-06 · El dueño no puede corregir ni retirar los avisos que publicó su administrador
**Severidad:** P2
**Backend:** `MailySoft/backend/apps/notas/services.py:150-164` — `_can_mutate` devuelve `True` para el owner del tenant sobre cualquier nota con `scope` `role` o `all`, aunque no la haya escrito ("supervisión", comentario en `:157-159`). Contrato:6734, :6740.
**Frontend:** `MailySoft/web-soft/src/pages/NotasPage.tsx:45` define `esMia` comparando autor; `:114` pasa `editable={esMia(n)}` a los avisos; `components/notas/NotaCard.tsx:92-103` solo pinta los botones de editar y eliminar cuando `editable` es `true`.
**Qué ve el usuario:** el administrador publicó "Cerramos a las 3 el viernes 15" con la fecha equivocada. El dueño ve la tarjeta en "Avisos de la clínica" pero sin lápiz ni bote de basura; el aviso equivocado se queda publicado para toda la clínica hasta que el administrador entre a corregirlo.
**Clase:** función invisible

### F-1B-07 · Casilla de tarea en avisos ajenos: el clic no hace nada y no dice nada
**Severidad:** P2
**Backend:** `MailySoft/backend/apps/notas/services.py:595-596` — `note_toggle_done` lanza 400 "Solo el autor puede marcar esta tarea como hecha o pendiente." si `note.author_id != user.pk`; no hay excepción para el owner. Contrato:6658-6660, :6742.
**Frontend:** `MailySoft/web-soft/src/components/agenda/RecordatoriosWidget.tsx:42-47` pinta la casilla para **cualquier** nota con `is_task`, sin comparar el autor, y el propio widget confirma que ahí caen avisos ajenos porque `:55` los etiqueta con " · aviso". `hooks/notas.ts:38-44` y `:55-57` — `useToggleNoteDone` no declara `onError`, así que el 400 se descarta en silencio.
**Qué ve el usuario:** el dueño publica un aviso a recepción, marcado como tarea, con recordatorio a las 9:00. La recepcionista abre `/agenda`, ve el aviso en "Mis recordatorios" con una casilla vacía y la pulsa: la casilla no cambia, no aparece ningún mensaje y la petición falla. Lo intenta tres veces y llama a soporte creyendo que el sistema está colgado.
**Clase:** botón fantasma

### F-1B-08 · No existe forma de corregir el motivo, la especialidad ni las notas de una cita ya creada
**Severidad:** P2
**Backend:** `MailySoft/backend/apps/core/permissions.py:194` — `policy["PATCH"] = {owner, admin, doctor, reception}`; el endpoint acepta `reason`, `specialty` y `notes` (contrato:1756, :1947-1951, :2222).
**Frontend:** `MailySoft/web-soft/src/api/agenda.ts` no tiene ninguna función que haga `PATCH` a `/agenda/citas/<id>/` — el archivo cubre listar, crear, serie, disponibilidad, tipos de cita, eventos, notas, reagendar, reactivar y estado, y nada más. `components/agenda/DetalleCitaModal.tsx:254-261` muestra "A qué venía", "Especialidad" y "Notas" como texto de solo lectura.
**Qué ve el usuario:** recepción capturó el motivo con una falta ("Dolo lumbar") y ese texto sale impreso en la hoja del día y viaja en la respuesta de la cita. No hay ningún lápiz en el modal de detalle. La única salida es cancelar la cita y crear otra, lo que deja una cancelación falsa en el historial del paciente.
**Clase:** función invisible

### F-1B-09 · Toda cancelación queda registrada sin motivo
**Severidad:** P2
**Backend:** `MailySoft/backend/apps/agenda/views.py:585-587` — el `InputSerializer` de `POST /agenda/citas/<id>/estado/` acepta `reason`, y el service lo escribe en `cancellation_reason` y en la bitácora (contrato:1963, :2112-2114).
**Frontend:** `MailySoft/web-soft/src/api/agenda.ts:145-153` — `changeAppointmentStatus` tiene `reason = ''` por defecto; `pages/AgendaPage.tsx:346-347` llama a la mutación solo con `{ id, status }`; `components/agenda/DetalleCitaModal.tsx:357-362` cancela de un clic sin pedir motivo; `components/agenda/AlertaCitas.tsx:112-114` marca "no asistió" igual.
**Qué ve el usuario:** una paciente cancela porque el médico se enfermó. La cita queda cancelada con `cancellation_reason` vacío. Al mes siguiente, cuando el dueño revisa por qué se cayó el 12 % de la agenda, la bitácora y la ficha solo dicen "Cancelada" — el campo existe en la base y ninguna pantalla lo llena nunca.
**Clase:** función invisible

### F-1B-10 · No se puede dirigir un aviso al dueño
**Severidad:** P2
**Backend:** `MailySoft/backend/apps/notas/services.py:68-75` — `_VALID_ROLES` incluye `owner`; `:332` solo rechaza los roles fuera de ese conjunto, y el reparto (`apps/notificaciones/recipients.py:57`) buscaría su membresía sin problema. Contrato:6583-6585.
**Frontend:** `MailySoft/web-soft/src/components/notas/NuevaNotaModal.tsx:158` — `ROLES.filter(r => r.key !== 'owner')` quita al dueño del selector de rol destino.
**Qué ve el usuario:** el administrador quiere dejarle un aviso al dueño ("faltan las firmas de consentimiento de la semana"). El desplegable de rol destino ofrece Administrador, Médico, Enfermería, Recepción, Finanzas y Solo lectura — el Dueño no está. Tiene que mandar el aviso a toda la clínica para que le llegue a una sola persona.
**Clase:** función invisible

### F-1B-11 · Enfermería ve "Volver a agendar" en Contactos y el backend responde 403
**Severidad:** P1
**Backend:** `MailySoft/backend/apps/core/permissions.py:193` — `policy["POST"] = {owner, admin, doctor, reception}`, sin `nurse` (comentario explícito en `:186`: "nurse NO crea citas en v1"); `apps/agenda/views.py:159` aplica esa clase. Contrato:2220.
**Frontend:** `MailySoft/web-soft/src/pages/ContactosPage.tsx:95` calcula la capacidad con `puedeEditar(role, 'agenda')`, que lee `PERMISOS.nurse.agenda === 'edit'` (`auth/permisos.ts:108`) y devuelve `true` para enfermería — en vez de usar `puedeAgendar` de `auth/permisos.ts:133-134`, que sí la excluye. Con eso se pintan los botones "Reagendar" (`:408`) y "Volver a agendar" (`:492`), que abren `CrearEventoModal` (`:518`) en modo cita (`components/agenda/CrearEventoModal.tsx:123`). El modal **no tiene ningún control de rol propio**: no importa `RoleContext` ni `auth/permisos` (`CrearEventoModal.tsx:1-16`), y el selector de segmentos tampoco filtra por rol (`ContactosPage.tsx:220-232`).
**Qué ve el usuario:** una enfermera entra a Pacientes, pulsa el segmento "Potenciales" y ve el botón azul "Volver a agendar" en cada tarjeta. Elige a un paciente, llena el asistente de dos pasos completo (paciente, médico, modalidad, consultorio, duración, tipo de cita) y al pulsar "Agendar cita" recibe un error. Todo el trabajo capturado se queda en el formulario. Desde `/agenda` esa misma enfermera no puede agendar, porque ahí sí se usa `puedeAgendar` (`pages/AgendaPage.tsx:235`, `:294`): la misma acción está permitida en una pantalla y prohibida en otra.
**Clase:** botón fantasma

---

### NO VERIFICABLE

1. **Qué pantalla exacta ve `finance` cuando el `GET /agenda/citas/` devuelve 403.** F-1B-01 está probado por ambos lados, pero asumí que el 403 llega a TanStack Query como error de consulta y produce el mensaje de `pages/AgendaPage.tsx:518-520`. Para confirmarlo haría falta leer `MailySoft/web-soft/src/lib/http.ts` —fuera de la lista de archivos de este encargo— y comprobar que un 403 **sin** `password_change_required` no dispara un efecto global (cierre de sesión, reintento de refresh o redirección) antes de llegar al componente.

2. **Si el 403 de `DELETE /agenda/eventos/<id>/` se muestra con su `detail` o con el texto genérico.** `components/agenda/EventoDetalleModal.tsx:62` pasa el error por `erroresDe(err, 'No se pudo guardar.')`. Para saber si el médico lee el mensaje real del backend ("No tienes permiso…") o el genérico haría falta revisar `MailySoft/web-soft/src/lib/apiErrors.ts` y cómo `ApiError` conserva el cuerpo de un 403 de DRF.

3. **Si algún otro punto de la app monta `CrearEventoModal` o `NuevaNotaModal` sin gate de rol.** Verifiqué los montajes existentes (`pages/AgendaPage.tsx:756`, `pages/ContactosPage.tsx:518`, `pages/NotasPage.tsx:131`) con `grep` sobre `web-soft/src`, pero no audité rutas cargadas de forma diferida ni el portal interno (`src/platform/`). Para cerrarlo haría falta un barrido de `src/platform/` con los mismos criterios.

---

### Defectos del contrato detectados

**D-1 · §3.5 (contrato:2213-2215) afirma "sin `agenda` contratada, 404 para los 7". Falso para los roles que el permiso de rol ya niega.**

El contrato dice que el guard de módulo "manda encima de toda esta tabla". El código dice lo contrario para `finance`: en las 15 vistas de agenda el permiso de rol va **antes** del guard en la lista (`MailySoft/backend/apps/agenda/views.py:159`, `:316`, `:447`, `:485`, `:583`, `:637`, `:680`, `:705`, `:789`, `:840`, `:899`, `:971`, `:1032`, `:1092`, `:1151`), y DRF corta en el primer permiso que devuelve `False`. `AppointmentPermission.has_permission` niega a `finance` (`apps/core/permissions.py:76-78`, `:191-192`) antes de que `RequiresAgenda` llegue a lanzar su `NotFound` (`apps/core/entitlement_guards.py:73-84`). Consecuencia real: una clínica **sin** el módulo `agenda` devuelve **403** a `finance` en `GET /agenda/citas/` y **404** a los otros seis roles. Lo mismo pasa con cualquier combinación método×rol que la policy no declare — por ejemplo `nurse` en `POST /agenda/citas/`, o `doctor` en `DELETE /agenda/eventos/<id>/`, que dan 403 aunque falte el módulo.

El propio contrato aplica bien este razonamiento en §9.4 (contrato:6744): "Aquí el 404 sí gana para todos los roles, **porque `NotePermission` los deja pasar a los 7**". Esa cláusula condicional es la correcta y es justo la que falta en §3.5. Corrección sugerida para la nota de §3.5: *"sin `agenda` contratada, 404 para los seis roles que el permiso de rol deja pasar; `finance` recibe 403 con o sin módulo, porque `AppointmentPermission` se evalúa antes."*

---

## Cruce 1C · Finanzas y recetas

Leyenda de roles: **O** owner · **A** admin · **D** doctor · **N** nurse · **R** reception ·
**F** finance · **L** readonly.

Rutas abreviadas: `permisos.py` = `MailySoft/backend/apps/core/permissions.py` ·
`src/…` = `MailySoft/web-soft/src/…` · `contrato:NNNN` = `MailySoft/docs/02-contrato.md:NNNN`.

Nota transversal que atraviesa media tabla: el guard de ruta del frontend
(`src/App.tsx:47`, `if (!accesoModulo(role, modulo)) return <Navigate …>`) decide el acceso a
**páginas** con `PERMISOS` (`src/auth/permisos.ts:104-112`), mientras que los botones dentro de
cada página usan `MATRIX` (`src/auth/permisos.ts:41-52`). **Son dos matrices distintas y no
coinciden entre sí**; varias filas de abajo se explican solo por eso.

---

### Tabla de cruce

#### Finanzas

| Acción | Backend permite | Frontend muestra | Veredicto |
|---|---|---|---|
| Entrar al módulo Finanzas | O A F R L — `FINANCE_VIEW_ROLES` `permisos.py:284` · contrato:5009-5034 | O A F L — `PERMISOS` sin clave `finanzas` para `reception` `src/auth/permisos.ts:109`, aplicado en `src/App.tsx:47,163` y `src/components/Topbar.tsx:44-45` | **FUNCIÓN INVISIBLE** (R) → F-1C-01 |
| Ver catálogo de servicios (`GET /finanzas/conceptos/`) | O A D R F L — `FinanceConceptPermission` `permisos.py:317` · contrato:4475 | Pantalla dedicada: solo O (`src/pages/MiConsultorioPage.tsx:102,116`); lectura indirecta como selector para O A D R (`src/components/finanzas/CotizacionesTab.tsx:96,246`) | **FUNCIÓN INVISIBLE** (A F R L sin pantalla) → F-1C-10 |
| Crear / editar / desactivar servicio | **solo O** — `FINANCE_CATALOG_MANAGE_ROLES` `permisos.py:301`, `permisos.py:317` · contrato:5012 | solo O — `esOwner` `src/pages/MiConsultorioPage.tsx:65,85` → `SeccionServicios editable` `src/components/consultorio/SeccionServicios.tsx:88` | **ALINEADO** (ver nota de `manageConcepts` en F-1C-10) |
| Ver catálogo de paquetes (`GET /finanzas/paquetes/`) | O A D R — `TreatmentPackagePermission` `permisos.py:393` · contrato:5013 | O A — `src/pages/PaquetesPage.tsx:55`, `src/components/Topbar.tsx:48`; selector "Agregar paquete" sí llega a O A D R (`src/components/finanzas/CotizacionesTab.tsx:103,333`) | **FUNCIÓN INVISIBLE** (D R) → F-1C-06 |
| Crear / editar / borrar paquete | **solo O** — `permisos.py:393,301` · contrato:5014 | solo O — `puedeEditar` `src/pages/PaquetesPage.tsx:56,248,260,468` | **ALINEADO** |
| Ver / editar configuración fiscal (`/finanzas/config/`) | O A — `FinanceConfigPermission` `permisos.py:604` · contrato:5015 | **nadie**: `useFiscalConfig` `src/hooks/finanzas.ts:327` y `updateFiscalConfig` `src/api/finanzas.ts:727` sin ningún consumidor | **FUNCIÓN INVISIBLE** → F-1C-02 |
| Ver cotizaciones (`GET /finanzas/cotizaciones/`) | O A D R **L** — `QuotePermission` `permisos.py:368` (`_QUOTE_ROLES` `:365` + READONLY) · contrato:5016 | O A D R — `PERMISOS.readonly` sin `cotizaciones` `src/auth/permisos.ts:111` + `src/App.tsx:47,164` | **FUNCIÓN INVISIBLE** (L) → F-1C-05 |
| Crear cotización | O A D R — `permisos.py:368` · contrato:5017 | O A D R — `can(role,'createQuote')` `src/auth/permisos.ts:39,48`, `src/components/finanzas/CotizacionesTab.tsx:101,213` | **ALINEADO** |
| Enviar cotización (`POST …/enviar/`) | O A D R — `permisos.py:368` · contrato:5018 | O A D R — `canCreate && status==='draft'` `src/components/finanzas/CotizacionesTab.tsx:447` | **ALINEADO** |
| Aceptar cotización (`POST …/aceptar/`) | O A D R — `permisos.py:368` · contrato:5018 | O A D R — `canCreate && (draft|sent)` `src/components/finanzas/CotizacionesTab.tsx:457` | **ALINEADO** |
| Rechazar / marcar vencida (`PATCH /cotizaciones/<id>/`) | O A D R — `QuoteDetailApi` `MailySoft/backend/apps/finanzas/views.py:644` + `permisos.py:368` · contrato:4571 | **nadie**: no existe función de PATCH de cotización en `src/api/finanzas.ts:470-505` | **FUNCIÓN INVISIBLE** → F-1C-07 |
| Descargar PDF de cotización | O A D R L — `QuotePermission` GET, `finanzas/views.py:713` · contrato:5019 | O A D R — botón sin gate propio (`src/components/finanzas/CotizacionesTab.tsx:440-446`) dentro de una página que L no alcanza | **FUNCIÓN INVISIBLE** (L, arrastre de F-1C-05) |
| Listar cargos (`GET /finanzas/cargos/`) | O A F R L **+ D si `doctors_see_costs`** — `ChargeListPermission` `permisos.py:546,578-584` · contrato:5020 | Cartera en /finanzas: O A F L (`src/components/finanzas/CobranzaTab.tsx:58-59` tras el guard); expediente: O A F R L + D con flag (`src/components/expediente/EstadoCuentaExpediente.tsx:46` vía `src/components/contactos/ExpedienteDrawer.tsx:96`) | **FUNCIÓN INVISIBLE** parcial (R pierde la cartera; conserva el expediente) → F-1C-01 |
| Ver un cargo por id | O A F R L, **D nunca** — `FinanceChargePermission` `permisos.py:417` · contrato:5021 | nadie: el front no llama al detalle de cargo (verificado en `src/api/finanzas.ts:557-566`) | **ALINEADO** (B-FIN-14 no produce botón fantasma) |
| Crear cargo | O A F — `permisos.py:546` (rama POST) · contrato:5022 | O A F — `can(role,'createCharge')` = `CORE_ROLES` `src/auth/permisos.ts:33,49`, `src/components/finanzas/CobrosPagosTab.tsx:71,91` | **ALINEADO** |
| Cancelar cargo (`DELETE`) | O A F — `FinanceChargePermission` `permisos.py:417` · contrato:5023 | O A F **y solo si `status!=='cancelled' && amount_paid===0`** — `src/components/finanzas/CobrosPagosTab.tsx:143` | **ALINEADO** (además anticipa la guarda de `finanzas/services.py:926`) |
| Ver pagos (lista y detalle) | O A F R L — `FinancePaymentPermission` `permisos.py:435` · contrato:5024 | O A F L — `src/components/finanzas/CobrosPagosTab.tsx:28` tras el guard de `/finanzas` | **FUNCIÓN INVISIBLE** (R) → F-1C-01 |
| Registrar pago | O A F R — `permisos.py:435,289` · contrato:5025 | O A F R — `can(role,'registerPayment')` `src/auth/permisos.ts:32,50` y `puedeCobrar` `src/auth/permisos.ts:218` en `src/components/expediente/EstadoCuentaExpediente.tsx:99` | **ALINEADO** por el expediente; en /finanzas R no llega (F-1C-01) |
| Editar / borrar / revertir pago | **nadie** (403, sin PATCH ni DELETE en la policy) — `permisos.py:435` · contrato:4629-4630, 5026 | nadie: no hay botón ni función (`src/api/finanzas.ts` no expone update/delete de pago) | **ALINEADO** |
| Ver estado de cuenta del paciente | O A F R L **+ D si `doctors_see_costs`** — `PatientStatementPermission` `permisos.py:502,530-543` · contrato:5027 | idéntico — `puedeVerEstadoCuenta` `src/auth/permisos.ts:208-215` con el flag de `useClinicSettings` y `?? false` (`src/components/contactos/ExpedienteDrawer.tsx:94-96`) | **ALINEADO**, fail-closed en ambos lados (ver F-1C-11) |
| Ver CFDI (lista y detalle) | O A F L — `CfdiPermission` `permisos.py:590` · contrato:5028 | O A F L — `viewCfdi` = `CFDI_VIEW_ROLES` `src/auth/permisos.ts:36,45`, `src/pages/FinanzasPage.tsx:44,67` | **ALINEADO** (R fuera de facturación) |
| Emitir CFDI | O A F — `permisos.py:590` · contrato:5029 | O A F — `can(role,'issueCfdi')` = `CORE_ROLES` `src/auth/permisos.ts:51`, `src/components/finanzas/CfdiTab.tsx:33,62` | **ALINEADO** |
| Cancelar CFDI | O A F — `permisos.py:590` · contrato:5030 | O A F — `canIssue && status==='stamped'` `src/components/finanzas/CfdiTab.tsx:122` | **ALINEADO** |
| Dashboard financiero | O A F L — `FinanceDashboardPermission` `permisos.py:304` · contrato:5031 | O A F L — `viewDashboard` = `DASHBOARD_ROLES` `src/auth/permisos.ts:35,43`, `src/pages/FinanzasPage.tsx:41` | **ALINEADO** |
| Reporte de periodo (JSON) | O A F L — `permisos.py:304`, `finanzas/views.py:1178` · contrato:5032 | O A F L — `src/components/finanzas/ResumenTab.tsx:61` dentro del tab `viewDashboard` | **ALINEADO** |
| Reporte de periodo (PDF) | O A F L — `finanzas/views.py:1224` · contrato:5032 | O A F L — `canExport = can(role,'viewDashboard')` `src/components/finanzas/ResumenTab.tsx:73,183` | **ALINEADO** |
| Cierre diario de caja | **O A F R** — `FinanceDeskPermission` `finanzas/views.py:92`, aplicado en `:1297` · contrato:5033 | O A F R en el componente (`src/components/finanzas/CierreDiarioTab.tsx:21`, `src/components/finanzas/CajaTab.tsx:29,40`) pero **R nunca llega a la página** (`src/App.tsx:47`) | **FUNCIÓN INVISIBLE** (R) → F-1C-01 |
| Panel de retención RFM | O A F L — `RetentionPermission` `permisos.py:1119` · contrato:5034 | O A F L — `can(role,'viewDashboard')` `src/components/finanzas/RetencionTab.tsx:70` | **ALINEADO** |

#### Recetas y PDFs

| Acción | Backend permite | Frontend muestra | Veredicto |
|---|---|---|---|
| Buscar medicamentos | O A D N L — `MedicationPermission` `permisos.py:983` (`CLINICAL_READ` `:670`) · contrato:3993 | O A D — el buscador solo existe dentro de `NuevaReceta` (`src/components/expediente/RecetasTab.tsx:1193`), que abre `puedeEmitir` (`:200`) | **FUNCIÓN INVISIBLE** (N L) — sin valor práctico, se anota por cobertura |
| Crear medicamento custom | O A D — `permisos.py:983` · contrato:3994 | **nadie**: `useCreateMedication` `src/hooks/recetas.ts:62` no tiene ningún consumidor | **FUNCIÓN INVISIBLE** → F-1C-09 |
| Ver historial de recetas | O A D N L — `PrescriptionPermission` `permisos.py:935` · contrato:3995 | O A D N L — `accesoClinico` = `puedeVerExpedienteClinico` `src/auth/permisos.ts:117` sobre `PERMISOS` `:105-111`, en `src/components/expediente/IndiceSecciones.tsx:44` | **ALINEADO** |
| Emitir receta | rol O A D **+ perfil Doctor activo con cédula** — `permisos.py:935` + `MailySoft/backend/apps/recetas/services.py:508-513,519-524` · contrato:3996, 3641-3643 | O A D **solo por rol** — `puedeEmitirReceta` `src/auth/permisos.ts:179-180`; botón en `src/components/expediente/RecetasTab.tsx:200` y `src/components/expediente/VisitaDeHoy.tsx:122` | **BOTÓN FANTASMA** → F-1C-04 |
| Anular receta | O A siempre; cualquier otro rol **solo si es el médico emisor** — `recetas/services.py:797-808` · contrato:3998, 3683-3684 | O A D **solo por rol** — `puedeAnularReceta` `src/auth/permisos.ts:183-184`; botón en `src/components/expediente/RecetasTab.tsx:387` vía `src/components/contactos/ExpedienteDrawer.tsx:314` | **BOTÓN FANTASMA** → F-1C-03 |
| Ver detalle de receta ("copiar a nueva") | O A D N L — `permisos.py:935` · contrato:3997 | O A D — `puedeEmitir` `src/components/expediente/RecetasTab.tsx:375` | **ALINEADO** (copiar solo sirve para emitir) |
| Pedir PDF de receta / consultar job / descargar | O A D N L — `permisos.py:935`, `recetas/views.py:376,427,456` · contrato:3999-4001 | O A D N L — botones "Farmacia"/"Paciente" sin gate propio (`src/components/expediente/RecetasTab.tsx:350-365`) dentro del tab que abre `accesoClinico` | **ALINEADO** |
| Listar / ver formatos de receta | **TODOS** los 7 — `PrescriptionFormatPermission` `permisos.py:1005` (`ALL_ROLES`) · contrato:4002-4003 | O A D — la única pantalla vive en Mi Consultorio, guardada por `puedeAccederConsultorio` `src/auth/permisos.ts:152`, `src/App.tsx:70` | **FUNCIÓN INVISIBLE** (N R F L) |
| Crear formato de receta | O A **D** — `permisos.py:1005` (POST) · contrato:4004 | O A — `editable = gestionable` `src/pages/MiConsultorioPage.tsx:59,79` → `src/components/consultorio/SeccionFormatos.tsx:150,159` | **FUNCIÓN INVISIBLE** (D) → F-1C-08 |
| Editar formato de receta | O A **D** — `permisos.py:1005` (PATCH) · contrato:4005 | O A — mismo `editable` (`src/components/consultorio/SeccionFormatos.tsx:292,367-368`) | **FUNCIÓN INVISIBLE** (D) → F-1C-08 |
| Autorizar formato (`is_authorized`) | O A (al doctor le da 400 el service) — `permisos.py:1005` + `recetas/services.py:1022-1025` · contrato:4006 | O A — `editable` sobre el checkbox `src/components/consultorio/SeccionFormatos.tsx:634-640` | **ALINEADO** |
| Dar de baja formato (`DELETE`) | O A — `MANAGE_ROLES` `permisos.py:68,1005` · contrato:4007 | O A — `editable` `src/components/consultorio/SeccionFormatos.tsx:292` | **ALINEADO** |
| Estado / descarga de PDF genérico (`/pdfs/job/<id>/`) | permiso del `kind`; si falla → **404, no 403** — `MailySoft/backend/apps/pdfs/views.py:36-42,60-66,92-94` · contrato:4008-4009, 4116 | mismo rol que encoló (por construcción); el 404 se muestra como "Trabajo de PDF no encontrado" — `src/api/pdfs.ts:33,40` + `src/components/VisorPdf.tsx:44-46` | **ALINEADO** en roles; mensaje engañoso → F-1C-12 |
| Verificar receta por QR (público) | `AllowAny`, sin tenant; expone folio, estado, fecha, médico + cédula, clínica, controlado, vigencia — `MailySoft/backend/apps/recetas/views_public.py:81-82,115-118,179-195` · contrato:3800-3831 | exactamente esos campos, **sin PII del paciente** — `src/pages/VerificarRecetaPage.tsx:157-174` | **ALINEADO** en datos expuestos; ver F-1C-13 por el estado |

---

### Hallazgos

### F-1C-01 · Recepción está bloqueada del módulo Finanzas completo, incluido el cierre de caja
**Severidad:** P1
**Backend:** `permisos.py:289` (`FINANCE_DESK_ROLES` incluye `reception`), `MailySoft/backend/apps/finanzas/views.py:92` (`FinanceDeskPermission` GET = O A F R) aplicado en `finanzas/views.py:1297`; `permisos.py:284` (`FINANCE_VIEW_ROLES` incluye `reception` para cargos, pagos y estado de cuenta); contrato:5024-5033 marca ✅ a recepción en registrar pago, ver pagos, ver cargos y **cierre diario**.
**Frontend:** `src/auth/permisos.ts:109` — la entrada `reception` de `PERMISOS` **no tiene la clave `finanzas`**, así que `accesoModulo('reception','finanzas')` devuelve `undefined`. `src/App.tsx:47` redirige a `/agenda` y `src/components/Topbar.tsx:44-45` no pinta el ítem del menú.
**Qué ve el usuario:** la recepcionista termina el turno, quiere hacer el corte del día y **no encuentra "Finanzas" en el menú**; si teclea `/finanzas` a mano la app la devuelve a la agenda sin explicación. Puede cobrar paciente por paciente desde el expediente (`src/components/expediente/EstadoCuentaExpediente.tsx:99`), pero no puede ver la cartera, ni el listado de pagos del día, ni imprimir el cierre de caja que el backend sí le autoriza.
**Clase:** función invisible
**Dato que confirma que es un bug y no una decisión:** otras tres piezas del propio frontend sí cuentan con recepción — `MATRIX.viewModule` (`src/auth/permisos.ts:31,42`), `DESK_ROLES` para `registerPayment` (`:32,50`) y el gate del cierre `puedeCobrar` (`:218`, usado en `src/components/finanzas/CierreDiarioTab.tsx:21`) —, y el encabezado de `src/components/finanzas/CajaTab.tsx:7` describe la pantalla como *"la pantalla de recepción"*.

### F-1C-02 · No existe pantalla para los datos fiscales del emisor: todo timbrado falla y no hay dónde arreglarlo
**Severidad:** P1
**Backend:** `permisos.py:604` (`FinanceConfigPermission`, GET/PATCH = O A) sobre `FiscalConfigApi` (`finanzas/views.py:333`); `MailySoft/backend/apps/finanzas/services.py:1148-1150` rechaza el timbrado con **400** `["Configura los datos fiscales del emisor (RFC) antes de timbrar."]` si `ClinicFiscalConfig.rfc` está vacío, y `GET /finanzas/config/` crea el registro **vacío** la primera vez (contrato:4532-4536).
**Frontend:** `src/hooks/finanzas.ts:327` (`useFiscalConfig`) y `src/api/finanzas.ts:723,727` (`fetchFiscalConfig` / `updateFiscalConfig`) existen y **no los consume ningún componente** (verificado por búsqueda en todo `src/`). La capacidad `manageFiscalConfig` está declarada en `src/auth/permisos.ts:23,47` y tampoco se usa en ninguna parte.
**Qué ve el usuario:** el dueño de una clínica nueva entra a Finanzas → Facturación (`src/pages/FinanzasPage.tsx:44,139`), elige un pago, teclea RFC y razón social del paciente, pulsa "Timbrar comprobante" (`src/components/finanzas/CfdiTab.tsx:85`) y recibe "Configura los datos fiscales del emisor (RFC) antes de timbrar." No hay ninguna pantalla en la aplicación donde configurarlos: ni en Mi Consultorio (`src/pages/MiConsultorioPage.tsx:70-98`) ni en Finanzas. El módulo CFDI queda inutilizable de fábrica.
**Clase:** función invisible

### F-1C-03 · "Anular receta" se muestra por rol; el backend la autoriza por pertenencia
**Severidad:** P1
**Backend:** `MailySoft/backend/apps/recetas/services.py:797-808` — `owner`/`admin` anulan cualquiera; **cualquier otro rol debe ser el médico emisor** (`doctor.id != prescription.doctor_id` → `PermissionDenied`, 403 "Solo el médico emisor o un administrador puede anular esta receta."). Contrato:3683-3684 y 3998 ("Propios").
**Frontend:** `src/auth/permisos.ts:183-184` — `puedeAnularReceta` es una comprobación de rol pura (O A D), sin mirar `receta.doctor`. Se propaga en `src/components/contactos/ExpedienteDrawer.tsx:314` y pinta el botón en `src/components/expediente/RecetasTab.tsx:387`, que solo condiciona por `!anulada` — el objeto de la lista **sí trae** `receta.doctor` (`src/components/expediente/RecetasTab.tsx:305`), así que la información para filtrar está disponible y no se usa.
**Qué ve el usuario:** la Dra. Ruiz abre el expediente de un paciente que también atiende el Dr. Gómez, ve "Anular" en la receta folio 27 emitida por él, la pulsa, **escribe el motivo obligatorio** en el diálogo (`src/components/expediente/RecetasTab.tsx:400-413`) y al confirmar el diálogo se cierra perdiendo el texto y aparece el mensaje genérico "No tienes permiso para esta acción." (`src/components/expediente/RecetasTab.tsx:409` → `src/lib/apiErrors.ts:27`). El mensaje explicativo del backend nunca llega (ver F-1C-14).
**Clase:** botón fantasma

### F-1C-04 · "Nueva receta" se ofrece a owner/admin que no tienen perfil de médico
**Severidad:** P1
**Backend:** `permisos.py:935` (`PrescriptionPermission` POST = O A D) es solo la capa externa; `MailySoft/backend/apps/recetas/services.py:508-513` exige además **perfil `Doctor` activo en el tenant** y responde `PermissionDenied` = 403 "Solo un médico puede emitir recetas…". Contrato:3641-3642 y 3996 ("Solo con perfil Doctor activo").
**Frontend:** `src/auth/permisos.ts:179-180` — `puedeEmitirReceta` es rol puro (O A D). Su propio comentario (`src/auth/permisos.ts:176-177`) reconoce el hueco y pide que "la UI muestre ese mensaje claro"; no lo hace. Botones en `src/components/expediente/RecetasTab.tsx:200` y `src/components/expediente/VisitaDeHoy.tsx:122`.
**Qué ve el usuario:** la administradora de una clínica (rol `admin`, sin perfil médico) abre la Visita de hoy, pulsa "Receta", **captura los renglones completos** —medicamento, dosis, frecuencia, vía, duración, signos vitales— y al guardar recibe "No tienes permiso para esta acción." (`src/components/expediente/RecetasTab.tsx:757` → `src/lib/apiErrors.ts:27`). Nada le indica que el problema es la falta de perfil médico y no un permiso de su puesto. Mismo caso para un `owner` que no atiende.
**Clase:** botón fantasma

### F-1C-05 · `readonly` no puede entrar a Cotizaciones aunque el backend le da lectura
**Severidad:** P2
**Backend:** `permisos.py:368` — `QuotePermission.policy["GET"] = _QUOTE_ROLES | {READONLY}`; contrato:5016 y 5019 marcan ✅ a readonly en "Ver cotizaciones" y "Descargar PDF de cotización".
**Frontend:** `src/auth/permisos.ts:111` — `readonly` no tiene la clave `cotizaciones` en `PERMISOS`, así que `src/App.tsx:47,164` lo redirige a `/agenda`. Curiosamente el gate interno de la página **sí** lo contempla (`src/pages/CotizacionesPage.tsx:17`, `can(role,'viewModule')` incluye readonly por `src/auth/permisos.ts:31,42`), pero es código muerto: el guard de ruta lo bloquea antes.
**Qué ve el usuario:** el contador externo con rol `readonly`, contratado para revisar sin tocar, no ve "Cotizaciones" en el menú y no puede consultar ni descargar el PDF de una cotización aceptada que sí originó cargos que él sí ve en Finanzas.
**Clase:** función invisible

### F-1C-06 · El médico y recepción no ven el catálogo de paquetes
**Severidad:** P2
**Backend:** `permisos.py:393` — `TreatmentPackagePermission.policy["GET"] = {OWNER, ADMIN, DOCTOR, RECEPTION}`, con la razón escrita en el docstring ("owner/admin/doctor arman calendarizaciones/cotizaciones desde el paquete; recepción también lo consulta al atender caja"); contrato:5013.
**Frontend:** `src/pages/PaquetesPage.tsx:55` (`puedeVer = role === 'owner' || role === 'admin'`) y `src/components/Topbar.tsx:48` (`puedeVerPaquetes = owner || admin`).
**Qué ve el usuario:** el médico que quiere revisar qué incluye el paquete "Regenerativo 6 sesiones" antes de proponerlo en consulta no tiene dónde abrirlo; solo puede inyectarlo a ciegas como renglones desde el selector "Agregar paquete" de la cotización (`src/components/finanzas/CotizacionesTab.tsx:333-345`), sin ver su ficha ni su precio de lista.
**Clase:** función invisible

### F-1C-07 · No hay forma de rechazar ni marcar vencida una cotización
**Severidad:** P2
**Backend:** `MailySoft/backend/apps/finanzas/views.py:644,647` — `QuoteDetailApi` acepta `PATCH` con `status ∈ {rejected, expired}` bajo `QuotePermission` (O A D R); contrato:4571 y 5018.
**Frontend:** `src/api/finanzas.ts:470-505` expone `fetchQuotes`, `createQuote`, `sendQuote`, `acceptQuote` y el PDF, y **nada más**; `src/components/finanzas/CotizacionesTab.tsx:439-466` solo ofrece PDF, enviar y aceptar. Los estados `rejected` y `expired` existen en el front únicamente como badges de solo lectura (`src/components/finanzas/CotizacionesTab.tsx:30-31`).
**Qué ve el usuario:** una cotización que el paciente rechazó se queda en "Enviada" para siempre. El embudo del Resumen (`src/components/finanzas/charts/EmbudoChart.tsx:60-61`) muestra siempre 0 rechazadas y 0 vencidas, y la tasa de conversión del dashboard queda inflada.
**Clase:** función invisible

### F-1C-08 · El médico no puede crear ni editar su propio formato de receta
**Severidad:** P2
**Backend:** `permisos.py:1005` — `PrescriptionFormatPermission.policy` da POST y PATCH a `{OWNER, ADMIN, DOCTOR}` con el docstring explícito "los médicos pueden crear su formato personal"; contrato:4004-4005.
**Frontend:** `src/pages/MiConsultorioPage.tsx:59,79` pasa `editable = gestionable = puedeGestionarConsultorio(role)` (O A, `src/auth/permisos.ts:156-157`) a `SeccionFormatos`; con `editable=false` la sección pinta `AvisoSoloLectura` y oculta los botones de alta y edición (`src/components/consultorio/SeccionFormatos.tsx:150,159,292`).
**Qué ve el usuario:** un médico que trabaja en dos clínicas y quiere su propio membrete (su color, su sello, sus secciones) entra a Mi Consultorio → Formatos y solo puede mirar. El modelo tiene el campo `doctor` justo para eso (`recetas/models.py:958`, contrato:3428) y el backend lo autoriza.
**Clase:** función invisible

### F-1C-09 · No hay alta de medicamento custom en ninguna pantalla
**Severidad:** P2
**Backend:** `permisos.py:983` — `MedicationPermission.policy["POST"] = {OWNER, ADMIN, DOCTOR}` sobre `POST /api/v1/recetas/medicamentos/` (contrato:3505, 3560-3575). Es la **única** vía de escritura del catálogo propio de la clínica (contrato:3935).
**Frontend:** `src/hooks/recetas.ts:62` (`useCreateMedication`) y `src/api/recetas.ts:56` (`createMedication`) existen y no los usa ningún componente; el único consumo del catálogo es el buscador de solo lectura (`src/components/expediente/RecetasTab.tsx:1193`).
**Qué ve el usuario:** el médico busca un medicamento que no está en el catálogo global, no lo encuentra y lo escribe como texto libre en cada receta. La clínica nunca puede construir su catálogo propio, aunque la capacidad esté implementada y auditada en el backend (`recetas/services.py:225-234`).
**Clase:** función invisible

### F-1C-10 · El catálogo de servicios y precios solo tiene pantalla para el dueño
**Severidad:** P2
**Backend:** `permisos.py:317` — `FinanceConceptPermission.policy["GET"] = FINANCE_VIEW_ROLES | {DOCTOR}` (O A F R L + D), con el comentario de `permisos.py:298-300` diciendo que la lectura se dejó abierta a propósito para que admin y el resto "sigan viendo el catálogo completo para cobrar/cotizar"; contrato:5011.
**Frontend:** `src/pages/MiConsultorioPage.tsx:102,116` mete `'servicios'` en `soloDueno`, así que la sección **ni aparece en el menú** salvo para `owner`. La única lectura que queda para los demás es el `<select>` de servicios al crear una cotización (`src/components/finanzas/CotizacionesTab.tsx:96,246`), que muestra el nombre pero no la lista de precios.
**Qué ve el usuario:** el administrador que necesita confirmar el precio de lista de un tratamiento antes de autorizar un descuento no tiene ninguna pantalla con la tarifa; tiene que abrir una cotización de prueba para que el precio se autocomplete.
**Clase:** función invisible
**Trampa comprobada del encargo:** `MATRIX.manageConcepts = MANAGE_ROLES` (owner **+ admin**, `src/auth/permisos.ts:34,46`) **contradice** al backend, que desde la decisión del 2026-07-16 solo deja escribir al dueño (`permisos.py:295-301`). No produce botón fantasma hoy **porque la capacidad no se usa en ningún sitio**: el gate real es `esOwner` (`src/pages/MiConsultorioPage.tsx:65,85`), que sí está bien. Es una mina: el día que alguien escriba `can(role,'manageConcepts')` para pintar un botón, el admin verá "Nuevo servicio" y recibirá 403.

### F-1C-11 · De dónde sale `doctors_see_costs` y qué cuesta pedirlo
**Severidad:** P2
**Backend:** `permisos.py:461-497` (`_tenant_doctors_see_costs`, devuelve `False` ante cualquier fallo → fail-closed) usado por `PatientStatementPermission` `permisos.py:540-541` y `ChargeListPermission` `permisos.py:582-583` (rama GET completa en `:578-584`); contrato:5047-5063. El flag se lee del endpoint `GET /api/v1/clinica/configuracion/`, cuyo permiso es `ClinicSettingsPermission` GET = `CLINICAL_READ` = **O A D N L** (`MailySoft/backend/apps/clinica/permissions.py:29`, contrato:413).
**Frontend:** `src/components/contactos/ExpedienteDrawer.tsx:94-96` — `useClinicSettings()` se llama **incondicionalmente** al abrir cualquier expediente y el flag se resuelve con `clinicSettings.data?.doctors_see_costs ?? false`.
**Qué ve el usuario:** dos efectos distintos.
1. **Fail-closed correcto y verificado:** mientras la petición está en vuelo, el médico de una clínica con el flag encendido no ve la entrada "Estado de cuenta" del índice (`src/components/expediente/IndiceSecciones.tsx:46`) ni se dispara `useStatement` (`src/components/contactos/ExpedienteDrawer.tsx:122`); aparecen al llegar la respuesta. Es un parpadeo, no una fuga. **Coincide con el fail-closed del backend.**
2. **Petición condenada:** para `reception` y `finance` —que no están en `CLINICAL_READ`— ese `GET /clinica/configuracion/` devuelve **403 en cada apertura de expediente**. No rompe nada (esos roles ya pasan por `can(role,'viewStatement')`), pero es una llamada que el backend niega siempre y que ensucia el diagnóstico de errores reales.
**Clase:** botón fantasma (silencioso: la petición, no un botón)

### F-1C-12 · El 404 de permiso de `/pdfs/job/` se le muestra al usuario como "no encontrado"
**Severidad:** P2
**Backend:** `MailySoft/backend/apps/pdfs/views.py:36-42` (`_kind_permission_ok`) y `:60-66`, `:92-94` — cuando el permiso registrado para el `kind` falla, la respuesta es **404** `{"detail": "Trabajo de PDF no encontrado."}`, deliberadamente indistinguible de "no existe" (contrato:4116, 3439-3441).
**Frontend:** `src/api/pdfs.ts:33,40` propaga el `ApiError` tal cual; `src/components/VisorPdf.tsx:44-46` solo traduce el **403** a "No tienes permiso para ver este documento" y para todo lo demás muestra `err.message`, que aquí es el `detail` del backend.
**Qué ve el usuario:** el modal del visor dice "Trabajo de PDF no encontrado." Hoy la coincidencia de roles lo hace poco frecuente (quien encola es quien descarga: `quote` usa `QuotePermission` en ambos extremos, `finance_report` usa `FinanceDashboardPermission` en ambos, contrato:5116-5117), pero cuando ocurre —cambio de rol a media sesión, job compartido por enlace— el mensaje manda a buscar un archivo perdido en vez de decir que no le corresponde. **Ningún manejo del frontend contempla que un 404 pueda significar "sin permiso".**
**Clase:** botón fantasma

### F-1C-13 · La verificación pública declara "auténtica y vigente" una receta controlada ya vencida
**Severidad:** P1
**Backend:** `MailySoft/backend/apps/recetas/views_public.py:115-118` — `estado = "anulada" if status == CANCELLED else "vigente"`; **`valid_until` no interviene** (contrato:3817). El mismo endpoint sí devuelve `vigencia` con la fecha real (`views_public.py:179-195`, contrato:3822-3823). Para un controlado del Grupo I la vigencia son 24 h (`recetas/services.py:75-81`, contrato:3949).
**Frontend:** `src/pages/VerificarRecetaPage.tsx:114` (`const anulada = data.estado === 'anulada'`), `:149` (banner verde "Receta auténtica y vigente") y `:164-174`, que imprime "Contiene medicamento controlado · vigente hasta {fecha}" **sin comparar esa fecha con hoy**, teniendo el dato en la mano.
**Qué ve el usuario:** el mostrador de una farmacia escanea el QR de una receta de clonazepam emitida hace tres días. La página pública muestra un check verde con "Receta auténtica y vigente. Emitida por la clínica, firma verificada." y debajo, en ámbar, "vigente hasta 09/08/2026" —una fecha ya pasada—. La única señal de alarma queda enterrada en una fecha que contradice el titular.
**Clase:** ninguna de las dos — contradicción de datos en la vista pública. El defecto de origen es del backend y ya está documentado en contrato:3817; el frontend lo **amplifica** al añadir la palabra "vigente" en verde teniendo el dato para no hacerlo. Se marca P1 y no P0 porque la receta impresa también lleva la vigencia (contrato:3952) y la verificación es un apoyo, no la única barrera.
**Nota positiva verificada:** la página pública **no muestra de más**. Se comprobó campo por campo contra `PrescriptionVerifyOutputSerializer` (contrato:3800-3827): cero datos del paciente, cero medicamentos, cero diagnóstico, cero `controlled_folio`. Solo folio, estado, fecha, nombre y cédula del médico, nombre de la clínica, marca de controlado y vigencia — exactamente lo que envía el backend.

### F-1C-14 · El mapeo de 403 borra el mensaje del backend, justo donde el motivo importa
**Severidad:** P2
**Backend:** los dos 403 de este alcance que **no** son de rol traen un mensaje que explica la regla real: "Solo el médico emisor o un administrador puede anular esta receta." (`recetas/services.py:808`) y "Solo un médico puede emitir recetas. El usuario no tiene un perfil de médico activo en esta clínica." (`recetas/services.py:510-512`). También `PatientStatementPermission.message` (`permisos.py:515`).
**Frontend:** `src/lib/apiErrors.ts:27` — `if (err.status === 403) return ['No tienes permiso para esta acción.']`, **antes** de mirar `err.body.detail`. Todos los consumidores del módulo pasan por ahí: `src/components/expediente/RecetasTab.tsx:273,409,757`, `src/components/finanzas/CobrosPagosTab.tsx:103,249`, `src/components/finanzas/CotizacionesTab.tsx:397`, `src/components/finanzas/SedeIndicador.tsx:62-67`.
**Qué ve el usuario:** es el multiplicador de F-1C-03 y F-1C-04. El médico que no puede anular la receta de un colega y el administrador que no puede emitir reciben el mismo texto genérico que si su puesto no tuviera acceso al módulo, y llaman a soporte porque "el sistema dice que no tengo permiso y sí lo tengo". La excepción bien hecha es `EstadoCuentaExpediente` (`src/components/expediente/EstadoCuentaExpediente.tsx:59-73`), que sí distingue el 403 y añade "El acceso a costos lo define tu clínica" — pero tampoco usa el `detail` del backend.
**Clase:** botón fantasma (el mensaje que lo acompaña)

---

### NO VERIFICABLE

1. **Rol cacheado tras cambiar de sesión.** `useRole()` alimenta todos los gates de este cruce. No se pudo confirmar desde el código si el rol persistido sobrevive a un cambio de usuario en la misma pestaña, porque `src/auth/RoleContext.tsx` y `src/lib/tokenStore.ts` quedan fuera de este alcance (son del Cruce 3). **Para confirmarlo:** leer `RoleContext` y comprobar si se reinicializa en `logout` y en `reloadMe`, y si el `queryClient` se vacía.
2. **`useCharges` en el expediente para un médico sin el flag.** `src/components/expediente/EstadoCuentaExpediente.tsx:46` llama a `useCharges({patient_id})` sin condicionarlo; con `doctors_see_costs=false` el backend responde 403 (`permisos.py:582-585`). En teoría el componente nunca se monta porque `verEstadoCuenta` sería false, pero no lo pude comprobar en ejecución. **Para confirmarlo:** entrar como `doctor` en una clínica con el flag apagado y revisar la pestaña de red al abrir un expediente.
3. **Descarga de un PDF fuera del alcance de sede.** Contrato:5124-5128 y 4119-4122 documentan que la revalidación del `kind` es solo por rol y no conoce sucursales. No pude construir el caso desde el frontend porque el `job_id` solo se obtiene del endpoint que sí acota por sede (`finanzas/views.py:727`). **Para confirmarlo:** un test de integración que encole un `finance_report` como owner en la sede Centro y lo descargue con el token de un admin acotado a Norte.
4. **`ReporteTab.tsx` y `DashboardTab.tsx` son componentes huérfanos.** Ningún `import` los referencia desde una página (`src/pages/FinanzasPage.tsx:5-8` solo monta Caja, Cobranza, Resumen y Cfdi). Llevan su propio gating de rol que no audité porque no se renderiza. **Para confirmarlo y cerrar:** borrarlos o volver a enrutarlos; mientras existan, cualquier auditoría futura los volverá a contar.

---

### Defectos del contrato detectados

Ninguno en este alcance. Se verificaron contra el código las diez afirmaciones del contrato que este cruce necesitaba y las diez coinciden:

| Afirmación del contrato | Verificado en |
|---|---|
| `FinanceConceptPermission` GET = O A F R L + D, escritura solo O (contrato:347) | `permisos.py:317-338` y `permisos.py:301` |
| `FinanceQuotePermission` deprecada y sin uso (contrato:348) | ninguna vista la referencia — `finanzas/views.py:514,644,673,689,713` usan `QuotePermission` |
| `QuotePermission` = O A D R, +L solo GET (contrato:349) | `permisos.py:365-390` |
| `TreatmentPackagePermission` GET O A D R, escritura solo O (contrato:350) | `permisos.py:393-414` |
| `FinancePaymentPermission` sin PATCH ni DELETE → 403 (contrato:352, 4629) | `permisos.py:435-447` |
| `CfdiPermission`: recepción no factura (contrato:354) | `permisos.py:590-602` |
| `RetentionPermission` = O A F L (contrato:375) | `permisos.py:1119-1136` |
| `PatientStatementPermission` / `ChargeListPermission` fail-closed con `doctors_see_costs` (contrato:381-386) | `permisos.py:502-588` y `:461-497` |
| `FinanceDeskPermission` en `finanzas/views.py:92`, GET O A F R (contrato:421) | `finanzas/views.py:92-101`, aplicado en `:1297` |
| `PdfJobStatusApi`/`PdfJobFileApi` responden 404 al fallar el permiso del `kind` (contrato:439-441) | `apps/pdfs/views.py:36-42, 60-66, 92-94` |
| `PrescriptionPermission` deja fuera a R y F; el service exige perfil Doctor y emisor para anular (contrato:370, 3684) | `permisos.py:935-981`, `recetas/services.py:508-513` y `:797-808` |

---

## Cruce 1D · Mi Consultorio, personal, autenticación, bitácora y plataforma

Leyenda de roles de clínica: **O**=owner · **A**=admin · **D**=doctor · **N**=nurse ·
**R**=reception · **F**=finance · **L**=readonly. Roles de plataforma: **SA**=super_admin ·
**S**=sales · **E**=engineering.

Rutas abreviadas: `contrato` = `MailySoft/docs/02-contrato.md` · `be/` =
`MailySoft/backend/apps/` · `fe/` = `MailySoft/web-soft/src/`.

**Nota de entrada, vale para toda la tabla de clínica.** La página `/mi-consultorio` está cerrada
a O A D por `puedeAccederConsultorio` (`fe/auth/permisos.ts:152-153`, aplicado en
`fe/App.tsx:70` y en el menú `fe/components/Topbar.tsx:140`). Todo lo que el backend abre a N R F L
dentro de esa página es inalcanzable por construcción; lo anoto una vez aquí y en cada fila digo
solo qué roles de los tres que sí entran ven la acción.

---

### Tabla de cruce · clínica (Mi Consultorio · Personal · Autenticación · Bitácora)

| Acción | Backend permite (archivo:línea) | Front la muestra a (archivo:línea) | Veredicto |
|---|---|---|---|
| Ver configuración de la clínica `GET /clinica/configuracion/` | O A D N L (`contrato:5424`; `be/clinica/permissions.py:37-38`) | O A D en Mi Consultorio (`fe/pages/MiConsultorioPage.tsx:108-119`); además **todos** los roles con acceso a Contactos, incluidos R y F (`fe/components/contactos/ExpedienteDrawer.tsx:94`) | **BOTÓN FANTASMA** (R, F) + **FUNCIÓN INVISIBLE** (N, L) → F-1D-07 |
| Editar configuración / membrete / `doctors_see_costs` `PUT` | O A (`contrato:5425`; `be/clinica/permissions.py:39`) | O A (`fe/pages/MiConsultorioPage.tsx:59,73`; `fe/components/consultorio/SeccionDatosClinica.tsx:141,196`) | ALINEADO |
| Listar y ver plantillas clínicas `GET /clinica/plantillas/` | O A D N L (`contrato:5465`; `be/clinica/permissions.py:54`) | O A D (`fe/pages/MiConsultorioPage.tsx:81,118`) | FUNCIÓN INVISIBLE (N, L) |
| Crear / editar / dar de baja plantilla | O A D (`contrato:5466-5469`; `be/clinica/permissions.py:22,55-57`) | O A D (`fe/auth/permisos.ts:160-161`; `fe/pages/MiConsultorioPage.tsx:60,81`) | ALINEADO |
| Listar categorías de paciente `GET /clinica/categorias/` | los 7 (`contrato:5488`; `be/clinica/permissions.py:71`) | O A D (`fe/pages/MiConsultorioPage.tsx:83,118`) | FUNCIÓN INVISIBLE (N R F L) |
| Crear / desactivar categoría | O A (`contrato:5489-5490`; `be/clinica/permissions.py:72-73`) | O A (`fe/pages/MiConsultorioPage.tsx:83`; `fe/components/consultorio/SeccionCategorias.tsx:51,55,99`) | ALINEADO |
| Ver universidades y credenciales de un médico `GET` | los 7, sobre **cualquier** médico (`contrato:5527,5543,5823-5825`; `be/clinica/permissions.py:87-88`) | solo O y D, y solo sobre **su propio** `doctor_id` de `/me/` (`fe/pages/MiConsultorioPage.tsx:66,97`; `fe/components/consultorio/SeccionPerfilMedico.tsx:24,40`) | FUNCIÓN INVISIBLE |
| Editar sello, foto y cédulas adicionales `PATCH /clinica/doctores/<id>/perfil/` | O A D, D solo el propio (`contrato:5509,5514-5517`; `be/clinica/permissions.py:26,90`) | O y D. **A queda fuera** (`fe/pages/MiConsultorioPage.tsx:66,115`) | **FUNCIÓN INVISIBLE** → F-1D-09 |
| Alta y baja de universidades del médico | O A D, D solo el propio (`contrato:5528-5529`) | O y D (`fe/pages/MiConsultorioPage.tsx:66`) | FUNCIÓN INVISIBLE (A) → F-1D-09 |
| Alta / edición / baja de credenciales | O A D, D solo el propio (`contrato:5544-5546`) | O y D (`fe/components/consultorio/SeccionPerfilMedico.tsx:149,175`) | FUNCIÓN INVISIBLE (A) → F-1D-09 |
| Ver la bandeja de validación `GET /clinica/credenciales/` | O A, comparación de strings a mano (`contrato:5547,5551`; `be/clinica/views.py:770-777`) | O A (`fe/pages/MiConsultorioPage.tsx:95,105-106,117`) | ALINEADO |
| Validar / rechazar una credencial `PATCH .../validar/` | O A, ídem a mano (`contrato:5548`; `be/clinica/views.py:796-803`) | O A (`fe/components/consultorio/SeccionCredencialesValidar.tsx:140,168`) | ALINEADO |
| Ver el catálogo de equipo `GET /clinica/equipo/` | O A **D** (`contrato:5585`; `be/clinica/permissions.py:99,106`) | O A (`fe/pages/MiConsultorioPage.tsx:91,105-106,117`) | FUNCIÓN INVISIBLE (D) → F-1D-11 |
| Crear / editar / borrar equipo | O A (`contrato:5586-5589`; `be/clinica/permissions.py:107-109`) | O A (`fe/components/consultorio/SeccionEquipo.tsx:56`) | ALINEADO |
| Listar sucursales `GET /clinica/sucursales/` | los 7, acotado por `allowed_sucursales` (`contrato:5606,5612-5614`; `be/clinica/permissions.py:134`) | solo O, y oculto además si `sede_unica` (`fe/pages/MiConsultorioPage.tsx:102,112,116`). La lectura real la cubre el selector del Topbar | FUNCIÓN INVISIBLE (menor) |
| Crear / editar / desactivar sucursal | **solo O** (`contrato:5607-5610,5810`; `be/clinica/permissions.py:131,135-137`) | **solo O** (`fe/pages/MiConsultorioPage.tsx:65,75,116`; `fe/components/consultorio/SeccionSucursales.tsx:138,146,243`) | ALINEADO — el admin **no** puede crear ni editar sedes desde la UI |
| Ver las sedes asignadas a un miembro `GET /clinica/membresias/<id>/sucursales/` | O A (`contrato:5637`; `be/clinica/permissions.py:159`) | O A (`fe/components/personal/SucursalesMiembro.tsx:46-47,69`) | ALINEADO |
| Reasignar las sedes de un miembro `PUT` | O A; el admin solo la diferencia simétrica dentro de su alcance (`contrato:5638,5648-5657,5814-5816`) | O A, sin replicar la regla fina: se apoya en el error del backend y lo muestra tal cual (`fe/components/personal/SucursalesMiembro.tsx:35-41,78-91`) | ALINEADO (la regla es de pertenencia, no de rol; el front hace lo correcto al no adivinarla) |
| Preguntas de historia clínica `GET /expediente/preguntas-hc/` | O A D N L (`contrato:373`) | O A (`fe/pages/MiConsultorioPage.tsx:105-106,117`) | FUNCIÓN INVISIBLE (D N L) → F-1D-11 |
| Escribir preguntas de historia clínica | O A (`contrato:373`) | O A (`fe/pages/MiConsultorioPage.tsx:93`) | ALINEADO |
| Catálogo de analitos `GET /expediente/analitos/` | O A **D** (`contrato:366`) | O A (`fe/pages/MiConsultorioPage.tsx:105-106`) | FUNCIÓN INVISIBLE (D) → F-1D-11 |
| Escribir analitos | O A (`contrato:366`) | O A (`fe/pages/MiConsultorioPage.tsx:89`) | ALINEADO |
| Plantillas de documento `GET /expediente/plantillas-documento/` | O A **D** (`contrato:365`) | O A (`fe/pages/MiConsultorioPage.tsx:105-106`) | FUNCIÓN INVISIBLE (D) → F-1D-11 |
| Escribir plantillas de documento | O A (`contrato:365`) | O A (`fe/pages/MiConsultorioPage.tsx:87`) | ALINEADO |
| Ver formatos de receta `GET /recetas/formatos/` | los 7 (`contrato:372`; `be/core/permissions.py:1024`) | O A D (sección visible a quien entra a la página, `fe/pages/MiConsultorioPage.tsx:79,118`) | FUNCIÓN INVISIBLE (N R F L) |
| Crear / editar formato de receta `POST` / `PATCH` | O A **D** (`contrato:372`; `be/core/permissions.py:1025-1026`) | O A (`fe/pages/MiConsultorioPage.tsx:59,79`; `fe/components/consultorio/SeccionFormatos.tsx:150,159`) | **FUNCIÓN INVISIBLE** → F-1D-10 |
| Borrar formato de receta `DELETE` | O A (`be/core/permissions.py:1027`) | O A (`fe/components/consultorio/SeccionFormatos.tsx:292`) | ALINEADO |
| Ver el horario de la agenda `GET /agenda/config/` | los 7 (`contrato:345`) | O A (`fe/pages/MiConsultorioPage.tsx:105-106,117`) | FUNCIÓN INVISIBLE (D) → F-1D-11 |
| Cambiar el horario de la agenda `PATCH` | O A (`contrato:345`) | O A (`fe/components/consultorio/SeccionHorarioAgenda.tsx:86,145`) | ALINEADO |
| Ver servicios y precios `GET /finanzas/conceptos/` | O A D F R L (`contrato:347`) | **solo O** en esta pantalla (`fe/pages/MiConsultorioPage.tsx:102,116`) | FUNCIÓN INVISIBLE aquí; el módulo Finanzas tiene otra entrada (fuera de este cruce) |
| Escribir conceptos de servicio | **solo O** (`contrato:347`) | **solo O** (`fe/pages/MiConsultorioPage.tsx:85`) | ALINEADO |
| Entrar a `/personal` | `PersonalPermission` GET = los 7 + guard `RequiresPersonal` (`contrato:6001-6003,6297`) | **solo O A L** — D N R F no tienen la clave `personal` en la matriz (`fe/auth/permisos.ts:105-111,115`; `fe/App.tsx:47,161`) | **FUNCIÓN INVISIBLE** → F-1D-12 |
| Listar médicos `GET /personal/doctores/` | los 7, acotado por sede (`contrato:6019,6297`) | O A L (por el guard de ruta) | FUNCIÓN INVISIBLE → F-1D-12 |
| Crear perfil de médico `POST` | O A (`contrato:6020,6299`) | O A (`fe/pages/PersonalPage.tsx:23,127`; `fe/components/personal/MiembroDetalleDrawer.tsx:349,425`) | ALINEADO |
| Editar cédula / especialidad / duración / semblanza `PATCH` | O A (`contrato:6022,6300`) | O A (`fe/components/personal/MiembroDetalleDrawer.tsx:152-171`) | ALINEADO |
| Reasignar consultorios y sedes de un médico | O A, admin por diferencia simétrica (`contrato:6301`) | O A (`fe/components/personal/MiembroDetalleDrawer.tsx:383-424`) | ALINEADO |
| Desactivar un médico `DELETE /personal/doctores/<id>/` | O A (`contrato:6023,6302`) | **nadie: no hay UI** (`fe/api/personal.ts:35` existe, sin llamador en componentes) | FUNCIÓN INVISIBLE → F-1D-13 |
| Listar consultorios `GET` | los 7, por sede (`contrato:6083,6303`) | O A L (guard de `/personal`) | FUNCIÓN INVISIBLE → F-1D-12 |
| Crear / editar / desactivar consultorio | O A, sede resuelta por `resolve_write_sucursal` (`contrato:6084-6087,6305-6307`) | O A (`fe/pages/PersonalPage.tsx:22,91,166`) | ALINEADO |
| Listar horarios de un médico `GET` | los 7, por sede (`contrato:6111,6308`) | O A (dentro de la ficha del equipo, `fe/components/personal/HorariosDoctor.tsx:48`) | FUNCIÓN INVISIBLE |
| Crear horario `POST` | O A (`contrato:6112,6309`) | O A (`fe/components/personal/HorariosDoctor.tsx:152,178`) | ALINEADO |
| Desactivar horario `DELETE` | O A (`contrato:6113,6310`) | O A (`fe/components/personal/HorariosDoctor.tsx:138`) | ALINEADO |
| Editar un horario | **nadie** — la vista no implementa `patch`: 405 para O A, 403 para el resto (`contrato:6131-6135,6311`) | no se ofrece; el componente documenta "editar = borrar y crear" (`fe/components/personal/HorariosDoctor.tsx:12`) | ALINEADO |
| Ver tipos de cita `GET` | los 7 + `RequiresAgenda` (`contrato:6332-6334`) | O A L (guard de `/personal`) | FUNCIÓN INVISIBLE → F-1D-12 |
| Crear / editar tipo de cita | O A (`contrato:6332-6334`) | O A (`fe/pages/PersonalPage.tsx:22,130`; `fe/components/personal/TiposCitaTab.tsx:12,47`) | ALINEADO |
| Listar el equipo `GET /miembros/` | O A; el admin solo roles operacionales de sus sedes **más él mismo** (`contrato:6323`; `be/tenancy/selectors.py:180-187`) | O A (`fe/pages/PersonalPage.tsx:23,25,127`); el front oculta además el grupo "Dueño" al no-owner (`fe/components/personal/EquipoTab.tsx:46,75`) | ALINEADO |
| Alta de miembro `POST /miembros/` | O A; nunca `owner`; el admin nunca `admin`; el rol debe estar en `ent.roles` (`contrato:6324-6326,6169`; `be/tenancy/services.py:218-230,247-253`) | O A; se excluye `owner` siempre, `admin` salvo owner, y se filtra por `capabilities.roles` de `/me/` (`fe/components/personal/NuevoMiembroDrawer.tsx:32-39`) | ALINEADO |
| Editar la ficha de **otro** miembro `PATCH /miembros/<id>/` | O A dentro de su alcance (`contrato:6324`; `be/tenancy/views.py:70-108`) | O A (`fe/components/personal/MiembroDetalleDrawer.tsx:118-125,273`) | ALINEADO |
| Editar la **propia** ficha siendo `admin` | **404** — `_member_get_or_404` rechaza a un no-owner sobre un target no operacional, incluido él mismo (`contrato:6215-6216`; `be/tenancy/views.py:103-108`, `be/tenancy/services.py:76-105`) | el admin ve su propia tarjeta y el panel completo de edición (`be/tenancy/selectors.py:185` la deja en la lista; `fe/components/personal/EquipoTab.tsx:136`, `fe/components/personal/MiembroDetalleDrawer.tsx:273,310-314`) | **BOTÓN FANTASMA** → F-1D-03 |
| Cambiar el rol de un miembro `PATCH` | O A; el admin solo roles operacionales; **sin** validar plan ni dueño único (`be/tenancy/services.py:385-388,406-411`) | O: los 7 incluido `owner`; A: los 5 operacionales (`fe/components/personal/MiembroDetalleDrawer.tsx:85-86,306-308`) | ALINEADO con el código · **contradice el contrato** (ver defectos) |
| Restablecer la contraseña de un miembro | O A dentro de su alcance (`contrato:6327`) | O A (`fe/components/personal/MiembroDetalleDrawer.tsx:127-134,328-332`) | ALINEADO |
| Bloquear / desbloquear una cuenta | O A, nunca la propia (`contrato:6328`; `be/tenancy/services.py:439-440`) | O A, botón deshabilitado si `esYoMismo` (`fe/components/personal/MiembroDetalleDrawer.tsx:335-336`) | ALINEADO |
| Subir el avatar de un miembro `POST /miembros/<id>/avatar/` | O A dentro de su alcance (`contrato:6329`; `be/tenancy/views.py:244`) | O A (`fe/components/personal/MiembroDetalleDrawer.tsx:200-210`) | ALINEADO (salvo el caso propio del admin, F-1D-03) |
| Quitar el avatar de un miembro `DELETE` | O A (`contrato:343,6329`; `be/tenancy/views.py:264`) | **nadie: no hay UI ni función de API** (`fe/api/miembros.ts:1-27`) | FUNCIÓN INVISIBLE → F-1D-13 |
| `POST /auth/login/` | público (`contrato:7180,7385`) | público (`fe/pages/LoginPage.tsx:60-70`) | ALINEADO |
| "¿Olvidaste tu contraseña?" | **no existe endpoint** (`contrato:7198-7202`) | botón visible para cualquiera, **sin `onClick`** (`fe/pages/LoginPage.tsx:172-174`) | **BOTÓN FANTASMA** → F-1D-04 |
| Cambiar la propia contraseña `POST /auth/change-password/` | todos los roles; mínimo **10** caracteres (`contrato:7322,7389-7391`; `MailySoft/backend/config/settings/base.py:416-417`) | todos; el formulario valida y promete **8** (`fe/pages/CambiarContrasenaPage.tsx:113-114,179`) | **BOTÓN FANTASMA** → F-1D-05 |
| `POST /auth/logout/` | `IsAuthenticated` (`contrato:7182`) | todos (`fe/platform/PlatformTopbar.tsx:37-45`) | ALINEADO |
| `GET /me/` con `active_role: null` (sin membresía o clínica suspendida) | 200 con `active_tenant: null`; **403 en toda la API de clínica** (`contrato:7387-7388,7654-7655`; `be/core/permissions.py:29-33`) | el front sustituye el `null` por `'readonly'` y pinta la app de clínica (`fe/auth/RoleContext.tsx:15`; `fe/pages/LoginPage.tsx:20`; `fe/App.tsx:50`) | **BOTÓN FANTASMA** → F-1D-06 |
| Leer la bitácora de la clínica `GET /audit/logs/` | **solo O** (`contrato:7715`; `be/audit/permissions.py:22,33-35`) | **nadie: no existe pantalla** (búsqueda de `audit/logs` en `fe/`: solo aparece en `fe/types/openapi.d.ts:315`) | **FUNCIÓN INVISIBLE** → F-1D-08 |

Nota de la fila de sucursales: `GET /clinica/sucursales/` devuelve **solo sedes activas**
(`contrato:5630-5631`), pero `fe/components/consultorio/SeccionSucursales.tsx:232` pinta una
insignia "Inactiva" que nunca puede aparecer. Es UI muerta, no deriva de permisos.

---

### Tabla de cruce · portal interno de plataforma

| Acción | Backend permite (archivo:línea) | Front la muestra a (archivo:línea) | Veredicto |
|---|---|---|---|
| Ver métricas globales `GET /plataforma/metricas/` | SA S E (`contrato:7832,8118`) | SA S E (`fe/platform/permisos.ts:22-24`, clave `dashboard`) | ALINEADO |
| Listar clínicas `GET /plataforma/clinicas/` | SA S E, **solo GET/HEAD** (`contrato:7833,8119`; `be/core/permissions.py:1193`) | SA S E (`fe/platform/permisos.ts:22-24`, clave `clinicas`); el front nunca manda otro método a esa ruta (`fe/api/plataforma.ts:49`) | ALINEADO |
| Ver la ficha de una clínica `GET /plataforma/clinicas/<id>/` | SA S E (`contrato:7835,8120`) | SA S E (`fe/pages/plataforma/ClinicasPage.tsx:136,163`) | ALINEADO |
| Crear una clínica `POST /plataforma/clinicas/` | SA S (`contrato:7834,8121`) | SA S (`fe/pages/plataforma/ClinicasPage.tsx:25,68`) | ALINEADO |
| Suspender / reactivar una clínica `POST .../estado/` | SA S (`contrato:7836,8122`) | SA S (`fe/pages/plataforma/ClinicasPage.tsx:139-149`; `fe/components/plataforma/ClinicaDetailDrawer.tsx:177-189`) | ALINEADO |
| Asignar o cambiar el plan `POST .../suscripcion/` | SA S (`contrato:7837,8123`) | SA S (`fe/pages/plataforma/SuscripcionesPage.tsx:47`) | ALINEADO |
| **Ajustar derechos a la medida `POST .../entitlements/`** | **solo SA** (`contrato:7838,8124`; `be/plataforma/services.py:613-616`) | **SA y S** — el botón "Ajustar" se gatea con el permiso de `clinicas` (`fe/components/plataforma/ClinicaDetailDrawer.tsx:108-113` con `puedeEditar` de `fe/pages/plataforma/ClinicasPage.tsx:25,163`) | **BOTÓN FANTASMA** → F-1D-02 |
| Listar el equipo interno `GET /plataforma/usuarios/` | **solo SA** (`contrato:7839,8129`) | solo SA (`fe/platform/permisos.ts:22-24`, clave `usuarios`) | ALINEADO |
| Crear / editar staff, restablecer su contraseña | **solo SA** (`contrato:7840-7842,8130-8135`) | solo SA (`fe/pages/plataforma/UsuariosPage.tsx:61,102-104`) | ALINEADO |
| No tocar el propio `platform_role` ni el propio `is_active` | prohibido a todos (`contrato:8133`; `be/plataforma/services.py:1140-1146`) | el modal oculta rol y "Activo" en la fila propia (`fe/components/plataforma/StaffFormModal.tsx:144-145,186-190,294,310`) | ALINEADO |
| Bitácora cross-tenant `GET /plataforma/auditoria/` | SA E (`contrato:7843,8136`) | SA E (`fe/platform/permisos.ts:22,24`, clave `auditoria`) | ALINEADO |
| Salud del sistema `GET /plataforma/sistema/` | SA E (`contrato:7844,8138`) | SA E (`fe/platform/permisos.ts:22,24`, clave `sistema`) | ALINEADO |
| Listar planes `GET /plataforma/planes/` | SA S (`contrato:7845,8125`) | SA (`edit`) y S (`view`) (`fe/platform/permisos.ts:22-23`, clave `planes`) | ALINEADO |
| Crear / editar un plan | **solo SA** (`contrato:7846-7847,8126-8127`) | solo SA (`fe/pages/plataforma/SuscripcionesPage.tsx:49`) | ALINEADO |
| Listado y resumen de suscripciones | SA S (`contrato:7848-7849,8128`) | SA S (`fe/pages/plataforma/SuscripcionesPage.tsx:47`; `fe/pages/plataforma/DashboardPage.tsx:21-22`) | ALINEADO |
| **Con qué rol de plataforma se navega** | inmutable en la sesión: el backend lee `user.platform_role` (`contrato:7134,7142-7143`; `be/authn/models.py:70-76`) | cualquier staff lo reescribe desde el menú "Ver como (demo)" (`fe/platform/PlatformTopbar.tsx:97-104`; `fe/platform/PlatformRoleContext.tsx:7,28`), y `PlatGuard` obedece ese rol local (`fe/App.tsx:87,90`) | **BOTÓN FANTASMA** → F-1D-01 |
| Rol efectivo antes de que responda `/me/` | ídem | `useState<PlatformRole>('super_admin')` (`fe/platform/PlatformRoleContext.tsx:19`) | **BOTÓN FANTASMA** → F-1D-01 |
| Staff de plataforma **sin** `TenantMembership` en la API de clínica | 403 en todo (`contrato:7654-7655`; `be/core/permissions.py:29-33`) | tras el login va al panel (`fe/pages/LoginPage.tsx:18`) y el enlace "Ir a mi clínica" solo aparece con `clinicRole` (`fe/platform/PlatformTopbar.tsx:105-111`); pero escribir `/agenda` o `/mi-consultorio` a mano lo trata como `readonly` (`fe/auth/RoleContext.tsx:15`) | **BOTÓN FANTASMA** → F-1D-06 |

---

### Hallazgos

**Ninguno es P0.** Verificado punto por punto: ningún hallazgo de este cruce concede acceso que el
backend no tenga ya, ni expone datos de otra clínica. La autoridad de permisos aguanta en los tres
lugares donde el front se equivoca (rol local de plataforma, rol `readonly` inventado, y las dos
comprobaciones a mano de credenciales).

### F-1D-01 · El menú "Ver como (demo)" deja a cualquier staff de Maily navegar como súper admin
**Severidad:** P1
**Backend:** `MailySoft/docs/02-contrato.md:7134` y `MailySoft/backend/apps/authn/models.py:70-76` — el rol de plataforma es un campo del `User`; las 9 clases de `§1.3.4` lo leen del token, no del cliente. `PlatformStaffListPermission` es solo `super_admin` (`contrato:7839`).
**Frontend:** `MailySoft/web-soft/src/platform/PlatformRoleContext.tsx:19` arranca en `'super_admin'` pase lo que pase y solo lo corrige un `useEffect` cuando llega `/me/` (`:21-26`); `setRole` queda expuesto (`:28`) y `MailySoft/web-soft/src/platform/PlatformTopbar.tsx:97-104` lo ofrece como menú "Ver como (demo)". `MailySoft/web-soft/src/App.tsx:87,90` gatea las rutas de plataforma con ese rol local, no con el real.
**Qué ve el usuario:** un ingeniero de Maily (`platform_role="engineering"`) abre el menú de su avatar, elige "Súper Admin" y el topbar le pinta Suscripciones y Equipo. Entra a Equipo y la lista queda vacía con "No se pudo cargar" — el backend contestó 403. Lo mismo le pasa a Ventas con Sistema y Auditoría. Además, durante el primer render de cualquier sesión el topbar muestra la navegación de súper admin a los tres roles.
**Clase:** botón fantasma

### F-1D-02 · Ventas ve el botón "Ajustar" de derechos a la medida, que es exclusivo del súper admin
**Severidad:** P1
**Backend:** `MailySoft/docs/02-contrato.md:7838` y `:8124` — `POST /api/v1/plataforma/clinicas/<id>/entitlements/` usa `PlatformPlanWritePermission` (solo `super_admin`), y el service lo revalida en `MailySoft/backend/apps/plataforma/services.py:613-616`.
**Frontend:** `MailySoft/web-soft/src/components/plataforma/ClinicaDetailDrawer.tsx:108-113` muestra "Ajustar" si `puedeEditar`, y esa prop llega desde `MailySoft/web-soft/src/pages/plataforma/ClinicasPage.tsx:25,163`, donde vale `puedeEditarPlat(role,'clinicas')` = super_admin **y** sales (`MailySoft/web-soft/src/platform/permisos.ts:23`). El modal que abre sí escribe: `MailySoft/web-soft/src/components/plataforma/AjustesClinicaModal.tsx:38` usa `useSetClinicaEntitlements`.
**Qué ve el usuario:** un vendedor cierra el trato de encender el módulo Recetas a la Clínica Dental del Valle. Abre la ficha, pulsa "Ajustar", marca Recetas, guarda — y recibe un error 403 sin explicación. Peor si no mira: cree que ya lo dejó encendido y el cliente llama el lunes porque no ve el módulo.
**Clase:** botón fantasma

### F-1D-03 · Un administrador ve su propia ficha y no puede guardar nada en ella: el backend responde 404
**Severidad:** P1
**Backend:** `MailySoft/backend/apps/tenancy/selectors.py:180-187` deja la membresía del propio actor en el listado aunque no sea operacional (`visibility_q |= Q(id=viewer_membership_id)`), pero `MailySoft/backend/apps/tenancy/views.py:103-108` (`_member_get_or_404`, compartido por `MemberDetailApi` y `MemberAvatarApi`, `:204,244,264`) devuelve **404** cuando el actor no es owner y el objetivo tiene rol no operacional — un `admin` sobre sí mismo cae exactamente ahí. El service repite el veto en `MailySoft/backend/apps/tenancy/services.py:76-105`. Documentado en `MailySoft/docs/02-contrato.md:6215-6216`.
**Frontend:** `MailySoft/web-soft/src/components/personal/EquipoTab.tsx:74-76,136` pinta la tarjeta del propio admin y abre el drawer con `puedeEditar={enabled}` = true; `MailySoft/web-soft/src/components/personal/MiembroDetalleDrawer.tsx:273,310-314` muestra el panel completo (nombre, rol, restablecer contraseña, avatar) y `:122` dispara `PATCH /miembros/<id>/`.
**Qué ve el usuario:** la administradora de la sede Norte entra a Personal → Equipo → Administrador → se ve a sí misma, corrige su apellido mal escrito y pulsa "Guardar cambios". Sale "Miembro no encontrado". Lo mismo al cambiar su foto. El único que puede corregirle el apellido es el dueño.
**Clase:** botón fantasma

### F-1D-04 · "¿Olvidaste tu contraseña?" es un botón sin comportamiento y sin endpoint detrás
**Severidad:** P1
**Backend:** `MailySoft/docs/02-contrato.md:7198-7202` — "No hay endpoint de registro público, ni de 'olvidé mi contraseña', ni de verificación de correo", verificado sobre `apps/authn/urls.py:19-22`. Quien pierde la contraseña depende de que el dueño la restablezca.
**Frontend:** `MailySoft/web-soft/src/pages/LoginPage.tsx:172-174` — `<button type="button">` con estilo de enlace, **sin `onClick`**.
**Qué ve el usuario:** la recepcionista de la Clínica Centro olvidó su contraseña un lunes a las 7:30. Pulsa el enlace tres veces y no pasa nada; no hay texto que le diga que tiene que pedírsela al dueño. Es la clase de caso que termina en una llamada a soporte.
**Clase:** botón fantasma

### F-1D-05 · La pantalla de cambio de contraseña promete 8 caracteres y el backend exige 10
**Severidad:** P1
**Backend:** `MailySoft/backend/config/settings/base.py:416-417` — `MinimumLengthValidator` con `min_length: 10`, aplicado en `password_change` (`MailySoft/docs/02-contrato.md:7322,7333`).
**Frontend:** `MailySoft/web-soft/src/pages/CambiarContrasenaPage.tsx:113-114` valida `nueva.length < 8` y `:179` rotula el campo "Nueva contraseña (mínimo 8 caracteres)". El resto del front sí usa 10 (`MailySoft/web-soft/src/components/personal/NuevoMiembroDrawer.tsx:55`, `MailySoft/web-soft/src/components/personal/MiembroDetalleDrawer.tsx:129`), así que es esta pantalla la que está mal.
**Qué ve el usuario:** el dueño de una clínica recién dada de alta entra por primera vez con su contraseña temporal. `RequireAuth` lo encierra en `/cambiar-contrasena` (`MailySoft/web-soft/src/auth/RequireAuth.tsx:47-49`): es la única pantalla que puede usar. Escribe una de 9 caracteres, la pantalla la acepta, el backend la rechaza con "Nueva contraseña: La contraseña es demasiado corta…" y el rótulo sigue diciendo 8. Primera experiencia del cliente con el producto.
**Clase:** botón fantasma

### F-1D-06 · Sin membresía activa el front inventa el rol `readonly` y pinta una app de clínica que responde 403 entera
**Severidad:** P1
**Backend:** `MailySoft/docs/02-contrato.md:7387-7388` — `/me/` responde 200 con `active_role: null` cuando el usuario no tiene clínica o la tiene `suspended`; `MailySoft/backend/apps/core/permissions.py:29-33` devuelve **403 en toda la API de clínica** a quien no tiene `TenantMembership` (`contrato:7654-7655`), y `core/tenant_context.py:157-160` hace lo mismo con una clínica suspendida.
**Frontend:** `MailySoft/web-soft/src/auth/RoleContext.tsx:15` sustituye ese `null` por `'readonly'`; `MailySoft/web-soft/src/pages/LoginPage.tsx:20` manda a `/agenda` a quien no es staff de plataforma y no tiene rol; y `MailySoft/web-soft/src/App.tsx:47,50` deja pasar porque `accesoModulo('readonly','agenda')` es `'view'` y el guard de módulo se salta mientras `capabilities` sea `null`.
**Qué ve el usuario:** Maily suspende a la Clínica del Bosque por falta de pago. El dueño entra al día siguiente, el login funciona, aterriza en la agenda con su nombre arriba y la rejilla vacía; cada panel dice "no se pudo cargar". Nadie le dice que la clínica está suspendida. Le pasa igual a un `sales` de Maily que teclee `/agenda` a mano.
**Clase:** botón fantasma

### F-1D-07 · El expediente pide la configuración de la clínica para recepción y finanzas, que reciben 403
> **Consolidado en `F-1A-09`.** El mismo defecto lo encontró otro cruce con un escenario mejor. Se conserva aquí la evidencia porque el ángulo es distinto, pero **no cuenta como hallazgo aparte** en el total del resumen.
**Severidad:** P2
**Backend:** `MailySoft/docs/02-contrato.md:5424,5794,5820-5822` — `ClinicSettingsPermission.GET` usa `CLINICAL_READ` (`MailySoft/backend/apps/clinica/permissions.py:38`), que **excluye a `reception` y `finance`**. Es la brecha B-CLI-11 ya registrada.
**Frontend:** `MailySoft/web-soft/src/components/contactos/ExpedienteDrawer.tsx:94-95` llama `useClinicSettings()` sin condicionar por rol, solo para leer `doctors_see_costs`. El drawer lo abre `MailySoft/web-soft/src/pages/ContactosPage.tsx:531`, y `reception` y `finance` tienen acceso a Contactos (`MailySoft/web-soft/src/auth/permisos.ts:109-110`).
**Qué ve el usuario:** nada roto — el valor cae a `false` por el `?? false` y `puedeVerEstadoCuenta` ya devuelve `true` para esos dos roles por otra vía (`MailySoft/web-soft/src/auth/permisos.ts:208-215`). Lo que queda es un 403 en cada apertura de expediente de recepción y de caja, que ensucia la bitácora y los registros de Sentry y hace ruido al depurar cualquier otro 403 real.
**Clase:** botón fantasma

### F-1D-08 · El dueño puede leer la bitácora de su clínica y no existe pantalla para hacerlo
**Severidad:** P2
**Backend:** `MailySoft/backend/apps/audit/permissions.py:22,33-35` — `AuditLogPermission` GET = `frozenset({owner})`; `GET /api/v1/audit/logs/` devuelve la bitácora completa del tenant con metadata, IP y user-agent (`MailySoft/docs/02-contrato.md:7715`).
**Frontend:** no existe. Búsqueda de `audit/logs` en todo `MailySoft/web-soft/src/`: la única aparición es el tipo generado `MailySoft/web-soft/src/types/openapi.d.ts:315`. La única pantalla de auditoría del front es la **cross-tenant de plataforma** (`MailySoft/web-soft/src/App.tsx:177`), que un dueño de clínica no puede abrir.
**Qué ve el usuario:** el dueño de la Clínica Norte quiere saber quién anuló la receta de un paciente el martes. La API se lo diría; el producto no tiene dónde preguntárselo. Está construido, probado y documentado (§12 completa) y ningún cliente lo puede usar. La bitácora es requisito NOM-024, así que es capacidad regulatoria muerta, no solo una función escondida.
**Clase:** función invisible

### F-1D-09 · El administrador no puede tocar su propio perfil médico aunque el backend se lo permite
**Severidad:** P2
**Backend:** `MailySoft/backend/apps/clinica/permissions.py:26,89-91` — `_DOCTOR_PROFILE_WRITE` = owner, admin, doctor para sello, foto, cédulas adicionales, universidades y credenciales; el guard M-1 de "solo tu propio perfil" aplica **únicamente al rol `doctor`** (`MailySoft/docs/02-contrato.md:5514-5517,5801-5803`). Y `/me/` sí devuelve `doctor_id` a un admin que ejerce, porque `ROLES_QUE_PUEDEN_EJERCER` lo incluye (`contrato:5928,7240-7241`).
**Frontend:** `MailySoft/web-soft/src/pages/MiConsultorioPage.tsx:66` define `editaPerfil = role === 'owner' || role === 'doctor'` y lo usa en `:97` y `:115`. El helper que sí refleja la regla del backend, `puedeGestionarPerfilMedico` (`MailySoft/web-soft/src/auth/permisos.ts:165-166`, owner/admin/doctor), está definido y **no se usa en ninguna parte** del código.
**Qué ve el usuario:** en una clínica chica el administrador suele ser también profesional — el propio contrato lo dice (`contrato:5928-5930`). Ese administrador-médico entra a Mi Consultorio y no encuentra "Mi perfil médico": no puede subir su sello, ni su foto, ni capturar sus credenciales COFEPRIS, aunque sus recetas las van a necesitar. Tiene que pedirle al dueño que lo haga por él desde otra pantalla.
**Clase:** función invisible

### F-1D-10 · El médico no puede crear ni editar su formato de receta, que es justamente para lo que se diseñó el permiso
> **Consolidado en `F-1C-08`.** El mismo defecto lo encontró otro cruce con un escenario mejor. Se conserva aquí la evidencia porque el ángulo es distinto, pero **no cuenta como hallazgo aparte** en el total del resumen.
**Severidad:** P2
**Backend:** `MailySoft/backend/apps/core/permissions.py:1025-1026` — `PrescriptionFormatPermission` POST y PATCH = owner, admin **y doctor**, con la razón escrita en el docstring (`:1010-1011`: "Los médicos pueden crear su formato personal"). DELETE sí es solo owner/admin (`:1027`). En el contrato, `§1.3.2` #35 (`MailySoft/docs/02-contrato.md:372`).
**Frontend:** `MailySoft/web-soft/src/pages/MiConsultorioPage.tsx:79` pasa `editable={gestionable}` (owner/admin) a la sección "Configuración de recetas"; `MailySoft/web-soft/src/components/consultorio/SeccionFormatos.tsx:150,159,202` esconde el botón de crear y el editor y muestra el aviso de solo lectura.
**Qué ve el usuario:** el médico de la clínica entra a Mi Consultorio → Configuración de recetas, ve la galería de formatos y un aviso de que no puede editar. No puede armar su membrete personal aunque el backend lo aceptaría; tiene que pedirle al administrador que lo haga.
**Clase:** función invisible

### F-1D-11 · Cinco catálogos que el médico puede leer y que el menú de Mi Consultorio le oculta
**Severidad:** P2
**Backend:** el GET admite al rol `doctor` en los cinco: equipo/departamentos (`MailySoft/backend/apps/clinica/permissions.py:99,106`, con el motivo escrito: "el médico lo consulta al armar el Plan Integral"), plantillas de documento (`MailySoft/docs/02-contrato.md:365`), analitos (`:366`), preguntas de historia clínica (`:373`, `CLINICAL_READ`) y horario de la agenda (`:345`, `AgendaConfigPermission` GET = los 7, "abierto para poder dibujar la rejilla").
**Frontend:** `MailySoft/web-soft/src/pages/MiConsultorioPage.tsx:105-107` mete las cinco secciones en `soloGestion` y `:117` las condiciona a `gestionable` = owner/admin.
**Qué ve el usuario:** el médico abre Mi Consultorio y su menú lateral tiene 4 entradas donde el dueño tiene 12. No puede consultar el catálogo de analitos antes de pedir un laboratorio, ni ver qué preguntas trae la historia clínica de su clínica, ni consultar el equipo que va a firmar el Plan Integral que está redactando.
**Clase:** función invisible

### F-1D-12 · La pantalla de Personal está cerrada a médico, enfermería, recepción y finanzas, y el backend los deja leer todo
**Severidad:** P2
**Backend:** `MailySoft/docs/02-contrato.md:6001,6297,6303,6308` y `:6332` — `PersonalPermission` GET = los 7 roles para médicos, consultorios y horarios (acotados por sede), y `AppointmentTypePermission` GET = los 7 para tipos de cita. Solo la escritura es owner/admin.
**Frontend:** `MailySoft/web-soft/src/auth/permisos.ts:105-111` — la clave `personal` solo existe para `owner` (`edit`), `admin` (`edit`) y `readonly` (`view`); `doctor`, `nurse`, `reception` y `finance` **no la tienen**. `MailySoft/web-soft/src/App.tsx:47,161` redirige a quien no la tenga, y `MailySoft/web-soft/src/components/Topbar.tsx:45` le quita la entrada del menú.
**Qué ve el usuario:** la recepcionista de la sede Centro necesita saber en qué consultorio atiende hoy la Dra. Ruiz y con qué horario, para acomodar un hueco. La API se lo daría acotado a su sede; el menú no tiene "Personal" y escribir `/personal` la devuelve a la agenda. La misma pantalla es la única que lista los tipos de cita, que ella usa todo el día.
**Clase:** función invisible

### F-1D-13 · Dos acciones de escritura sin ninguna UI: desactivar un médico y quitar el avatar de un miembro
**Severidad:** P2
**Backend:** `DELETE /api/v1/personal/doctores/<id>/` = owner/admin, baja lógica irreversible por API (`MailySoft/docs/02-contrato.md:6023,6073,6302`). `DELETE /api/v1/miembros/<id>/avatar/` = owner/admin (`contrato:343,6329`; `MailySoft/backend/apps/tenancy/views.py:264`).
**Frontend:** la función de API del primero existe pero no la llama ningún componente (`MailySoft/web-soft/src/api/personal.ts:35`, sin uso fuera de `hooks/personal.ts`); la del segundo **ni siquiera está escrita** (`MailySoft/web-soft/src/api/miembros.ts:1-27` solo tiene list, create, update y upload de avatar).
**Qué ve el usuario:** se va un médico de la clínica. El dueño bloquea su cuenta (eso sí existe), pero su perfil de médico sigue activo y sigue apareciendo en el selector de médicos de la agenda y en los listados. No hay botón que lo apague. Y un miembro con una foto de perfil equivocada solo la puede reemplazar, nunca quitar.
**Clase:** función invisible

---

### NO VERIFICABLE

1. **Si un `admin` puede llegar por la UI a reescribir las sedes del dueño (B-CLI-01).** Tengo el
   lado backend: `PUT /clinica/membresias/<id>/sucursales/` no valida jerarquía de roles
   (`MailySoft/docs/02-contrato.md:5659-5662`). Del lado front, el único camino es
   `SucursalesMiembro` dentro del drawer del equipo, y ahí el `admin` nunca ve al dueño porque
   `MailySoft/backend/apps/tenancy/selectors.py:180-187` lo excluye del listado. No encontré ruta de
   UI, pero tampoco descarté que un `membership.id` cacheado por TanStack Query de una sesión
   anterior lo alcance. **Para confirmarlo:** un test e2e con actor `admin` que abra el drawer con el
   id de membresía del dueño inyectado a mano y observe si el `PUT` sale y con qué código responde.

2. **Qué peticiones dispara realmente un `sales` en el primer render del panel.**
   `MailySoft/web-soft/src/platform/PlatformRoleContext.tsx:19` arranca en `'super_admin'` y
   `MailySoft/web-soft/src/pages/plataforma/DashboardPage.tsx:16-17,21-22` decide con ese rol si
   consulta `/plataforma/auditoria/` y `/plataforma/suscripciones/resumen/`. Leí el código pero no lo
   ejecuté: no sé si el `useEffect` de corrección gana la carrera antes de que se monte el
   `useQuery`. **Para confirmarlo:** entrar como `sales`, abrir la pestaña de red y buscar un 403 en
   `/api/v1/plataforma/auditoria/` en el primer segundo de sesión.

3. **Si `MiembroDetalleDrawer` rompe en una clínica sin el módulo `personal`.** El drawer llama
   `useDoctorsManage`, `useConsultoriosManage` y `useSucursales`
   (`MailySoft/web-soft/src/components/personal/MiembroDetalleDrawer.tsx:71-73`), y los dos primeros
   pegan a `apps/personal`, que sí lleva `RequiresPersonal` y responde **404**
   (`MailySoft/docs/02-contrato.md:5887-5889`). Ese cruce es el 2 (gating por módulo), no lo mapeé.
   **Para confirmarlo:** una clínica con el módulo `personal` apagado y `miembros` accesible, y ver
   qué pinta el drawer.

---

### Defectos del contrato detectados

**D-1 · `§8.5` afirma que crear un segundo dueño está bloqueado "incluso para el owner"; por PATCH no lo está.**
`MailySoft/docs/02-contrato.md:6326` dice: "Crear un segundo `owner` | **no** | … 400 incluso para
el owner (solo el bootstrap de plataforma lo evita, `:231-238`)", citando
`MailySoft/backend/apps/tenancy/services.py:223-230`. Esa comprobación vive **solo dentro de
`member_create`**. `member_update` (`MailySoft/backend/apps/tenancy/services.py:406-411`) valida
únicamente que el rol esté en `_VALID_ROLES` y guarda:

```python
if role is not None:
    if role not in _VALID_ROLES:
        raise ValidationError(f"Rol inválido '{role}'.")
    membership.role = role
```

Es decir: un dueño **sí** puede ascender a un miembro existente a `owner` con
`PATCH /api/v1/miembros/<id>/` y la clínica queda con dos dueños. El frontend ofrece exactamente ese
camino: `MailySoft/web-soft/src/components/personal/MiembroDetalleDrawer.tsx:85-86` incluye `owner`
en el selector de rol cuando el actor es el dueño. La fila de la matriz debe distinguir alta de
edición, o el backend debe replicar la regla en `member_update`.

**D-2 · `§8.5` no dice que el PATCH de rol se salta la allow-list del plan.**
`MailySoft/docs/02-contrato.md:668-669` acota bien la regla al alta ("Se hace valer al dar de alta un
miembro", `services.py:247-253`), pero la matriz de `:6324` ("Ver / editar / dar de alta a un
miembro") no distingue, y el lector natural asume que editar el rol también se valida. No es así:
`member_update` no consulta `entitlements_for_tenant` en ningún punto
(`MailySoft/backend/apps/tenancy/services.py:380-411`). Consecuencia real: en plan **Básico** —que no
incluye `admin` ni `finance`— el alta rechaza esos roles con 400, pero el PATCH los acepta. El
frontend refuerza la asimetría: filtra por `capabilities.roles` al dar de alta
(`MailySoft/web-soft/src/components/personal/NuevoMiembroDrawer.tsx:32-39`) y **no** al editar
(`MailySoft/web-soft/src/components/personal/MiembroDetalleDrawer.tsx:85-86`). El miembro queda con
un rol que el plan no cubre y luego recibe 404 en todos los endpoints de su módulo.

---

## Cruce 2 · Gating por módulo

Rutas absolutas abreviadas: `BE/` = `/Users/emanuelrealgamboa/Desktop/Maily360/MailySoft/backend/`,
`FE/` = `/Users/emanuelrealgamboa/Desktop/Maily360/MailySoft/web-soft/src/`.

### Tabla A · Espejo del catálogo

| elemento | backend (`BE/apps/core/modules.py`) | frontend (`FE/lib/modulos.ts`) | veredicto |
|---|---|---|---|
| `agenda` / "Agenda y citas" | `:28` | `:14`, `:20` | IDÉNTICO |
| `recordatorios` / "Recordatorios de cita" | `:29` | `:14`, `:21` | IDÉNTICO |
| `expediente` / "Expediente clínico" | `:30` | `:14`, `:22` | IDÉNTICO |
| `recetas` / "Recetas" | `:31` | `:14`, `:23` | IDÉNTICO |
| `notas` / "Notas y tareas" | `:32` | `:14`, `:24` | IDÉNTICO |
| `servicios` / "Servicios y precios" | `:35` | `:15`, `:25` | IDÉNTICO |
| `paquetes` / "Paquetes" | `:36` | `:15`, `:26` | IDÉNTICO |
| `cotizaciones` / "Cotizaciones" | `:37` | `:15`, `:27` | IDÉNTICO |
| `cobranza` / "Cobranza y estado de cuenta" | `:38` | `:15`, `:28` | IDÉNTICO |
| `cfdi` / "Facturación CFDI" | `:39` | `:15`, `:29` | IDÉNTICO |
| `calendarizacion` / "Calendarización de tratamientos" | `:42` | `:16`, `:30` | IDÉNTICO |
| `personal` / "Gestión de personal" | `:45` | `:16`, `:31` | IDÉNTICO |
| `MODULE_REQUIRES` → `MODULO_REQUIERE` (5 entradas: recordatorios→agenda, paquetes→servicios, cotizaciones→servicios, cfdi→cobranza, calendarizacion→{expediente,servicios,cotizaciones}) | `:50-60` | `:35-41` | IDÉNTICO |
| `ROLE_REQUIRES` → `ROL_REQUIERE` (7 roles; doctor/nurse→expediente, reception→agenda, finance→cobranza, owner/admin/readonly vacíos) | `:66-74` | `:44-52` | IDÉNTICO |
| `MODULE_GROUPS` → `MODULO_GRUPOS` (Clínico 5, Comercial 5, Especiales 1, Operación 1) | `:78-101` | `:55-60` | IDÉNTICO (mismo orden) |
| `expandir_dependencias` vs `expandirDependencias` (cierre transitivo con pila) | `:119-139` | `:69-82` | EQUIVALENTE — misma semántica |
| `roles_disponibles` vs `rolesDisponibles` (`requeridos <= activos` ≡ `every(r => activos.has(r))`) | `:192-208` | `:106-111` | EQUIVALENTE |
| Universo de módulos: `ALL_MODULES = frozenset(Module.values)` vs `TODOS_LOS_MODULOS = MODULO_GRUPOS.flatMap(...)` | `:104` | `:63` | **DIVERGE EN ORIGEN** → F-2-11 |
| `dependencias_faltantes` `:142`, `validar_modulos` `:162` | sí | sin equivalente | ESPERADO (validación es del backend, `modules.py:163-166`) |
| `dependientesDe` (cascada al apagar) | sin equivalente | `:88-103` | ESPERADO (ajuste en vivo del super-admin) |

Consumidores reales del espejo: `FE/components/plataforma/EditorModulos.tsx:17-20`, `:80`, `:86`;
`FE/components/plataforma/AjustesClinicaModal.tsx:14-17`, `:56`, `:62`, `:110`;
`FE/components/plataforma/ClinicaDetailDrawer.tsx:8`, `:140`.

**Veredicto del espejo: sincronizado.** Los 12 slugs, sus etiquetas, las 5 dependencias duras, los 7
roles y los 4 grupos coinciden uno a uno. La única diferencia estructural es de dónde sale la lista
completa de módulos (F-2-11).

---

### Tabla B · Rutas vs guards

| ruta | `modulo=` / `requiere=` (`FE/App.tsx`) | endpoints que consume | guard `Requires*` del backend | veredicto |
|---|---|---|---|---|
| `/agenda` | `modulo="agenda" requiere="agenda"` `:159` | `/agenda/citas/`, `/agenda/eventos/`, `/agenda/disponibilidad/`, `/agenda/config/` (`FE/api/agenda.ts:36,95,61`; `FE/api/agendaConfig.ts:15`) | `RequiresAgenda` en `AppointmentListCreateApi` `BE/apps/agenda/views.py:154`/`:159`, `AgendaBlockListCreateApi` `:894`/`:899`, `AgendaDisponibilidadApi` `:430`/`:447`, `AgendaConfigApi` `:700`/`:705` | COINCIDE |
| `/agenda` (dependencia oculta) | igual | `/personal/doctores/`, `/personal/consultorios/` (`FE/hooks/agenda.ts:161`, `:171` → `FE/api/personal.ts:21`, `:44`) | `RequiresPersonal` `BE/apps/personal/views.py:74`, `:329` | **NO COINCIDE** → F-2-08 |
| `/contactos` | `modulo="contactos"`, **sin** `requiere` `:160` | `/pacientes/*` (`FE/api/pacientes.ts:52-105`), `/clinica/categorias/` (`FE/api/clinica.ts:128`) | `PatientPermission` sin guard de módulo `BE/apps/pacientes/views.py:112`, `:281`; `PatientCategoryPermission` `BE/apps/clinica/views.py:319` | **COINCIDE** — pacientes no es módulo vendible (`Topbar.tsx:31` lo documenta) |
| `/contactos` → `ExpedienteDrawer` | hereda: sin `requiere` | evoluciones/signos/diagnósticos/historia (`FE/hooks/expediente.ts` vía `IndiceSecciones.tsx:52-54`) | `RequiresExpediente` `BE/apps/expediente/views_evoluciones.py:99`, `:335`; `views_signos.py:80`; `views_historia.py:52` | **NO COINCIDE** → F-2-06 |
| `/contactos` → `ExpedienteDrawer` | hereda | `/expediente/<id>/recetas/` (`FE/api/recetas.ts:70`) | `RequiresRecetas` `BE/apps/recetas/views.py:199` | COINCIDE — gateado en `IndiceSecciones.tsx:44` |
| `/contactos` → `ExpedienteDrawer` | hereda | `/finanzas/estado-cuenta/<id>/` (`FE/api/finanzas.ts:705`) | `RequiresCobranza` `BE/apps/finanzas/views.py:1109` (`AccountStatementApi` `:1102`) | **PARCIAL** — gateado en la sección (`IndiceSecciones.tsx:46`), NO en el badge (`ExpedienteDrawer.tsx:122`) → F-2-07 |
| `/contactos` → `CalendarizacionTab` | hereda | `/expediente/calendarizacion/*` | `RequiresCalendarizacion` `BE/apps/expediente/views_calendarizacion.py:137` | COINCIDE — gateado en `IndiceSecciones.tsx:45` |
| `/personal` | `modulo="personal" requiere="personal"` `:161` | `/personal/consultorios/` (`FE/api/personal.ts:44`), `/miembros/` (`FE/api/miembros.ts:8`) | `RequiresPersonal` `BE/apps/personal/views.py:329`; `/miembros/` **sin** guard de módulo `BE/apps/tenancy/views.py:118` | COINCIDE (el front es más restrictivo en `/miembros/`; sin impacto: todo plan activo trae `personal`) |
| `/notas` | `modulo="notas" requiere="notas"` `:162` | `/notas/*` (`FE/api/notas.ts:13-42`) | `RequiresNotas` `BE/apps/notas/views.py:95`, `:213`, `:331` | COINCIDE |
| `/finanzas` → Caja / Cobranza / Resumen | `modulo="finanzas" requiere="cobranza"` `:163` | `/finanzas/cargos/`, `/pagos/`, `/dashboard/`, `/reporte/`, `/cierre-diario/`, `/retencion/` (`FE/api/finanzas.ts:558,608,97,183,277,348`) | `RequiresCobranza` `BE/apps/finanzas/views.py:766`, `:898`, `:1143`, `:1178`, `:1297`, `:1365` | COINCIDE |
| `/finanzas` → pestaña **Facturación** | igual (`requiere="cobranza"`) | `/finanzas/cfdi/` (`FE/api/finanzas.ts:658`, `:662`) | `RequiresCfdi` `BE/apps/finanzas/views.py:989` (`CfdiListCreateApi` `:984`), `:1077` | **NO COINCIDE** → F-2-02 |
| `/cotizaciones` | `modulo="cotizaciones" requiere="cotizaciones"` `:164` | `/finanzas/cotizaciones/` (`FE/api/finanzas.ts:473`), `/finanzas/conceptos/` (`:380`) | `RequiresCotizaciones` `BE/apps/finanzas/views.py:514`; `RequiresServicios` `:201` | COINCIDE (`cotizaciones` arrastra `servicios`, `modules.py:53`) |
| `/cotizaciones` → selector de paquete | igual | `/finanzas/paquetes/` (`FE/api/paquetes.ts:29`, `CotizacionesTab.tsx:97`) | `RequiresPaquetes` `BE/apps/finanzas/views.py:383` (`PackageListCreateApi` `:374`) | **NO COINCIDE** → F-2-09 |
| `/paquetes` | `modulo="cotizaciones" requiere="paquetes"` `:167` | `/finanzas/paquetes/` (`FE/api/paquetes.ts:29`), `/finanzas/conceptos/` (`PaquetesPage.tsx:7`) | `RequiresPaquetes` `BE/apps/finanzas/views.py:383`, `:441`; `RequiresServicios` `:201` | COINCIDE — ver nota abajo |
| `/mi-consultorio` | **sin `ClinicRoute`**: `ConsultorioRoute` solo de rol `:168`, `:76-82` | `/recetas/formatos/`, `/expediente/preguntas-hc/`, `/expediente/plantillas-documento/`, `/expediente/analitos/`, `/agenda/config/`, `/finanzas/conceptos/` | `RequiresRecetas` `BE/apps/recetas/views.py:554`; `RequiresExpediente` `BE/apps/expediente/views_preguntas.py:46`, `views_catalogos.py:77`, `:182`; `RequiresAgenda` `BE/apps/agenda/views.py:705`; `RequiresServicios` `BE/apps/finanzas/views.py:201` | **NO COINCIDE** (solo `servicios` está gateado, `MiConsultorioPage.tsx:114`) → F-2-05 |
| global `<AlertaCitas />` `:186` | ninguno (fuera de `ClinicRoute` y de `RequireAuth`) | `/agenda/citas/` (`AlertaCitas.tsx:73`) | `RequiresAgenda` `BE/apps/agenda/views.py:159` | condicionado a rol (`AlertaCitas.tsx:70`), no a módulo — sin impacto práctico (todo plan trae `agenda`) |
| global `<LuzRecordatorios />` `:188` | ninguno | `/notas/recordatorios/` (`FE/api/notas.ts:42`) | `RequiresNotas` `BE/apps/notas/views.py:331` (`NoteRemindersApi` `:324`) | condicionado a `!!user` (`LuzRecordatorios.tsx:46`), no a módulo ni a tenant → dispara 404 en el panel de plataforma |

**Nota sobre `/paquetes` (App.tsx:167).** El gating de módulo es correcto: `requiere="paquetes"` ↔
`RequiresPaquetes`. El `modulo="cotizaciones"` es gating de **rol**: `PERMISOS[rol].cotizaciones`
(`FE/auth/permisos.ts:105-111`) admite owner/admin/doctor/reception, exactamente los mismos que
`TreatmentPackagePermission.policy["GET"]` (`BE/apps/core/permissions.py:410`). Coincide hoy **por
casualidad**: son dos listas mantenidas por separado que no se declaran ligadas en ningún lado. El
comentario de `App.tsx:165-166` ("no es un Modulo del menú → solo RequireAuth aquí") contradice a la
línea 167, que sí pasa `modulo`.

**`recordatorios`.** Confirmado: el frontend **no condiciona nada** a ese módulo. `grep -rn
"'recordatorios'" FE/` solo devuelve `lib/modulos.ts:14` y `:56` (el catálogo). Ver F-2-04.

**`calendarizacion`.** La UI **no** lo asume disponible: `IndiceSecciones.tsx:45` exige
`tieneModulo('calendarizacion')`, y el override está enrutado en
`AjustesClinicaModal.tsx:110-131` (grupo "Especiales"). Correcto.

---

### Hallazgos

### F-2-01 · La clínica Premium compra CFDI y no hay pantalla para capturar los datos fiscales del emisor
> **Consolidado en `F-1C-02`.** El mismo defecto lo encontró otro cruce con un escenario mejor. Se conserva aquí la evidencia porque el ángulo es distinto, pero **no cuenta como hallazgo aparte** en el total del resumen.
**Severidad:** P1
**Backend:** `BE/apps/finanzas/views.py:330-333` — `FiscalConfigApi` (`GET`/`PATCH /finanzas/config/`)
con `FinanceConfigPermission, RequiresCfdi`. `BE/apps/finanzas/services.py:1148-1150` — timbrar
aborta con `ValidationError("Configura los datos fiscales del emisor (RFC) antes de timbrar.")` si
no hay `ClinicFiscalConfig` con RFC. `BE/apps/tenancy/management/commands/seed_planes.py:130-147`
(plan `premium`) vende `cfdi`.
**Frontend:** `FE/api/finanzas.ts:723-728` y `FE/hooks/finanzas.ts:327-334` existen
(`useFiscalConfig`, `useUpdateFiscalConfig`) y **no los importa nadie**: `grep -rn "fiscalConfig\|FiscalConfig" FE/`
solo devuelve esas definiciones. La capacidad `manageFiscalConfig` está declarada en
`FE/auth/permisos.ts:23` y `:47` y tampoco se usa en ninguna pantalla.
**Qué ve el usuario:** clínica en plan Premium ($8,900/mes, comprado explícitamente por la
facturación). La dueña entra a Finanzas → Facturación, elige un paciente y un pago, escribe el RFC
del receptor y pulsa "Emitir CFDI". El backend responde 400 "Configura los datos fiscales del emisor
(RFC) antes de timbrar." y **no existe ninguna pantalla en toda la app donde configurarlos**. El
módulo más caro del catálogo es inutilizable desde la interfaz.
**Clase:** gating de módulo desalineado (camino inverso: módulo activo sin pantalla enrutada)

### F-2-02 · La pestaña Facturación se pinta por rol y nunca pregunta por el módulo `cfdi`
**Severidad:** P1
**Backend:** `BE/apps/finanzas/views.py:984`, `:989` — `CfdiListCreateApi` con `RequiresCfdi` →
404 (`BE/apps/core/entitlement_guards.py:84`).
`BE/apps/tenancy/management/commands/seed_planes.py:37-42` — `_COMERCIAL` (lo que trae el plan `pro`)
es `servicios, paquetes, cotizaciones, cobranza`: **sin `cfdi`**. `pro` es el plan destacado
(`seed_planes.py:109`, `:126` `is_featured: True`).
**Frontend:** `FE/pages/FinanzasPage.tsx:44-45` declara la pestaña `facturacion` con
`capability: 'viewCfdi'` y `:67` la filtra **solo por rol** (`TABS.filter(t => can(role, t.capability))`).
`FE/components/finanzas/CfdiTab.tsx:29` lanza `useCfdiList()` sin comprobar `tieneModulo('cfdi')`;
`:91` solo distingue `isLoading`; con error cae al `map` de `:107` y muestra el vacío de `:134-137`.
El botón "Emitir CFDI" se pinta con `canIssue = can(role, 'issueCfdi')` (`:33`).
**Qué ve el usuario:** clínica en plan Pro (el que más se vende). El dueño entra a Finanzas, ve la
pestaña **Facturación**, elige un paciente y lee **"Sin comprobantes."** — idéntico a lo que vería
una clínica que sí tiene CFDI y aún no ha timbrado nada. Pulsa "Emitir CFDI", llena el formulario y
recibe **"No encontrado."**. No hay en ninguna parte la frase "tu plan no incluye facturación".
**Clase:** gating de módulo desalineado

### F-2-03 · No existe ningún manejador que distinga "no contratado" de "no existe el registro"
**Severidad:** P1
**Backend:** `BE/apps/core/entitlement_guards.py:84` — `raise NotFound("No encontrado.")` para módulo
apagado. El cuerpo es `{"detail": "No encontrado."}`, **byte por byte el mismo** que el 404 anti-IDOR
de un id ajeno o inexistente (`BE/apps/pacientes/views.py`, documentado en
`FE/types/openapi.d.ts:920`, `:940`, `:962`). El propio docstring del guard
(`entitlement_guards.py:12-16`) explica que la indistinguibilidad es deliberada hacia fuera.
**Frontend:** `FE/lib/apiErrors.ts:27` trata el 403 con un mensaje propio; `:29-37` vuelca
`body.detail` tal cual para todo lo demás; `:61-63` `esSinPermiso()` existe para 403 y **no hay
equivalente para 404**. `FE/lib/http.ts:216-220` propaga el `status` sin clasificarlo.
`FE/lib/queryClient.ts:17-20` no reintenta 4xx (correcto) pero nadie interpreta el resultado.
`grep -rn "404" FE/` devuelve solo comentarios y tipos: **cero código de manejo**.
**Qué ve el usuario:** es el multiplicador de F-2-02, F-2-05, F-2-06, F-2-07, F-2-08 y F-2-09. La
recepcionista de una clínica Básico abre un paciente y el saldo desaparece sin explicación; el dueño
de una Pro ve "Sin comprobantes"; el de una clínica con `recetas` revocado ve "No encontrado." en
Configuración de recetas y llama a soporte creyendo que se le borraron los formatos. Ninguno de los
tres puede llegar solo a la conclusión correcta ("tu plan no lo incluye"), que además es la única que
genera una venta.
**Clase:** gating de módulo desalineado

### F-2-04 · `recordatorios` se cobra en todos los planes, no bloquea nada y la UI lo muestra sin condición
**Severidad:** P1
**Backend:** `BE/apps/core/entitlement_guards.py:93` define `RequiresRecordatorios` y **ninguna vista
lo usa** (verificado: `grep -rn "Requires" BE/apps --include="*.py"` no devuelve una sola aparición,
y `require_module` no se invoca en ningún punto de `apps/`). `BE/apps/agenda/reminders.py:20`
(`schedule_reminders_for_appointment`) programa los WhatsApp en cada alta de cita sin consultar
entitlements. `BE/apps/tenancy/management/commands/seed_planes.py:27-33` mete `RECORDATORIOS` en
`_CLINICO`, es decir en los cinco planes, y `:71` y `:97` lo listan como feature de venta
("Recordatorios WhatsApp"). Coincide con B-T-07 del contrato (`docs/02-contrato.md:462`).
**Frontend:** cero referencias al slug fuera del catálogo: `grep -rn "'recordatorios'" FE/` →
`lib/modulos.ts:14` y `:56`, nada más. `FE/components/agenda/DetalleCitaModal.tsx:291-296` pinta el
bloque "Recordatorios" de forma incondicional. No existe pantalla para `reminders_enabled` ni
`reminder_offsets_minutes`, aunque los tipos ya están escritos (`FE/types/agendaConfig.ts:18-19`).
**Qué ve el usuario:** el super-admin apaga `recordatorios` a una clínica desde "Ajustes a la medida"
(`FE/components/plataforma/AjustesClinicaModal.tsx:118`), por ejemplo porque la clínica no quiso
pagarlo. La clínica **sigue enviando WhatsApp** en cada cita y los sigue viendo en el detalle de la
cita como si nada. Además, ninguna clínica puede configurar los offsets desde la UI. Es P1 porque hay
dinero de por medio en las dos direcciones: envíos con costo que se ejecutan sin contrato, y un
módulo facturado que el cliente no puede tocar.
**Clase:** gating de módulo desalineado

### F-2-05 · `/mi-consultorio` no pasa por `ClinicRoute`: siete de sus trece secciones consumen endpoints con guard de plan
**Severidad:** P2
**Backend:** `RequiresRecetas` en `/recetas/formatos/` (`BE/apps/recetas/views.py:554`, `:617`);
`RequiresExpediente` en `/expediente/preguntas-hc/` (`BE/apps/expediente/views_preguntas.py:46`,
`:94`), `/expediente/plantillas-documento/` (`views_catalogos.py:77`, `:118`) y
`/expediente/analitos/` (`views_catalogos.py:182`, `:216`); `RequiresAgenda` en `/agenda/config/`
(`BE/apps/agenda/views.py:705`); `RequiresServicios` en `/finanzas/conceptos/`
(`BE/apps/finanzas/views.py:201`).
**Frontend:** `FE/App.tsx:168` enruta con `ConsultorioRoute` (`:76-82`), que solo compone
`RequireAuth` + `ConsultorioGuard` (rol owner/admin/doctor, `:68-72`) — **sin `requiere`**.
`FE/pages/MiConsultorioPage.tsx:108-119` filtra `seccionesVisibles` por sede única, por rol y por un
único módulo: `:114`, `if (s.key === 'servicios' && !tieneModulo('servicios')) return false`. Las
secciones `formatos` `:40`, `historia-clinica` `:47`, `plantillas-documento` `:44`, `analitos` `:45`
y `horario-agenda` `:39` no consultan módulo alguno.
**Qué ve el usuario:** el super-admin revoca `recetas` a un consultorio de nutrición que no receta
(`AjustesClinicaModal.tsx:118`). El dueño entra a Mi Consultorio, sigue viendo "Configuración de
recetas" en el menú lateral y al pulsarla recibe la alerta "No encontrado."
(`FE/components/consultorio/SeccionFormatos.tsx:144-145`). Lo mismo con "Catálogo de analitos" o
"Preguntas de historia clínica" si se revoca `expediente`.
**Clase:** gating de módulo desalineado

### F-2-06 · El expediente clínico se ofrece por rol y nunca pregunta por el módulo `expediente`
**Severidad:** P2
**Backend:** `RequiresExpediente` en evoluciones (`BE/apps/expediente/views_evoluciones.py:99`),
diagnósticos (`:335`), signos (`BE/apps/expediente/views_signos.py:80`) e historia clínica
(`BE/apps/expediente/views_historia.py:52`).
**Frontend:** `FE/components/expediente/IndiceSecciones.tsx:44-47` sí consulta el módulo para
recetas, calendarización, cobranza y agenda — pero `:87-118` construye las secciones `signos`,
`libro`, `diagnosticos` e `historia` **solo** con `accesoClinico`, que es puro rol
(`ExpedienteDrawer.tsx:86` → `puedeVerExpedienteClinico(role)`,
`FE/auth/permisos.ts:117`). Los contadores de `:52-54` disparan las tres queries igualmente.
El propio comentario de `IndiceSecciones.tsx:41-42` declara la regla que estas cuatro secciones no
cumplen.
**Qué ve el usuario:** clínica con `expediente` revocado por override (o recién creada, sin
suscripción: `BE/apps/tenancy/entitlements.py:87` deja `modulos = set()` cuando no hay plan). El
médico abre un paciente desde Pacientes y ve cuatro tarjetas —Signos, Libro clínico, Diagnósticos,
Historia clínica— con el contador en blanco; al entrar a cualquiera, "No encontrado.".
**Clase:** gating de módulo desalineado

### F-2-07 · El badge de saldo del expediente consulta cobranza sin comprobar el módulo, mientras la sección de al lado sí lo comprueba
**Severidad:** P2
**Backend:** `BE/apps/finanzas/views.py:1102`, `:1109` — `AccountStatementApi` con
`PatientStatementPermission, RequiresCobranza`.
**Frontend:** `FE/components/expediente/IndiceSecciones.tsx:46` sí lo gatea
(`verCuenta = verEstadoCuenta && tieneModulo('cobranza')`), pero
`FE/components/contactos/ExpedienteDrawer.tsx:122` lanza
`useStatement(verEstadoCuenta && paciente ? paciente.id : null)` con `verEstadoCuenta` calculado solo
por rol y flag de clínica (`:95` → `puedeVerEstadoCuenta`, `FE/auth/permisos.ts:208-215`).
Dos criterios distintos para el mismo módulo en dos archivos que se renderizan juntos.
**Qué ve el usuario:** clínica en plan Básico (`seed_planes.py:88-105`: clínico + `personal`, sin
`cobranza`). La recepcionista abre pacientes durante todo el día; cada apertura dispara una petición
que devuelve 404 y el badge de saldo del encabezado nunca aparece. Nadie sabe si es un error del
sistema o si la clínica "no tiene esa función". La sección de Estado de cuenta, en cambio, ni se
ofrece — lo que hace el hueco aún más confuso.
**Clase:** gating de módulo desalineado

### F-2-08 · La agenda depende del módulo `personal`, que su ruta no exige
**Severidad:** P2
**Backend:** `BE/apps/personal/views.py:69`, `:74` — `DoctorListCreateApi` con
`PersonalPermission, RequiresPersonal`; `:324`, `:329` — `ConsultorioListCreateApi` con el mismo
guard. `BE/apps/core/modules.py:50-60` — `agenda` **no** declara ninguna dependencia.
**Frontend:** `FE/App.tsx:159` exige solo `requiere="agenda"`. `FE/pages/AgendaPage.tsx:10` importa
`useConsultorios` y `useDoctors`, que en `FE/hooks/agenda.ts:161` y `:171` llaman a
`FE/api/personal.ts:21` (`/personal/doctores/`) y `:44` (`/personal/consultorios/`). El mismo par lo
usa `FE/components/expediente/CalendarizacionTab.tsx:51`.
**Qué ve el usuario:** clínica con `personal` revocado por override y `agenda` activa. La
recepcionista entra a la agenda y la reja se dibuja **sin columnas**: no hay médicos ni consultorios
que listar. El modal de crear cita abre con los dos selectores vacíos y la cita no se puede agendar.
La pantalla no dice por qué.
**Clase:** gating de módulo desalineado

### F-2-09 · Cotizaciones y calendarización consumen `paquetes`, que ninguno de los dos requiere
**Severidad:** P2
**Backend:** `BE/apps/core/modules.py:53` (`COTIZACIONES → {SERVICIOS}`) y `:57-59`
(`CALENDARIZACION → {EXPEDIENTE, SERVICIOS, COTIZACIONES}`): **ninguno arrastra `PAQUETES`**.
`BE/apps/finanzas/views.py:374`, `:383` — `PackageListCreateApi` con `RequiresPaquetes`.
**Frontend:** `FE/App.tsx:164` enruta `/cotizaciones` con `requiere="cotizaciones"`;
`FE/components/finanzas/CotizacionesTab.tsx:97` llama `usePaquetes()` y `:325-345` pinta el selector
"Agregar paquete" y su botón. `FE/components/expediente/CalendarizacionTab.tsx:259` hace lo mismo
dentro del expediente, alcanzable con `requiere` heredado de `/contactos` (ninguno).
**Qué ve el usuario:** clínica con `cotizaciones` encendido y `paquetes` apagado por override (el
backend lo permite: `validar_modulos` no exige `paquetes` para `cotizaciones`,
`BE/apps/core/modules.py:162-189`). El médico cotiza en consulta, ve el desplegable "Agregar paquete"
permanentemente vacío y, si intenta usarlo, obtiene "No encontrado.".
**Clase:** gating de módulo desalineado

### F-2-10 · El guard de módulo del frontend falla ABIERTO cuando `/me/` no trae `capabilities`
**Severidad:** P2
**Backend:** `BE/apps/authn/views.py:427-429` — `capabilities` sale **`null`** cuando no hay tenant
activo, no solo mientras carga. `BE/apps/core/entitlement_guards.py:78-84` — el backend hace lo
contrario: sin tenant, `entitlements_del_request` devuelve `None` y el guard responde 404
(*fail-closed*, documentado en `docs/02-contrato.md:489`).
**Frontend:** `FE/App.tsx:50` —
`if (requiere && capabilities !== null && !tieneModulo(requiere))`: con `capabilities === null`
**se salta la comprobación de módulo**. El rol acompaña: `FE/auth/RoleContext.tsx:15` cae a
`'readonly'`, y `PERMISOS.readonly` (`FE/auth/permisos.ts:111`) concede `agenda: 'view'`,
`contactos: 'view'`, `personal: 'view'`, `finanzas: 'view'` y `notas: 'edit'`. El destino por defecto
tras login para un usuario sin `active_role` es `/agenda` (`FE/pages/LoginPage.tsx:20`).
**Qué ve el usuario:** un usuario cuya membresía se desactivó (o un miembro del staff de Maily sin
clínica que teclea `/agenda`) entra con sesión válida, aterriza en la agenda, **atraviesa los cinco
guards de módulo** y ve la pantalla completa fallando petición por petición con "No encontrado.". No
es una fuga —el backend bloquea de verdad— pero es la única ruta por la que el gating del frontend
deja de existir.
**Clase:** gating de módulo desalineado

### F-2-11 · El universo de módulos del frontend se deriva de los grupos, no del catálogo
**Severidad:** P2
**Backend:** `BE/apps/core/modules.py:104` — `ALL_MODULES = frozenset(Module.values)`: sale del enum,
así que un módulo nuevo entra automáticamente.
**Frontend:** `FE/lib/modulos.ts:63` — `TODOS_LOS_MODULOS = MODULO_GRUPOS.flatMap(g => g.modulos)`:
sale de la agrupación de presentación (`:55-60`). Los dos consumidores del catálogo iteran sobre los
grupos, no sobre `ModuloId`: `FE/components/plataforma/EditorModulos.tsx:80` y
`FE/components/plataforma/AjustesClinicaModal.tsx:110`.
**Qué ve el usuario:** hoy no hay divergencia (los 12 coinciden). El día que se agregue un módulo al
enum, a `MODULO_LABEL` y a `MODULE_GROUPS` del backend pero se olvide `MODULO_GRUPOS` del frontend,
TypeScript **no falla** (`MODULO_GRUPOS` es un array, no un `Record<ModuloId, …>` exhaustivo) y el
super-admin simplemente nunca verá la casilla para encenderlo: el módulo queda invendible sin que
nada reviente. Es la única clase de deriva que el espejo actual no puede detectar sola.
**Clase:** gating de módulo desalineado

---

### NO VERIFICABLE

1. **Efecto real de un 404 sobre las pantallas de `/mi-consultorio` que no muestran error.** Verifiqué
   `SeccionFormatos.tsx:144-145` y `SeccionAnalitos.tsx:215-216` (sí renderizan `AlertaErrores`), pero
   no leí completas `SeccionHistoriaClinica.tsx` ni `SeccionPlantillasDocumento.tsx`. **Para
   confirmar:** buscar `isError` en esos dos archivos y comprobar si, como `CfdiTab`, caen al render
   de lista vacía.

2. **Si una clínica puede existir de verdad sin suscripción.** `BE/apps/tenancy/entitlements.py:87`
   deja `modulos = set()` cuando `TenantSubscription` no existe, y eso sostiene el escenario más duro
   de F-2-05 y F-2-06. No revisé el service de alta de clínica del panel de plataforma. **Para
   confirmar:** leer `BE/apps/plataforma/services.py` en la función que crea el tenant y ver si asigna
   plan de forma obligatoria.

3. **Si el backend valida las dependencias al guardar un override.** `BE/apps/plataforma/services.py:579-650`
   (`set_clinic_entitlements`) no llama a `validar_modulos` — solo lo hacen los serializers de **planes**
   (`BE/apps/plataforma/serializers.py:607`, `:665`). Si es así, el super-admin puede dejar
   `calendarizacion` encendida con `cotizaciones` apagada y la única defensa es la expansión del
   frontend (`AjustesClinicaModal.tsx:62`). **Para confirmar:** leer completo
   `set_clinic_entitlements` y su serializer de entrada (`BE/apps/plataforma/views.py:942-946`).

4. **`/notas/recordatorios/` disparándose en el panel de plataforma.** `LuzRecordatorios.tsx:46`
   consulta con `enabled = !!user`, sin comprobar tenant ni módulo, y está montado globalmente
   (`FE/App.tsx:188`), fuera de `RequireAuth` y de cualquier `ClinicRoute`. Con `capabilities === null`
   el backend responde 404 (`entitlement_guards.py:78-84`). Es un 404 recurrente por sesión de staff,
   no un fallo funcional. **Para confirmar:** abrir `/plataforma/dashboard` con una cuenta de staff sin
   clínica y mirar la pestaña de red.

---

### Defectos del contrato detectados

1. **§1.4.1, línea 462 (B-T-07) se queda corto.** El contrato dice que el guard de `recordatorios`
   "no [se aplica] en ninguna vista", que es exacto pero incompleto: omite que (a) la funcionalidad
   **sí se ejecuta** (`BE/apps/agenda/reminders.py:20` programa envíos en cada cita sin consultar
   entitlements) y (b) el módulo **se factura en los cuatro planes** (`seed_planes.py:27-33`, `:70`,
   `:96`). Leído tal cual, B-T-07 parece deuda técnica inocua; en realidad es una capacidad de costo
   que se entrega sin contrato y que un override no puede revocar. Sugerido: ampliar B-T-07 con esas
   dos consecuencias.

2. **§1.4 no documenta que `capabilities` de `/me/` puede ser `null` de forma permanente.** §1.4.3
   (línea 514-515) afirma que "el mismo objeto alimenta el bloqueo del backend y el `capabilities` de
   `/me/`, así que front y backend no se pueden contradecir". No es cierto en el caso sin tenant:
   `BE/apps/authn/views.py:427-429` devuelve `null`, el backend es *fail-closed*
   (`entitlement_guards.py:78-84`) y el frontend es *fail-open* (`FE/App.tsx:50`). Sugerido: anotar el
   caso `capabilities = null` en §1.4.3 con su asimetría.

3. **§1.4.3 no dice si los overrides se validan.** Documenta la fórmula
   `(Plan.modules ∪ modules_on) − modules_off` (línea 502) pero no si el resultado pasa por
   `validar_modulos`. Es la diferencia entre "el super-admin no puede dejar un estado incoherente" y
   "el frontend es la única defensa". Ver NO VERIFICABLE #3.

4. **Comentario obsoleto en el código, no en el contrato.** `FE/App.tsx:165-166` dice que `/paquetes`
   usa "solo `RequireAuth` aquí"; la línea 167 pasa `modulo="cotizaciones" requiere="paquetes"`. No
   afecta al comportamiento, pero es la clase de comentario que lleva al siguiente agente a suponer
   que la ruta no tiene gating.

---

## Cruce 3 · Caché entre clínicas y entre sedes

Rutas relativas a `MailySoft/`. Frontend: `web-soft/src/`. Backend: `backend/`.

**Dos hechos del contrato que fijan la severidad de todo lo que sigue** (verificados, no supuestos):

1. **No existe cambio de clínica dentro de una sesión.** `docs/02-contrato.md:302-304`: *"`X-Tenant-ID`
   no existe en el código"*; un usuario con dos membresías activas **siempre opera sobre la más
   antigua** (`backend/apps/core/tenant_context.py:113`, `:156-165`). El único paso de tenant A a
   tenant B en el mismo navegador es **cambiar de usuario**, y eso pasa obligatoriamente por
   `login()` o `logout()`, que ambos hacen `queryClient.clear()`
   (`web-soft/src/auth/AuthContext.tsx:110` y `:129`). **Ninguna queryKey lleva el tenant, y sin
   embargo el escenario "el médico que trabaja en la clínica A y en la B entra a la B y ve los
   pacientes de A" NO es alcanzable hoy**: no puede entrar a la B.
2. **El alcance por sede no es una barrera de seguridad.** `docs/02-contrato.md:549-552`: un bug de
   sede *"nunca expone otro negocio (eso lo sostiene RLS); en el peor caso expone otra sede del
   mismo negocio — aceptado por diseño"* (`backend/apps/clinica/sucursal_scope.py:4-12`).

Por eso **no hay ningún P0 en este cruce**. Bajar una fuga entre sedes del mismo tenant a P1 no es
suavizar: es lo que dice el contrato. Lo que sí queda es un hueco real (F-3-01) y tres fragilidades.

**Ventana de exposición configurada** (`web-soft/src/lib/queryClient.ts:13-27`):

| Parámetro | Valor | Línea |
|---|---|---|
| `staleTime` | `30_000` (30 s) | `queryClient.ts:16` |
| `gcTime` | **no configurado** → default de `@tanstack/react-query ^5.101.0` = 5 min | ausente en `queryClient.ts:13-27`; versión en `web-soft/package.json:16` |
| `refetchOnWindowFocus` | `false` | `queryClient.ts:21` |

`refetchOnWindowFocus: false` es lo que hace que la ventana **no** sea de 30 s. `staleTime` no
dispara nada por sí solo: solo marca el dato como viejo. Con el foco desactivado, un refetch exige
montar un observer nuevo (navegar y volver), cambiar la key, o invalidar. **Un componente montado de
forma permanente sirve caché vieja indefinidamente.** Ese matiz es el corazón de F-3-01.

---

### Tabla · Inventario de queryKeys

68 `useQuery` en los 20 archivos de `web-soft/src/hooks/`. Cero `useInfiniteQuery`.
Columna "acotado por sede en backend": ✔ = el endpoint llama `sucursal_scope_ids(request)` o
`actor_sucursal_ids`. "invalidado" = cubierto por `invalidateQueries` de prefijo al cambiar de sede
(`web-soft/src/auth/SucursalContext.tsx:105-107`, prefijos `['personal']`, `['agenda']`,
`['finanzas']`).

| hook (archivo:línea) | queryKey | ¿tenant? | ¿sucursal? | ¿acotado por sede en backend? | veredicto |
|---|---|---|---|---|---|
| `useAppointmentsForDay` (hooks/agenda.ts:59) | `['agenda','citas',dayKey,sucursalId]` | no | **sí** | ✔ `apps/agenda/views.py:239` | PASA |
| `useTodayAppointmentsLive` (hooks/agenda.ts:70) | `['agenda','citas',today,sucursalId]` | no | **sí** | ✔ `apps/agenda/views.py:239` | PASA |
| `useAppointmentsForPatient` (hooks/agenda.ts:81) | `['agenda','citas','paciente',patientId,sucursalId]` | no | **sí** | ✔ `apps/agenda/views.py:239` | PASA |
| `useAgendaEvents` (hooks/agenda.ts:97) | `['agenda','eventos',dayKey,sucursalId]` | no | **sí** | ✔ `apps/agenda/views.py:930` | PASA |
| `useAgendaItemNotes` (hooks/agenda.ts:133) | `['agenda','item-notes',kind,id]` | no | no | detalle por id, no acotado (`docs/02-contrato.md:608`) | PASA (invalidado) |
| `useActiveDoctors` (hooks/agenda.ts:164) | `['personal','doctores','activos',sucursalId]` | no | **sí** | ✔ `apps/personal/views.py:118` | PASA |
| `useActiveConsultorios` (hooks/agenda.ts:174) | `['personal','consultorios','activos',sucursalId]` | no | **sí** | ✔ `apps/personal/views.py:359` | PASA |
| `useDisponibilidad` (hooks/agenda.ts:213) | `['agenda','disponibilidad',doctorId,consultorioId,from,to,sucursalId]` | no | **sí** | ✔ `apps/agenda/views.py:461` | PASA |
| `useAppointmentTypes` (hooks/agenda.ts:232) | `['agenda','tipos-cita','activos']` | no | no | no | PASA (catálogo de clínica; invalidado) |
| `useAppointmentTypesManage` (hooks/agenda.ts:241) | `['agenda','tipos-cita','manage']` | no | no | no | PASA (invalidado) |
| `useAgendaConfig` (hooks/agendaConfig.ts:18) | `['agenda','config']` | no | no | no | PASA (config de clínica, declarado en `agendaConfig.ts:13-14`) |
| `useAnalitos` (hooks/analitos.ts:26) | `['analitos','lista',onlyActive]` | no | no | no | PASA |
| `useCalendarizaciones` (hooks/calendarizacion.ts:28) | `['calendarizaciones',patientId]` | no | no | no (lecturas; `views_calendarizacion.py:372,450` son POST) | PASA |
| `useCalendarizacion` (hooks/calendarizacion.ts:37) | `['calendarizacion',planId]` | no | no | no | PASA |
| `useClinicSettings` (hooks/clinica.ts:62) | `['clinica','settings']` | no | no | no | PASA |
| `useTemplates` (hooks/clinica.ts:81) | `['clinica','templates',kind]` | no | no | no | PASA |
| `useCategories` (hooks/clinica.ts:115) | `['clinica','categories']` | no | no | no | PASA |
| `useDoctorActual` (hooks/clinica.ts:145) | `['clinica','doctor-actual',doctorId]` | no | no | no | PASA |
| `useUniversities` (hooks/clinica.ts:172) | `['clinica','universities',doctorId]` | no | no | no | PASA |
| `useCredentials` (hooks/clinica.ts:205) | `['clinica','credentials',doctorId]` | no | no | no | PASA |
| `useCredentialsToValidate` (hooks/clinica.ts:248) | `['clinica','credentials-validate',status]` | no | no | no | PASA |
| `useEquipo` (hooks/equipo.ts:29) | `['equipo','lista',onlyActive]` | no | no | no (`ClinicTeamMemberListCreateApi`, `apps/clinica/views.py:834`, sin scope) | PASA |
| `useAllergies` (hooks/expediente.ts:83) | `['expediente',patientId,'alergias',includeResolved]` | no | no | no | PASA |
| `useHistoria` (hooks/expediente.ts:112) | `['expediente',patientId,'historia']` | no | no | no | PASA |
| `usePreguntasHc` (hooks/expediente.ts:136) | `['expediente','preguntas-hc']` | no | no | no | PASA |
| `useSignos` (hooks/expediente.ts:174) | `['expediente',patientId,'signos']` | no | no | no | PASA |
| `useSignosSeries` (hooks/expediente.ts:183) | `['expediente',patientId,'signos','series',since]` | no | no | no | PASA |
| `useEvoluciones` (hooks/expediente.ts:203) | `['expediente',patientId,'evoluciones']` | no | no | no | PASA |
| `useEvolucionImagenes` (hooks/expediente.ts:233) | `['expediente','evolucion',evolutionId,'imagenes']` | no | no | no | PASA |
| `useIndicacionesEnfermeria` (hooks/expediente.ts:265) | `['expediente',patientId,'indicaciones-enfermeria']` | no | no | no | PASA |
| `useDiagnosticos` (hooks/expediente.ts:276) | `['expediente',patientId,'diagnosticos',onlyActive]` | no | no | no | PASA |
| `useLibroClinico` (hooks/expediente.ts:311) | `['expediente',patientId,'libro',page]` | no | no | no | PASA |
| `useResumenBorrador` (hooks/expediente.ts:355) | `['expediente','evolucion',evolutionId,'resumen-borrador']` | no | no | no | PASA |
| `useResumenes` (hooks/expediente.ts:378) | `['expediente',patientId,'resumenes']` | no | no | no | PASA |
| `useDashboard` (hooks/finanzas.ts:69) | `['finanzas','dashboard',range,sucursalId]` | no | **sí** | ✔ `apps/finanzas/views.py:1149` | PASA |
| `usePeriodReport` (hooks/finanzas.ts:83) | `['finanzas','report',params,sucursalId]` | no | **sí** | ✔ `apps/finanzas/views.py:1204` | PASA |
| `useDailySheet` (hooks/finanzas.ts:108) | `['finanzas','dailySheet',date,sucursalId]` | no | **sí** | ✔ `apps/finanzas/views.py:1313` | PASA |
| `useRetencion` (hooks/finanzas.ts:122) | `['finanzas','retencion',sucursalId]` | no | **sí** | ✔ `apps/finanzas/views.py:1374` | PASA |
| `useConcepts` (hooks/finanzas.ts:140) | `['finanzas','concepts',sucursalId,includeInactive]` | no | **sí** | ✔ `apps/finanzas/views.py:229` | PASA |
| `useQuotes` (hooks/finanzas.ts:177) | `['finanzas','quotes',params,sucursalId]` | no | **sí** | ✔ `apps/finanzas/views.py:579` | PASA |
| `useCharges` (hooks/finanzas.ts:232) | `['finanzas','charges',params,sucursalId]` | no | **sí** | ✔ `apps/finanzas/views.py:796` | PASA |
| `usePayments` (hooks/finanzas.ts:261) | `['finanzas','payments',params,sucursalId]` | no | **sí** | ✔ `apps/finanzas/views.py:922` | PASA |
| `useCfdis` (hooks/finanzas.ts:284) | `['finanzas','cfdi',params]` | no | **NO** | ✔ `apps/finanzas/views.py:1012` | **F-3-02** (invalidado, pero sin sede en la key) |
| `useAccountStatement` (hooks/finanzas.ts:317) | `['finanzas','statement',patientId,range]` | no | no | no — compartido a propósito (`apps/finanzas/views.py:1012`: `None if patient_id`) | PASA (correcto, declarado en `finanzas.ts:51`) |
| `useFiscalConfig` (hooks/finanzas.ts:329) | `['finanzas','fiscalConfig']` | no | no | no | PASA |
| `useMembers` (hooks/miembros.ts:27) | `['miembros',sucursalId]` | no | **sí** | ✔ `apps/tenancy/views.py:146` | PASA |
| `useNotes` (hooks/notas.ts:22) | `['notas','list',filters,sucursalId]` | no | **sí** | ✔ `apps/notas/views.py:155` | PASA |
| `useReminders` (hooks/notas.ts:32) | `['notas','recordatorios',params]` | no | **NO** | ✔ `apps/notas/views.py:359` | **F-3-01 · falla** |
| `useUnreadCount` (hooks/notificaciones.ts:19) | `['notificaciones','conteo']` | no | no | no | PASA |
| `useNotifications` (hooks/notificaciones.ts:31) | `['notificaciones','list',{onlyUnread}]` | no | no | no | PASA |
| `usePatient` (hooks/pacientes.ts:53) | `['pacientes','detail',id]` | no | no | no | PASA |
| `usePatients` (hooks/pacientes.ts:65) | `['pacientes','list',segment,search,dateFrom,dateTo,categoryId]` | no | no | no — pacientes son del tenant, no de la sede | PASA |
| `usePaquetes` (hooks/paquetes.ts:37) | `['paquetes','lista',onlyActive,sucursalId]` | no | **sí** | ✔ `apps/finanzas/views.py:405` | PASA |
| `usePaquete` (hooks/paquetes.ts:45) | `['paquetes','detalle',id]` | no | no | detalle por id | PASA |
| `useDoctorsManage` (hooks/personal.ts:34) | `['personal','doctores','manage']` | no | **NO** | ✔ `apps/personal/views.py:118` | **F-3-02** (invalidado) |
| `useConsultoriosManage` (hooks/personal.ts:68) | `['personal','consultorios','manage']` | no | **NO** | ✔ `apps/personal/views.py:359` | **F-3-02** (invalidado) |
| `useDoctorSchedules` (hooks/personal.ts:107) | `['personal','horarios',doctorId,sucursalId]` | no | **sí** | ✔ `apps/personal/views.py:599` | PASA |
| `usePlanIntegralBorrador` (hooks/planIntegral.ts:39) | `['expediente',patientId,'plan-integral','borrador',treatmentPlanId]` | no | no | no | PASA |
| `usePlanIntegrales` (hooks/planIntegral.ts:61) | `['expediente',patientId,'plan-integral','lista']` | no | no | no | PASA |
| `usePlantillasDocumento` (hooks/plantillasDocumento.ts:34) | `['plantillas-documento','lista',section,onlyActive]` | no | no | no | PASA |
| `usePlatformMetrics` (hooks/plataforma.ts:53) | `['plataforma','metricas']` | n/a | n/a | cross-tenant por diseño (panel interno) | PASA |
| `usePlatformClinicas` (hooks/plataforma.ts:58) | `['plataforma','clinicas',search,status]` | n/a | n/a | cross-tenant por diseño | PASA |
| `usePlatformStaff` (hooks/plataforma.ts:63) | `['plataforma','usuarios',search]` | n/a | n/a | cross-tenant por diseño | PASA |
| `usePlatformAuditoria` (hooks/plataforma.ts:69) | `['plataforma','auditoria',params]` | n/a | n/a | cross-tenant por diseño | PASA |
| `usePlatformSistema` (hooks/plataforma.ts:133) | `['plataforma','sistema']` | n/a | n/a | cross-tenant por diseño | PASA |
| `usePlatformPlanes` (hooks/plataforma.ts:142) | `['plataforma','planes']` | n/a | n/a | catálogo global | PASA |
| `usePlatformSuscripciones` (hooks/plataforma.ts:148) | `['plataforma','suscripciones','lista',params]` | n/a | n/a | cross-tenant por diseño | PASA |
| `usePlatformSuscripcionesResumen` (hooks/plataforma.ts:158) | `['plataforma','suscripciones','resumen']` | n/a | n/a | cross-tenant por diseño | PASA |
| `usePlatformClinicaDetail` (hooks/plataforma.ts:219) | `['plataforma','clinica',id]` | n/a | n/a | cross-tenant por diseño | PASA |
| `useMedicationSearch` (hooks/recetas.ts:53) | `['medicamentos','buscar',term,kind]` | no | no | no | PASA |
| `usePrescriptions` (hooks/recetas.ts:75) | `['recetas',patientId]` | no | no | no | PASA |
| `usePrescription` (hooks/recetas.ts:84) | `['recetas','detalle',prescriptionId]` | no | no | no | PASA |
| `useFormatosReceta` (hooks/recetas.ts:163) | `['recetas','formatos']` | no | no | no | PASA |
| `useSucursales` (hooks/sucursales.ts:30) | `['sucursales','lista']` | no | no | usa `allowed_sucursales` (del usuario, no de la sede activa) | PASA |
| `useSucursalesDeMiembro` (hooks/sucursales.ts:71) | `['sucursales','miembro',membershipId]` | no | no | no | PASA |

**Cobertura:** 68 queries. 20 llevan la sucursal en la key. 14 endpoints acotados por sede en el
backend; de esos, **11 llevan la sede en la key**, 3 no (`useCfdis`, `useDoctorsManage`,
`useConsultoriosManage` — los tres cubiertos por invalidación de prefijo) y **1 no lleva ni sede ni
invalidación: `useReminders`**. Cero queries llevan el tenant, lo cual está cubierto por
`queryClient.clear()` en las tres transiciones de sesión (ver más abajo).

---

### Qué se invalida al cambiar de sede

Selector: `web-soft/src/components/Topbar.tsx:197-259` (`SelectorSucursal`), oculto con una sola
sede (`Topbar.tsx:202`); opción "Todas las sucursales" solo con más de una (`Topbar.tsx:231`,
`SucursalContext.tsx:112`). Ambas ramas llaman `setActiveSucursal`
(`Topbar.tsx:233` y `:248`).

`setActiveSucursal` (`web-soft/src/auth/SucursalContext.tsx:96-108`) hace exactamente tres cosas:

1. `setSeleccionSucursal(siguiente)` → escribe `localStorage['maily.sucursal']`
   (`web-soft/src/lib/sucursalStore.ts:69-78`), que es lo que lee `http.ts:134` para mandar el
   header `X-Sucursal-Id` (`web-soft/src/lib/http.ts:135`). La escritura ocurre **antes** del
   `setState`, así que no hay ventana en la que la key nueva se pida con el header viejo.
2. `setSeleccionState(siguiente)` → re-render del provider; **toda query cuya key incluya
   `activeSucursalId` cambia de key y refetchea sola.** Ese es el mecanismo principal, no la
   invalidación.
3. Tres invalidaciones de prefijo, y solo tres:

```
SucursalContext.tsx:105   invalidateQueries({ queryKey: ['personal'] })
SucursalContext.tsx:106   invalidateQueries({ queryKey: ['agenda'] })
SucursalContext.tsx:107   invalidateQueries({ queryKey: ['finanzas'] })
```

**Lo que NO se invalida:** `['notas']`, `['miembros']`, `['paquetes']`, `['pacientes']`,
`['expediente']`, `['clinica']`, `['equipo']`, `['recetas']`, `['analitos']`, `['sucursales']`,
`['notificaciones']`, `['calendarizaciones']`, `['plantillas-documento']`, `['medicamentos']`,
`['plataforma']`.

De esos quince prefijos, catorce no consumen ningún endpoint acotado por sede, o llevan la sede en
la key y se refrescan solos (`['miembros']` en `miembros.ts:27`, `['paquetes']` en `paquetes.ts:37`,
`['notas','list',…]` en `notas.ts:22`). **El único que consume un endpoint acotado por sede sin
llevarla en la key y sin invalidación es `['notas','recordatorios',…]`** → F-3-01.

Nota sobre `['paquetes']` y `['miembros']`: el comentario de `Topbar.tsx:188-190` dice que el cambio
de sede refresca "personal/consultorios/agenda/finanzas". Paquetes y miembros no están en esa lista
y sí dependen de la sede; están cubiertos por su key, no por la invalidación. Funciona, pero el
comentario está desactualizado respecto al código.

---

### Qué se limpia al cerrar sesión o cambiar de usuario

`queryClient.clear()` se llama en **las tres** transiciones de sesión, no solo en logout:

| Transición | Qué hace | Línea |
|---|---|---|
| **logout explícito** | `clearAccessToken()` + `clearAllDrafts()` + `queryClient.clear()`, dentro de un `finally` (se ejecuta aunque el POST `/auth/logout/` falle por red) | `auth/AuthContext.tsx:118-133`; el `clear()` en `:129`, los borradores en `:125` |
| **login (arranque de sesión)** | `queryClient.clear()` **antes** de `authApi.login(input)` — si otra cuenta usó esta pestaña sin recargar, su caché se descarta antes de pedir nada | `auth/AuthContext.tsx:110` |
| **sesión perdida / refresh fallido** | `onAccessTokenChange` → token `null` → `queryClient.clear()` + `setUser(null)` | `auth/AuthContext.tsx:94-104`, el `clear()` en `:99`. Lo dispara `clearAccessToken()` de `lib/http.ts:113` y `:117` |

El token nunca se persiste: vive en una variable de módulo (`lib/tokenStore.ts:14`), documentado en
`tokenStore.ts:9-11`. El refresh va en cookie `httpOnly` que JS no lee
(`docs/02-contrato.md:244`).

**Qué sobrevive a un cambio de usuario en la misma máquina** (todo lo de `localStorage`, ver la
sección siguiente): la selección de sede `maily.sucursal`, los dos snooze por uid, la preferencia de
vista de contactos, y `maily_demo_role`. **Ninguno lleva datos de paciente.**

`maily.sucursal` merece la aclaración porque es el único que viaja en una petición: al cerrar
sesión, `user` pasa a `null` → `sucursales` queda vacío → `idsKey` cambia → el efecto de
reconciliación (`SucursalContext.tsx:83-94`) llama `elegirDefault([])` = `null` y **borra la clave**
(`sucursalStore.ts:71`). El `SucursalProvider` está montado por encima de las rutas
(`web-soft/src/App.tsx:145`), así que el efecto sí corre. Y aunque no corriera, el peor caso no es
una fuga: `resolve_active_sucursal` valida el header contra las sedes permitidas del usuario nuevo y
levanta **403** si no está (`backend/apps/clinica/sucursal_scope.py:302-308`).

---

### Almacenamiento local (localStorage / sessionStorage)

Cero `sessionStorage`, cero `IndexedDB` en `web-soft/src/`.

| clave | qué guarda | ¿PII? | ¿separada por usuario/clínica? | archivo:línea |
|---|---|---|---|---|
| `maily:draft:v1:{userId}:{tenantId}:{formType}:{entityId}` | Borrador sin guardar de historia clínica, evolución SOAP, calendarización, resumen clínico o plan integral | **SÍ — datos clínicos de paciente** | **Sí, usuario + tenant en la clave** | `lib/draftKeys.ts:38`; escritura `hooks/useLocalDraft.ts:80`; consumidores en `components/expediente/HistoriaTab.tsx:139`, `EvolucionSoapStepper.tsx:119`, `CalendarizacionTab.tsx:328`, `PlanIntegralModal.tsx:168`, `ResumenClinicoModal.tsx:94` |
| `maily.sucursal` | UUID de la sede activa, o el centinela `__todas__` | No | No, pero se limpia al perder `user` y el backend rechaza una sede ajena con 403 | `lib/sucursalStore.ts:24`, `:69-78` |
| `maily.alertaCitas.snooze.{uid}` | `{ appointmentId: timestampMs }` — pausas de la alerta de citas | No: UUIDs y epochs, sin nombres. El nombre del paciente se lee de la respuesta de la API (`AlertaCitas.tsx:44`), no del storage | Sí, por `uid` (`user.id`) | `components/agenda/AlertaCitas.tsx:16`, `:21`, `:32`; se escribe en `:115` y `:123` |
| `maily.luzRecordatorios.snooze.{uid}` | Un epoch: hasta cuándo ocultar la luz de recordatorios | No | Sí, por `uid` | `components/agenda/LuzRecordatorios.tsx:10`, `:15`, `:25` |
| `maily.pacientes.vista` | `'cards'` o `'lista'` | No | No (preferencia visual) | `pages/ContactosPage.tsx:49`, `:61`, `:66` |
| `maily_demo_role` | Rol de UI forzado a mano | No | No | `auth/useRole.ts:17`, `:36`, `:50` — **código muerto**, ver F-3-04 |

`clearAllDrafts()` (`lib/draftKeys.ts:46-58`) barre por prefijo `maily:draft:` **todas** las claves
de borrador, sin filtrar por usuario — correcto para un logout. Se llama en un solo sitio:
`auth/AuthContext.tsx:125`.

---

### Hallazgos

### F-3-01 · Los recordatorios no llevan la sede en la clave ni se invalidan al cambiar de sucursal
**Severidad:** P1
**Backend:** `backend/apps/notas/views.py:359` — `NoteRemindersApi.get` acota el listado con
`sucursal_ids=sucursal_scope_ids(request)`; el docstring lo declara cierre de hueco de seguridad
(`views.py:340-341`). Es decir: el backend **sí** separa los recordatorios por sede, y el frontend no
recoge esa separación.
**Frontend:** `web-soft/src/hooks/notas.ts:32` — `queryKey: [...notasKey, 'recordatorios', params]`,
donde `params` son solo `date_from`/`date_to`. Sin `activeSucursalId`, a diferencia de su hermano
`useNotes` (`notas.ts:22`), que sí lo lleva. Y `['notas']` no está entre los tres prefijos que
invalida `web-soft/src/auth/SucursalContext.tsx:105-107`.
**Qué ve el usuario:** el dueño de una clínica con dos sedes (Centro y Norte) —o cualquier admin con
`MembershipSucursal` en ambas, `docs/02-contrato.md:571`— está en la pantalla de Agenda con el panel
lateral "Mis recordatorios" abierto (`components/agenda/RecordatoriosWidget.tsx:14`). Cambia de
Centro a Norte en el selector del Topbar. La agenda, el personal y las finanzas se refrescan; **el
panel de recordatorios sigue mostrando los avisos de Centro**, y la luz amarilla de la esquina
(`components/agenda/LuzRecordatorios.tsx:46`) sigue encendida por un recordatorio de Centro. El texto
de un aviso de clínica es campo libre y puede nombrar a un paciente.
**Duración:** no son 30 s. `staleTime` marca el dato viejo pero no refetchea, y
`refetchOnWindowFocus` está en `false` (`lib/queryClient.ts:16` y `:21`). El refetch exige un
observer nuevo. `LuzRecordatorios` está montado a nivel de `App` (`web-soft/src/App.tsx:188`) y
**nunca se desmonta**: sirve el dato viejo hasta recargar la página o cerrar sesión. El widget de la
agenda se corrige solo si el usuario navega fuera y vuelve.
**Por qué P1 y no P0:** el cruce es entre dos sedes del **mismo** tenant. El contrato declara ese
caso "aceptado por diseño" para el backend (`docs/02-contrato.md:549-552`,
`backend/apps/clinica/sucursal_scope.py:4-12`). No hay forma de que aparezca un dato de otra clínica.
**Clase:** caché sucia

### F-3-02 · Tres claves dependen de la invalidación de prefijo en vez de llevar la sede
**Severidad:** P2
**Backend:** los tres endpoints acotan por sede — `backend/apps/finanzas/views.py:1012`
(`CfdiListCreateApi`), `backend/apps/personal/views.py:118` (`DoctorListCreateApi`) y
`backend/apps/personal/views.py:359` (`ConsultorioListCreateApi`), los tres con
`sucursal_scope_ids(request)`.
**Frontend:** `web-soft/src/hooks/finanzas.ts:284` (`['finanzas','cfdi',params]`),
`web-soft/src/hooks/personal.ts:34` (`['personal','doctores','manage']`) y
`web-soft/src/hooks/personal.ts:68` (`['personal','consultorios','manage']`) — ninguna incluye la
sucursal. Hoy quedan cubiertas porque `web-soft/src/auth/SucursalContext.tsx:105` y `:107` invalidan
los prefijos `['personal']` y `['finanzas']`.
**Qué ve el usuario:** hoy, nada: al cambiar de sede las tres se refrescan. El defecto es de diseño,
no de comportamiento. Sus hermanas de la misma pantalla sí llevan la sede
(`hooks/agenda.ts:164`, `:174`; `hooks/personal.ts:107`), así que la misma pantalla usa dos
convenciones. El día que alguien renombre un prefijo, mueva CFDI a su propio namespace o quite una
de las tres líneas de invalidación, estas tres claves se convierten silenciosamente en F-3-01 — sin
que ningún test lo note.
**Clase:** caché sucia

### F-3-03 · La sesión que expira sola deja los borradores clínicos en el equipo; solo el logout los borra
**Severidad:** P2
**Backend:** el access token dura 15 min y el refresh 7 días (`docs/02-contrato.md:243-244`,
`backend/config/settings/base.py:257-258`). Que la sesión se caiga sin logout es el camino normal, no
el excepcional: basta cerrar el portátil un fin de semana.
**Frontend:** asimetría entre las dos rutas de fin de sesión. `logout()` llama `clearAllDrafts()`
(`web-soft/src/auth/AuthContext.tsx:125`) **y** `queryClient.clear()` (`:129`). La ruta de sesión
perdida (`AuthContext.tsx:94-104`) llama **solo** `queryClient.clear()` (`:99`): los borradores se
quedan. La red de seguridad es el TTL de 48 h de `hooks/useLocalDraft.ts:38`, que además solo se
aplica **al leer** la clave (`useLocalDraft.ts:187-190`), no por un barrido periódico: un borrador
cuya pantalla nadie vuelve a abrir permanece en disco indefinidamente.
**Qué ve el usuario:** el médico de una clínica escribe media nota de evolución de un paciente en la
computadora compartida del consultorio, se distrae y no guarda. Su sesión expira sola. En el
`localStorage` de ese equipo queda
`maily:draft:v1:{userId}:{tenantId}:evolucion:{patientId}` con el texto clínico. **No lo ve otro
usuario de la app** — la clave incluye `userId` y `tenantId` (`lib/draftKeys.ts:38`), así que la
siguiente sesión no lo lee ni lo ofrece. Lo ve quien abra las herramientas de desarrollo o el perfil
del navegador en esa máquina. Es retención de PII más allá de la sesión, no fuga entre tenants.
**Clase:** caché sucia

### F-3-04 · `maily_demo_role` persiste un rol de UI que nadie lee, con `owner` por defecto
> **Consolidado en `F-5-01`.** El mismo defecto lo encontró otro cruce con un escenario mejor. Se conserva aquí la evidencia porque el ángulo es distinto, pero **no cuenta como hallazgo aparte** en el total del resumen.
**Severidad:** P2
**Backend:** el rol real sale de `GET /me/ → active_role` (`docs/02-contrato.md:308-310`,
`backend/apps/authn/serializers.py:71-100`), y el backend es la autoridad de permisos
(`docs/02-contrato.md:305-307`).
**Frontend:** `web-soft/src/auth/useRole.ts` persiste un rol en `localStorage['maily_demo_role']`
(`:17`, `:50`) con `DEFAULT_ROLE = 'owner'` (`:18`) y lo devuelve cuando `getActiveRole()` es null
(`:33-37`). `getActiveRole()` lee una variable de memoria de `lib/tokenStore.ts:46` que **nunca se
puebla**: `setActiveRole` (`tokenStore.ts:50`) no tiene un solo llamador en `web-soft/src`
(verificado por grep). Es decir, si este hook se usara, todo usuario vería la UI de `owner`.
**Qué ve el usuario:** nada, hoy. `web-soft/src/auth/useRole.ts` **no lo importa ningún archivo**: el
`useRole` que consumen los 20 componentes es el de `web-soft/src/auth/RoleContext.tsx:20`, que
deriva del rol real de `AuthContext` con fallback `'readonly'` — mínimo privilegio
(`RoleContext.tsx:15`). El archivo es código muerto con un default peligroso y un comentario que
todavía afirma que "el plumbing de autenticación real no existe" (`useRole.ts:4-7`), lo cual ya no es
cierto. La clave `maily_demo_role` no se escribe nunca hoy, pero sobreviviría a un cambio de usuario
si alguien conectara el hook.
**Clase:** caché sucia (estado de sesión persistido)

---

### NO VERIFICABLE

1. **Ventana real de exposición de F-3-01 en producción.** Necesitaría el `gcTime` efectivo. No está
   configurado en `web-soft/src/lib/queryClient.ts:13-27`, así que se hereda el default de
   `@tanstack/react-query ^5.101.0` (`web-soft/package.json:16`), documentado como 5 min. Ese default
   no lo puedo citar con `archivo:línea` de este repo. Para confirmarlo: leer `gcTime` en
   `node_modules/@tanstack/query-core/build/modern/queryClient.js`, o hacer explícito el valor en
   `queryClient.ts` — que es lo recomendable de todas formas, porque hoy un dato clínico sobrevive en
   memoria un tiempo que nadie del proyecto eligió.
2. **Si el header `X-Sucursal-Id` viaja en las primeras peticiones tras un cambio de usuario.** La
   secuencia parece cerrada — la reconciliación de `SucursalContext.tsx:83-94` corre al cambiar
   `idsKey`, y el backend rechaza con 403 una sede no permitida
   (`backend/apps/clinica/sucursal_scope.py:302-308`) — pero el orden real entre ese efecto y el
   primer `fetch` de los hijos depende del ciclo de React. Para confirmarlo hace falta una prueba
   e2e: iniciar sesión con un usuario de la clínica A y sede Norte, cerrar sesión, iniciar con un
   usuario de la clínica B sin recargar, y mirar el header de la primera petición de datos en la
   pestaña de red. `web-soft` ya tiene `npm run test:e2e`.
3. **Si algún aviso de `notas` lleva de hecho datos de paciente.** F-3-01 asume que el campo de texto
   libre de un aviso puede nombrar a un paciente, lo cual es plausible pero no está probado. Para
   confirmarlo: revisar el modelo en `backend/apps/notas/models.py` y una muestra de datos reales.
   No cambia el hallazgo — la clave debe llevar la sede igual —, solo su severidad exacta dentro de
   P1.

---

## Cruce 4 · Header X-Sucursal-Id y alcance por sede

**Cómo sale el header (único punto).** `MailySoft/web-soft/src/lib/http.ts:134-135` inyecta
`X-Sucursal-Id` en **toda** petición que pase por `doFetch`, sin lista de rutas. El valor viene de
`lib/sucursalStore.ts:57-60` (`getActiveSucursalId`), que lee `localStorage['maily.sucursal']`
(`:24`) **directamente, sin pasar por React**. `auth/SucursalContext.tsx:96-108` es quien escribe
esa clave; `:110` deriva `activeSucursalId`.

Tres estados posibles (`sucursalStore.ts:30`, `:44-50`):

| Selección | ¿Header? | Qué hace el backend |
|---|---|---|
| `{modo:'sede', id}` | **sí** | `resolve_active_sucursal` valida contra `allowed_sucursales` (`sucursal_scope.py:305-309`) |
| `{modo:'todas'}` | **no** | `sucursal_scope_ids` acota a las sedes del actor (`:476-505`); las ESCRITURAS caen a la sede `is_default` (`:416-419`) |
| `null` (primer arranque) | **no** | ídem |

**No hay peticiones fuera del cliente.** `grep -rn "fetch(\|axios\|XMLHttpRequest" src/` no devuelve
ninguna llamada de red fuera de `lib/http.ts` (el único acierto es `refetch()` de TanStack Query en
`src/pages/plataforma/SistemaPage.tsx:129`). Los PDFs bajan por `requestBlob` (`http.ts:237`), que
comparte el mismo `doFetch`. Los avatares son `<img src>` a Cloudinary: no necesitan header.

---

### Tabla A · Endpoints acotados por sede vs header enviado

Columna 3 idéntica en todas las filas porque la inyección es global: **`http.ts:134-135` manda el
header siempre que haya una sede concreta elegida (`sucursalStore.ts:57-60`), y NUNCA en modo
"Todas" ni antes de la primera elección.** Se abrevia como `http.ts:134-135 (global)`.

#### Agenda — `apps/agenda/views.py`

| endpoint | función de alcance (archivo:línea) | ¿front manda header? | veredicto |
|---|---|---|---|
| `GET /agenda/citas/` | `sucursal_scope_ids` — `views.py:239` | `http.ts:134-135` (global); consumido en `hooks/agenda.ts:56-60` con la sede en la queryKey | PASA |
| `GET /agenda/disponibilidad/` | `sucursal_scope_ids` — `views.py:461` | ídem; `hooks/agenda.ts:211-214` | PASA |
| `GET /agenda/eventos/` | `sucursal_scope_ids` — `views.py:930` | ídem; `hooks/agenda.ts:94-98` | PASA |
| `GET\|PATCH\|DELETE /agenda/citas/<id>/` | `_appointment_get_or_404` — `views.py:97-118`, `:505` | **el front no llama a esta ruta** (`grep "agenda/citas/" src/api/ src/hooks/` → solo lista, serie, notas, reagendar, reactivar, estado) | PASA (superficie no usada) |
| `POST /agenda/citas/<id>/estado/` | `views.py:605` | `api/agenda.ts:150` | PASA |
| `POST /agenda/citas/<id>/reagendar/` | `views.py:649` | `api/agenda.ts:136` | PASA |
| `POST /agenda/citas/<id>/reactivar/` | `views.py:683` | `api/agenda.ts:141` | PASA |
| `PATCH\|DELETE /agenda/eventos/<id>/` | `_agenda_block_get_or_404` — `views.py:121-135`, `:984` | `api/agenda.ts:105`, `:110` | PASA |
| `GET\|POST /agenda/citas/<id>/notas/` | hereda el 404 del padre — `views.py:1041` | `api/agenda.ts:116`, `:119` | PASA |
| `GET\|POST /agenda/eventos/<id>/notas/` | ídem — `views.py:1101` | `api/agenda.ts:122`, `:125` | PASA |
| **`DELETE /agenda/notas/<id>/`** | **ninguna** — `agenda_item_note_get(note_id=…)` sin `sucursal_ids`, `views.py:1156` | `api/agenda.ts:127-129` ← `hooks/agenda.ts:148-153` ← `components/agenda/NotasHilo.tsx:71` | **Brecha de backend (B-AGE-01) NO amplificada por el front** — ver F-4-08 |
| `POST /agenda/citas/`, `POST /agenda/eventos/` | `resolve_write_sucursal` — `services.py:445`, `blocks.py:91` | header, sin `sucursal_id` en el body (`components/agenda/CrearEventoModal.tsx:198-199`) | **F-4-02** |

#### Personal — `apps/personal/views.py`

| endpoint | función de alcance | ¿front manda header? | veredicto |
|---|---|---|---|
| `GET /personal/doctores/` | `sucursal_scope_ids` — `views.py:118` | global; `hooks/personal.ts:32-36` (key sin sede, pero `SucursalContext.tsx:105` invalida `['personal']`) | PASA |
| `GET\|PATCH\|DELETE /personal/doctores/<id>/` | **ninguna** — `_get_doctor_or_404` llama `doctor_get(doctor_id=…)`, `views.py:239-247`; `doctor_get` ni siquiera acepta `sucursal_ids` (`selectors.py:21`) | el front solo usa PATCH/DELETE, con ids salidos de la lista acotada (`components/personal/MiembroDetalleDrawer.tsx:71`, `:91`, `:165`) | **Brecha de backend NO amplificada por el front** — ver F-4-09 |
| `GET /personal/consultorios/` | `sucursal_scope_ids` — `views.py:359` | global; `hooks/personal.ts:66-70` | PASA |
| `PATCH\|DELETE /personal/consultorios/<id>/` | `sucursal_scope_ids` — `views.py:455` | `api/personal.ts:54`, `:59` | PASA |
| `POST /personal/consultorios/` | `resolve_active_sucursal` → `resolve_write_sucursal` — `views.py:388` | manda `sucursal_id` explícito cuando hay una elegida (`components/personal/NuevoConsultorioDrawer.tsx:63-64`) | PASA |
| `GET /personal/doctores/<id>/horarios/` | `sucursal_scope_ids` — `views.py:599` | global; `hooks/personal.ts:105-109` (sede en la key) | PASA |
| `POST /personal/doctores/<id>/horarios/` | `resolve_active_sucursal` — `views.py:641` | manda `sucursal_id` explícito (`components/personal/HorariosDoctor.tsx:79`) | PASA |
| `DELETE /personal/horarios/<id>/` | `sucursal_scope_ids` — `views.py:686` | `api/personal.ts:79` | PASA |

#### Finanzas — `apps/finanzas/views.py`

| endpoint | función de alcance | ¿front manda header? | veredicto |
|---|---|---|---|
| `GET /finanzas/conceptos/` | `sucursal_scope_ids` — `views.py:229` | global; `hooks/finanzas.ts:138-141` | PASA |
| `GET\|PATCH\|DELETE /finanzas/conceptos/<id>/` | **ninguna** — `_get_or_404`, `views.py:273` (B-FIN-15) | el front no pide el detalle; trabaja sobre la fila de la lista (`components/consultorio/SeccionServicios.tsx:60`) | brecha de backend no alcanzable por el front |
| `GET /finanzas/paquetes/` | `sucursal_scope_ids` — `views.py:405` | global; `hooks/paquetes.ts:33-40` | PASA |
| `GET\|PATCH\|DELETE /finanzas/paquetes/<id>/` | **ninguna** — `_get_or_404`, `views.py:453` (B-FIN-15) | `hooks/paquetes.ts:43-49` con id salido de la lista acotada (`pages/PaquetesPage.tsx:110-113`); la queryKey del detalle no lleva sede | brecha de backend no amplificada; ver F-4-06 |
| `GET /finanzas/cotizaciones/` **sin** `patient_id` | `sucursal_scope_ids` — `views.py:579` | global; `hooks/finanzas.ts:175-178` | PASA |
| `GET /finanzas/cargos/` **sin** `patient_id` | `sucursal_scope_ids` — `views.py:796` | global; `hooks/finanzas.ts:229-234` | PASA |
| `GET /finanzas/cargos/` **con** `patient_id` | **ninguna, a propósito** — `views.py:796` | `components/finanzas/CobrosPagosTab.tsx:27` | **F-4-01** |
| `GET /finanzas/pagos/` (mismo patrón) | `views.py:922` | `CobrosPagosTab.tsx:28` | ver F-4-01 |
| `GET /finanzas/cfdi/` | `views.py:1012` | `api/finanzas.ts:658` | PASA |
| detalle/acción por id: cotización, cargo, pago, CFDI | `_scope_or_404` → 404 — `views.py:130-166`, `:866` | `api/finanzas.ts:481`, `:485`, `:566`, `:666` | acotado; **desalineado con el listado por paciente** → F-4-01 |
| `GET /finanzas/estado-cuenta/<patient_id>/` | **nunca, por diseño** — `views.py:1110-1125` | `api/finanzas.ts:705`; la UI pinta la columna Sede (`EstadoCuentaTab.tsx:139`) y es de solo lectura | PASA (deliberado y bien señalizado) |
| `GET /finanzas/dashboard/ · /reporte/ · /reporte/pdf/ · /cierre-diario/ · /retencion/` | `sucursal_scope_ids` — `views.py:1149`, `:1204`, `:1249`, `:1313`, `:1374` | global; `hooks/finanzas.ts:67-70`, `:81-84`, `:106-109`, `:120-123` (sede en la key) + `SedeIndicador.tsx:28-49` | PASA |
| `POST /finanzas/cargos/ · /pagos/ · /cotizaciones/` | `_resolve_write_sucursal` — `views.py:169-190`, `:836`, `:952`, `:607` | header, **sin `sucursal_id` en el body** (`CobrosPagosTab.tsx:75-76`, `:193-196`) | **F-4-02** |

#### Notas — `apps/notas/views.py`

| endpoint | función de alcance | ¿front manda header? | veredicto |
|---|---|---|---|
| `GET /notas/` | `sucursal_scope_ids` — `views.py:155` | global; `hooks/notas.ts:20-24` (sede en la key) | PASA |
| `GET\|PATCH\|DELETE /notas/<id>/` | `sucursal_scope_ids` → `note_get` — `views.py:80` | `api/notas.ts:23`, `:28` | PASA |
| `GET /notas/recordatorios/` | `sucursal_scope_ids` — `views.py:359` | global, **pero la queryKey no lleva sede** — `hooks/notas.ts:29-35` | **F-4-05** |
| `POST /notas/` | `resolve_active_sucursal` — `views.py:187`; el service revalida con `allowed_sucursales` (`services.py:214`) | el owner manda `sucursal_id` explícito (`components/notas/NuevaNotaModal.tsx:85-89`) | PASA |

#### Equipo / miembros — `apps/tenancy/views.py`

| endpoint | función de alcance | ¿front manda header? | veredicto |
|---|---|---|---|
| `GET /miembros/` | `sucursal_scope_ids` — `views.py:146` | global; `hooks/miembros.ts:25-30` (sede en la key) | PASA |
| `GET\|PATCH /miembros/<id>/`, `POST /miembros/<id>/avatar/` | `allowed_sucursales`, **no** `sucursal_scope_ids` — `views.py:73-96` | `api/miembros.ts:18`, `:25` | PASA — deliberado (§1.5.5): el dueño parado en Centro edita a alguien de Norte |
| `POST /miembros/` | `resolve_active_sucursal` — `views.py:170` | header | PASA |

#### Expediente / calendarización — `apps/expediente/views_calendarizacion.py`

| endpoint | función de alcance | ¿front manda header? | veredicto |
|---|---|---|---|
| `POST .../plan/<id>/cotizacion/` | `resolve_active_sucursal` + `resolve_write_sucursal` — `:372-378` | global, sin `sucursal_id` en el body (`api/calendarizacion.ts:101`) | **F-4-02** |
| `POST` agendar sesión de tratamiento | ídem — `:450-460` | `api/calendarizacion.ts:73`, `:84` | **F-4-02** |

#### Sin alcance por sede (verificado, no es brecha)

`apps/pacientes/**` no llama a ninguna de las cinco funciones (contrato `02-contrato.md:1164-1167`);
`Patient` no tiene campo `sucursal`. `GET /clinica/equipo/` tampoco (`clinica/views.py:841-849`).
`GET /clinica/sucursales/` usa `allowed_sucursales` (`clinica/views.py:970`), no el header.

---

### ¿Qué pasa si falta el header?

**Ningún endpoint de LECTURA depende del fallback "sin header = sin filtro".** Los 12 usos de
`resolve_active_sucursal` en el repo son todos de ESCRITURA: `agenda/views.py:273`, `:394`, `:947`;
`personal/views.py:388`, `:641`; `notas/views.py:187`; `tenancy/views.py:170`;
`finanzas/views.py:182`; `expediente/views_calendarizacion.py:372`, `:450`. Todo listado expuesto
usa `sucursal_scope_ids`, que **siempre** acota (`sucursal_scope.py:429-505`).

**Primer render, sin sede persistida.** `getActiveSucursalId()` devuelve `null`
(`sucursalStore.ts:45-50`) → sale sin header. La usuaria acotada a Norte **ve solo Norte**:
`sucursal_scope_ids` cae por la rama de alcance parcial (`sucursal_scope.py:502-505`) y devuelve sus
sedes permitidas. **No hay fuga en la primera carga.** Se corrige solo cuando
`SucursalContext.tsx:83-94` reconcilia y escribe la sede `is_default`.

**Primer render con sede persistida de OTRA sesión.** Ese es el caso que sí rompe: ver F-4-04.

---

### El selector de sede

**Se oculta con una sola sucursal.** `components/Topbar.tsx:202` — `if (sucursales.length <= 1)
return null`. Igual en `components/finanzas/SedeIndicador.tsx:31`. No se consulta `sede_unica` ni
`max_sucursales`: se usa el largo de `/me.sucursales`, que el backend arma con `allowed_sucursales`
(`apps/authn/views.py:418`). Es el criterio correcto — una clínica con dos sedes donde el usuario
solo tiene una asignada tampoco tiene nada que elegir.

**Opción "todas".** `Topbar.tsx:231` la muestra cuando `puedeVerTodas`, definido en
`SucursalContext.tsx:112` como `sucursales.length > 1` — es decir, **a cualquier rol con más de una
sede permitida, no solo al `owner`**. Contra §1.5.2 eso es correcto de seguridad (el backend acota
igual) pero engañoso de etiqueta: ver F-4-07.

**Qué manda en el header al elegir "todas".** Nada. `setActiveSucursal(null)`
(`Topbar.tsx:233`) → `{modo:'todas'}` → `getActiveSucursalId()` devuelve `null`
(`sucursalStore.ts:57-60`) → `http.ts:134-135` omite el header. Para LEER es correcto. Para
ESCRIBIR es el origen de F-4-02.

`components/common/SelectorSedes.tsx` **no es el selector de sede activa**: son las casillas de "en
qué sedes está disponible este servicio/paquete" (`:19-33`), usadas en `PaquetesPage.tsx:319` y
`SeccionServicios.tsx:386`. No toca el header.

---

### Tabla B · Listado acotado → detalle al que navega

**Hecho estructural que reduce el riesgo:** `App.tsx:159-168` no tiene ninguna ruta con parámetro de
id. Todo detalle es un modal o drawer alimentado con el objeto de la lista; el usuario nunca teclea
un id. Por eso casi todas las brechas de detalle del backend quedan fuera del alcance del front.

| listado (pantalla, archivo:línea) | ¿acotado por sede? | detalle al que navega (archivo:línea) | ¿el detalle está acotado? | veredicto |
|---|---|---|---|---|
| Agenda · citas del día (`pages/AgendaPage.tsx` ← `hooks/agenda.ts:56-60`) | sí (`views.py:239`) | `components/agenda/DetalleCitaModal.tsx` (objeto en memoria) → estado/reagendar/reactivar | sí (`views.py:605`, `:649`, `:683`) | sin riesgo |
| Agenda · hilo de notas de una cita (`api/agenda.ts:116`) | sí, hereda el 404 del padre (`views.py:1041`) | `DELETE /agenda/notas/<id>/` (`NotasHilo.tsx:71`) | **no** (`views.py:1156`) | brecha real de backend, **no alcanzable desde la UI** → F-4-08 |
| Agenda · eventos (`hooks/agenda.ts:94-98`) | sí (`views.py:930`) | `EventoDetalleModal.tsx:131` → PATCH/DELETE evento | sí (`views.py:984`) | sin riesgo |
| Agenda · catálogo de médicos del modal (`hooks/agenda.ts:162-166`) | sí (`views.py:118`) | no navega a detalle; solo alimenta el `<select>` | n/a | sin riesgo |
| Contactos · pacientes (`pages/ContactosPage.tsx`) | **no, por diseño** (`02-contrato.md:1164-1167`) | `ExpedienteDrawer` → expediente, recetas, estado de cuenta | tampoco (mismo diseño) | sin riesgo de sede: el paciente es de la clínica, no de la sede |
| Contactos · citas del paciente dentro del expediente (`hooks/agenda.ts:79-82`) | sí (`views.py:239`) | modal de cita | sí | sin riesgo |
| Finanzas · Caja · cargos **filtrados por paciente** (`CobrosPagosTab.tsx:27`) | **no** (`views.py:796`) | botón "Cancelar cargo" → `DELETE /finanzas/cargos/<id>/` (`CobrosPagosTab.tsx:147`) | **sí** → 404 (`views.py:866`, `:877`) | **F-4-01 · botón fantasma** |
| Finanzas · Caja · pagos filtrados por paciente (`CobrosPagosTab.tsx:28`) | **no** (`views.py:922`) | no hay acción de cancelar pago en el front | n/a | sin riesgo hoy |
| Finanzas · aplicar pago a cargos (`CobrosPagosTab.tsx:182-184`, `:196`) | **no** (lista por paciente) | `POST /finanzas/pagos/` con `allocations[]` | `payment_register` valida tenant, **no sede del cargo** (`services.py:988-989`) | **F-4-03** |
| Finanzas · cotizaciones (`hooks/finanzas.ts:175-178`) | sí sin `patient_id` (`views.py:579`) | enviar/aceptar/PDF (`api/finanzas.ts:481`, `:485`, `:495`) | sí (`_quote_get_scoped`) | sin riesgo |
| Finanzas · estado de cuenta (`EstadoCuentaTab.tsx:41-42`) | **nunca, por diseño** | solo lectura + PDF/Excel; columna "Sede" visible (`:139`) | n/a | correcto |
| Finanzas · conceptos (`SeccionServicios.tsx:96`) | sí (`views.py:229`) | edición en línea desde la fila, sin GET de detalle | detalle no acotado (`views.py:273`) pero no se usa | sin riesgo desde la UI |
| Finanzas · paquetes (`PaquetesPage.tsx:99`) | sí (`views.py:405`) | `usePaquete(id)` (`hooks/paquetes.ts:43-49`, `PaquetesPage.tsx:110-113`) | **no** (`views.py:453`) | id siempre de la lista acotada → **F-4-06** solo por la caché |
| Personal · equipo (`hooks/miembros.ts:25-30`) | sí (`tenancy/views.py:146`) | `MiembroDetalleDrawer` → `PATCH /miembros/<id>/` | por `allowed_sucursales`, deliberado (`tenancy/views.py:73-96`) | correcto |
| Personal · médicos (`hooks/personal.ts:32-36`) | sí (`views.py:118`) | `MiembroDetalleDrawer.tsx:165` → `PATCH /personal/doctores/<id>/` | **no** (`views.py:239-247`) | brecha de backend, **no amplificada** → F-4-09 |
| Personal · consultorios (`hooks/personal.ts:66-70`) | sí (`views.py:359`) | `NuevoConsultorioDrawer` → PATCH/DELETE | sí (`views.py:455`) | sin riesgo |
| Personal · horarios del médico (`hooks/personal.ts:105-109`) | sí (`views.py:599`) | `DELETE /personal/horarios/<id>/` | sí (`views.py:686`) | sin riesgo |
| Notas · lista (`hooks/notas.ts:20-24`) | sí (`views.py:155`) | editar/borrar/marcar hecho (`pages/NotasPage.tsx:95`) | sí (`views.py:80`) | sin riesgo |
| Notas · recordatorios (`hooks/notas.ts:29-35`) | sí (`views.py:359`) | `RecordatoriosWidget.tsx:14`, `LuzRecordatorios.tsx:46` | sí | **F-4-05** (caché, no alcance) |

---

### Hallazgos

### F-4-01 · La caja del paciente ofrece "Cancelar cargo" sobre cargos de otra sede y el backend responde 404
**Severidad:** P1
**Backend:** `MailySoft/backend/apps/finanzas/views.py:796` — `scope_ids = None if (raw_patient or
appointment_id) else sucursal_scope_ids(request)`: con `patient_id` el listado **no** se acota por
sede (deliberado, `02-contrato.md:4868`). Pero `MailySoft/backend/apps/finanzas/views.py:857-869` y
`:877-885` — `ChargeDetailApi._get_or_404` sí acota con `_scope_or_404` (`:130-166`) y devuelve
**404 "Cargo no encontrado."** para un cargo fuera de alcance.
**Frontend:** `MailySoft/web-soft/src/components/finanzas/CobrosPagosTab.tsx:27` pide los cargos con
`{patient_id}`; `:135` pinta la columna Sede de cada fila; `:143-149` renderiza el botón Cancelar
para **toda** fila con `status !== 'cancelled'` y `amount_paid === 0`, sin mirar `c.sucursal`.
`:147` dispara `cancelCharge.mutate(c.id)` → `hooks/finanzas.ts:245-251` → `api/finanzas.ts:566`.
**Qué ve el usuario:** clínica con Norte y Centro. Un `admin` asignado solo a Norte abre Finanzas →
Caja → elige a la paciente María. La tabla de cargos le muestra un cargo de $3,000 con la columna
Sede diciendo **"Centro"** y su botón de cancelar activo. Al pulsarlo aparece "Cargo no encontrado"
sobre una fila que está en pantalla. Llama a soporte convencido de que el sistema está roto.
**Clase:** alcance de sede (botón fantasma)

### F-4-02 · En modo "Todas las sucursales" no sale el header y toda escritura cae en la sede predeterminada del tenant
**Severidad:** P1
**Backend:** `MailySoft/backend/apps/clinica/sucursal_scope.py:416-419` — sin `sucursal_id` en el
body, sin consultorio y sin header, `resolve_write_sucursal` resuelve la sede `is_default` del
tenant. `:421-424` la valida contra `allowed_sucursales` y levanta `ValidationError` si no está.
Llamado desde `finanzas/views.py:182-190` (cargo, pago, cotización), `agenda/services.py:445`,
`agenda/blocks.py:91`, `expediente/views_calendarizacion.py:373`, `:452`.
**Frontend:** `MailySoft/web-soft/src/auth/SucursalContext.tsx:97` pone `{modo:'todas'}` →
`lib/sucursalStore.ts:57-60` devuelve `null` → `lib/http.ts:134-135` omite el header. Los
formularios de escritura no compensan: `components/finanzas/CobrosPagosTab.tsx:75-76` manda solo
`{patient_id, description, amount}`; `components/agenda/CrearEventoModal.tsx:198-199` lo dice
explícito ("No mandamos sucursal_id"). Ninguna pantalla deshabilita el alta ni advierte cuando
`esTodas` es true.
**Qué ve el usuario:** dos escenarios.
(a) La dueña de una clínica con Norte y Centro (default: Centro) deja el selector en "Todas las
sucursales" y pasa el día cobrando en Norte. Cada pago queda grabado con `sucursal = Centro`. El
cierre diario de Norte sale en ceros y el de Centro cuadra de más; nadie ve un error.
(b) Un `admin` asignado a Norte y Sur (default del tenant: Centro, que no tiene) elige "Todas",
intenta registrar un cobro y recibe **400 "No tienes acceso a esa sucursal para esta operación."**
sobre un formulario que no menciona ninguna sucursal. No hay forma de deducir que la salida es
volver a elegir una sede en el Topbar.
**Clase:** alcance de sede

### F-4-03 · Un pago puede aplicarse a un cargo de otra sede desde la caja del paciente
**Severidad:** P2
**Backend:** `MailySoft/backend/apps/finanzas/services.py:988-989` — `payment_register` valida
`_ensure_same_tenant` del paciente y de la sucursal del PAGO, pero **no** valida la sede de cada
cargo en `allocations`. El pago se graba con la sede del actor (`views.py:952`) mientras el cargo
que salda es de otra. Contrasta con `_ensure_sucursal_allowed` (`services.py:150-170`), que sí
existe para CFDI.
**Frontend:** `MailySoft/web-soft/src/components/finanzas/CobrosPagosTab.tsx:182-184` construye
`outstanding` a partir de `charges` (el listado por paciente, sin acotar); `:196` y `:224-238` los
ofrece como casillas de asignación; `:194-200` los envía en `allocations`.
**Qué ve el usuario:** una recepcionista de Norte cobra $1,000 a un paciente y los aplica a un cargo
generado en Centro. Funciona. El cierre diario de Norte registra el ingreso; el saldo del cargo de
Centro baja. Es contabilidad cruzada entre sedes sin registro de que fue intencional. No expone
datos nuevos (el estado de cuenta ya es compartido por diseño), por eso P2 y no P1.
**Clase:** alcance de sede

### F-4-04 · La sede elegida sobrevive al cierre de sesión y se manda como header al entrar otro usuario
**Severidad:** P1
**Backend:** `MailySoft/backend/apps/clinica/sucursal_scope.py:305-309` — si el header trae un UUID
que no está en `allowed_sucursales` del usuario, `resolve_active_sucursal` levanta
`PermissionDenied` → **403 en todo endpoint que llame a `resolve_active_sucursal` o a
`sucursal_scope_ids`** (`:468`).
**Frontend:** `MailySoft/web-soft/src/auth/AuthContext.tsx:118-133` — `logout()` limpia el token
(`:122`), los borradores (`:125`) y el caché de queries (`:129`), pero **no** la clave
`maily.sucursal`; `login()` (`:110`) tampoco. Nada en `src/` llama a `setSeleccionSucursal(null)`
salvo la reconciliación (`auth/SucursalContext.tsx:91`), que corre en un `useEffect` **después** del
montaje. Mientras tanto `lib/http.ts:134-135` lee `lib/sucursalStore.ts:57-60`, que va directo a
`localStorage` sin pasar por React.
**Qué ve el usuario:** en la tablet del mostrador, la administradora de la Clínica A cierra sesión
con "Sede Norte" activa. Entra la recepcionista de la Clínica B en la misma pestaña. Las primeras
peticiones salen con el UUID de Norte (Clínica A) y el backend responde 403 en cadena. Las pantallas
cuyos hooks llevan la sede en la queryKey se recuperan solas al reconciliar; las que no
(`hooks/personal.ts:32-36`, `:66-70`; `hooks/notas.ts:29-35`; `hooks/paquetes.ts:43-49`;
`hooks/sucursales.ts:28-32`) se quedan en estado de error hasta un refresh manual. **No hay fuga**
—es fail-closed y RLS sigue en pie— pero la sesión arranca rota.
**Clase:** alcance de sede

### F-4-05 · Los recordatorios no se refrescan al cambiar de sede
> **Consolidado en `F-3-01`.** El mismo defecto lo encontró otro cruce con un escenario mejor. Se conserva aquí la evidencia porque el ángulo es distinto, pero **no cuenta como hallazgo aparte** en el total del resumen.
**Severidad:** P2
**Backend:** `MailySoft/backend/apps/notas/views.py:359` — `NoteRemindersApi` acota con
`sucursal_scope_ids(request)`; el contenido cambia según la sede activa.
**Frontend:** `MailySoft/web-soft/src/hooks/notas.ts:29-35` — `useReminders` usa la queryKey
`['notas','recordatorios', params]`, **sin `activeSucursalId`** (a diferencia de `useNotes` en
`:20-24`, que sí lo lleva). Y `auth/SucursalContext.tsx:105-107` solo invalida `['personal']`,
`['agenda']` y `['finanzas']` — nunca `['notas']`.
**Qué ve el usuario:** la coordinadora cambia el selector de Norte a Centro. La lista de Notas se
refresca; el widget de recordatorios (`components/agenda/RecordatoriosWidget.tsx:14`) y la luz de
la agenda (`components/agenda/LuzRecordatorios.tsx:46`) siguen mostrando los avisos de Norte hasta
que la query quede stale. Es información de la misma clínica, por eso P2.
**Clase:** alcance de sede (caché)

### F-4-06 · El detalle de paquete se cachea sin la sede en la clave y el backend no lo acota
**Severidad:** P2
**Backend:** `MailySoft/backend/apps/finanzas/views.py:453` — `PackageDetailApi._get_or_404` llama
`package_get` sin `sucursal_ids`, mientras el listado sí acota (`:405`). Es B-FIN-15 del contrato
(`02-contrato.md:4867`).
**Frontend:** `MailySoft/web-soft/src/hooks/paquetes.ts:43-49` — la queryKey del detalle es
`paquetesKeys.detalle(id)`, sin sede, y `auth/SucursalContext.tsx:105-107` no invalida
`['paquetes']`. El id siempre sale de la lista acotada (`pages/PaquetesPage.tsx:110-113`), así que
el front no alcanza el hueco por sí solo.
**Qué ve el usuario:** el dueño abre el paquete "Blanqueamiento" estando en Norte, cierra el editor,
cambia a Centro y lo vuelve a abrir. Se le sirve la copia cacheada de Norte. Como el backend no
acota el detalle, el contenido sería idéntico de todas formas: hoy no hay diferencia visible. Se
registra porque el día que el backend cierre B-FIN-15, esta clave lo neutraliza.
**Clase:** alcance de sede (caché)

### F-4-07 · "Todas las sucursales" se ofrece a roles que no ven todas las sucursales
**Severidad:** P2
**Backend:** `MailySoft/backend/apps/clinica/sucursal_scope.py:492-505` — sin header, un actor con
alcance PARCIAL recibe solo sus sedes; solo `owner` (`:478-479`) o un rol cuyas
`MembershipSucursal` cubran todas las sedes obtiene la vista consolidada real. §1.5.2 del contrato
(`02-contrato.md:566-574`) lo dice igual.
**Frontend:** `MailySoft/web-soft/src/auth/SucursalContext.tsx:112` — `puedeVerTodas =
sucursales.length > 1`, sin mirar el rol. `components/Topbar.tsx:231-241` pinta la opción con la
etiqueta literal "Todas las sucursales" y `components/finanzas/SedeIndicador.tsx:42` la explica como
"Estás viendo el consolidado de **todas tus** sucursales" (esta segunda sí es precisa).
**Qué ve el usuario:** un `admin` asignado a Norte y Sur, en una clínica con Norte, Sur y Centro,
elige "Todas las sucursales" y lee el dashboard creyendo que ve el negocio completo. Le faltan los
ingresos de Centro. La cifra que reporta a la dueña está mal y nadie sabe por qué. El filtrado es
correcto; lo que engaña es la etiqueta.
**Clase:** alcance de sede

### F-4-08 · `DELETE /agenda/notas/<id>/` sin acotar por sede: brecha de backend real, no alcanzable desde el front
**Severidad:** P2 (P1 si se considera el acceso directo a la API, que queda fuera de esta auditoría)
**Backend:** `MailySoft/backend/apps/agenda/views.py:1156` — `agenda_item_note_get(note_id=note_id)`
sin `sucursal_ids`, a diferencia de todo el resto del módulo (`views.py:86-93` fija la regla
contraria). Confirmado en `02-contrato.md:2199` como B-AGE-01. La vista solo implementa `delete`
(`:1153`): el riesgo es borrar, no leer.
**Frontend:** `MailySoft/web-soft/src/components/agenda/NotasHilo.tsx:71` expone el botón de
papelera; `:53` lo condiciona a autor, `owner` o `admin` → `hooks/agenda.ts:148-153` →
`api/agenda.ts:127-129`. Se monta desde `components/agenda/DetalleCitaModal.tsx:323` y
`components/agenda/EventoDetalleModal.tsx:131`.
**Qué ve el usuario:** nada anómalo. Para conocer el `note_id` hay que haber cargado el hilo con
`GET /agenda/citas/<id>/notas/`, y ese padre **sí** está acotado (`agenda/views.py:1041` →
`:97-118`): un admin de Norte recibe 404 sobre una cita de Centro y nunca ve el id. **El frontend no
amplifica la brecha.** Explotarla exige llamar a la API a mano con un id obtenido por otra vía.
**Clase:** alcance de sede

### F-4-09 · `PATCH|DELETE /personal/doctores/<id>/` sin acotar por sede: brecha de backend, no amplificada por el front
**Severidad:** P2
**Backend:** `MailySoft/backend/apps/personal/views.py:239-247` — `_get_doctor_or_404` llama
`doctor_get(doctor_id=…)`, y `doctor_get` ni siquiera acepta un parámetro de alcance
(`apps/personal/selectors.py:21`), mientras el listado sí acota (`views.py:118`).
`02-contrato.md:6021-6023` ya lo marca como "acotado por sede: **no**".
**Frontend:** `MailySoft/web-soft/src/components/personal/MiembroDetalleDrawer.tsx:71` toma la lista
de médicos con `useDoctorsManage()` (acotada), `:91` resuelve `doctorPerfil` desde esa lista y `:165`
manda el PATCH con `doctorPerfil.id`. El front nunca llama a `GET /personal/doctores/<id>/`
(`src/api/personal.ts` solo tiene lista, alta, PATCH y DELETE).
**Qué ve el usuario:** nada. Un admin de Norte solo ve en el drawer a los médicos asignados a Norte,
así que solo puede editar esos. La brecha existe en la API, no en la pantalla.
**Clase:** alcance de sede

### F-4-10 · `X-Sucursal-Id` no está declarado en `CORS_ALLOW_HEADERS`
**Severidad:** P2 hoy · P0 funcional el día que el SPA se sirva desde otro origen
**Backend:** `MailySoft/backend/config/settings/base.py:485-489` y
`config/settings/production.py:87-91` definen `CORS_ALLOWED_ORIGINS`, `CORS_ALLOW_CREDENTIALS` y
`CORS_ALLOW_ALL_ORIGINS`, pero **nunca** `CORS_ALLOW_HEADERS`. La lista por defecto de
`django-cors-headers` no incluye `x-sucursal-id`. Es B-T-11 (`02-contrato.md:751-754`).
**Frontend:** `MailySoft/web-soft/src/lib/http.ts:22` — `BASE_URL = VITE_API_URL ?? '/api/v1'`, y
`web-soft/.env:3` lo fija en `/api/v1` (ruta relativa). Hoy no hay preflight: en dev va por el proxy
de Vite (`vite.config.ts:24-31`) y en producción Django sirve el SPA.
**Qué ve el usuario:** hoy, nada. El día que alguien despliegue el front en Vercel o Cloudflare y
ponga `VITE_API_URL=https://api.maily.mx/api/v1`, el navegador manda un preflight `OPTIONS` con
`Access-Control-Request-Headers: x-sucursal-id`, el backend no lo autoriza y **toda** petición
—lectura incluida— falla antes de salir. La app queda en blanco y el error de consola no menciona
sucursales. Es una bomba de despliegue de un solo renglón.
**Clase:** alcance de sede

### F-4-11 · El comentario de `http.ts` sobre el alcance del header está obsoleto y es falso
**Severidad:** P2
**Backend:** `sucursal_scope_ids` se usa hoy en agenda (`agenda/views.py:111`, `:132`, `:239`,
`:461`, `:930`), notas (`notas/views.py:80`, `:155`, `:359`), finanzas (11 llamadas,
`finanzas/views.py:163`…`:1374`), equipo (`tenancy/views.py:146`) y personal
(`personal/views.py:118`, `:359`, `:455`, `:599`, `:686`).
**Frontend:** `MailySoft/web-soft/src/lib/http.ts:131-133` — "el backend la usa para filtrar
**personal y consultorios**; los demás endpoints la **ignoran**". Es la documentación de la Fase 1;
quedó tres fases atrás.
**Qué ve el usuario:** nada directo. El riesgo es de mantenimiento: quien lea ese comentario puede
concluir que la inyección global del header es innecesaria y restringirla a dos rutas, apagando de
un golpe el scoping de agenda, notas, finanzas y equipo sin que ningún test de frontend lo note.
**Clase:** alcance de sede

---

### NO VERIFICABLE

1. **Orden exacto de ejecución en el arranque de F-4-04.** Tengo la evidencia de los dos lados
   (`AuthContext.tsx:118-133` no borra `maily.sucursal`; `http.ts:134-135` lee `localStorage` fuera
   de React; `SucursalContext.tsx:83-94` reconcilia en un `useEffect`; `sucursal_scope.py:305-309`
   responde 403), pero **no verifiqué en ejecución** si alguna query llega a disparar antes de que
   corra el efecto de reconciliación. Para confirmarlo: entrar con el usuario A, cerrar sesión,
   entrar con un usuario B de otra clínica en la misma pestaña y mirar la pestaña Red del navegador
   buscando un `X-Sucursal-Id` con el UUID de la clínica A y su respuesta 403.

2. **Frecuencia real de F-4-02(b).** Depende de que exista un actor no-owner con dos o más sedes
   asignadas que **no** incluyan la `is_default` del tenant. La configuración es posible
   (`MembershipSucursalesApi`, `clinica/urls.py:138`) pero no comprobé si hay tenants así en
   producción. Para confirmarlo: `SELECT` de `MembershipSucursal` agrupado por membresía, cruzado
   contra `Sucursal.is_default`.

3. **PDFs asíncronos.** `finanzas/views.py:1249` resuelve el alcance con `sucursal_scope_ids` antes
   de encolar el job, y `api/finanzas.ts:199` hace polling con `pdfJobBlob`. No verifiqué si la ruta
   de descarga del job terminado revalida la sede o solo el id del job. Haría falta leer
   `apps/pdfs/views.py` completo, fuera del alcance de este cruce.

---

### Defectos del contrato detectados

1. **§1.5.5 se contradice con §3.4.2 sobre la nota de cita, y §3.4.2 es la correcta.**
   `02-contrato.md:608` dice que un admin de Norte "puede **borrar** por id la nota de una cita de
   Centro" y remite a §3.4.2 sin más; §3.4.2 (`:2199`) precisa que la vista **solo implementa
   `delete`** (`agenda/views.py:1153`) y que un GET muere en 405. La fila de §1.5.5 ya trae la
   corrección incrustada, pero un lector que se quede en §1.5 puede creer que también se lee.
   Verificado: `AgendaItemNoteDetailApi` (`views.py:1144-1168`) solo define `delete`.

2. **§6.3.7 tiene los dos hechos de F-4-01 pero no los cruza.** `02-contrato.md:4868` ("con
   `patient_id` → no acotado, a propósito") y `:4869` ("detalle/acción por id → sí, 404") son
   correctas por separado. La consecuencia —que un listado no acotado alimenta acciones que sí lo
   están, y por tanto produce 404 sobre filas visibles— no está escrita en ninguna parte. Debería
   ser una nota bajo la tabla.

3. **§8.2.1 marca el detalle de médico como "no acotado" sin clasificarlo como brecha.**
   `02-contrato.md:6021-6023` lista `GET|PATCH|DELETE /personal/doctores/<id>/` con "Acotado por
   sede: **no**" en texto plano, mientras que el mismo desalineamiento en agenda y finanzas sí lleva
   identificador de brecha (B-AGE-01, B-FIN-15). Falta el identificador, o falta la justificación de
   por qué aquí es aceptable. En agenda la regla escrita es "si no lo veo en el listado, no lo puedo
   tocar por id" (`agenda/views.py:86-93`); personal la incumple sin decir por qué.

4. **§1.5.4 no advierte del efecto de "sin header" en las ESCRITURAS.** El bloque
   (`02-contrato.md:593-602`) contrapone bien `resolve_active_sucursal` y `sucursal_scope_ids` para
   LECTURAS, y cierra con "`resolve_active_sucursal` queda para conveniencia y para alimentar
   escrituras". No dice que, sin header, esa alimentación cae en la sede `is_default` del tenant
   —que es exactamente lo que produce F-4-02—. La regla vive solo en §1.5.3, punto 4. Convendría un
   renglón cruzado.

5. **§1.7.4 califica B-T-11 de "inocuo" sin condición de caducidad.** `02-contrato.md:751-754` dice
   "Hoy es inocuo" y explica por qué (mismo origen). Le falta la condición explícita: *deja de ser
   inocuo en el momento en que `VITE_API_URL` apunte a otro host*. Tal como está, un lector puede
   archivar la brecha en vez de atarla al despliegue.

---

## Cruce 5 · Bundle y XSS

Alcance verificado: `MailySoft/web-soft/src` (raíz de comandos: `MailySoft/web-soft/`), más
`index.html`, `vite.config.ts`, `.env*` y el bundle construido en `dist/`.
Contrato consultado: `MailySoft/docs/02-contrato.md` §1.2 (líneas 237-313) y §11.3 (7315-7377).

### Tabla de puntos binarios

| punto | comando verificado | resultado | veredicto |
|---|---|---|---|
| 1 · Cero `dangerouslySetInnerHTML` | `grep -rn "dangerouslySetInnerHTML" src/` | 0 coincidencias (exit 1) | **PASA** |
| 1b · Otros sumideros de HTML crudo | `grep -rn "innerHTML" src/` · `grep -rn "insertAdjacentHTML\|outerHTML\|createContextualFragment" src/` · `grep -rnE "\beval\(\|new Function\(\|document\.write\(" src/` | 0 coincidencias en las tres (exit 1) | **PASA** |
| 2 · Cero `fetch(` fuera de `lib/http.ts` | `grep -rn "fetch(" src/ \| grep -v "^src/lib/http.ts:" \| grep -vE "\brefetch\("` | 0 coincidencias (exit 1). El único `fetch` real es `src/lib/http.ts:151`; `src/pages/plataforma/SistemaPage.tsx:129` es `refetch()` de TanStack Query, no la API del navegador | **PASA** |
| 2b · `axios`, `XMLHttpRequest`, `sendBeacon`, `EventSource`, `WebSocket` | `grep -rnE "axios\|XMLHttpRequest\|sendBeacon\|EventSource\|WebSocket" src/` | 0 coincidencias (exit 1) | **PASA** |
| 2c · Los 21 módulos de `src/api/` pasan por el cliente central | `for f in src/api/*.ts; do grep -q "from '../lib/http'" "$f" \|\| echo "SIN http.ts: $f"; done` | 0 archivos listados | **PASA** |
| 3 · Access token solo en memoria | `grep -rn "localStorage\|sessionStorage" src/ \| grep -iE "token\|access\|jwt\|refresh"` | 0 coincidencias de código (exit 1). El único acierto textual es el comentario `src/lib/tokenStore.ts:9` que prohíbe justamente eso | **PASA** |
| 3b · Ningún otro sumidero de persistencia | `grep -rn "indexedDB\|IndexedDB" src/` → 0 (exit 1) · `grep -rn "document.cookie" src/` → 1 solo acierto, `src/lib/csrf.ts:12`, que **lee** `csrftoken`, no escribe | **PASA** |
| 4 · Cero secretos en `src/` o en `.env` versionado | `git ls-files \| grep -iE "\.env"` → `MailySoft/.env.production.example`, `MailySoft/backend/.env.example`, `MailySoft/web-soft/.env.example` (los tres son plantillas) | **PASA** |
| 4b · `.env` local no está commiteado | `git check-ignore -v MailySoft/web-soft/.env` → `MailySoft/.gitignore:62:.env` · `git log --all --diff-filter=A -- '**/.env'` → 0 commits · barrido de árboles: `git rev-list --all \| xargs git ls-tree -r --name-only \| grep -E "(^\|/)\.env$"` → 0 | **PASA** |
| 4c · Solo variables `VITE_*` | `grep -rn "import\.meta\.env" src/` → 3 aciertos: `src/main.tsx:13` (`VITE_SENTRY_DSN`), `src/main.tsx:18` (`VITE_SENTRY_ENVIRONMENT`), `src/lib/http.ts:22` (`VITE_API_URL`). Ninguna otra | **PASA** |
| 4d · Sin llaves ni URLs privadas | `grep -rniE "(api[_-]?key\|secret\|private[_-]?key\|BEGIN (RSA\|PRIVATE)\|sk_live\|sk_test\|pk_live\|AKIA\|cloudinary://\|postgres(ql)?://\|redis://\|amqp://)" src/` → 0 aciertos reales (todos los aciertos son de la palabra `password` en tipos y formularios) · `grep -rnoE "https?://…" src/` (excluyendo `openapi.d.ts`) → 1 sola URL absoluta, `src/components/consultorio/SeccionCredencialesValidar.tsx:69`, el portal público de la SEP | **PASA** |
| 4e · `dist/` no versionado | `git check-ignore -v dist/index.html` → `MailySoft/.gitignore:133:dist/` | **PASA** |
| 5 · Refresh ante 401 una sola vez y no sobre `/auth/refresh/` | Lectura completa de `src/lib/http.ts` (299 líneas). Guardas dobles: `http.ts:192` (`!options.skipAuthRefresh && path !== REFRESH_PATH`) y `http.ts:107` (`skipAuthRefresh: true` en el propio refresh). Reintento único: `http.ts:196` reinyecta `skipAuthRefresh: true`. Promesa compartida: `http.ts:88-97` (`refreshInFlight` + `ensureRefresh`) | **PASA** |
| 6 · Sin datos de prueba en el bundle | `grep -rn "\bCLINICAS\b" src/` → un solo acierto, la declaración en `src/data/clinicas.ts:21`; ningún importador. Verificación empírica en el bundle: `cat dist/assets/clinicas-DVGP8C-5.js` contiene **solo** `ESTADO_CLINICA` y `mxn`; `grep -rl "Bienestar M" dist/` → 0 (exit 1) | **PASA** (ver F-5-04) |
| 6b · Sin `mock`/`fixture`/`dummy`/`stub` en `src/` | `grep -rniE "\b(mock\|fixture\|dummy\|fake\|stub)\b" src/` → 0 · `find src -name "*.test.*" -o -name "*.spec.*" -o -name "__mocks__"` → 0 | **PASA** |
| 6c · Cadenas "demo" que sí llegan a producción | `grep -rn "demo" src/` → `src/auth/useRole.ts:5,17`, `src/auth/permisos.ts:67`, `src/platform/PlatformTopbar.tsx:95` | **FALLA** (F-5-01, F-5-02) |
| 7 · `lib/csrf.ts` alineado con el contrato §1.2 | `src/lib/csrf.ts:9-22` lee la cookie `csrftoken` y `src/lib/http.ts:146-149` la devuelve en `X-CSRFToken`; el contrato exige exactamente eso en `02-contrato.md:256-261` | **PASA** |
| 7b · Sesión: JWT en memoria + refresh en cookie httpOnly | `src/lib/tokenStore.ts:14` (variable de módulo) + `src/lib/http.ts:128-129` (`Bearer`) + `src/lib/http.ts:155` (`credentials: 'include'`), contra `02-contrato.md:243-244` | **PASA** |
| — · Política de CSP | no comprobable desde el frontend (cabecera de servidor) | **NO VERIFICABLE** |

---

### Punto 3 en detalle · cómo sobrevive la sesión a un F5

El access token vive en una variable de módulo, `src/lib/tokenStore.ts:14`
(`let accessToken: string | null = null`). Un F5 destruye el módulo: **el access token se pierde**.

La sesión se recupera así:

1. `src/auth/AuthContext.tsx:73-76` — si no hay cookie `csrftoken`, corta a `anonymous` sin pegarle
   a la API (evita un 403 ruidoso).
2. `src/auth/AuthContext.tsx:78-89` — llama `authApi.refresh()` y luego `authApi.me()`.
3. `src/api/auth.ts:36-40` — `POST /auth/refresh/`; el refresh viaja solo en la cookie httpOnly
   `maily_refresh`, que JS nunca ve.
4. `src/api/auth.ts:38` — el nuevo access vuelve a memoria con `setAccessToken`.

Coincide con `02-contrato.md:243-244` (access en memoria, 15 min; refresh en cookie httpOnly
`SameSite=Strict`, `Path=/api/v1/auth/`, 7 días) y con `02-contrato.md:268` (el refresh **lee la
cookie, no el cuerpo**; sin cookie → 401). No hay `SessionAuthentication` en la API
(`02-contrato.md:251-252`), así que la cookie de sesión de Django no participa.

**Consecuencia real:** un XSS en esta app no puede robar un token persistido ni el refresh; como
mucho usa la sesión mientras la pestaña vive. Es el diseño correcto y está implementado.

### Punto 5 en detalle · traza del 401

- **Flag de reintento:** `RequestOptions.skipAuthRefresh` (`src/lib/http.ts:62`). El reintento se
  emite en `src/lib/http.ts:196` con `{ ...options, skipAuthRefresh: true }`, y esa llamada va
  directo a `doFetch`, no a `fetchWithRefresh`. No hay recursión posible: como máximo **dos**
  peticiones por llamada del usuario.
- **Promesa compartida:** `src/lib/http.ts:88` (`refreshInFlight`) y `src/lib/http.ts:90-97`
  (`ensureRefresh`). Si diez peticiones dan 401 a la vez, se dispara **un solo**
  `POST /auth/refresh/`; las otras nueve esperan la misma promesa.
- **Exclusión del propio refresh:** doble candado.
  `src/lib/http.ts:192` compara `path !== REFRESH_PATH` (`REFRESH_PATH = '/auth/refresh/'`,
  `src/lib/http.ts:25`), y `src/lib/http.ts:105-108` además pasa `skipAuthRefresh: true`.
  El candado de la ruta es el que salva a `src/api/auth.ts:37`, que llama `/auth/refresh/`
  **sin** `skipAuthRefresh` (bootstrap y login); la cadena literal coincide exactamente, así
  que hoy funciona.

### Punto 7 en detalle · qué espera el backend

| | Contrato | Frontend |
|---|---|---|
| Sesión | JWT: access en memoria por `Authorization: Bearer`, refresh en cookie httpOnly `maily_refresh` (`02-contrato.md:243-244`). **No hay `SessionAuthentication`** (`:251-252`) | `src/lib/tokenStore.ts:14` + `src/lib/http.ts:128-129` + `credentials: 'include'` en `:155` |
| CSRF | Cookie `csrftoken` legible por JS (`CSRF_COOKIE_HTTPONLY=False`, `02-contrato.md:259-260`, confirmado en `backend/config/settings/production.py:59`), devuelta en el **header** `X-CSRFToken`. Solo `/auth/refresh/` y `/auth/logout/` llevan `@csrf_protect` (`02-contrato.md:256-258`) | `src/lib/csrf.ts:11-22` lee la cookie; `src/lib/http.ts:146-149` manda `X-CSRFToken` en **todo** POST/PUT/PATCH/DELETE |
| Mismo origen | `DEPLOY-RAILWAY.md:5` — Django sirve la API y el React en **un solo dominio**, precisamente porque el login por cookie lo exige | `src/lib/http.ts:22` — `VITE_API_URL` por defecto `/api/v1` (ruta relativa) |

El frontend manda el header en más métodos de los que el backend exige. Es un superconjunto
inofensivo: Django ignora `X-CSRFToken` donde no hay `@csrf_protect`. **Alineado.**

Nota de despliegue (no es un hallazgo, es una restricción a no romper): `csrf.ts` depende de que
`document.cookie` del origen del frontend vea la cookie `csrftoken` que pone el backend. Si algún
día se separan los dominios (front en un servicio, API en otro), `getCsrfToken()` devolverá `null`,
`AuthContext.tsx:73-76` cortará a `anonymous` en cada carga y el refresh/logout responderán 403.
`DEPLOY-RAILWAY.md:5` ya lo advierte.

---

### Hallazgos

### F-5-01 · Hook `useRole` huérfano que persiste un rol de demostración y falla abierto a `owner`
**Severidad:** P2
**Backend:** `MailySoft/docs/02-contrato.md:308-310` — `GET /me/` devuelve `active_role` y es la
única fuente del rol de la sesión; el rol del frontend nunca concede permisos.
**Frontend:** `src/auth/useRole.ts:17` define `STORAGE_KEY = 'maily_demo_role'`,
`src/auth/useRole.ts:18` define `DEFAULT_ROLE: Role = 'owner'`, `src/auth/useRole.ts:36` lee ese
rol de `localStorage` y `src/auth/useRole.ts:50` lo escribe. El archivo **no tiene ningún
importador**: `grep -rn "auth/useRole'" src/` → 0 coincidencias (exit 1); todo el código consume
`useRole` desde `src/auth/RoleContext.tsx:20`, que sí deriva el rol de `/me/` vía `AuthContext` y
cae a `'readonly'` (mínimo privilegio) en `src/auth/RoleContext.tsx:15`.
**Qué ve el usuario:** hoy, nada — verificado: `grep -rl "maily_demo_role" dist/` → 0
coincidencias (exit 1), Rollup lo elimina por *tree shaking* al no tener importadores. El riesgo es
de mantenimiento y es concreto: **existen dos hooks exportados con el nombre idéntico `useRole`**,
uno que falla cerrado (`RoleContext.tsx`) y otro que falla abierto a `owner`
(`useRole.ts:18`). El día que un autocompletado importe el segundo, cualquier sesión sin
`active_role` resuelto (los milisegundos antes de que `/me/` responda, o un usuario sin membresía)
pinta la UI completa de dueño: botones de finanzas, alta de personal y configuración de la clínica.
El backend los rechazaría con 403 — botón fantasma, no fuga —, pero es la falla que esta auditoría
ya nombra como la más cara en soporte.
**Clase:** bundle

### F-5-02 · Selector "Ver como (demo)" en producción, con rol por defecto `super_admin`
> **Consolidado en `F-1D-01`.** El mismo defecto lo encontró otro cruce con un escenario mejor. Se conserva aquí la evidencia porque el ángulo es distinto, pero **no cuenta como hallazgo aparte** en el total del resumen.
**Severidad:** P2
**Backend:** `MailySoft/docs/02-contrato.md:308-310` — el rol real sale de `/me/`; el backend es la
autoridad y bloquea aunque la UI muestre de más.
**Frontend:** `src/platform/PlatformTopbar.tsx:95` pinta la etiqueta literal
`Ver como (demo)` sobre un menú que llama `setRole()` (`src/platform/PlatformTopbar.tsx:26,34`).
`src/platform/PlatformRoleContext.tsx:19` inicializa el estado en `'super_admin'` y solo lo corrige
en el `useEffect` de `src/platform/PlatformRoleContext.tsx:21-26`, cuando `/me/` ya respondió.
Verificado en el bundle construido: `grep -rl "Ver como (demo)" dist/` →
`dist/assets/plataforma-B-39TeeA.js`, es decir **sí se despacha**.
**Qué ve el usuario:** un miembro del equipo interno con rol `sales` entra al panel de plataforma.
Entre el montaje y la respuesta de `/me/`, la barra de navegación se pinta como `super_admin` y
muestra las secciones de ingeniería; luego desaparecen. Si alcanza a hacer clic, recibe un 403. Y
en estado estable puede elegirse a sí mismo `super_admin` desde el menú y navegar por pantallas
que la API le negará una por una. Nótese la asimetría con el lado de clínica: `RoleContext.tsx:9`
usa `'readonly'` como valor por defecto (mínimo privilegio) y `PlatformRoleContext.tsx:19` usa el
máximo. El alcance es el equipo interno de Maily, no las clínicas, y no hay fuga de datos porque el
backend filtra; por eso es P2 y no P1.
**Clase:** bundle

### F-5-03 · Google Fonts cargado desde CDN externo en el shell de una app de salud
**Severidad:** P2
**Backend:** no aplica — es un recurso del documento HTML, anterior a cualquier llamada a la API.
El contrato no describe el shell del frontend.
**Frontend:** `MailySoft/web-soft/index.html:9-10` (`preconnect` a `fonts.googleapis.com` y
`fonts.gstatic.com`) y `MailySoft/web-soft/index.html:11-14` (`<link rel="stylesheet">` a
`fonts.googleapis.com/css2?family=Inter…`).
**Qué ve el usuario:** nada visible, y ese es el punto. Cada carga de la app desde el consultorio
—recepcionista, médico, cada pestaña— envía la IP y el User-Agent de la clínica a un tercero fuera
de México, en un producto que maneja expedientes clínicos. No es una fuga de secretos: la URL es
pública y no hay `VITE_*` ni token en ella; es un flujo de datos hacia un tercero que nadie
declaró. Dos consecuencias operativas: (a) si `fonts.googleapis.com` no es alcanzable —red de
clínica con filtrado, o corte de CDN— la app carga con la fuente de respaldo, degradación
tolerable; (b) un `<link rel="stylesheet">` de origen ajeno tiene, sin `integrity` ni CSP, permiso
para inyectar CSS arbitrario en la app, y CSS con selectores de atributo es un canal de
exfiltración conocido. Se cita aquí porque el cruce cubre la integridad del bundle, no porque
viole la letra del punto 4.
**Clase:** bundle

### F-5-04 · Arreglo de seis clínicas ficticias en `src/data/clinicas.ts`
**Severidad:** P2
**Backend:** no aplica — es un literal del frontend, ningún endpoint lo produce ni lo consume.
**Frontend:** `src/data/clinicas.ts:21` declara `export const CLINICAS: Clinica[]` con seis
clínicas inventadas y sus cifras de negocio (nombre, ciudad, plan, usuarios, pacientes, ingreso
mensual). El archivo **sí** lo importan cuatro módulos de producción, pero ninguno toca `CLINICAS`:
`src/pages/plataforma/ClinicasPage.tsx:6`, `src/pages/plataforma/DashboardPage.tsx:4`,
`src/pages/plataforma/SuscripcionesPage.tsx:9` y
`src/components/plataforma/ClinicaDetailDrawer.tsx:4` importan `ESTADO_CLINICA` y `mxn`;
`src/types/plataforma.ts:27` importa solo el tipo `EstadoClinica`.
**Qué ve el usuario:** hoy, nada — y esto está **verificado contra el bundle**, no supuesto:
`cat dist/assets/clinicas-DVGP8C-5.js` devuelve el chunk completo y contiene únicamente
`ESTADO_CLINICA` y `mxn`; el arreglo desapareció por *tree shaking*. Confirmado por el negativo:
`grep -rl "Bienestar M" dist/` → 0 coincidencias (exit 1). El hallazgo es de higiene: un archivo
llamado `data/clinicas.ts` que cuatro pantallas de plataforma ya importan es exactamente donde
alguien va a buscar "los datos de las clínicas", y una sola línea que use `CLINICAS` como respaldo
de un estado de carga metería seis clínicas falsas —con ingresos falsos— en el panel comercial
interno. Además `src/auth/permisos.ts:67` deja escrito que el rol "lo simulamos con un selector
para la demo", comentario que ya no describe el sistema (`RoleContext.tsx` usa `/me/`).
**Clase:** bundle

---

### NO VERIFICABLE

- **Política de CSP (`Content-Security-Policy`).** `index.html` no lleva ninguna `<meta http-equiv>`
  de CSP (revisadas las 20 líneas del archivo). Una CSP se sirve normalmente como cabecera HTTP
  desde el servidor que entrega el `index.html`, que aquí es el mismo servicio Django
  (`DEPLOY-RAILWAY.md:5`). **Falta para confirmar:** la configuración de cabeceras del servicio web
  (middleware de seguridad o WhiteNoise en `MailySoft/backend/config/settings/production.py`), que
  cae fuera del alcance de este cruce. Sin CSP, F-5-03 pasaría de riesgo teórico a riesgo real.
- **Frescura del bundle de `dist/`.** Los veredictos empíricos de los puntos 6 y 6c se apoyan en
  `dist/`, construido el 3 de agosto (`ls -la dist/`), mientras el árbol de trabajo tiene cambios
  posteriores sin construir (`git status` marca ~35 archivos modificados). Los tres archivos que
  sustentan esos veredictos —`src/data/clinicas.ts` (4 jun), `src/auth/useRole.ts` y
  `src/platform/PlatformTopbar.tsx`— no aparecen entre los modificados, así que la evidencia se
  sostiene. **Falta para cerrarlo sin reservas:** un `npm run build` y repetir los tres `grep`
  sobre `dist/assets/`.
- **`SIGNING_KEY` y demás secretos del backend.** Fuera del alcance de este cruce, que solo audita
  `web-soft/`. No se encontró ningún secreto en el frontend, ni en disco ni en el historial de git.

---
