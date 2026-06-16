# Expediente Clínico — Análisis del sistema legacy (app.maily.mx)

> **Propósito:** insumo para el plan de implementación del módulo de **Expediente Clínico**
> en Maily360 (Maily Soft).
> **Fecha:** 2026-06-16.
> **Fuente:** capturas del expediente legacy (paciente demo "Acatempan Flores Abigail").
> Decisiones ya tomadas con el dueño: ver §7 y [`../DECISIONES-CLAVE.md`](../DECISIONES-CLAVE.md).

---

## 1. Resumen ejecutivo

Lo que el legacy llama "expediente" en realidad **mezcla tres dominios distintos** en una sola
pantalla. Separarlos es la decisión arquitectónica más importante de este módulo:

| Dominio | Qué es | Cómo tratarlo |
|---|---|---|
| **A. Expediente clínico** | Historia clínica, evolución, signos vitales, diagnósticos, alergias, recetas, estudios, documentos, consentimientos | Regulado (NOM-004), trazable, **inmutable**, permisos estrictos. Es el foco de este plan. |
| **B. CRM / fidelización** | "Experiencia" (pareja, hijos, aniversarios, hobbies, gustos), "Expectativas" | Módulo aparte, no clínico. Para trato personalizado y marketing (cumpleaños, "Maily App"). |
| **C. Finanzas (por paciente)** | Cotizaciones, Estado de Cuenta | Pertenece al módulo **Finanzas** (hoy pendiente). El expediente solo lo *consume* (vista de saldo). |

> El expediente legacy proviene de una clínica **multi-especialidad** (hay campos
> **odontológicos** y una **encuesta nutricional** dentro de la historia clínica genérica).
> Esto conecta con **D-12** (especialidades como extensiones): parte de esos bloques deben ser
> **módulos por especialidad**, no núcleo obligatorio.

---

## 2. Cómo se accede y estructura general

Se entra desde un botón **"Ficha"** en el expediente del paciente. La pantalla tiene **dos zonas**:

- **Izquierda — "Paciente":** resumen + ficha editable en acordeón de **7 secciones**.
- **Derecha — "Historia Clínica":** **9 módulos** colapsables con contador de registros.

---

## 3. Inventario completo del legacy

### 3.1 Ficha del paciente (izquierda) — 7 secciones

| Sección | Contenido | Dominio |
|---|---|---|
| **Datos Generales** | Domicilio, colonia, ciudad, estado, CP; celular, teléfono (con etiqueta, ej. "hija"), teléfono secundario; email; lugar de nacimiento; ocupación; religión; **costo de consulta personalizado**; casilla **"Finado"**; "Enviar Maily App"; "Eliminar contacto definitivamente". Resumen superior: foto, nombre, **alergias (rojo)**, edad, estado civil, escolaridad, **tipo de sangre**, categoría, género, antecedentes patológicos, médico que envía, diagnóstico. | Demográfico (Patient) |
| **Cie** | Diagnósticos codificados (catálogo CIE). | Clínico |
| **Alergias** | Texto libre, destacado en rojo (bandera de seguridad). | Clínico |
| **Padecimiento Actual** | Antecedentes de importancia, padecimiento actual, tratamientos actuales, prioridad y análisis médico. | Clínico |
| **Experiencia** | Texto libre + Pareja (con aniversario) + Hijos (con cumpleaños) + Empresa (con aniversario) + Hobbies: gustos, series/películas, música, deportes, comida, vehículos. | **CRM** |
| **Expectativas** | Qué espera el paciente del tratamiento. | Mixto (CRM) |
| **Observaciones** | Notas operativas sueltas ("enviar estudios"). | Operativo |

### 3.2 Historia Clínica (derecha) — 9 módulos

1. **Historia Clínica** (formal, exportable a PDF) — 6 bloques:
   - **AHF** (Antecedentes Heredo-Familiares): ~17 campos texto libre (diabetes, hipertensión, cáncer, alérgicas…).
   - **APP** (Antecedentes Personales Patológicos): ~26 campos (infancia, quirúrgicos, transfusionales, adicciones, hospitalizaciones, alergias…).
   - **ANP** (Antecedentes No Patológicos): casa habitación, actividad física, inmunizaciones **+ odontológico** (pasta dental, brackets, amalgamas).
   - **Hábitos Alimenticios**: encuesta nutricional (~32 alimentos con frecuencia "X/7" + comidas del día). *Tinte de nutrición.*
   - **Gineco-Obstétricos**: menarca, FUM, IVSA, G/A/P/C, citología, mastografía, planificación… (solo mujeres).
   - **Exploración física**: ~18 aparatos y sistemas con hallazgos en texto.

2. **Enfermería** — **signos vitales longitudinales** (serie temporal). Cada registro: fecha, hora, responsable + Peso, Estatura, F. Cardiaca, F. Respiratoria, P. Arterial, Temperatura, Sat O2, Glucosa, Observaciones; **"Otros parámetros"**: Colesterol, Triglicéridos, Urea, Creatinina, Hemoglobina; **IMC calculado**. Historial de tomas + **gráficas de tendencia** por parámetro.

3. **Evolución** — **nota por cada consulta** (lo más importante; 161 registros en el demo).
   Campos: Antecedentes Patológicos, Interrogatorio, Estudios, Exploración Física, Diagnósticos
   Actuales, Tratamiento, Plan y Recomendaciones, Indicaciones para Enfermería.
   Panel lateral con **snapshot de signos vitales** de ese día. Botones Foto / Gráfica / Aparatos.
   **Exploración por aparatos** con semáforo (gris/verde/naranja/rojo) + "Más" en cada uno
   (Cerebro, S. Nervioso, S. Visual, Metabólico, Corazón, S. Vascular, Respiratorio, Hepático,
   Páncreas, Renal, Gastro, Osteoarticular, Tendo, Reproductor, Inmuno-hematológico, Extremidades,
   Piel, Otros). Imprimir.

4. **Estudios de Laboratorio** — 3 pestañas (**Clínicos / Gabinete / Especiales**). Subida de
   archivos organizados en **carpetas por categoría y fecha** (Inmunología, Química sanguínea,
   Biometría, EGO, Ecografías, Biopsias, Rx, Gamagrama, Audiología…). Miniaturas; eliminar.

5. **Documentos Médicos** — constancias y similares: **título + cuerpo** (con plantilla). Imprimir / PDF / WhatsApp / editar / eliminar.

6. **Recetas** — **buscador de medicamento** (catálogo) + cuerpo + Recomendaciones + Tratamiento + **"Copia Recomendación/Tratamiento"** (reusar de receta previa) + "Mostrar Signos". Imprimir / PDF / WhatsApp / editar / eliminar. Historial.

7. **Consentimientos** — solo "Nuevo" / "Mostrar anteriores" (sin más funciones en el legacy → a diseñar, ver §8).

8. **Cotizaciones** — partidas (cantidad / descripción / P.U. / total), título, total general,
   "Cotización precargada", confirmar, imprimir / duplicar. *(Dominio Finanzas, ver §9.)*

9. **Estado de Cuenta** — movimientos (Pago / Consulta / Tratamiento / Medicamento / Producto),
   concepto + monto, **saldo acumulado** (cargos en rojo, abonos en negro), detalle, imprimir.
   *(Dominio Finanzas, ver §9.)*

---

## 4. Mapeo contra el backend actual

| Pieza legacy | Estado hoy en Maily360 | Acción |
|---|---|---|
| Datos demográficos básicos (nombre, sexo, fecha nac., CURP, teléfono, email, avatar) | ✅ `Patient` | Reusar |
| Domicilio estructurado, estado civil, escolaridad, ocupación, religión, lugar nac., tipo de sangre, teléfonos extra, finado(+fecha), costo consulta, categoría | ❌ | **Ampliar `Patient`** (campos NOM-004) |
| Alergias (estructuradas), diagnósticos (CIE) | ❌ (solo `notes` libre) | **Construir** |
| Historia clínica formal (AHF/APP/ANP/hábitos/gineco/exploración) | ❌ | **Construir** |
| Signos vitales (Enfermería) | ❌ | **Construir** (serie temporal) |
| Nota de evolución | ❌ | **Construir** (inmutable + addendum) |
| Estudios (archivos), Documentos, Recetas, Consentimientos | ❌ | **Construir** |
| Familia / hobbies / aniversarios (Experiencia) | ❌ | **Construir como CRM aparte** |
| Cotizaciones, Estado de Cuenta | ❌ (Finanzas pendiente) | **Construir en dominio Finanzas** |
| Cita "Atendida", doctor, bitácora, multi-tenant + RLS, roles, avatares, PDF | ✅ `agenda`, `personal`, `audit`, `core` | Reusar / integrar |

---

## 5. Arquitectura propuesta (alto nivel)

**Dominio clínico — app(s) nueva(s)** (p. ej. `expediente`):

- `Allergy` — alergias estructuradas (bandera de seguridad, visible para todos los roles).
- `Diagnosis` — diagnóstico, idealmente ligado a catálogo **CIE-10**.
- `MedicalHistory` — historia clínica formal (AHF/APP/ANP/hábitos/gineco/exploración basal).
  Documento "vivo" por paciente, **versionado** (snapshot al actualizar). Núcleo fijo + secciones
  flexibles (JSON validado) para lo que varía por especialidad (D-12).
- `VitalSignsRecord` — signos vitales (Enfermería). Serie temporal; núcleo fijo + parámetros
  extra extensibles; **IMC derivado** (no se guarda). Lo captura enfermería.
- `EvolutionNote` (consulta) — **nace de una cita "Atendida"**, **inmutable**; correcciones vía
  `Addendum`. Incluye exploración por aparatos (estado + detalle) y referencia a la toma de signos.
- `Addendum` — corrección/agregado a una nota firmada (autor + fecha).
- `LabStudy` / `StudyFile` — estudios por tipo (clínico/gabinete/especial) y categoría; archivos.
- `MedicalDocument` — constancias/cartas: título + cuerpo; genera PDF.
- `Prescription` (+ `PrescriptionItem`) — recetas; usa catálogo de medicamentos.
- `InformedConsent` (+ plantillas) — consentimientos firmados (ver §8).

**Catálogos** (compartidos): `CIECode` (CIE-10, global), `Medication` (global + custom por tenant),
`StudyCategory` (configurable por tenant).

**Dominio CRM** — `PatientProfile` / preferencias: pareja, hijos, aniversarios, hobbies,
expectativas. Para fidelización (recordatorios de cumpleaños, "Maily App").

**Dominio Finanzas** — app `finanzas`: `Quote` (+items), `LedgerEntry` (cargo/abono),
`Payment`. El "Estado de Cuenta" del expediente es una **vista filtrada por paciente** (ver §9).

**Ampliar `Patient`** con los campos demográficos NOM-004 listados en §4.

---

## 6. Patrón de implementación

Se sigue la arquitectura por capas del proyecto: `URLs → Views (delgadas) → Serializers →
Services/Selectors → Models`, multi-tenant con **TenantAwareModel + RLS**, tipado mypy, tests
pytest ≥80% en lógica de negocio, sin secretos hardcodeados. Ver
[`.claude/skills/django-clean-architecture/SKILL.md`](../../.claude/skills/django-clean-architecture/SKILL.md).

---

## 7. Decisiones de diseño clave

**Ya tomadas con el dueño:**
1. **Notas de evolución inmutables + addendum** (estilo NOM-004). Una nota firmada no se edita ni
   se borra; se corrige con un agregado fechado y con autor.
2. **La consulta nace de una cita "Atendida"** (agenda ↔ expediente trazable).
3. **Separar 3 dominios**: clínico / CRM / finanzas.

**Recomendadas (a confirmar):**
4. **Historia clínica**: conjunto **estándar NOM-004** con almacenamiento flexible (preparado para
   especialidades, D-12), en lugar de 100+ columnas rígidas o un constructor configurable completo
   desde el día 1.
5. **No borrado físico de información clínica.** El legacy permite borrar evoluciones, recetas,
   documentos y movimientos (bote rojo). Esto **choca con NOM-004 y con la inmutabilidad** ya
   decidida. → Baja lógica / cancelación con motivo + bitácora; nunca `DELETE` real.
6. **Signos vitales ↔ evolución**: la nota muestra los signos de la toma del mismo día (vincular).
7. **PDF y WhatsApp**: definir librería de PDF (p. ej. WeasyPrint) y reusar el adapter de WhatsApp
   existente (hoy simulado) para enviar recetas/constancias.
8. **Permisos**: médico escribe HC/evolución/recetas/diagnósticos; enfermería captura signos
   vitales; recepción no toca lo clínico; **alergias visibles para todos** (seguridad).

---

## 8. Consentimientos — propuesta de contenido (estaba vacío en el legacy)

Convertirlo en **consentimientos informados con plantillas configurables por clínica**:

- **Plantillas** (por tenant): consentimiento general de atención, de procedimiento específico,
  **aviso de privacidad / consentimiento de datos (LFPDPPP)**, consentimiento de **telemedicina**,
  manejo de datos de **menores**, uso de imagen.
- **Al generar uno**: se elige plantilla → se autollenan datos del paciente y de la clínica →
  fecha → **captura de firma** (en pantalla/tableta, o subir el papel firmado escaneado) → **PDF**.
- **Estado**: pendiente / firmado. Una vez firmado: **inmutable**, con quién y cuándo (bitácora).
- **Vinculable** a un procedimiento o a una cotización cuando aplique.

---

## 9. Cotizaciones + Estado de Cuenta + Finanzas — flujo propuesto

Estas dos secciones **no son expediente**: son la vista *por paciente* del módulo Finanzas.

**Flujo:**
1. **Cotización** = presupuesto (no afecta saldo). Partidas + total. Puede partir de una
   "cotización precargada" (paquetes típicos de la clínica).
2. El paciente acepta → **"Confirmar cotización"** convierte las partidas en **cargos** en su
   estado de cuenta.
3. **Estado de cuenta** = libro mayor del paciente: **cargos** (consulta, tratamiento, medicamento,
   producto) y **abonos** (pagos). **Saldo = cargos − abonos.**
4. **Integraciones automáticas** (cuando exista Finanzas):
   - Cita **Atendida** → cargo de consulta (usa el costo personalizado del paciente o la tarifa).
   - **Receta / venta de medicamento** → cargo.
   - **Cotización confirmada** → cargos de tratamiento/procedimiento.
5. **Pagos**: registrar abono (efectivo, depósito, tarjeta) con recibo.

**Recomendación de arquitectura:** la lógica vive en la app **`finanzas`** (`Quote`,
`LedgerEntry`, `Payment`). El "Estado de Cuenta" del expediente es solo una **vista de solo
lectura filtrada por paciente**; Finanzas (nivel clínica) es la agregación global + reportes.
Esto evita duplicar lógica. → **Construir el esqueleto de Finanzas en paralelo o justo después
del núcleo clínico**, pero no bloquear el expediente con él.

---

## 10. Cumplimiento (NOM-004 / NOM-024 / LFPDPPP)

- **NOM-004-SSA3-2012** (contenido del expediente clínico): la estructura legacy ya se aproxima
  (HC con antecedentes + exploración, notas de evolución, consentimientos). **Validar con la
  norma** los campos obligatorios al diseñar los modelos.
- **NOM-024 / bitácora**: ya existe `audit`. Registrar **acceso y cambios** al expediente (dato
  más sensible del sistema).
- **LFPDPPP**: minimización de PII, consentimiento de datos, control de acceso por rol y
  aislamiento multi-tenant (RLS) ya presentes.
- ⚠️ **Eliminar la posibilidad de borrado físico** de información clínica (ver §7.5).

---

## 11. Propuesta de fases (MVP primero)

- **Fase A — Núcleo clínico (MVP):** ampliar `Patient` (demográficos NOM-004) + `Allergy` +
  `MedicalHistory` + `VitalSignsRecord` (Enfermería) + `EvolutionNote` (desde cita atendida,
  inmutable) + `Diagnosis`. → Ya es un expediente usable por un médico.
- **Fase B — Documentos y soporte:** `Prescription` (+catálogo medicamentos) + `MedicalDocument`
  + `LabStudy`/archivos + **PDF** + WhatsApp + `InformedConsent`.
- **Fase C — No clínico:** CRM (Experiencia/preferencias) + Finanzas (Cotizaciones + Estado de
  Cuenta) en su propio dominio.
- **Después (D-12):** catálogo CIE-10, especialidades como extensiones, bloques odontológico /
  nutricional avanzados.

---

## 12. Decisiones pendientes antes del plan

1. **Alcance de la primera entrega** (¿solo Fase A, o A+B?). → **Resuelto: solo Fase A.**
2. **Modelado de la historia clínica** (estándar NOM-004 flexible vs. configurable). → **Resuelto:
   estándar NOM-004 con almacenamiento flexible.**
3. Confirmar §7.5 (no borrado físico) y §8 (alcance de consentimientos). → **Confirmado.**
4. Frontend: librería de gráficas para signos vitales y de PDF para documentos.

---

## 13. Historia clínica: núcleo universal vs. extensiones por especialidad

> Responde a: *"¿cómo dividimos la historia clínica para un expediente clínico especial; qué
> campos deberíamos mover por especialidad?"*. Conecta con **D-12** (especialidades como
> extensiones, después del núcleo).

### 13.1 El concepto en 3 capas

Una historia clínica no es "una talla única". Tiene una **base que todo médico necesita** y
**capas extra** que solo ciertos casos usan:

1. **Núcleo universal** — se llena para **cualquier** paciente, sin importar la especialidad.
   Es la columna vertebral del expediente.
2. **Módulos condicionales (por el paciente, no por la especialidad)** — dependen del **sexo o la
   edad**: gineco-obstétrico (mujeres), perinatal/crecimiento/vacunación (niños).
3. **Extensiones por especialidad** — secciones que solo aparecen si la clínica/médico ejerce esa
   especialidad: odontograma (dental), encuesta nutricional fina (nutrición), etc.

### 13.2 Reparto de los bloques del legacy

| Bloque del legacy | Capa | Por qué |
|---|---|---|
| Identificación / demográficos | **Núcleo** | Todo paciente. |
| Antecedentes Heredo-Familiares (AHF) | **Núcleo** | Universal. |
| Antecedentes Personales Patológicos (APP) | **Núcleo** | Universal. |
| No patológicos — general (vivienda, actividad física, inmunizaciones, toxicomanías) | **Núcleo** | Universal. |
| No patológicos — **dental** (lavado, pasta, amalgamas, brackets) | **Especialidad: Odontología** | Solo importa en dental. |
| Hábitos alimenticios — corto (n.º comidas, dieta especial, intolerancias) | **Núcleo (mínimo)** | Útil para todos. |
| Hábitos alimenticios — **encuesta de 32 alimentos × frecuencia** | **Especialidad: Nutrición** | Detalle solo para nutriólogo. |
| Gineco-Obstétricos | **Condicional (mujeres)** | No aplica a hombres; se profundiza en Ginecología. |
| Exploración física general por aparatos | **Núcleo** | Universal. |
| Exploración profunda de un sistema | **Especialidad** | Detalle según especialista. |
| Signos vitales + somatometría | **Núcleo** | Universal. |
| Padecimiento actual / interrogatorio / evolución / diagnóstico | **Núcleo** | Universal. |

### 13.3 Esta clínica es multi-disciplina

Por el Estado de Cuenta del demo (botox, rinomodelación, hydrafacial, ortodoncia, limpieza dental,
consulta psicológica) se ve que la clínica mezcla **estética/longevidad + odontología + nutrición +
psicología + medicina general**. Extensiones que tendrían sentido más adelante:

- **Medicina estética / longevidad:** áreas tratadas, productos y dosis aplicadas, fotos
  antes/después, consentimiento de procedimiento.
- **Odontología:** odontograma, periodontograma, lo dental de "no patológicos".
- **Nutrición:** antropometría (circunferencias, % grasa), recordatorio de 24 h, plan de alimentación.
- **Psicología:** examen mental, antecedentes psicosociales, notas de sesión.

### 13.4 Cómo se construye (sin rehacer luego)

- **Fase A (ahora):** se construye **solo el núcleo universal**. La historia clínica se guarda con
  `JSONField` por bloque (D-EC-4), lo que deja el **"gancho"** para enchufar extensiones después.
  Decisión concreta: **sacar del núcleo lo dental y la encuesta nutricional fina** (van como
  extensiones futuras) y dejar **gineco-obstétrico como bloque condicional por sexo** dentro del
  núcleo (es muy común, no vale la pena diferirlo).
- **Después (D-12):** se añade el **sistema de módulos/plugins** (ver §13.5). Cada especialidad es
  un módulo con su *schema* de secciones/campos. La clínica que lo tiene activo ve, además del
  núcleo, las secciones de esas especialidades. Así un cardiólogo no ve campos de odontología, y un
  dentista no llena consumo de tortillas.

**Regla práctica para decidir si un campo es núcleo o de especialidad:**
*¿lo necesitaría un médico general de cualquier especialidad para entender al paciente?* → núcleo.
*¿solo tiene sentido para un tipo de especialista?* → extensión por especialidad.

### 13.5 Módulos como plugins, liberados por la plataforma

Decisión del dueño (2026-06-16): el **super administrador de la plataforma** decide **qué módulos
de especialidad tiene cada clínica**, según lo que el cliente contrate/solicite. Es un sistema de
**entitlements (derechos de uso) por tenant**, patrón estándar de SaaS. Modelo:

| Pieza | Nivel | Qué hace |
|---|---|---|
| `SpecialtyModule` | **Global** (plataforma) | Catálogo de módulos: clave (`dental`, `nutrition`, `aesthetics`, `psychology`…), nombre, descripción, *schema* de secciones/campos que aporta. Hereda de `BaseModel` (no es por tenant). |
| `TenantModule` | **Por clínica** | Activación: `tenant` + `module` + `is_active` + `activated_by` (staff de plataforma) + fechas. **Fuente de verdad** de qué puede usar cada clínica. |

**Quién lo controla:** el **staff de plataforma** (sin membresía de clínica). Hoy opera vía
**Django admin**; a futuro vía el **Panel de Plataforma** (hoy pendiente/mock). La gestión de
módulos por cliente es, de hecho, una función natural de ese panel.

**Control de acceso (gating):**
- **Backend = autoridad.** Un helper `tenant_has_module(tenant, "dental")` que permisos/services
  consultan antes de leer/escribir secciones de ese módulo. Módulo no activo → la sección no existe
  / 403.
- **Frontend.** Un endpoint (p. ej. ampliar `/me/` o `/tenant/modulos/`) devuelve los módulos
  activos; la UI solo muestra las pestañas/secciones liberadas.

**Relación con planes (futuro, opcional):** un "plan" sería solo un **paquete de módulos** que
pre-puebla los `TenantModule`. Como el dueño quiere activar **según lo que cada cliente pida**, la
base es la **activación por clínica** (manual); los planes se pueden montar encima después sin
rehacer.

**No bloquea la Fase A:** el núcleo universal se construye igual. El sistema de módulos es la
**Fase D** del plan.
