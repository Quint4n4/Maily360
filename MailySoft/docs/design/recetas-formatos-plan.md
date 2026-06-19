# Formatos de receta configurables por clínica — plan de diseño

> Estado: **plan** (2026-06-18). Sin implementar. Continuación de `recetas-plan.md` (B1).
> Origen: el cliente "Clínica Camsa" usa recetas en **media carta horizontal** muy densas
> (membrete con varias cédulas + signos + indicaciones largas + sueros/terapias + firma)
> donde **el texto se encima** por falta de espacio. Otras recetas convienen en formato
> **digital** para el paciente. Se necesita que **cada clínica elija/configure su formato**.

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

1. **Estándar · carta vertical** — el actual (`prescription.html`). Limpio, una página.
2. **Compacta · media carta horizontal** — 5.5×8.5 in apaisada. Maquetada en **2 columnas** (datos+signos | Rp+indicaciones) para meter mucho sin encimar; tipografía y tamaños controlados; si no cabe, **continúa en otra media hoja** (no se monta). Resuelve el caso Camsa.
3. **Digital · para el paciente** — carta vertical amigable: tratamiento explicado en tarjetas ("Qué tomar / Cómo / Por cuánto tiempo"), pensada para enviar por WhatsApp/correo. WhatsApp aún simulado.

## 5. Qué se personaliza (sobre el formato elegido)

| Opción | Valores | Notas técnicas |
|---|---|---|
| **Logo** | imagen | ya existe en `ClinicSettings.logo`; encajado proporcional (`_image_box`) |
| **Color de acento** | paleta curada (o hex) | se inyecta en el template Django (`{{ accent }}`), NO como CSS var (xhtml2pdf no soporta `var()`) |
| **Tipografía** | set seguro: Helvetica (sans), Times (serif) en MVP | fuentes custom (Lato, etc.) = embeber TTF con `@font-face`/`registerFont` → fase posterior |
| **Tamaño/orientación** | Carta vertical · Media carta horizontal · A5 | `@page { size: ... }` (xhtml2pdf lo respeta; media carta = tamaño custom) |
| **Secciones a incluir** | signos, indicaciones, medicamentos, sueros/terapias, diagnóstico | flags en el contexto → `{% if %}` en el template |
| **Modo de membrete** | digital (el sistema arma el encabezado) · papel pre-impreso (deja espacio superior, no imprime encabezado) | reusa `letterhead_full/half` + `*_spaces` ya existentes |

## 6. Modelo de datos propuesto

Modelo nuevo **`PrescriptionFormat(TenantAwareModel)`** (1..N por tenant, permite que una clínica tenga varios — ej. "Compacta sueros" y "Digital paciente"):

- `name` (str) — nombre que le pone la clínica.
- `base_layout` (choice: `standard` | `compact` | `digital`) — la plantilla base.
- `accent_color` (str hex, validado).
- `font` (choice del set seguro).
- `paper` (choice: `letter` | `half_letter_landscape` | `a5`).
- `sections` (JSON validado por whitelist: `{signos, indicaciones, medicamentos, sueros, diagnostico}` bool).
- `letterhead_mode` (choice: `digital` | `preprinted`).
- `is_default` (bool) — el que se usa si no se elige otro.
- RLS por tenant (USING + WITH CHECK), baja lógica, bitácora de cambios.

**MVP:** la clínica configura **1 formato default**. **Extensión:** varios formatos + **selector al emitir/imprimir** la receta (el médico elige cuál usar para esa receta).

> Alternativa más simple (si se prefiere no crear modelo): añadir los campos a `ClinicSettings` (formato único por clínica). Se descarta porque limita a un solo formato y Camsa necesita ≥2.

## 7. Generador de PDF (cómo cambia `apps/recetas/pdf.py`)

- `prescription_pdf_build(prescription, format=None)`: resuelve el `PrescriptionFormat` (el pasado, o el `is_default` del tenant, o el "standard" de fábrica si no hay ninguno).
- Selecciona el **template** según `base_layout`: `recetas/formats/standard.html` | `compact.html` | `digital.html` (refactor del actual a `formats/`).
- Inyecta en el contexto: `accent`, `font`, `sections`, `paper`, `letterhead_mode` + los datos ya existentes (clínica, médico, paciente, items, signos).
- `@page size` se fija por `paper`; el color por `{{ accent }}`; las secciones por flags.
- Mantiene la seguridad ya implementada: `_link_callback` (solo `data:`), imágenes base64 con dimensiones proporcionales, autoescape de Django.

## 8. Pantalla de configuración (Mi Consultorio → Recetas → Formato)

- **Galería** de los 3 formatos con **vista previa** (mockup ya diseñado): la clínica elige uno como base.
- **Panel de personalización:** logo (ya cargado), color de acento (paleta), tipografía, tamaño de hoja, secciones (checkboxes), modo de membrete.
- Botones **"Vista previa PDF"** (genera un PDF de ejemplo con datos ficticios) y **"Guardar formato"**.
- Permisos: owner/admin configuran; el médico puede elegir formato al emitir (si hay varios).

## 9. Conexión con lo que ya existe (no se parte de cero)

- `ClinicSettings` (logo, datos, membrete full/half + espacios, `recipe_use_responsible_doctor`) → base de identidad y modo pre-impreso.
- `pdf.py` + `prescription.html` → se generaliza a varios templates + parámetros.
- `ClinicTemplate` (kind=recipe) → **contenido** (recomendaciones), independiente del formato.
- `_image_box` (dimensiones proporcionales), `_link_callback` (seguridad), bitácora, RLS → se reutilizan tal cual.

## 10. Consideraciones técnicas (xhtml2pdf)

- **CSS variables NO soportadas** → el color de acento se inyecta vía template Django, no `var()`.
- **Tipografías:** solo fuentes base (Helvetica/Times/Courier) sin embeber; fuentes de marca requieren `@font-face` con TTF accesible → fase posterior (decidir si subir TTF por clínica o un set fijo curado).
- **Tamaño/orientación:** `@page { size: 8.5in 5.5in; }` para media carta horizontal; validar márgenes.
- **Evitar encimado:** maquetar en **flujo** (tablas, `page-break-inside: avoid` por bloque), nunca posiciones absolutas; si el contenido excede, paginar.
- **Calidad visual:** si más adelante se quiere acabado superior (sombras, fuentes finas), evaluar **WeasyPrint** (requiere libs de sistema en el Dockerfile) vs seguir con xhtml2pdf.

## 11. Plan por fases

1. **F1 — Formato "Compacta · media carta"** (resuelve Camsa, sin encimado) + refactor de `pdf.py` a `formats/` con selector. (Opcional: "Digital paciente" en paralelo.)
2. **F2 — Modelo `PrescriptionFormat`** + personalización (color, tipografía, tamaño, secciones, modo membrete) + RLS + bitácora.
3. **F3 — Pantalla de galería + vista previa** en Mi Consultorio (frontend).
4. **F4 — Multi-formato:** selector de formato al emitir la receta (varios por clínica).
5. **F5 (opcional)** — fuentes de marca embebidas / evaluación de WeasyPrint.

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
| **Institución que expide el título** | ⚠️ parcial (`DoctorUniversity`) | estructurar en credenciales (decisión 2) |
| Cédula profesional | ✅ `cedula_profesional` | validar formato; marcar si vencida |
| **Cédula de especialidad** | ⚠️ texto (`cedulas_adicionales`) | estructurar en credenciales (decisión 2) |
| Especialidad | ✅ `doctor.specialty` | — |
| Firma autógrafa o digital | ✅ imagen de sello/firma | firma electrónica avanzada (e.firma) = futuro |
| Domicilio del establecimiento | ✅ `ClinicSettings.address` | — |
| Teléfono del establecimiento | ✅ `phone`/`mobile` | — |
| Nombre completo del paciente | ✅ `patient.full_name` | — |
| Edad del paciente | ✅ (el PDF la calcula) | — |
| Nombre genérico del medicamento | ✅ `generic_name` (catálogo) | — |
| Denominación comercial (opcional) | ✅ `commercial_name` | — |
| Forma farmacéutica | ✅ `medication_form` | — |
| **Dosis (sin abreviaturas)** | ⚠️ dentro de `indication` libre | **campo estructurado** |
| **Frecuencia** | ⚠️ dentro de `indication` | **campo estructurado** |
| **Vía de administración** | ❌ no existe | **agregar campo** |
| **Duración del tratamiento** | ⚠️ dentro de `indication` | **campo estructurado** |
| Fecha de emisión | ✅ `issued_at` | — |
| **Diagnóstico en la receta** | ⚠️ opcional/separado | incluirlo (COFEPRIS marca "receta sin diagnóstico" como error que invalida) |
| Folio | ✅ consecutivo por tenant | para controlados: **folio autorizado oficial** |
| **Código de verificación (QR/barras)** | ❌ | **agregar QR** de validación de autenticidad |
| Bitácora / trazabilidad | ✅ NOM-024 (`audit`) | reforzar para controlados |
| **Medicamentos controlados** (grupo, vigencia, recetario especial) | ❌ | **módulo aparte** (ver abajo) |

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
