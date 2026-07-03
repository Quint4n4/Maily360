# Tipos de la API desde OpenAPI (drf-spectacular → openapi-typescript)

El frontend deriva sus tipos de **salida** de la API del esquema OpenAPI que
genera el backend con `drf-spectacular`, en lugar de mantenerlos a mano.

## Archivos

- `schema.yml` — esquema OpenAPI versionado (generado desde el backend).
- `../src/types/openapi.d.ts` — tipos TypeScript generados a partir de `schema.yml`
  (NO editar a mano; se regenera).
- `../src/types/plataforma.ts` — tipos del portal de plataforma que **derivan**
  de `components['schemas'][…]` del archivo generado (Fase 5). Ver los comentarios
  ahí para qué se deriva y qué se mantiene a mano.

## Cómo regenerar (2 pasos)

Cuando cambie un serializer del backend:

### 1) Backend: generar el esquema

Dentro de Docker (el schema endpoint solo se expone con `DEBUG=True`; también
está en `/api/schema/`):

```bash
docker compose exec -T backend python manage.py spectacular \
  --file /tmp/schema.yml
docker compose exec -T backend cat /tmp/schema.yml > web-soft/openapi/schema.yml
```

> `--validate` es opcional; hoy hay endpoints (APIViews planas sin serializer,
> p. ej. varias vistas de `recetas`) que emiten warnings/errores de "unable to
> guess serializer". No bloquean la generación. Las vistas de **plataforma** ya
> están anotadas con `@extend_schema(...)`, así que sus componentes SÍ salen con
> nombres estables (`ClinicaOutput`, `PlanOutput`, `SystemHealthOutput`, …).

### 2) Frontend: generar los tipos TS

```bash
cd web-soft
npm run types:api    # openapi-typescript ./openapi/schema.yml -o ./src/types/openapi.d.ts
```

Luego `npx tsc -b`: si un cambio del backend rompe un tipo derivado, el
frontend deja de compilar (esa es la señal de que hay que reconciliar).

## Adopción (estado)

- **Adoptado:** capa de API del portal de plataforma
  (`src/types/plataforma.ts`, salidas). Los outputs derivan del esquema; algunos
  campos-enum se estrechan del `string` genérico del backend al enum de UX
  (documentado en cada tipo).
- **A mano todavía:** el resto de dominios (`src/types/api.ts`) y los tipos de
  **entrada** (formularios) de plataforma — el esquema los expone como
  `…Request` con opcionalidad por default que no conviene arrastrar al form.
  Migrarlos es trabajo futuro, endpoint por endpoint.
