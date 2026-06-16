# Plan de diseño — Módulo "Expediente Clínico" (Fase A · núcleo clínico)

> Plan acordado con el dueño el **2026-06-16**.
> Estado: **Fase A COMPLETA (implementación)** — Backend **A1–A4 IMPLEMENTADOS y auditados**
> (2026-06-16; hallazgos ALTO corregidos en cada una, RLS `WITH CHECK`, bitácora de accesos,
> regla del médico robusta; **871 tests verdes**). Frontend **A5 IMPLEMENTADO** (`web-soft`:
> tipos/api/hooks + pestañas en el expediente + `recharts`; **`npm run build` sin errores TS**).
> **Pendiente:** verificación visual en navegador y actualizar `ESTADO-DEL-PROYECTO.md`/reportes.
> Análisis base: [`expediente-clinico-analisis-legacy.md`](expediente-clinico-analisis-legacy.md).
> Alcance de esta entrega: **solo Fase A (núcleo clínico)**. Fases B y C después.

---

## 1. Objetivo

Dar a las clínicas un **expediente clínico electrónico** real (hoy solo existe un campo
`notes` libre en `Patient`). La Fase A entrega lo mínimo para que un médico trabaje:
ficha clínica del paciente, **alergias** (bandera de seguridad), **historia clínica formal**,
**signos vitales** con tendencias, **notas de evolución** por consulta y **diagnósticos**.

No incluye (van en fases posteriores): recetas, documentos, estudios, consentimientos (Fase B);
CRM/"Experiencia" y Finanzas/cotizaciones (Fase C).

---

## 2. Decisiones tomadas (locked)

- **D-EC-1 · Evolución inmutable + addendum.** Una nota de evolución firmada **no se edita ni se
  borra**; se corrige creando un `Addendum` con autor y fecha. (Estilo NOM-004.)
- **D-EC-2 · La evolución nace de una cita "Atendida".** Toda `EvolutionNote` referencia una
  `agenda.Appointment` en estado `ATTENDED` del mismo paciente y tenant. Trazabilidad agenda↔expediente.
- **D-EC-3 · Separar 3 dominios.** Clínico (esta app), CRM (después), Finanzas (después). Las
  secciones legacy "Experiencia", "Cotizaciones" y "Estado de Cuenta" NO entran aquí.
- **D-EC-4 · Historia clínica estándar NOM-004 con almacenamiento flexible.** Campos clave
  estructurados + un `JSONField` por bloque (antecedentes, hábitos, gineco, exploración), validado
  por schema. Permite añadir campos sin migración y preparar las especialidades (D-12) sin rehacer.
- **D-EC-5 · Sin borrado físico de información clínica.** Contra el legacy (bote rojo). Todo es
  soft-delete / cancelación con motivo + bitácora. NUNCA `DELETE` real.
- **D-EC-6 · IMC derivado.** No se almacena; se calcula de peso/talla en el selector/serializer.
- **D-EC-7 · Validación estricta de entrada (whitelist).** Cada serializer **rechaza campos no
  declarados** y valores fuera de las opciones permitidas (`choices`). Los `JSONField` solo aceptan
  las **claves y tipos de su schema** (validador por bloque). Objetivo: que el formulario solo
  acepte exactamente lo que se pide → menos superficie de ataque (inyección, mass-assignment).
  Se cubre con tests (ver §8).
- **D-EC-8 · Respuestas precargadas.** Donde la respuesta se puede intuir, se usan **opciones
  predefinidas** (`choices` / catálogos) y **defaults** en lugar de texto libre, para no escribir
  todo a mano. Ej.: estado civil, escolaridad, tipo de sangre; antecedentes con default "Negado"
  + detalle opcional; exploración por aparato con default "Sin alteraciones"; severidad de
  alergia. El texto libre queda solo para lo que de verdad lo necesita (padecimiento, evolución).
- **D-EC-9 · Especialidades = plugins activados por plataforma.** El expediente es **universal**
  para todos. Las especialidades (dental, nutrición, estética, psicología…) son **módulos** que el
  **super administrador de la plataforma** libera **por clínica** según lo contratado/solicitado.
  Mecanismo: catálogo global `SpecialtyModule` + activación por tenant `TenantModule` (entitlement,
  fuente de verdad) + **gating** en backend (un módulo no activo → no existe/403) + UI condicional.
  El núcleo (Fase A) no depende de esto, pero deja el gancho (JSON flexible). El sistema de módulos
  se construye en una fase aparte (parte de D-12). Adelanta parte del "Panel de Plataforma".

---

## 3. Modelo de datos

### 3.1 Ampliar `apps/pacientes` · `Patient` (datos NOM-004)

Todos **opcionales** (conviven con el expediente provisional, D-06). Migración aditiva.

| Campo | Tipo | Notas |
|---|---|---|
| `address_street` | Char(255), blank | Calle y número. |
| `address_neighborhood` | Char(120), blank | Colonia. |
| `city` | Char(120), blank | Ciudad. |
| `state` | Char(120), blank | Estado. |
| `postal_code` | Char(10), blank | CP. |
| `birthplace` | Char(160), blank | Lugar de nacimiento. |
| `marital_status` | choices, blank | Soltero/Casado/… |
| `education` | choices, blank | Escolaridad. |
| `occupation` | Char(120), blank | Ocupación. |
| `religion` | Char(80), blank | Religión. |
| `blood_type` | choices, blank | A+/A−/…/O−. |
| `phone_secondary` | Char(20), blank | 2º teléfono. |
| `phone_label` | Char(40), blank | Etiqueta del 2º teléfono (ej. "hija"). |
| `is_deceased` | Bool, default False | "Finado". |
| `deceased_at` | Date, null | Fecha de defunción. |
| `custom_consultation_fee` | Decimal(10,2), null | Costo de consulta personalizado (lo usará Finanzas). |
| `category` | Char(60), blank | Categoría libre del paciente (v1). |

### 3.2 App nueva: `apps/expediente`

Todos los modelos heredan de `TenantAwareModel` (UUID, timestamps, soft-delete, `tenant`,
`created_by`, `TenantManager`). Migración `0002_enable_rls.py` activa **RLS** en todas las tablas.

#### `Allergy(TenantAwareModel)` — alergia (bandera de seguridad)
| Campo | Tipo | Notas |
|---|---|---|
| `patient` | FK Patient | Indexado. |
| `substance` | Char(160) | Sustancia/medicamento (ej. "Penicilina"). |
| `reaction` | Char(255), blank | Reacción observada. |
| `severity` | choices, blank | leve/moderada/severa. |
| `is_active` | Bool | Soft (vigente/resuelta). |

#### `Diagnosis(TenantAwareModel)` — diagnóstico
| Campo | Tipo | Notas |
|---|---|---|
| `patient` | FK Patient | Indexado. |
| `evolution` | FK EvolutionNote, null | Consulta donde se asentó (opcional). |
| `cie_code` | Char(10), blank | CIE-10 texto libre en v1; catálogo después (D-12). |
| `description` | Char(255) | Texto del diagnóstico. |
| `kind` | choices | presuntivo/definitivo. |
| `status` | choices | activo/resuelto. |

#### `MedicalHistory(TenantAwareModel)` — historia clínica formal (1 por paciente)
| Campo | Tipo | Notas |
|---|---|---|
| `patient` | FK Patient, único activo | Documento vivo (se actualiza, bitácora en `audit`). |
| `heredo_familiares` | JSONField | Bloque AHF (schema validado). |
| `personales_patologicos` | JSONField | Bloque APP. |
| `no_patologicos` | JSONField | Bloque APNP **general** (vivienda, actividad física, inmunizaciones, toxicomanías). Lo **dental** se mueve a la extensión Odontología (ver análisis §13). |
| `habitos_alimenticios` | JSONField | Versión **corta** (n.º de comidas, dieta especial, intolerancias). La encuesta detallada de 32 alimentos se mueve a la extensión Nutrición. |
| `gineco_obstetricos` | JSONField | **Condicional por sexo**: se muestra/llena solo en mujeres. |
| `exploracion_fisica_basal` | JSONField | Exploración por aparatos basal (estado + detalle). |
| `padecimiento_actual` | Text, blank | Antecedentes de importancia, padecimiento, tratamientos, prioridad. |

> Los `JSONField` se validan con un **schema por bloque** en el serializer (claves y tipos
> conocidos, default "Negado"/"Sin alteraciones"). Así no encajonamos columnas y preparamos las
> **extensiones por especialidad** (D-12) sin rehacer. La Fase A construye **solo el núcleo
> universal**; el reparto núcleo vs especialidad está en el análisis §13.

#### `VitalSignsRecord(TenantAwareModel)` — signos vitales (serie temporal, "Enfermería")
| Campo | Tipo | Notas |
|---|---|---|
| `patient` | FK Patient | Indexado. |
| `appointment` | FK Appointment, null | Cita asociada (para enlazar con la evolución del día). |
| `measured_at` | DateTime | Momento de la toma (default ahora). |
| `weight_kg` / `height_m` | Decimal, null | Peso y talla. **IMC se deriva** (no se guarda). |
| `heart_rate` / `resp_rate` | Int, null | FC / FR. |
| `systolic` / `diastolic` | Int, null | Presión arterial. |
| `temperature_c` | Decimal, null | Temperatura. |
| `oxygen_saturation` | Int, null | Sat O2. |
| `glucose` | Int, null | Glucosa. |
| `extra_params` | JSONField | Colesterol, triglicéridos, urea, creatinina, hemoglobina… (extensible). |
| `notes` | Char(255), blank | Observaciones. |

Índice `(tenant, patient, measured_at)` para historial y series de gráficas.

#### `EvolutionNote(TenantAwareModel)` — nota de consulta (**inmutable**)
| Campo | Tipo | Notas |
|---|---|---|
| `patient` | FK Patient | Indexado. |
| `appointment` | FK Appointment | Debe estar `ATTENDED` y ser del mismo paciente/tenant (D-EC-2). |
| `doctor` | FK Doctor | Autor clínico (= médico de la cita). |
| `vital_signs` | FK VitalSignsRecord, null | Toma del día (D-EC-6). |
| `antecedentes` / `interrogatorio` / `estudios` | Text, blank | Campos del legacy. |
| `exploracion_fisica` | JSONField | Por aparatos: estado (semáforo) + detalle. |
| `diagnosticos_texto` | Text, blank | Resumen; los estructurados van en `Diagnosis`. |
| `tratamiento` / `plan_recomendaciones` / `indicaciones_enfermeria` | Text, blank | |
| `is_locked` | Bool, default True | Firmada al crear → inmutable. |

> **Inmutabilidad:** el service solo permite crear; no hay update/delete. Se valida en tests
> (D-EC-1). Correcciones vía `Addendum`.

#### `Addendum(TenantAwareModel)` — corrección a una nota firmada
| Campo | Tipo | Notas |
|---|---|---|
| `evolution` | FK EvolutionNote | Nota corregida. |
| `author` | FK User | Quién corrige. |
| `body` | Text | Texto del addendum. |

---

## 4. API (endpoints)

Prefijo `api/v1/`. Anidados bajo el paciente. Vistas delgadas; lógica en services/selectors.

| Método | Endpoint | Descripción |
|---|---|---|
| `GET/PUT` | `expediente/<patient_id>/historia/` | Leer/actualizar la historia clínica (upsert). |
| `GET/POST` | `expediente/<patient_id>/alergias/` | Listar / agregar alergia. |
| `DELETE` | `expediente/alergias/<id>/` | Baja lógica (resolver). |
| `GET/POST` | `expediente/<patient_id>/signos/` | Listar / registrar toma de signos. |
| `GET` | `expediente/<patient_id>/signos/series/` | Series para gráficas (por parámetro). |
| `GET/POST` | `expediente/<patient_id>/evoluciones/` | Listar / crear nota (requiere cita ATTENDED). |
| `POST` | `expediente/evoluciones/<id>/addendum/` | Agregar addendum a una nota. |
| `GET/POST` | `expediente/<patient_id>/diagnosticos/` | Listar / agregar diagnóstico. |

---

## 5. Permisos (autoridad: backend)

Nuevas clases en `apps/core/permissions.py` heredando de `HasClinicRole`.

- **Lectura clínica** (`CLINICAL_READ` = owner, admin, doctor, nurse, readonly). Recepción y
  finanzas **no** ven contenido clínico. *(Las alergias sí se exponen en la ficha del paciente
  para todos los roles, como bandera de seguridad.)*
- **Historia clínica / Evolución / Diagnósticos — escritura:** owner, admin, **doctor**.
- **Signos vitales — escritura:** owner, admin, doctor, **nurse** (enfermería los captura).
- **Regla del médico:** un `doctor` solo crea evolución sobre **citas atendidas suyas** (valida
  `appointment.doctor.membership.user == request.user`). Reusa el patrón self de agenda.

> Regla base del proyecto: sin membresía activa → **403**. Doble barrera: permiso + selector
> filtrando por `tenant` (+ RLS en BD).

---

## 6. Frontend (`web-soft/`)

El expediente del paciente ya existe (conectado a agenda). Se le agregan **pestañas**:

- **Resumen / banderas:** alergias (rojo), diagnósticos activos, últimos signos.
- **Historia clínica:** formulario por bloques (acordeón), guardar.
- **Signos vitales:** tabla de tomas + **gráficas de tendencia** (nueva librería, p. ej. `recharts`).
- **Evolución:** lista de notas (solo lectura una vez creadas) + "Nueva evolución" (habilitada solo
  si hay una cita atendida) + addendums.
- **Diagnósticos:** lista + alta.

Soporte: `api/expediente.ts`, `hooks/useExpediente.ts`, `types/expediente.ts`. Cliente HTTP central
(refresh 401, CSRF) ya existente. El rol del front solo controla la UX; manda el backend (403).

---

## 7. Plan por sub-fases (orden de construcción)

| Sub-fase | Qué incluye | Estado |
|---|---|---|
| **A1 · Cimiento** | App `apps/expediente`, ampliar `Patient` (NOM-004), `Allergy`, migraciones (datos + RLS), permisos base, services/selectors/views/urls de alergias + ficha. Bitácora NOM-024 en alergias. | ✅ **IMPLEMENTADO + auditado** (321 tests) |
| **A2 · Historia clínica** | `MedicalHistory` + schemas de validación por bloque + upsert API + bitácora (READ/UPDATE) + gineco condicional por sexo + RLS `WITH CHECK`. | ✅ **IMPLEMENTADO + auditado** (402 tests) |
| **A3 · Signos vitales** | `VitalSignsRecord` (append-only) + IMC derivado + series para gráficas + paginación + bitácora READ/CREATE + RLS `WITH CHECK`. **Ojo frontend:** `GET /signos/` ahora es paginado (`.results`). | ✅ **IMPLEMENTADO + auditado** (471 tests módulo) |
| **A4 · Evolución + diagnósticos** | `EvolutionNote` (desde cita ATTENDED, inmutable, única por cita) + `Addendum` + `Diagnosis` (crear/resolver) + regla del médico (`actor_role` explícito) + bitácora READ/CREATE/RESOLVE + RLS `WITH CHECK`. | ✅ **IMPLEMENTADO + auditado** (871 tests) |
| **A5 · Frontend + cierre** | `web-soft`: `types/expediente.ts`, `api/expediente.ts`, `hooks/expediente.ts`, `components/expediente/*`; expediente con pestañas (Resumen+alergias / Historia clínica / Signos+gráfica recharts / Evolución+addenda / Diagnósticos); paciente NOM-004; helpers de permisos UI. **`npm run build` verde.** | ⏳ **Frontend implementado (compila)** — falta verificación visual + actualizar ESTADO-DEL-PROYECTO |

---

## 8. Tests (objetivo)

Por capa, con pytest + factory_boy, ≥80% en lógica de negocio:
- **Multi-tenant / RLS:** aislamiento + IDOR cross-tenant en cada recurso.
- **Inmutabilidad (D-EC-1):** no se puede editar/borrar una `EvolutionNote`; addendum sí.
- **Cita atendida (D-EC-2):** crear evolución falla si la cita no está `ATTENDED` o es de otro paciente.
- **Regla del médico:** un doctor no crea evolución sobre cita de otro doctor → 403.
- **IMC (D-EC-6):** cálculo correcto; series de signos ordenadas.
- **Permisos por rol:** recepción/finanzas no leen contenido clínico; alergias visibles a todos.
- **Validación estricta (D-EC-7):** el serializer rechaza **campos no permitidos** y valores fuera
  de `choices`; los `JSONField` rechazan **claves desconocidas** y tipos inválidos. Tests que
  envían basura/campos extra y esperan **400**, no que se guarden.

```bash
docker compose exec -T backend python -m pytest apps/expediente/ -q -o addopts=""
```

---

## 9. Cumplimiento

- **NOM-004-SSA3-2012:** validar campos obligatorios del expediente al cerrar cada modelo.
- **NOM-024 / bitácora:** registrar en `audit` acceso y cambios al expediente (dato más sensible).
- **LFPDPPP:** minimización de PII, RLS, control por rol.
- **Sin borrado físico** de información clínica (D-EC-5).

---

## 10. Después de la Fase A

- **Fase B:** recetas (+catálogo medicamentos), documentos médicos, estudios (archivos), **PDF**,
  WhatsApp, consentimientos (plantillas configurables, §8 del análisis).
- **Fase C:** CRM/"Experiencia" (perfil de preferencias) + Finanzas (cotizaciones + estado de
  cuenta, §9 del análisis).
- **Fase D · Sistema de módulos/plugins (D-12):** catálogo `SpecialtyModule` (global) +
  `TenantModule` (activación por clínica) + gating en backend + endpoint de módulos activos para el
  frontend + **activación por el super admin de plataforma** (Django admin primero, Panel de
  Plataforma después) + **primer módulo de especialidad** (p. ej. estética o dental) como prueba
  del mecanismo. Ver análisis §13.4. También: catálogo CIE-10.
