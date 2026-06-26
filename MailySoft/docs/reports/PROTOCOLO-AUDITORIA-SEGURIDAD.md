# Protocolo de Auditoría de Seguridad — Maily Soft / Maily360

> **Propósito:** que CADA auditoría de seguridad sea **idéntica, completa y repetible**, sin importar
> quién (o qué sesión) la ejecute. Este documento resuelve el problema histórico de "se perdía contexto
> y no se hacían las mismas auditorías". Es el playbook del auditor.
>
> **Cómo se ejecuta:** se invoca al agente `django-security` (modelo sonnet) apuntándolo a este protocolo
> y al módulo/diff a auditar. El agente aplica la skill `django-clean-architecture` (§Seguridad) + este
> protocolo + OWASP Django/DRF Cheat Sheets.
>
> Actualizado: **2026-06-25**.

---

## 0. Clasificación del sistema (por qué somos desconfiados por diseño)

Maily Soft procesa **datos de salud**: expedientes clínicos, diagnósticos, recetas, signos vitales, datos
de contacto del paciente. Es la categoría de datos más sensible bajo el marco normativo mexicano:

- **NOM-024-SSA3-2010** — sistemas de registro electrónico para la salud: exige **bitácora de auditoría**
  e impide el acceso no autorizado al expediente clínico electrónico.
- **NOM-004-SSA3-2012** — del expediente clínico: regula contenido mínimo, **inmutabilidad** y confidencialidad.
- **LFPDPPP** — clasifica los datos de salud como **datos sensibles** (nivel de protección más alto). Una
  fuga entre tenants distintos (clínicas distintas) es una **violación directa** con consecuencias legales
  para Maily y para cada clínica.

> Regla del auditor: ante datos de salud, **peca de cauteloso**. No alarmes sin evidencia, pero un riesgo
> de fuga cross-tenant o de PII en logs se trata como crítico hasta probar lo contrario.

---

## Las 3 fases de la auditoría

Toda auditoría recorre estas **3 fases en orden**. Ninguna se omite. Cada hallazgo se anota con
`archivo:línea`, cómo se explotaría y la corrección concreta.

```
FASE 1 — Código y control de acceso     (OWASP, estática)        → ¿el código es explotable?
FASE 2 — Aislamiento multi-tenant + PII  (NOM-024/004 · LFPDPPP)  → ¿se puede fugar/ver datos ajenos?
FASE 3 — Configuración de prod + deps    (hardening · CVEs)       → ¿el despliegue es seguro?
```

> **Complemento frontend:** si el módulo tiene UI conectada, además se corre el checklist de
> [`docs/design/frontend-security-testing.md`](../design/frontend-security-testing.md) (tokens, XSS,
> secretos en el bundle). El frontend NO es la frontera de seguridad — el backend lo es — pero abre
> agujeros propios (XSS, fuga de tokens).

---

## FASE 1 — Código y control de acceso (OWASP / estática)

Pregunta guía: *¿hay algo explotable en el código mismo?*

### 1.1 Secretos hardcodeados
- [ ] Cero `SECRET_KEY = "..."`, contraseñas, API keys, tokens o llaves de cifrado en código o settings.
- [ ] Todo valor sensible viene de `env("NOMBRE")` (django-environ). Sin defaults para secretos en `production.py`.
- [ ] Las credenciales de usuarios DEMO (seeders/docs de DEV) **no cuentan** como hallazgo, pero se confirma
      que jamás se reusan en staging/prod y que `.env.*` está en `.gitignore` (solo `.env.example` versionado).
- [ ] Nada sensible en mensajes de commit (quedan permanentes en git).

```bash
grep -rniE "SECRET_KEY *=|password *=|passwd|api_key|api-key|secret *=|token *=|AES|private_key|BEGIN .*PRIVATE" backend/ --include=*.py | grep -v "env("
grep -rn "\.env" backend/.gitignore
```

### 1.2 Inyección SQL
- [ ] Cero `.raw(`, `.extra(`, `cursor.execute` con f-strings/concatenación de input del usuario.
- [ ] El único `cursor.execute` admitido es el `set_config` del contexto de tenant, y va **parametrizado** (`%s`).

```bash
grep -rnE "\.raw\(|\.extra\(|cursor\.execute" backend/apps backend/config --include=*.py
```

### 1.3 Inyección / XSS
- [ ] Cero `mark_safe`, `|safe`, `format_html` con input sin escapar; cero `eval`/`exec`.
- [ ] En plantillas PDF (recetas/expediente): los valores interpolados en `<style>` (color, tipografía)
      están **validados** (color = regex `^#[0-9A-Fa-f]{6}$`; tipografía = `ChoiceField` cerrado).
- [ ] WeasyPrint usa un `url_fetcher` seguro que bloquea todo lo que no sea `data:` (sin SSRF/LFI vía PDF).

```bash
grep -rnE "mark_safe|format_html|\|safe|autoescape off|eval\(|exec\(" backend/apps --include=*.py --include=*.html
```

### 1.4 AuthZ / permisos por rol
- [ ] Todo endpoint tiene `permission_classes` explícito; cero endpoints "pelados".
- [ ] Cada `AllowAny` se justifica (p. ej. verificación pública de PDF por HMAC) y **no expone PII**.
- [ ] Los permisos usan las clases declarativas `HasClinicRole` (policy por método HTTP), no guards
      imperativos `if role not in (...)` dispersos (más frágiles ante refactor). Si hay un guard imperativo,
      es hallazgo INFO de higiene (no de acceso si funciona).
- [ ] La **matriz de roles** del módulo coincide con `ESTADO-DEL-PROYECTO.md §5`. Verificar que ningún
      permiso quedó **más laxo** que lo documentado.

```bash
grep -rnL "permission_classes" backend/apps/<modulo>/views*.py   # vistas sin permisos declarados
grep -rn "AllowAny\|permission_classes" backend/apps/<modulo>/views*.py
```

### 1.5 IDOR y CRUD seguro (lecciones reales — ver §"Regresiones")
- [ ] Cada detail endpoint (`GET/PATCH/DELETE /x/<id>/`) lee vía un **selector** `x_get`, nunca
      `Model.objects.get()` inline en la view.
- [ ] El `InputSerializer` de PATCH **no** expone `is_active`/`status`/flags de estado ni campos de identidad.
- [ ] El servicio de update tiene `_IMMUTABLE_FIELDS` que cubre `id`, `tenant`, `tenant_id`, timestamps,
      `deleted_at`, flags de estado y FK de identidad.
- [ ] Cada FK relacionada que entra a un servicio valida `related.tenant_id == tenant.id`.
- [ ] Recursos de otro tenant → **404** (no 403, no revelar existencia). Denegación por rol → **403**.

---

## FASE 2 — Aislamiento multi-tenant y datos sensibles (NOM-024 / NOM-004 / LFPDPPP)

Pregunta guía: *¿puede un tenant ver/escribir datos de otro, o se filtra PII?* Esta es la fase de mayor
riesgo legal. **El check estrella es la RLS por tabla.**

### 2.1 Doble barrera de aislamiento (la regresión #1 del proyecto)
- [ ] Todo modelo de negocio hereda de `TenantAwareModel` (barrera 1: `TenantManager` filtra por tenant).
- [ ] **CADA tabla `TenantAwareModel` tiene su política RLS en Postgres (barrera 2).** Esto se verifica
      tabla por tabla, no se asume. Para cada modelo nuevo debe existir una migración `enable_rls` con
      `ENABLE/FORCE ROW LEVEL SECURITY` + `CREATE POLICY ... USING (tenant_id = current_tenant_id()) WITH CHECK (...)`.

```bash
# 1) Listar todos los modelos TenantAware del módulo:
grep -rn "TenantAwareModel" backend/apps/<modulo>/models.py
# 2) Listar las tablas con RLS declarada en migraciones:
grep -rniE "ROW LEVEL SECURITY|CREATE POLICY" backend/apps/<modulo>/migrations/
# 3) Cruzar: TODA tabla del paso 1 debe aparecer en el paso 2. Las que falten = hallazgo.
```

> ⚠️ **Brecha conocida abierta (2026-06-25):** `notas_notes`, `agenda_item_notes`, `agenda_blocks`,
> `agenda_appointment_types` tienen `TenantManager` pero **les falta RLS**. Documentado en
> `ESTADO-DEL-PROYECTO.md §9`. Verificar si ya se corrigió al auditar esos módulos.

- [ ] El GUC `app.current_tenant_id` se alimenta con `SET SESSION` (no `SET LOCAL`, que se borra entre
      queries sin transacción) y se limpia en el `finally` de `TenantAPIView`. (Regresión histórica crítica.)
- [ ] `TenantMiddleware`/`resolve_membership` filtra `is_active=True` **y** `deleted_at__isnull=True` **y**
      `tenant.status != SUSPENDED`, con `order_by` determinista. Sin membresía activa → 403 en todo.
- [ ] Uso de `Model.all_objects` (bypass de tenant) **solo** en `apps/plataforma` (cross-tenant intencional)
      y nunca en una view de clínica. Cualquier `all_objects` fuera de plataforma es hallazgo crítico.

```bash
grep -rn "all_objects" backend/apps --include=*.py   # debe salir solo en plataforma/
```

### 2.2 Datos sensibles / PII (LFPDPPP)
- [ ] Cero PII (nombre, teléfono, CURP, diagnóstico) en logs en texto claro. Teléfonos enmascarados
      (últimos 4 dígitos) en adapters. `APP_LOG_LEVEL` default `INFO` (no `DEBUG`) en prod.
- [ ] Minimización: resultados de Celery con expiración (`CELERY_RESULT_EXPIRES`); no se acumulan datos de
      tareas indefinidamente.
- [ ] Validación de PII de formato: CURP (patrón RENAPO), teléfono E.164 antes de enviar, email normalizado.
- [ ] **Títulos de notificación / payloads** no filtran PII evitable (caso abierto: el título de `team_note`
      incluye el nombre del paciente — decisión UX vs LFPDPPP pendiente de ADR).

```bash
grep -rniE "logger\.(info|debug|warning|error).*(phone|telefono|curp|nombre|email|diagn)" backend/apps --include=*.py
```

### 2.3 Bitácora de auditoría (NOM-024)
- [ ] Las acciones sensibles del módulo (create/update/delete, login, bloqueo, restablecer contraseña,
      acceso a expediente) llaman a `audit_record` con actor, rol, tenant y un identificador **no-PII** del recurso.
- [ ] La bitácora es **inmutable** y solo la consultan Dueño/Admin.

### 2.4 Inmutabilidad clínica (NOM-004)
- [ ] Las notas de evolución, recetas y signos vitales son **append-only / inmutables**: se corrigen con
      addenda o anulación con motivo, nunca se editan/borran en silencio.

---

## FASE 3 — Configuración de producción y dependencias

Pregunta guía: *¿el despliegue está endurecido y las dependencias son seguras?*

### 3.1 Configuración de producción (`config/settings/production.py`)
- [ ] `DEBUG=False` (doble seguro: env con default False + hardcode en production.py).
- [ ] `ALLOWED_HOSTS` explícito vía env, **sin default** (falla ruidoso si falta).
- [ ] Cookies de refresh/sesión: `Secure=True`, `HttpOnly=True`, `SameSite=Strict/Lax`. CSRF double-submit
      (`CSRF_COOKIE_HTTPONLY=False` es correcto y justificado: el front lee la cookie para el header).
- [ ] HSTS: `SECURE_HSTS_SECONDS` (1 año), `INCLUDE_SUBDOMAINS`, `PRELOAD`. `SECURE_SSL_REDIRECT=True`.
- [ ] CORS **no abierto** (`CORS_ALLOW_ALL_ORIGINS=False`), orígenes en lista explícita.
- [ ] `SECURE_CONTENT_TYPE_NOSNIFF`, `X_FRAME_OPTIONS=DENY`. **CSP** configurada (hoy pendiente — anotar).
- [ ] `JWT_SIGNING_KEY` obligatoria en prod (no cae a `SECRET_KEY`).
- [ ] Docs OpenAPI (`/api/schema/`, `/api/docs/`) **solo** con `DEBUG=True` (no exponer superficie en prod).
- [ ] Contraseñas con **Argon2** (primer hasher), nunca cifrado reversible.

### 3.2 Dependencias con CVE
- [ ] Backend: revisar versiones en `pyproject.toml`/`poetry.lock`; correr `pip-audit` si está disponible
      (no instalar nada nuevo solo para esto).
- [ ] Frontend: `npm audit --production` en `web-soft/`.
- [ ] Eliminar dependencias declaradas pero no usadas (reducen superficie).

```bash
grep -nE "Django|Pillow|xhtml2pdf|djangorestframework|celery" backend/pyproject.toml
grep -n "\"xlsx\"\|\"exceljs\"" web-soft/package.json
```

> **Pendientes conocidos (2026-06-25):** Pillow `10.4.0` (CVE) → 12.2.0; `xlsx 0.18.5` front (CVE) → evaluar
> `exceljs`; `xhtml2pdf 0.2.17` declarada pero ya reemplazada por WeasyPrint → quitar. Django ya en `5.2.15`.

---

## Escala de severidad y veredicto

| Sello | Significado | Efecto |
|---|---|---|
| 🔴 **CRÍTICO** | Explotable; expone datos o permite tomar control (fuga cross-tenant, RCE, secreto en git) | **Bloquea el despliegue.** |
| 🟠 **ALTO** | Riesgo serio (IDOR, bypass de permisos, PII en logs) | Corregir antes de mergear. |
| 🟡 **MEDIO** | Endurecimiento recomendado (CVE sin explotación directa, RLS faltante con barrera 1 intacta) | Backlog prioridad alta. |
| 🟢 **INFO** | Buena práctica / higiene (guard imperativo, docstring viejo) | Anotar. |

**Veredicto final (uno de dos):**
- ✅ **SEGURO PARA DESPLEGAR / CONSTRUIR ENCIMA** (post-fixes)
- ❌ **NO DESPLEGAR — corregir críticos/altos primero**

---

## Plantilla del reporte (guardar en `docs/reports/security-audit-<modulo>.md`)

```markdown
# Auditoría de seguridad — <Módulo> (<fase/paso>)

| Campo | Valor |
|---|---|
| Auditor | django-security |
| Commit auditado | `<hash>` |
| Commit de remediation | `<hash>` |
| Fecha | <AAAA-MM-DD> |
| Marco normativo | NOM-024 · NOM-004 · LFPDPPP |
| Veredicto final | <resumen en una línea> |

## Clasificación del sistema
<por qué estos datos son sensibles>

## Hallazgos por severidad
### 🔴 CRÍTICO-N — <título>
**Descripción / Archivo (`archivo:línea`) / Cómo se explotaría / Remediación / Estado**
### 🟠 ALTO-N — ...
### 🟡 MEDIO-N — ...
### 🟢 INFO-N — ...

## Resumen de hallazgos
| Sub-paso | Críticos | Altos | Medios | Total | Todos corregidos |

## Controles positivos verificados
| Control | Descripción | Ubicación |

## Pendientes de seguridad para producción
| Pendiente | Riesgo | Acción requerida |

## Veredicto
<pre-fixes vs post-fixes>

## Referencias normativas
NOM-024 · NOM-004 · LFPDPPP · OWASP Django/DRF Cheat Sheet · ADR-0003
```

---

## Regresiones recurrentes — SIEMPRE re-verificar (lecciones de auditorías pasadas)

Estos bugs ya aparecieron y se corrigieron; el auditor los re-verifica en cada módulo nuevo porque
**tienden a reaparecer**:

1. **RLS faltante o inactiva por tabla** (FASE 2.1) — la regresión más cara. Cada modelo nuevo necesita su
   migración `enable_rls`. El GUC con `SET SESSION`, no `SET LOCAL`.
2. **`is_active`/`status` editable por PATCH** ("puerta trasera del is_active") — debe estar en `_IMMUTABLE_FIELDS`.
3. **IDOR por `Model.objects.get()` en la view** — siempre vía selector `x_get` con filtro de tenant → 404.
4. **FK a otro objeto sin validar tenant** en el servicio — validar `related.tenant_id == tenant.id`.
5. **PII en logs** (teléfono/nombre/CURP) — enmascarar; `APP_LOG_LEVEL=INFO` en prod.
6. **Admin de Django expone datos cross-tenant** — restringir a `is_platform_staff`/`is_superuser`.
7. **Endpoint sin `permission_classes`** o `AllowAny` que filtra PII.
8. **Datos de Celery/tareas sin expiración** (minimización LFPDPPP).
9. **OpenAPI público en prod** — solo con `DEBUG=True`.

---

## Cómo invocar la auditoría (para el dueño)

> "Audita la seguridad de `apps/<modulo>` siguiendo `docs/reports/PROTOCOLO-AUDITORIA-SEGURIDAD.md`
> (las 3 fases) y guarda el reporte en `docs/reports/security-audit-<modulo>.md`."

El auditor recorre Fase 1 → 2 → 3, llena la plantilla, asigna severidades y da un veredicto. Si hay UI,
añade el checklist de `frontend-security-testing.md`.
