---
name: db-schema
description: Criterios de diseño de esquema en Django y PostgreSQL — modelado, tipos, relaciones y borrados, índices justificados, prevención de N+1, migraciones reversibles, borrado lógico y campos de auditoría. Úsala al diseñar el modelo de datos, al escribir migraciones y al revisar consultas.
---

# Diseño de esquema y consultas

## Modelado

- **Un modelo por concepto del negocio.** Si tienes que explicar un modelo con un "y también",
  probablemente son dos.
- Tipos correctos, no `CharField` para todo: `DecimalField` para dinero (**nunca `FloatField`**,
  0.1 + 0.2 no es 0.3 y eso en un POS es un descuadre de caja), `DateTimeField` con zona horaria,
  `BooleanField` no nulo con default.
- `null=True` solo cuando "no hay dato" es distinto de "está vacío". En texto, prefiere `""` a
  `NULL`: dos formas de decir "nada" es una fuente permanente de bugs.
- Todo modelo lleva `created_at` y `updated_at` (`auto_now_add` / `auto_now`). En datos sensibles,
  además `created_by`.
- **Unicidad en la base de datos, no solo en el formulario.** `unique_together` o
  `UniqueConstraint`. La validación en el serializer se salta con dos peticiones simultáneas; la
  restricción en la base, no.

## Relaciones y borrado

Elige `on_delete` con intención y escribe por qué:

- `PROTECT` — el default sensato en datos de negocio. Impide borrar un producto que ya se vendió.
- `CASCADE` — solo cuando el hijo no tiene sentido sin el padre (un renglón de una venta).
- `SET_NULL` — cuando la relación es informativa y puede perderse sin daño.

`CASCADE` por descuido es cómo se borra un histórico de ventas al eliminar un proveedor.

## Índices

**Un índice sin una consulta que lo necesite es peso muerto:** cada escritura lo actualiza.

Ponlos donde:
- Una FK que se filtra seguido (`tenant_id` siempre).
- Un campo por el que se busca o se ordena en un listado real.
- Un índice compuesto cuando la consulta filtra por dos campos juntos — el orden de las columnas
  importa: primero el de igualdad, después el de rango.

Ejemplo concreto: el listado de ventas del POS filtra por sucursal y rango de fechas. El índice es
`(branch_id, sold_at)`, en ese orden. Al revés sirve mucho menos.

## N+1

El problema: listar 50 ventas dispara 51 consultas — una por la lista y una por cada venta al tocar
sus productos. El usuario ve una pantalla lenta sin causa aparente.

- `select_related()` para ForeignKey y OneToOne (hace JOIN).
- `prefetch_related()` para relaciones inversas y ManyToMany (segunda consulta).
- Un `for` que dentro accede a `objeto.relacion.campo` es N+1 hasta que se demuestre lo contrario.

Verificación: cuenta consultas en el test (`django_assert_num_queries`). El número debe ser
constante aunque crezcan los datos.

## Migraciones

- **Reversibles.** Si una no lo es, dilo en el PR con letras grandes.
- Nunca renombrar y cambiar el tipo de una columna en la misma migración.
- Agregar una columna `NOT NULL` a una tabla con datos son tres pasos: agregar nullable, rellenar,
  volver obligatoria. Hacerlo en uno solo falla en producción y no en tu máquina, porque tu máquina
  no tiene datos.
- Migración de datos separada de la migración de estructura.
- Antes de correr una migración en producción: backup, y saber cómo volver atrás.

## Borrado lógico

En registros clínicos, ventas y facturas: `is_active` o `deleted_at`, nunca `DELETE`. Un borrado
físico es irreversible y en datos de salud puede ser inaceptable. Filtra los borrados en el manager
por defecto para que no se cuelen en los listados.

## Revisión

| # | Punto |
|---|---|
| 1 | Dinero en `DecimalField`, no `FloatField` |
| 2 | Cada `on_delete` es una decisión, no el default |
| 3 | Cada índice tiene una consulta real que lo justifica |
| 4 | Sin N+1 en listados; verificado contando consultas |
| 5 | Restricciones de unicidad en la base, no solo en el serializer |
| 6 | Migraciones reversibles, o advertencia explícita |
| 7 | `created_at` y `updated_at` en todos los modelos |
| 8 | Borrado lógico donde el dato no puede perderse |
