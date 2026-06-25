# Expediente como SaaS — rediseño (núcleo simple + plugins)

> Estado: **plan** (2026-06-24). Maqueta aprobada por el dueño.
> Objetivo: que el expediente sea **intuitivo y con pocos clics** para CUALQUIER
> clínica (no solo medicina regenerativa). Un **núcleo básico** común a todas +
> **plugins** por especialidad en fases futuras. Reúsa lo que ya existe; el cambio
> es ~80% UX/presentación, no de datos.

## 1. Decisiones tomadas con el dueño (2026-06-24) — locked

- **D-EXP-1 · Expediente "centrado en la visita".** Al entrar al expediente:
  izquierda fija (identificación, alergias, indicaciones de enfermería); centro
  con una tarjeta **"Visita de hoy"** de 3 pasos: ① Enfermería (signos) → ②
  Evolución (SOAP) → ③ Receta; abajo, el **historial** (Libro clínico + visitas).
  Se eliminan los acordeones apilados.
- **D-EXP-2 · Evolución SOAP guiada paso a paso.** S → O → A → P, un paso a la vez,
  con guía. **Genérica** (deja de estar amarrada a medicina regenerativa).
- **D-EXP-3 · Exploración física selectiva.** El médico **agrega solo los aparatos
  que revisó hoy** (no los 18 sistemas). Sigue guardando en `EvolutionNote.exploracion_fisica`.
- **D-EXP-4 · Recetas con botón directo** (sin acordeón) dentro de la visita; **citas =
  recordatorio** al final (solo consultar las visitas).
- **D-EXP-5 · Historia Clínica configurable = núcleo NOM-004 fijo + preguntas extra.**
  Los bloques obligatorios de ley NO se pueden quitar; el admin **agrega/edita/borra
  preguntas propias** encima. (Fase 2.)
- **D-EXP-6 · Núcleo + plugins.** Núcleo básico (datos, alergias, enfermería, HC,
  evolución SOAP, recetas, libro) para todas las clínicas; plugins por especialidad
  (dental, regenerativa, nutrición…) enchufan secciones/campos sin tocar el núcleo.
  (Alineado con D-EC-9: especialidades activadas por super-admin.)

## 2. Al guardar la visita
Al guardar el paso de enfermería/evolución, la "Visita de hoy" se **cierra como un
capítulo del Libro clínico** (ya existe) y aparece en el historial: "Visita del 24 jun ✓".

## 3. Fases

### Fase 1 — Reordenar expediente + Evolución SOAP guiada (ARRANCA AHORA)
Frontend principalmente; el backend REÚSA todo (modelos, hooks y services ya existen:
`useEvolutionNotes/useCreateEvolutionNote`, `useVitalSigns/useCreateVitalSigns`,
`useEvolutionImages`, recetas, etc.). NO cambiar modelos ni romper el guardado actual.
- Reorganizar `ExpedienteDrawer`/`FichaPaciente`: izquierda fija + **"Visita de hoy"** (3 pasos) + historial abajo (Libro + citas).
- Rehacer `EvolucionTab` → **SOAP guiado** (stepper S/O/A/P) reusando los mismos campos
  (interrogatorio+antecedentes→S; signos+estudios+exploración→O; diagnósticos→A;
  tratamiento+recomendaciones+indicaciones enfermería→P).
- **Exploración selectiva**: en el paso O, "agregar aparato" en vez de mostrar los 18.
- **Recetas**: botón directo "+ Receta" en la visita.
- **Citas**: franja-recordatorio al final.
- Verificar `tsc -b`.

### Fase 2 — Historia Clínica configurable (núcleo NOM-004 + preguntas extra)
Diseño de datos (D-EXP-5):
- **`MedicalHistoryQuestion(TenantAwareModel)`** (nuevo, en `apps/expediente`): catálogo de
  preguntas EXTRA que el admin define por clínica.
  - `label` (texto de la pregunta), `field_type` (choices: `text` | `textarea` | `boolean`
    | `select` | `number` | `date`), `options` (JSON, solo para `select`),
    `section` (agrupador opcional, ej. "Estilo de vida"), `order` (PositiveInteger),
    `is_required` (bool), `is_active` (bool, soft-delete).
  - Las preguntas son SOLO adicionales; el **núcleo NOM-004 de `MedicalHistory` no se toca**.
- **`MedicalHistory.custom_answers`** (nuevo JSONField): respuestas a las preguntas extra,
  como `{ "<question_id>": <valor> }`. Snapshot por clave: si una pregunta se borra, las
  respuestas viejas quedan registradas.
- Backend:
  - Selectors/services para CRUD de `MedicalHistoryQuestion` (permiso owner/admin) y para
    guardar `custom_answers` en el upsert de `MedicalHistory`.
  - Endpoints de gestión (owner/admin) + el output de HC incluye las preguntas activas
    (para render) y las `custom_answers`.
  - Tests (CRUD, validación de tipos, aislamiento multi-tenant, permisos).
- Frontend:
  - Mini *form builder* en **Mi Consultorio** (agregar/editar/borrar/ordenar preguntas, elegir tipo).
  - Render dinámico en la HC del paciente: **núcleo NOM-004 fijo** + las preguntas extra activas.

### Fase 3 — Formalizar núcleo vs plugins
- Registro de "qué es núcleo" y "qué aporta cada plugin"; activación por especialidad
  (super-admin). Base para vender especialidades.

### Fase 4 — Plugins por especialidad (+ opcional dictado/IA)
- Dental (odontograma), regenerativa (terapias), nutrición, estética… como módulos.

## 4. Pros y contras
| ✅ | ⚠️ |
|---|---|
| Mucho más vendible: simple para cualquier consultorio | Reorganiza componentes que YA funcionan → no romper el guardado |
| Menos clics → adopción | La HC configurable (Fase 2) es la pieza nueva de fondo |
| Reúsa casi todo el backend | Mantener NOM-004 correcto con exploración selectiva |
| Base para monetizar plugins | Definir bien núcleo vs plugin para no rehacer |

## 5. Reglas
Arquitectura por capas, tipado, multi-tenant + RLS; evoluciones/recetas siguen
**inmutables**; nada de romper la captura actual (reusar hooks/services existentes).
