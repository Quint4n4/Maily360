# Formatos de receta configurables por clínica — diseño e implementación

> Estado: **IMPLEMENTADO** — fases F1, F2 (parcial), F3, F4 y F5 completadas. Actualizado **2026-06-23**.
> Origen: el cliente "Clínica Camsa" usa recetas en **media carta horizontal** muy densas
> (membrete con varias cédulas + signos + indicaciones largas + sueros/terapias + firma)
> donde **el texto se encima** por falta de espacio. Otras recetas convienen en formato
> **digital** para el paciente. Se necesita que **cada clínica elija/configure su formato**.
>
> Lo implementado difiere del plan original en estos puntos clave:
> - Se eliminó el formato "Estándar" (carta vertical genérica); quedaron **2 formatos base**: `compact` (Farmacia) y `digital` (Paciente).
> - Se añadió el campo **`theme`** (4 estilos decorativos predefinidos) en vez de dejar el diseño libre.
> - Al emitir una receta se generan **ambas versiones** (Farmacia + Paciente) usando el mismo formato configurado (color, tipografía, tema).
> - Se implementó **validación híbrida de credenciales** del médico: el doctor captura, el admin valida o rechaza; solo las credenciales con `validation_status="validada"` aparecen en la receta.
> - La tarjeta del historial muestra las **cédulas validadas reales** del médico (campo `cedulas_validadas` en el serializer, con prefetch para evitar N+1).

## 1. Problema

- Hoy hay **un solo formato** de PDF (`prescription.html`, "membrete digital limpio", carta vertical).
- Distintas clínicas (y hasta distintos casos dentro de una clínica) requieren formatos distintos:
  - Media carta horizontal densa (sueros/terapias, tipo Camsa).
  - Carta vertical estándar.
  - Receta digital amigable para enviar al paciente.
- El "encimado" de Camsa viene de un diseño **rígido de posiciones fijas**; un formato **maquetado en flujo** (tablas, sin posiciones absolutas) evita que el texto se monte.

## 2. Principio de diseño: separar 3 capas

| Capa | Qué es | Dónde vive hoy |
|---|---|---|
| **Formato (diseño)** | tamaño, orientación, colores, tipografía, qué secciones y dónde | `prescription.html` (único) — **a generalizar** |
| **Contenido** | medicamentos, indicaciones, recomendaciones | lo captura el médico + `ClinicTemplate` (plantillas de texto) |
| **Identidad de la clínica** | logo, datos, médico, membrete | `ClinicSettings` + `Doctor` |

Estandarizar = **parametrizar la capa de formato** y dejar que la clínica la elija/configure, sin tocar contenido ni identidad.

## 3. Decisión: formatos predefinidos + personalización (NO diseño libre)

Que cada clínica diseñe desde cero sería caótico y poco profesional. Se ofrecen **plantillas base profesionales** + **personalización acotada** encima. Es el patrón de los sistemas serios (temas configurables).

## 4. Formatos predefinidos (plantillas base)

_(Plan original: 3 formatos. Implementado: 2. Ver nota de evolución en el encabezado.)_

1. ~~**Estándar · carta vertical**~~ — **eliminado**. Se descartó durante la implementación; el formato `digital` cubre ese caso.
2. **Compacta · media carta horizontal** (`compact`) — 5.5×8.5 in apaisada. Maquetada para la receta de **Farmacia**: medicamentos, dosis, signos vitales en espacio reducido sin encimar. Template: `recetas/formats/compact.html`. Resuelve el caso Camsa.
3. **Digital · para el paciente** (`digital`) — carta vertical (8.5×11 in). Receta completa del **Paciente**: medicamentos con indicaciones, recomendaciones, diagnóstico, QR de verificación. Template: `recetas/formats/digital.html`.

> Al emitir una receta, el backend genera **ambas versiones** usando el mismo `PrescriptionFormat` configurado (conservando color, tipografía y tema). La UI muestra dos botones: **"Farmacia"** y **"Paciente"**.

### 4.1 Estilos decorativos — campo `theme` (nuevo 2026-06-23)

El campo `PrescriptionFormat.theme` controla el **fondo/marco** del PDF sin alterar la estructura del contenido. Implementado en `recetas/formats/_theme_bg.html` (include compartido para `compact` y `digital`).

| `theme` | Descripción |
|---|---|
| `ondas` (default) | SVG de ondas suaves en la esquina superior derecha y pie de página, en el color de acento |
| `minimal` | Sin decoración de fondo (solo contenido) |
| `barra` | Barra lateral izquierda sólida en el color de acento (0.32 cm) |
| `geometrico` | Círculos superpuestos en esquinas con el color de acento (opacidad 10–16%) |

El encabezado y pie "running" de los PDF **no llevan fondo blanco** para que los temas decorativos sean visibles. El QR lleva su propio fondo blanco en el HTML para seguir siendo escaneable.

## 5. Qué se personaliza (sobre el formato elegido)

| Opción | Valores | Notas técnicas |
|---|---|---|
| **Logo** | imagen | ya existe en `ClinicSettings.logo`; encajado proporcional (`_image_box`) |
| **Color de acento** | paleta curada (o hex) | se inyecta en el template Django (`{{ accent }}`), NO como CSS var (WeasyPrint no soporta `var()`) |
| **Tipografía** | set seguro: Helvetica (sans), Times (serif) en MVP | fuentes custom (Lato, etc.) = embeber TTF con `@font-face`/`registerFont` → fase posterior |
| **Tamaño/orientación** | Carta vertical · Media carta horizontal · A5 | `@page { size: ... }` (WeasyPrint lo respeta; media carta = tamaño custom) |
| **Secciones a incluir** | signos, indicaciones, medicamentos, sueros/terapias, diagnóstico | flags en el contexto → `{% if %}` en el template |
| **Modo de membrete** | digital (el sistema arma el encabezado) · papel pre-impreso (deja espacio superior, no imprime encabezado) | reusa `letterhead_full/half` + `*_spaces` ya existentes |

## 6. Modelo de datos — `PrescriptionFormat` (IMPLEMENTADO)

`PrescriptionFormat(TenantAwareModel)` — 1..N por tenant:

| Campo | Tipo | Descripción |
|---|---|---|
| `name` | CharField(120) | Nombre descriptivo que pone la clínica |
| `base_layout` | choice: `compact` \| `digital` | Plantilla base. ~~`standard`~~ eliminado |
| `theme` | choice: `ondas` \| `minimal` \| `barra` \| `geometrico` | Estilo decorativo del fondo/marco. Default `ondas`. **Nuevo 2026-06-23** |
| `accent_color` | CharField hex (#RRGGBB) | Color de acento inyectado como variable Django en el template |
| `font` | choice: `helvetica` \| `times` | Tipografía base (solo fuentes seguras para WeasyPrint) |
| `paper` | choice: `letter` \| `half_letter_landscape` | Tamaño de hoja según `base_layout` |
| `sections` | JSONField | Secciones a incluir: `{signos, indicaciones, medicamentos, sueros, diagnostico}` bool |
| `letterhead_mode` | choice: `digital` \| `preprinted` | Membrete: el sistema lo imprime o deja espacio (papel pre-impreso) |
| `is_default` | BooleanField | El formato que se usa si no se especifica otro |
| `is_authorized` / `doctor_id` | BooleanField / FK | Formato propio del médico con autorización del dueño |
| `is_active`, `deleted_at` | — | Baja lógica |

RLS por tenant (USING + WITH CHECK), bitácora de cambios. La clínica puede tener varios formatos. El selector `prescription_format_resolve` busca en orden: (1) formato pasado explícitamente, (2) formato del médico con `is_authorized=True`, (3) formato `is_default` del tenant, (4) objeto de fábrica en memoria (digital + ondas + dorado).

**Color en recetas pasadas:** `prescription_format_resolve` clona el formato configurado conservando color, tipografía y tema cuando se fuerza un `layout_override` (p. ej. para ver la versión Farmacia de una receta antigua cuyo formato guardado era `digital`). Así el color elegido se aplica también al historial.

## 7. Generador de PDF — `apps/recetas/pdf.py` (IMPLEMENTADO)

- `prescription_pdf_build(prescription, format=None, layout_override=None)`: resuelve el `PrescriptionFormat` vía `prescription_format_resolve`.
- Selecciona el **template** según `base_layout`: `recetas/formats/compact.html` | `recetas/formats/digital.html`. ~~`standard.html`~~ eliminado.
- Inyecta en el contexto: `accent`, `font`, `sections`, `paper`, `letterhead_mode`, **`theme`**, `fmt_layout` + los datos ya existentes (clínica, médico, paciente, items, signos, credenciales validadas).
- `@page size` por `paper`; color por `{{ accent }}` (variable Django, no CSS var); secciones por flags; tema por `{% include "_theme_bg.html" %}`.
- Seguridad: `_link_callback` (solo `data:`), imágenes base64 con dimensiones proporcionales, autoescape Django.
- **Arreglos PDF entregados 2026-06-23:**
  - Formato `digital` ya no se recorta (márgenes y tamaño de logo de encabezado corregidos).
  - Los temas decorativos (p. ej. `ondas`) son visibles: el encabezado/pie "running" no llevan `background:white` que los tapaba.
  - El QR lleva `background:white` propio en el HTML para mantenerse escaneable en cualquier tema.

### 7.1 Credenciales validadas en el PDF y en la tarjeta del historial

- El PDF solo incluye las credenciales del médico con `validation_status="validada"`.
- El serializer `_DoctorBriefSerializer` expone `cedulas_validadas`: lista de `credential_number` de las credenciales validadas, con prefetch para evitar N+1 (`validated_credentials` en `prescription_list`).
- `cedula_profesional` (campo legacy del modelo `Doctor`) se mantiene como respaldo cuando el médico no tiene ninguna credencial validada.

## 8. Pantalla de configuración — Mi Consultorio → Recetas (IMPLEMENTADO)

_(Implementación 2026-06-23; difiere del plan original)_

- Sección única de Recetas en Mi Consultorio. Se reestructuró: el médico responsable es siempre el tratante (se quitó el interruptor). Se quitaron los contactos de WhatsApp de la config (se moverán a Comunicaciones cuando se implemente el módulo).
- **`SeccionFormatos.tsx`**: selector de formato base (`compact` / `digital`), selector de estilo (`ondas` / `minimal` / `barra` / `geometrico`), color de acento, tipografía, secciones (interruptores), modo de membrete. **Vista previa en vivo** (maqueta renderizada en el editor).
- Botón **"Guardar formato"**.
- Permisos: owner/admin configuran el formato de la clínica; el médico puede tener su propio formato con autorización del dueño (campo `is_authorized`).

> ~~Galería de 3 formatos~~ — se simplificó a selector desplegable (2 opciones) con vista previa en vivo.

## 8-bis. Validación híbrida de credenciales del médico (IMPLEMENTADO 2026-06-23)

Flujo de 3 estados para `DoctorCredential.validation_status`:

| Estado | Quién actúa | Resultado |
|---|---|---|
| `pendiente` (default) | El doctor captura/solicita revisión | La credencial NO aparece en la receta |
| `validada` | Admin/dueño valida (con nota opcional) | La credencial SÍ aparece en la receta |
| `rechazada` | Admin/dueño rechaza con motivo | La credencial NO aparece; el doctor ve el motivo |

**Endpoints nuevos** (en `apps/clinica/urls.py`):
- `GET /api/v1/clinica/credenciales/` — bandeja del administrador: lista todas las credenciales del tenant (para revisar y validar).
- `PATCH /api/v1/clinica/credenciales/<credential_id>/validar/` — valida o rechaza con motivo.

**Notificaciones** (integradas con `apps/notificaciones`):
- `CREDENTIAL_REVIEW` → al admin/dueño cuando el doctor agrega una credencial (para que la revise).
- `CREDENTIAL_RESULT` → al doctor cuando admin/dueño valida o rechaza (para que sepa el resultado).
- Ambas son best-effort (dentro de `try/except`; un fallo no impide la acción principal).

**Modelo** (`apps/clinica/models.py`):
- `DoctorCredential.validation_status` (CharField, choices `pendiente`/`validada`/`rechazada`, default `pendiente`, db_index).
- `DoctorCredential.validation_note` (CharField 300, blank, default `""`).
- Clase `CredentialValidationStatus(TextChoices)` nueva.

**Frontend** (`apps/clinica/` en `web-soft`):
- `SeccionCredencialesValidar.tsx` — bandeja del admin: lista credenciales pendientes con botones "Validar" / "Rechazar + motivo".
- `CredencialEstadoBadge.tsx` — badge de color por estado (pendiente/validada/rechazada) visible en la ficha del médico.
- `types/credenciales.ts` — tipo `DoctorCredentialOut` con `validation_status` y `validation_note`.

## 9. Conexión con lo que ya existe (no se parte de cero)

- `ClinicSettings` (logo, datos, membrete full/half + espacios, `recipe_use_responsible_doctor`) → base de identidad y modo pre-impreso.
- `pdf.py` + `prescription.html` → se generaliza a varios templates + parámetros.
- `ClinicTemplate` (kind=recipe) → **contenido** (recomendaciones), independiente del formato.
- `_image_box` (dimensiones proporcionales), `_link_callback` (seguridad), bitácora, RLS → se reutilizan tal cual.

## 10. Consideraciones técnicas — WeasyPrint

> Nota: el plan original evaluaba xhtml2pdf. Se optó por **WeasyPrint** (DR-3 de `recetas-plan.md`) por su mejor soporte CSS y calidad visual. Las consideraciones de CSS variables siguen aplicando.

- **CSS variables NO soportadas por WeasyPrint** → el color de acento se inyecta vía template Django (`{{ accent }}`), no `var()`.
- **Tipografías:** solo fuentes base (Helvetica/Times) sin embeber en el MVP; fuentes de marca requieren `@font-face` con TTF → fase futura.
- **Tamaño/orientación:** `@page { size: 8.5in 5.5in; }` para media carta horizontal (formato `compact`); `@page { size: letter; }` para carta vertical (formato `digital`).
- **Evitar encimado:** maquetado en flujo (tablas, `page-break-inside: avoid` por bloque), no posiciones absolutas.
- **Fondo decorativo (`_theme_bg.html`):** usa `position:fixed` (WeasyPrint lo soporta para fondos de página); el encabezado/pie no llevan `background:white` para que los temas sean visibles; el QR lleva su propio `background:white`.

## 11. Plan por fases — estado al 2026-06-23

| Fase | Descripción original | Estado |
|---|---|---|
| **F1** | Formato "Compacta · media carta" + refactor `pdf.py` a `formats/` | **IMPLEMENTADO** |
| **F2** | Modelo `PrescriptionFormat` + personalización (color, tipografía, secciones, membrete) | **IMPLEMENTADO** |
| **F3** | Pantalla de configuración en Mi Consultorio (frontend) | **IMPLEMENTADO** (con vista previa en vivo; se simplificó de galería a selector desplegable) |
| **F4** | Dos versiones al emitir (Farmacia + Paciente) | **IMPLEMENTADO** (como "dos versiones" del mismo formato, no como selector de formato distinto al emitir) |
| **F5** | Estilos decorativos (`theme`) | **IMPLEMENTADO** (4 estilos: ondas / minimal / barra / geometrico) |
| — | Validación híbrida de credenciales + cédulas validadas en PDF | **IMPLEMENTADO** (2026-06-23, añadido fuera del plan original) |
| F5-orig | Fuentes de marca embebidas / evaluación WeasyPrint | Pendiente |

## 12. Decisiones tomadas con el dueño (2026-06-18)

1. **Nombre comercial de la clínica:** SÍ. Agregar `commercial_name` en `ClinicSettings` para el membrete (independiente de `Tenant.name`).
2. **Credenciales del médico como lista estructurada:** SÍ. Modelo nuevo (título + institución + número de cédula + tipo) en vez del texto plano `cedulas_adicionales`. Cubre "institución que expide el título" y "cédula de especialidad" de COFEPRIS.
3. **Formato por médico:** SÍ, pero como **validación/permiso aparte**: el médico puede tener su propio encabezado **solo si él lo decide o el dueño de la clínica lo autoriza**. Default = formato de la clínica.
4. **Sueros/terapias + catálogos estructurados:** SÍ. `PrescriptionItem` lleva `tipo` (medicamento | suero | terapia) y se mantienen/extienden **catálogos preestablecidos estructurados** (como `GlobalMedication` hoy) para los tres tipos.

## 13. Cumplimiento normativo COFEPRIS 2026 (análisis de brechas)

Marco: Reglamento de Insumos para la Salud + Ley General de Salud (reforma DOF ene-2026: gestión digital obligatoria) + NOM-024-SSA3-2010. Desde ene-2026 COFEPRIS puede hacer **verificaciones remotas** del cumplimiento documental (Art. 396 LGS) → la trazabilidad y los datos completos son críticos.

| Requisito COFEPRIS | ¿Lo tenemos? | Acción |
|---|---|---|
| Nombre del médico, sin abreviaturas | ✅ `doctor.full_name` | — |
| **Institución que expide el título** | ✅ `DoctorCredential.institution` (validada) | — |
| Cédula profesional | ✅ `cedula_profesional` / `DoctorCredential` | validar formato; marcar si vencida |
| **Cédula de especialidad** | ✅ `DoctorCredential` (tipo + número, validada) | — |
| Especialidad | ✅ `doctor.specialty` | — |
| Firma autógrafa o digital | ✅ imagen de sello/firma | firma electrónica avanzada (e.firma) = futuro |
| Domicilio del establecimiento | ✅ `ClinicSettings.address` | — |
| Teléfono del establecimiento | ✅ `phone`/`mobile` | — |
| Nombre completo del paciente | ✅ `patient.full_name` | — |
| Edad del paciente | ✅ (el PDF la calcula) | — |
| Nombre genérico del medicamento | ✅ `generic_name` (catálogo) | — |
| Denominación comercial (opcional) | ✅ `commercial_name` | — |
| Forma farmacéutica | ✅ `medication_form` | — |
| **Dosis (sin abreviaturas)** | ✅ `PrescriptionItem.dose` (F2) | — |
| **Frecuencia** | ✅ `PrescriptionItem.frequency` (F2) | — |
| **Vía de administración** | ✅ `PrescriptionItem.route` (F2) | — |
| **Duración del tratamiento** | ✅ `PrescriptionItem.duration` (F2) | — |
| Fecha de emisión | ✅ `issued_at` | — |
| **Diagnóstico en la receta** | ✅ `Prescription.diagnosis` (lo captura el médico) | — |
| Folio | ✅ consecutivo por tenant | para controlados: **folio autorizado oficial** |
| **Código de verificación (QR/barras)** | ✅ QR de verificación (F5) | — |
| Bitácora / trazabilidad | ✅ NOM-024 (`audit`) | reforzar para controlados |
| **Medicamentos controlados** (grupo, vigencia, recetario especial) | ✅ `controlled_group` (F6) | el folio oficial del recetario especial sigue siendo trámite del médico |

### Brechas a cubrir (derivadas de la norma)
- **Renglón de medicamento estructurado:** además del `indication` libre, separar **dosis · frecuencia · vía de administración · duración** (campos), para cumplir COFEPRIS y poder validar "sin abreviaturas". El `indication` libre puede quedar como nota adicional.
- **Diagnóstico obligatorio/recomendado en la receta:** enlazar el/los `Diagnosis` del expediente o capturar uno; advertir si la receta sale sin diagnóstico (configurable por clínica).
- **QR de verificación:** generar un QR en el PDF que apunte a un endpoint público de validación (folio + hash) para confirmar autenticidad. Útil para todas las recetas (clave en receta electrónica 2026) y obligatorio en controladas.
- **Validación de cédula profesional:** formato correcto y bandera de vigencia (no emitir con cédula marcada como vencida).

### Módulo de medicamentos controlados (psicotrópicos/estupefacientes) — F6 implementado

**Lo que implementó F6 (backend — 2026-06-19):**
- `PrescriptionItem.controlled_group` (snapshot DR-7): grupo COFEPRIS copiado del catálogo al crear la receta. Inmutable.
- `Prescription.controlled_folio` (CharField 60): folio del recetario especial que el médico ingresa manualmente. Requerido si `is_controlled`.
- `Prescription.valid_until` (DateTimeField, null): calculado automáticamente — Grupo I = 24 h, Grupos II–V = 30 días desde `issued_at`. Configurable via `settings.CONTROLLED_VALIDITY_HOURS`.
- `Prescription.is_controlled` (property): True si algún ítem tiene `controlled_group != 'none'`.
- `prescription_create`: valida `controlled_folio` obligatorio si la receta es controlada; calcula `valid_until`; auditoría reforzada con `PRESCRIPTION_CONTROLLED_CREATE`.
- PDF (3 templates): aviso visible "MEDICAMENTO CONTROLADO — Grupo X", folio oficial y vigencia si `is_controlled`.
- Endpoint verify (F5): expone `controlado` (bool) y `vigencia` (datetime|null) sin PII.
- 2 migraciones: `0009_f6_controlled_fields` + `0029_f6_prescription_controlled_create`.
- 20 tests nuevos en `test_f6_controlled.py`, suite completa 285 verdes.

**Lo que queda como operativo/externo (NO implementado — fuera del alcance del software):**

| Proceso | Quién lo hace | Referencia |
|---|---|---|
| Emisión del folio oficial / código de barras del recetario especial | El médico ante COFEPRIS (trámite físico) | Art. 240 Ley General de Salud; Reglamento Insumos |
| Recetario bajo llave (control de acceso físico a los talonarios) | El médico / clínica (proceso operativo) | NOM-024 §6.4 |
| Reporte de extravíos a COFEPRIS en < 72 h | El médico / clínica (obligación legal directa) | Art. 240 bis LGS |
| Surtido único en farmacia (verificar que no se surtió antes) | La farmacia / sistema de farmacovigilancia COFEPRIS | Reglamento Insumos Art. 251 |
| Integración de firma electrónica avanzada (e.firma SAT) en la receta | Fase futura (F7) — requiere PKI + interop COFEPRIS | — |

## 14. Impacto en el modelo de datos (resumen)

- `ClinicSettings`: + `commercial_name`.
- **`DoctorCredential(TenantAwareModel)`** (nuevo, lista por médico): `title` (ej. "Maestría en Cirugía Estética"), `institution`, `credential_number` (cédula), `type` (profesional | especialidad | posgrado), `order`. Sustituye a `cedulas_adicionales` (texto) y absorbe la idea de `DoctorUniversity`.
- `PrescriptionItem`: + `kind` (medicamento | suero | terapia), + `dose`, + `frequency`, + `route` (vía de administración), + `duration`. (`indication` libre se conserva como nota.)
- `GlobalMedication`/`Medication`: + `controlled_group` (none | I | II | III | IV | V). Catálogos estructurados también para **sueros** y **terapias** (mismo patrón o un `kind` en el catálogo).
- `Prescription`: + `diagnosis` (texto o FK a `Diagnosis`), + datos de verificación (folio/hash para QR). Para controladas: folio autorizado + vigencia.
- **Endpoint público de validación** (QR): `GET /verificar-receta/<folio-o-hash>` (sin PII; solo confirma autenticidad/estado).

## 15. Plan por fases (actualizado)

1. **F1 — Formato "Compacta · media carta"** (resuelve Camsa, sin encimado) + refactor de `pdf.py` a `formats/`.
2. **F2 — Cumplimiento COFEPRIS (datos):** renglón estructurado (dosis/frecuencia/vía/duración + tipo), credenciales estructuradas del médico (`DoctorCredential`), `commercial_name`, diagnóstico en la receta. (Es lo que vuelve la receta **legalmente válida**.)
3. **F3 — `PrescriptionFormat`** + personalización (color, tipografía, tamaño, secciones, modo membrete) + formato por médico con autorización (decisión 3).
4. **F4 — Pantalla de galería + vista previa** (frontend).
5. **F5 — QR de verificación** + endpoint público de validación.
6. **F6 — Módulo de medicamentos controlados** (grupo, folio autorizado, vigencia, bitácora de folios, reporte de extravíos). Fase dedicada por su complejidad regulatoria.
7. **F7 (opcional)** — fuentes de marca embebidas / e.firma / evaluación WeasyPrint.

> Prioridad sugerida: **F2 antes que la estética** — una receta bonita pero sin vía de administración/diagnóstico **no cumple COFEPRIS**. El formato Compacta (F1) y el cumplimiento (F2) son lo urgente.
