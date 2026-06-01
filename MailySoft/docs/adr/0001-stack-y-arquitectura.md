# ADR-0001: Stack tecnologico y arquitectura de Maily Soft

| Campo | Valor |
|---|---|
| Estado | **Aceptada** |
| Fecha | 2026-06-01 |
| Autores | Equipo de arquitectura Maily |
| Revisado por | — |

---

## Contexto

Maily Soft es una nueva plataforma SaaS de gestion clinica que debe servir a multiples clinicas (tenants) de forma aislada. Los requisitos que guian la decision de arquitectura son:

1. **Multi-tenancy con aislamiento fuerte**: los datos de una clinica no pueden ser visibles para otra bajo ningun escenario (incluyendo bugs de codigo).
2. **Identidad global del paciente**: un mismo paciente puede ser atendido por multiples clinicas; su identidad es unica en la plataforma (Master Patient Index), pero sus expedientes son propiedad del tenant.
3. **Extensibilidad por especialidad**: la plataforma debe soportar flujos muy distintos (odontologia, nutricion, psicologia, medicina general) sin convertirse en un monolito inmanejable.
4. **Cumplimiento NOM-024-SSA3**: bitacora de auditoria inmutable para accesos y modificaciones a expedientes clinicos.
5. **Velocidad de iteracion inicial**: el equipo es pequeno, se necesita mover rapido sin sacrificar calidad.
6. **Operacion economica**: infraestructura que escale desde cero sin costos fijos prohibitivos.

---

## Decision

### Backend: Django 5 + Django REST Framework + PostgreSQL

**Por que Django sobre FastAPI / Node / Rails:**
- ORM maduro con soporte real para multi-tenant (Row Level Security via postgresql).
- Ecosistema de librerias probadas en produccion (SimpleJWT, Celery, Channels, django-storages).
- django-stubs + mypy da seguridad de tipos sin el overhead de un lenguaje compilado.
- Admin de Django es util en etapas iniciales para operaciones internas.
- El equipo tiene experiencia previa con Django.

**Por que PostgreSQL sobre MySQL / MongoDB:**
- Row Level Security (RLS) nativo: segunda capa de aislamiento de tenant independiente del codigo.
- JSONB para datos clinicos semi-estructurados sin sacrificar integridad relacional.
- Soporte excelente con psycopg3.

### Arquitectura: Monolito modular con capas explicitas

```
URLs -> Views (thin) -> Serializers (validate/format) -> Services/Selectors -> Models -> DB
```

**Por que monolito modular sobre microservicios:**
- El equipo inicial no tiene capacidad operativa para mantener N servicios independientes.
- Los dominios clinicos (agenda, expediente, facturacion) estan fuertemente acoplados; separarlos prematuramente crea distributed-monolith.
- Un monolito bien modularizado puede extraer servicios en el futuro si el volumen lo requiere.
- Tiempo de desarrollo significativamente menor.

**Capas obligatorias:**
- `services.py`: toda logica de escritura. Keyword-only args. Nombrado accion+entidad.
- `selectors.py`: toda logica de lectura. Sin efectos secundarios.
- `views.py`: parsear request, llamar 1 servicio/selector, devolver Response. Sin logica.
- `serializers.py`: validar entrada y formar salida. Sin `create()`/`update()` con logica.

### Multi-tenancy: shared database, row-level isolation

**Modelo elegido:** base de datos compartida, esquema compartido, filtrado por `tenant_id` en cada tabla + RLS en PostgreSQL.

**Por que no base de datos por tenant:**
- Complejidad operativa prohibitiva para un equipo pequeno.
- Migrations para N tenants se vuelven inmanejables.
- El costo de N instancias de DB es alto en las etapas iniciales.

**Mecanismo de aislamiento (defensa en profundidad):**
1. `TenantAwareModel`: modelo abstracto con `tenant` FK. Manager por defecto filtra por tenant.
2. Selectors verifican explicitamente que el recurso pertenece al tenant del request.
3. RLS de PostgreSQL como ultima linea de defensa (se configura en el Paso 2).
4. Tests que verifican que no hay fuga de datos entre tenants.

### Especialidades como modulos de dominio

Cada especialidad es un modulo dentro de `apps/`:

```
apps/
  core/           # TenantAwareModel, User, Tenant, permisos base
  agenda/         # Citas y disponibilidad (generica)
  expediente/     # Expediente clinico base
  odontologia/    # Extension de expediente para odontologia
  facturacion/    # CFDI 4.0, pagos
  mensajeria/     # WhatsApp, notificaciones
```

Los modulos de especialidad extienden el expediente base sin modificarlo. Esto permite activar/desactivar especialidades por tenant como "plugins".

### Frontend: React (por definir framework exacto)

La decision entre Next.js vs Vite + React Router se pospone hasta que el backend API este estable. Los placeholders `web-soft/` y `web-platform/` reservan el espacio en el monorepo.

### Tareas asincronas: Celery + Redis

- Envio de notificaciones (WhatsApp, email, SMS)
- Generacion de PDFs (recetas, CFDI)
- Sincronizacion con sistemas externos
- Tareas de limpieza y mantenimiento

### WebSockets: Django Channels + Redis

Para notificaciones en tiempo real (turno listo, resultado de laboratorio) sin polling.

---

## Alternativas consideradas y descartadas

| Alternativa | Razon de descarte |
|---|---|
| FastAPI | Sin admin, sin ORM maduro, ecosistema menos robusto para clinica |
| NestJS (Node) | Curva de aprendizaje del equipo, menos librerias para dominio medico |
| Microservicios desde el inicio | Complejidad operativa prematura, equipo pequeno |
| MongoDB | Sin RLS nativo, integridad referencial debil para datos clinicos |
| MySQL | Sin RLS nativo, JSON menos maduro que PostgreSQL JSONB |
| Base de datos por tenant | Inmanejable operativamente a escala, costo prohibitivo |

---

## Consecuencias

**Positivas:**
- Stack conocido por el equipo = velocidad de entrega alta.
- Arquitectura por capas = codigo mantenible y testeable.
- Multi-tenant con RLS = aislamiento fuerte desde el dia 1.
- Monolito modular = facil de entender, facil de descomponer en el futuro.

**Riesgos y mitigaciones:**
- **Riesgo:** El monolito crece sin control → **Mitigacion:** Revisiones de arquitectura periodicas; modulos con interfaces explicitas.
- **Riesgo:** RLS mal configurado crea falsa sensacion de seguridad → **Mitigacion:** Tests de penetracion de tenancy en cada release.
- **Riesgo:** Celery se convierte en caja negra → **Mitigacion:** Flower para monitoreo; alertas en Sentry.

---

## Referencias

- [HackSoft Django Styleguide](https://github.com/HackSoftware/Django-Styleguide)
- [OWASP Django Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Django_Security_Cheat_Sheet.html)
- [PostgreSQL Row Level Security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
- [NOM-024-SSA3-2010](http://www.dof.gob.mx/normasOficiales/4300/salud6a/salud6a.htm)
