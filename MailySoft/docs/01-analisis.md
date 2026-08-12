# Análisis — Maily360 / MailySoft

> Define **qué** se construye, no cómo. Producido en Cowork (fases 0 y 1).
> No se modifica durante la programación: si algo cambia aquí, se replantea el contrato.
>
> **Documento de adopción retroactiva.** Este análisis no se escribió antes del código: se
> reconstruyó **desde el código** el 2026-08-11, consolidando la documentación previa del repo.
> Donde la documentación vieja contradecía al código, ganó el código.
> Cada afirmación de aquí está verificada contra un archivo del repo; lo que no se pudo verificar
> está marcado como tal.
>
> - **Fecha de adopción del modelo de trabajo: 2026-08-11.** Todo commit posterior pasa por el
>   `reviewer` en modo gate.
> - Último commit auditado: `cfbc1e6` (2026-07-27).
> - Lo que el sistema **hace hoy** a nivel de API, modelos y permisos va en `docs/02-contrato.md`
>   (sesión A2, `architect` en modo inverso). Este documento es el **qué** y el **para quién**.
> - La documentación previa archivada está en `docs/_legacy/`, con su índice y la razón de cada
>   movimiento.

---

## 1. El problema

Una clínica privada mexicana lleva su operación en tres lugares que no se hablan: la agenda en un
cuaderno o en WhatsApp, el expediente del paciente en papel o en un sistema viejo, y el cobro en una
libreta aparte. Cuando el dueño abre una segunda sucursal, deja de ver lo que pasa en la primera. Y
cuando llega una revisión, no puede demostrar quién vio ni quién modificó el expediente de un
paciente.

**Cómo lo hacen hoy:** el punto de partida real es `app.maily.mx`, un sistema PHP heredado, más
papel y WhatsApp alrededor. Maily360 es la migración de ese sistema a una plataforma nueva.

**Qué les cuesta hoy:** citas perdidas y empalmadas, expedientes incompletos que se descubren en la
consulta, cobros que se olvidan, y exposición legal por no tener bitácora de accesos a datos de
salud.

**El problema del lado del negocio (Emanuel):** el mismo software debe venderse a muchas clínicas
sin duplicar el código ni mezclar los datos de una con los de otra. Eso es lo que convierte esto de
un proyecto a la medida en un producto con ingreso recurrente.

## 2. Quiénes lo usan

Hay **dos ejes de identidad independientes**: los roles dentro de una clínica y el staff interno de
Maily. Un usuario puede tener rol de clínica, ser staff de plataforma, o ambos.

### Roles de clínica (7 — `backend/apps/tenancy/models.py:95`)

| Rol | Quién es | Qué hace en el sistema | Dispositivo |
|---|---|---|---|
| `owner` Dueño | El médico o inversionista dueño de la clínica | Todo. Único que ve la **bitácora de auditoría**, administra **sucursales** y el **catálogo de servicios y paquetes** | Escritorio y móvil |
| `admin` Administrador | Gerente de la clínica | Casi todo lo operativo, pero **no** ve la bitácora ni crea sucursales ni edita el catálogo de precios | Escritorio |
| `doctor` Médico | Quien da la consulta | Su agenda, expediente, notas de evolución, recetas. Solo agenda **para sí mismo** y en **sus** consultorios | Escritorio y tablet |
| `nurse` Enfermería | Apoyo clínico | Mueve al paciente por el flujo de la cita, captura signos vitales, alergias. **No agenda** | Tablet |
| `reception` Recepción | Front desk | Agenda, reagenda, da de alta pacientes, cotiza y **recibe pagos**. No ve expediente clínico ni recetas | Escritorio |
| `finance` Finanzas | Quien factura y cobra | Cargos, pagos, CFDI, dashboard. **No** ve agenda ni expediente | Escritorio |
| `readonly` Solo lectura | Contador externo, auditor, socio | Lee finanzas y panel de retención. No escribe nada | Escritorio |

Tres reglas duras que no se leen en la tabla:

- **Sin membresía activa → 403 en todo.** La autoridad de permisos es el backend; el rol del
  frontend solo decide qué se muestra (`backend/apps/core/permissions.py:81`, *fail-closed*).
- **Qué roles existen en una clínica depende de su plan.** `Plan.roles` es una allow-list y un rol
  también necesita su módulo activo: `finance` no existe si la clínica no tiene el módulo de
  cobranza (`backend/apps/core/modules.py:66`, `backend/apps/tenancy/models.py:240`).
- **Los roles operativos se acotan por sucursal.** El `owner` ve todas las sedes; todos los demás,
  incluido `admin`, solo las que tienen asignadas (`backend/apps/clinica/sucursal_scope.py:200`).

### Staff interno de Maily (3 — `backend/apps/authn/models.py:35`)

| Rol | Qué hace |
|---|---|
| `super_admin` | Alta y suspensión de clínicas, asignación de plan y de módulos, staff interno |
| `sales` | Alta de clínicas y suscripciones |
| `engineering` | Métricas, salud del sistema, bitácora cross-tenant |

Opera **cross-tenant** deliberadamente, con `all_objects` (bypass explícito del filtro por clínica)
y sin membresía en ninguna clínica.

### Quién NO es usuario del sistema hoy

**El paciente.** No hay portal ni app de paciente. Existe una única pantalla pública sin sesión:
la verificación de una receta por QR (`web-soft/src/pages/VerificarRecetaPage.tsx`). La app del
paciente ("Maily te cuida") está diseñada en `documentacion/` pero **no existe en el código**.

## 3. Flujos principales

### Flujo 1 — Alta de una clínica nueva (comercial)

1. Maily (staff `super_admin` o `sales`) crea la clínica desde el portal interno: nombre, dueño,
   contraseña temporal.
2. Se le asigna un **plan**, que define qué módulos ve, cuántas sucursales, consultorios y usuarios
   puede tener, y qué roles puede crear.
3. Se siembran las etiquetas de sistema del catálogo de pacientes (Favorito, VIP) y la sucursal
   inicial.
4. El dueño entra y el sistema lo **obliga a cambiar la contraseña** antes de hacer nada
   (`User.must_change_password`).
5. El dueño da de alta a su equipo creando cuentas con contraseña inicial. **No hay invitación por
   correo.**

**Qué puede salir mal:** que la clínica quede sin plan (le tocan cero módulos y el sistema se ve
vacío); que el dueño exceda el límite de usuarios del plan a media captura del equipo; que la
contraseña temporal se comparta por WhatsApp y nadie la cambie.

### Flujo 2 — Del agendado a la nota de evolución (clínico, el flujo central)

1. Recepción agenda una cita: paciente existente, o **paciente provisional creado al vuelo** con
   solo el nombre. Paciente y cita se crean en **una sola transacción**: si la cita falla, el
   expediente no se crea.
2. La cita lleva tipo (con color), modalidad (consultorio / teléfono / video / a domicilio) y
   sucursal. El sistema **impide el empalme** por médico, por consultorio y contra bloqueos, en el
   servicio y con restricciones de la base de datos.
3. El día de la cita, un vigilante in-app le recuerda a recepción o al médico mover el estado:
   Agendada → En sala → En consulta → Atendida. **Nunca cambia el estado solo**: lo confirma una
   persona.
4. Enfermería captura signos vitales y alergias.
5. El médico escribe la **nota de evolución SOAP**. Solo puede escribirla si la cita está
   **Atendida**, solo una nota por cita, y **la nota nace bloqueada**: no se edita ni se borra. Una
   corrección se agrega como **addendum** firmado.
6. Diagnósticos e imágenes de evolución cuelgan de esa nota.
7. Si aplica, el médico emite la **receta**: inmutable, con folio consecutivo, snapshot de los
   signos vitales, y dos PDFs (media carta para farmacia, carta completa para el paciente). Anular
   sí; editar no.
8. Todo se "encuaderna" en el **Libro Clínico** del paciente, exportable a PDF en tres modos.

**Qué puede salir mal:** que el médico dé la consulta y nunca marque la cita como Atendida, con lo
que no puede escribir la nota; que se agende un paciente nuevo que ya existía con otro nombre
escrito distinto (**no hay detección de duplicados**); que el médico use telemedicina y el sistema
lo acote a consultorios — resuelto: las citas sin consultorio no aplican esa regla.

### Flujo 3 — Del servicio al cobro (comercial de la clínica)

1. La clínica define su **catálogo de servicios** con precio y claves SAT, y opcionalmente
   **paquetes** de sesiones. Solo el dueño edita el catálogo.
2. Recepción o el médico arma una **cotización** con renglones, descuento por monto o por
   porcentaje, y vigencia. Se envía y se acepta.
3. Al aceptarse se generan **cargos** (cuentas por cobrar), que pueden colgar de una cita.
4. Se registran **pagos**, que se asignan a cargos específicos.
5. Con el pago se puede emitir un **CFDI 4.0**, o cancelarlo con motivo.
6. El dueño ve dashboard, reporte financiero, cierre diario y un **panel de retención** que
   segmenta pacientes por recencia, frecuencia y gasto, calculado en vivo.

**Qué puede salir mal:** que el CFDI se emita con datos fiscales mal capturados — **el timbrado
real contra un PAC nunca se ha probado**; que un médico vea el estado de cuenta de su paciente
cuando la clínica no quería (hay un interruptor por clínica, `doctors_see_costs`).

### Flujo 4 — Coordinación interna del equipo

Notas y tareas personales con recordatorio; avisos dirigidos a un rol o a toda la clínica; hilo de
notas del equipo sobre una cita concreta. Todo dispara **notificaciones in-app** (campana con
sondeo cada 30 s, más una luz de recordatorios vencidos). No hay WebSockets: fue una decisión
explícita para no pagar complejidad operativa.

## 4. Pantallas

### Aplicación de la clínica (`web-soft/src/pages/`)

| Pantalla | Quién entra | Qué ve | Qué puede hacer |
|---|---|---|---|
| `LoginPage` | Cualquiera | Acceso por correo | Entrar. El token de acceso vive en memoria, el de refresco en cookie `httpOnly` |
| `CambiarContrasenaPage` | Usuario con cambio forzado | — | Fijar su contraseña definitiva |
| `AgendaPage` | Todos menos Finanzas | Tablero por día, por consultorio, con columna fija de Telemedicina/Externo | Agendar, reagendar, reactivar, cambiar estado, crear bloqueos y reuniones, comentar la cita |
| `ContactosPage` (Pacientes) | Todos | Lista o tarjetas, búsqueda en servidor, filtros por segmento y etiqueta | Alta, edición, baja, avatar, etiquetas, abrir el expediente |
| Expediente (**drawer**, no ruta) | Owner, Admin, Médico, Enfermería, Solo lectura | Dos columnas con índice de secciones: alergias, historia clínica configurable, signos vitales con gráficas, evoluciones SOAP, diagnósticos, imágenes, planes de tratamiento, plan integral, recetas | Capturar la visita del día, emitir receta, imprimir el Libro Clínico |
| `PersonalPage` | Todos ven; solo Owner/Admin editan | Equipo por rol, consultorios, tipos de cita | CRUD de personal y consultorios, bloqueo de cuentas, restablecer contraseña, perfil médico |
| `NotasPage` | Todos | Mis notas y tareas · Avisos de la clínica | Crear, fijar, marcar hecha, dirigir un aviso a un rol |
| `FinanzasPage` | Owner, Admin, Finanzas, Recepción, Solo lectura (por pestaña) | Dashboard, cobros y pagos, CFDI, estado de cuenta, retención | Registrar pagos, emitir y cancelar CFDI, exportar |
| `CotizacionesPage` | Owner, Admin, Médico, Recepción (Solo lectura ve) | Cotizaciones y su estado | Crear, enviar, aceptar, PDF |
| `PaquetesPage` | Owner, Admin, Médico, Recepción | Paquetes de tratamiento | Solo el dueño los crea y edita |
| `MiConsultorioPage` | Owner, Admin (Médico en lo suyo) | Configuración de la clínica: membrete, formato de receta con vista previa, credenciales del médico, plantillas, sucursales, configuración de agenda | Configurar. La bandeja de validación de credenciales es de Owner/Admin |
| `VerificarRecetaPage` | **Público, sin sesión** | Validez de una receta desde su QR | Solo verificar |

### Portal interno de Maily (`web-soft/src/pages/plataforma/`)

`DashboardPage` (métricas globales) · `ClinicasPage` (alta, detalle, suspender, asignar plan y
editar módulos) · `SuscripcionesPage` (planes y suscripciones) · `UsuariosPage` (staff interno) ·
`AuditoriaPage` (bitácora cross-tenant) · `SistemaPage` (salud real de servicios).

**Todas conectadas a datos reales.** No queda ningún panel con datos falsos; el único residuo es un
arreglo de clínicas ficticias en `web-soft/src/data/clinicas.ts:21` que ya nadie importa — código
muerto por borrar.

## 5. Módulos

Los módulos **no son fases de construcción**: son el catálogo comercial que decide qué ve cada
clínica según su plan. La fuente de verdad es `backend/apps/core/modules.py`.

| # | Módulo | Grupo | Qué incluye | Depende de |
|---|---|---|---|---|
| 1 | `agenda` | Clínico | Citas, tipos de cita, bloqueos y reuniones, disponibilidad, series | — |
| 2 | `recordatorios` | Clínico | Recordatorios de cita (motor Celery) | 1 |
| 3 | `expediente` | Clínico | Alergias, historia clínica, signos vitales, evoluciones SOAP, diagnósticos, imágenes, libro clínico | — |
| 4 | `recetas` | Clínico | Recetas inmutables, catálogo de medicamentos, formatos y PDFs, controlados | — |
| 5 | `notas` | Clínico | Notas, tareas y avisos internos | — |
| 6 | `personal` | Operación | Doctores, consultorios, horarios, equipo | — |
| 7 | `servicios` | Comercial | Catálogo de conceptos cobrables con claves SAT | — |
| 8 | `paquetes` | Comercial | Paquetes de sesiones | 7 |
| 9 | `cotizaciones` | Comercial | Cotizaciones con descuentos | 7 |
| 10 | `cobranza` | Comercial | Cargos, pagos, estado de cuenta, reportes | — |
| 11 | `cfdi` | Comercial | Facturación CFDI 4.0 | 10 |
| 12 | `calendarizacion` | Especial | Calendarización de tratamientos | 3, 7, 9 |

> `calendarizacion` no viene en ningún plan estándar: se enciende caso por caso como override.
> **Multi-sucursal no es un módulo**: es el límite `max_sucursales` del plan. Se decidió así a
> propósito para no tener dos fuentes de verdad.

### Planes (`backend/apps/tenancy/management/commands/seed_planes.py`)

| Plan | Precio/mes | Módulos | Sucursales | Consultorios | Usuarios | Activo |
|---|---|---|---|---|---|---|
| Solo | $900 | los 5 clínicos | 1 | 1 | 1 | no |
| Básico | $1,500 | clínicos + `personal` | 1 | 1 | 3 | sí |
| Pro | $4,500 | + los 4 comerciales sin CFDI | 1 | 5 | ilimitado | sí (destacado) |
| Premium | $8,900 | + `cfdi` | ilimitado | ilimitado | ilimitado | sí |
| Enterprise | a cotizar | + `cfdi` | ilimitado | ilimitado | ilimitado | sí |

Los límites y los módulos se pueden **sobrescribir por clínica** desde el portal interno
(`TenantEntitlements`), sin tocar el plan. Un módulo apagado responde **404, no 403**: la clínica no
sabe que existe algo que no compró.

⚠ **Estos precios están en el código y en `docs/_legacy/`, pero las presentaciones comerciales de
`documentacion/` manejan cifras completamente distintas ($13,990, $22,990, $199/mes, $399/mes).
Antes de vender la siguiente licencia hay que fijar una sola lista.**

## 6. Alcance

**Incluye (verificado en código):**

- Multi-tenant real: 15 apps Django, aislamiento por clínica con **doble barrera** — filtro en
  Django más Row Level Security en PostgreSQL. **Ninguna tabla con datos de clínica quedó sin
  política RLS**, incluidas las tablas intermedias de las relaciones muchos-a-muchos, y hay un
  **test guardián** que recorre todos los modelos contra el catálogo de PostgreSQL y falla en CI si
  alguien agrega una tabla sin política (`backend/apps/core/tests/test_rls_coverage.py`). Es la
  pieza de seguridad mejor resuelta del proyecto.
- Multi-sucursal: sedes por clínica, asignación de personal a sedes, alcance de agenda, finanzas y
  avisos por sede.
- Planes, módulos y límites por clínica, con el backend como autoridad (91 vistas con guard de
  módulo).
- Expediente clínico con inmutabilidad y addenda, pensado para NOM-004.
- Recetas inmutables con PDF, verificación pública por QR firmado con HMAC, y módulo de
  controlados.
- Finanzas de punta a punta: catálogo, cotizaciones, cargos, pagos, CFDI 4.0, reportes, cierre
  diario, panel de retención RFM.
- Bitácora de auditoría con **más de 100 tipos de acción**, visible solo para el dueño.
- Portal interno de Maily, conectado a datos reales.
- PDFs asíncronos con Celery (7 tipos de documento).
- Sentry en backend y frontend, condicionado a variable de entorno.
- Pruebas: suite de backend con pytest y 9 pruebas E2E con Playwright.
- Despliegue en Railway con Docker, y soporte para rol de base de datos sin privilegios.

**NO incluye:** *(esta lista evita el 90% de los conflictos)*

- **App o portal del paciente.** Diseñada, no construida.
- **Identidad global del paciente entre clínicas** (Master Patient Index). Prometida en ADR-0001,
  nunca implementada. Cada clínica tiene sus propios expedientes.
- **Recordatorios reales por WhatsApp.** El adaptador es un placeholder que solo escribe en el log
  (`backend/adapters/whatsapp.py`). El motor de Celery existe; el envío no.
- **Timbrado real de CFDI contra un PAC.** El modelo, los endpoints y el flujo existen; nunca se
  validó contra un proveedor autorizado.
- **Compra en autoservicio.** El alta de clínica la hace Maily desde el portal interno. El flujo de
  "elige tu plan y crea tu clínica" está solo en maquetas.
- **Cambio de clínica activa para un usuario con varias membresías.** Ver §9, riesgo 2.
- **Catálogo configurable de especialidades.** Hoy es texto libre en el perfil del médico.
- **Módulos por especialidad** (dental, nutrición, fisioterapia). Se resolvió por planes y módulos
  genéricos, no por plugins.
- **Base de datos dedicada para Enterprise.** Es una promesa comercial sin implementación.
- **Tiempo real por WebSockets.** Las dependencias están instaladas y sin usar; las notificaciones
  son por sondeo.
- **Detección y fusión de pacientes duplicados.**
- **Cobro automatizado de la suscripción.** No hay pasarela de pago conectada: la suscripción se
  registra, no se cobra.

## 7. Datos sensibles

**¿Maneja datos personales o de salud?** Sí, y de la categoría más protegida.

**Cuáles:** nombre, fecha de nacimiento, sexo, teléfono y correo del paciente; historia clínica
completa incluyendo antecedentes heredo-familiares, gineco-obstétricos y hábitos; signos vitales;
notas de evolución; diagnósticos con código CIE-10; imágenes clínicas; recetas y medicamentos
controlados; datos fiscales del paciente para el CFDI. Del lado del personal: cédula profesional y
credenciales académicas.

**Quién puede verlos:** el expediente clínico lo leen Owner, Admin, Médico, Enfermería y Solo
lectura. **Recepción y Finanzas no leen expediente ni recetas** — es una decisión explícita. Un
médico solo puede escribir sobre las citas que son suyas. Las alergias son la excepción
deliberada: las lee cualquier rol, porque un dato de alergia oculto puede matar a alguien.

**¿Requiere bitácora de auditoría?** Sí, y existe: quién, qué acción, sobre qué recurso, con qué
rol, en qué clínica y desde qué IP. La consulta la ve **solo el dueño**, para que un administrador
de una sede no vea la actividad de otra.

**Marco normativo:** el proyecto se declara alineado a NOM-024, NOM-004 y LFPDPPP. **Esa alineación
nunca la revisó un abogado.** Está construida sobre la interpretación de un desarrollador y de un
modelo de lenguaje. Antes de vender a una clínica que exija cumplimiento por contrato, esto se
consulta con un especialista y el resultado se convierte en puntos fijos del checklist de
seguridad, no en prosa.

**Técnicamente implementado hoy:** contraseñas con Argon2, tokens híbridos (acceso en memoria,
refresco en cookie `httpOnly` con CSRF double-submit), validación real de imágenes subidas,
minimización de PII en la bitácora, aislamiento por RLS, y borrado lógico en lugar de físico.

## 8. Restricciones

- **Presupuesto y fecha:** producto propio, sin cliente que imponga fecha. Prioridad declarada de
  los próximos 3 meses.
- **Costo de infraestructura:** ~30 USD/mes en Railway para todos los proyectos de Emanuel juntos.
  Maily360 corre ahí con Postgres, Redis, un worker de Celery y Cloudinary para archivos. **Hoy la
  infraestructura no se repercute al cliente.** Con planes desde $1,500 MXN/mes hay margen de
  sobra, pero la cuota mensual debe incluirla explícitamente.
- **Sistemas con los que debe convivir:** `app.maily.mx`, el sistema PHP heredado del que migra.
  No hay integración: es reemplazo, no coexistencia. Servicios externos previstos: PAC para CFDI,
  WhatsApp Business API, Cloudinary, Sentry.
- **Volumen esperado:** hoy 1 a 3 usuarios concurrentes por clínica (personal administrativo). La
  arquitectura está dimensionada para muchas clínicas pequeñas, no para una clínica enorme.
- **Techo técnico conocido:** el aislamiento por RLS fija una variable de sesión en PostgreSQL. Con
  la configuración actual (`DB_TENANT_GUC_MODE=session`) **no se puede poner un pooler en modo
  transacción** delante de la base. El modo compatible ya está implementado detrás de una bandera,
  pero apagado. Al escalar réplicas, el límite es el número de conexiones de Postgres.
- **Restricción de proceso:** desde el 2026-08-11 este repo opera con el modelo de seis fases. El
  código anterior a esa fecha no bloquea nada — se audita una vez y se convierte en backlog
  priorizado (*clean as you code*).

## 9. Riesgos conocidos al momento de la adopción

> Esto **no es** `docs/00-deuda.md`. Es lo que salió de auditar la documentación previa contra el
> código en la sesión A1, y sirve de insumo para la sesión A3, donde el `reviewer` audita el código
> por su cuenta y produce la deuda priorizada de verdad. Si A3 no confirma un punto de aquí con
> `archivo:línea`, gana A3.

1. **No existe procedimiento de respaldo ni restauración probada.** Cero referencias a `pg_dump` o
   a un runbook de restore en todo el repo. Un sistema con datos de salud en producción sin una
   restauración jamás probada no tiene respaldo, tiene una esperanza. **Este es el riesgo más
   grave del proyecto.**
2. **Un usuario con membresía en dos clínicas siempre opera sobre la misma, sin poder cambiar.** La
   elección explícita de clínica (`X-Tenant-ID` validado contra el JWT) se prometió en ADR-0002 y
   nunca se implementó. Consecuencia concreta: un médico que trabaja en dos clínicas puede escribir
   una nota de evolución en la clínica equivocada, y por diseño esa nota es inmutable.
3. **La IP de la bitácora se toma de `X-Forwarded-For` sin lista de proxies confiables.** Cualquier
   cliente puede falsificar la IP que queda registrada en la bitácora de auditoría — que es
   justamente el registro que se usaría como evidencia.
4. **PII y texto clínico en el título y cuerpo de las notificaciones.** El aviso de una nota de
   equipo incluye el nombre del paciente y un extracto de la nota. Hay que decidirlo y
   documentarlo, no dejarlo sin decidir.
5. **CSP nunca configurada.** El bloque entero está comentado en la configuración de producción.
6. **CFDI nunca validado contra un PAC real.** Riesgo comercial directo: se vende facturación que
   no se ha probado end-to-end.
7. **Hallazgo de alcance por sucursal abierto:** el detalle de una nota de cita no se acota por
   sede (`backend/apps/agenda/views.py:1144`). Lo predijo la propia auditoría de sucursales y sigue
   ahí.
8. **Dependencias declaradas y no usadas:** `xhtml2pdf` (el motor real es WeasyPrint) y
   `channels`/`channels-redis` (no hay ni un consumer). Superficie de ataque gratis.
9. **ESLint instalado sin archivo de configuración:** el lint del frontend no revisa nada.
10. **Un recordatorio se encola antes de que la transacción confirme**
    (`backend/apps/agenda/reminders.py:82`, `apply_async` sin `transaction.on_commit`): puede
    dispararse sobre una cita que terminó sin guardarse.

**Documentación que quedó por corregir, no por archivar:** `README.md` describe el proyecto del
primer día (dice que ambos frontends están "pendientes"); `CHANGELOG.md` se detuvo siete semanas
antes del último commit; `DECISIONES-CLAVE.md` y varios documentos vivos de `docs/design/` tienen
desviaciones puntuales listadas en `docs/_legacy/README.md`.

---

## Anexo — Cómo leer la documentación de este repo a partir de hoy

| Quieres saber… | Lee |
|---|---|
| Qué es el producto y para quién | este documento |
| Qué hace el sistema hoy, endpoint por endpoint | `docs/02-contrato.md` (pendiente, sesión A2) |
| Qué está mal y en qué orden se arregla | `docs/00-deuda.md` (pendiente, sesión A3) |
| Por qué se decidió algo | `docs/DECISIONES-CLAVE.md` y `docs/adr/` |
| Cómo se audita la seguridad | `docs/reports/PROTOCOLO-AUDITORIA-SEGURIDAD.md` |
| Qué falta de rendimiento y escalabilidad | `docs/reports/metricas-refactor-huerfanos-escalabilidad.md` |
| Cómo se despliega | `docs/DEPLOY-RAILWAY.md` y `docs/deploy-rol-app-nosuperuser.md` |
| Qué se pensó antes y ya no aplica | `docs/_legacy/` y su índice |
