---
name: django-backend
description: Convenciones de código para proyectos Django y Django REST Framework — apps por dominio, capa de servicios y selectores, serializers por caso de uso, manejo de errores, paginación y tests con pytest. Úsala al implementar o revisar cualquier código de backend en este stack.
---

# Convenciones de backend

## Estructura

Apps por **dominio de negocio** (`inventory`, `billing`, `appointments`), nunca por capa técnica
(`api`, `models`, `utils`). Cuando un día quites la facturación, quieres borrar una carpeta, no
perseguir diez archivos.

```
inventory/
├── models.py       # estructura y propiedades derivadas. Sin lógica de negocio.
├── selectors.py    # lecturas: funciones que devuelven querysets o datos
├── services.py     # escrituras y reglas de negocio. Transacciones aquí.
├── serializers.py  # uno por caso de uso
├── views.py        # valida entrada, llama al service, devuelve respuesta
├── permissions.py
└── tests/
```

**La vista no decide.** Si tiene un `if` sobre una regla del negocio, ese `if` va en `services.py`.
El nombre formal del patrón es *service layer*; el beneficio concreto es que la misma regla sirve
para un endpoint, un comando de consola y una tarea programada sin duplicarse.

## Servicios

```python
@transaction.atomic
def transfer_stock(*, product: Product, from_branch: Branch,
                   to_branch: Branch, quantity: int, user: User) -> StockTransfer:
    if quantity <= 0:
        raise ValidationError("La cantidad debe ser mayor a cero.")
    # ... regla de negocio
```

- Argumentos con nombre obligatorio (`*`): en la llamada se lee qué es cada cosa.
- Tipado siempre. Con `mypy` o sin él, el tipo es documentación que no envejece.
- `@transaction.atomic` en toda operación que escriba en más de una tabla. Un traspaso de
  inventario que descuenta de una sucursal y falla al sumar en la otra deja mercancía inexistente.

## Serializers

Uno por caso de uso: `ProductListSerializer`, `ProductDetailSerializer`, `ProductCreateSerializer`.
Reutilizar el de escritura para lectura termina exponiendo campos internos el día que alguien
agrega uno.

Los campos calculados van en el serializer, no en el modelo. Validación de forma en el serializer;
validación de reglas de negocio en el service.

## Vistas y errores

- Respuesta de error consistente en toda la API. Define la forma en el contrato y respétala.
- `ValidationError` de Django o DRF, nunca `Exception` genérica.
- Nunca devuelvas el mensaje interno de una excepción al cliente.
- Paginación en todo listado. Sin ella, el listado que hoy tiene 30 filas mañana tiene 30,000 y
  tumba la pantalla.

## Tests con pytest

- Factories con `factory_boy`. Nada de fixtures JSON.
- Un test por camino feliz y al menos uno por caso borde y por permiso denegado.
- Nombres descriptivos en español: `def test_no_permite_traspaso_con_stock_insuficiente():`
- `django_assert_num_queries` en los listados, para que un N+1 futuro rompa el test.
- El test de aislamiento de tenant es obligatorio si el proyecto es multitenant.

## Revisión

| # | Punto |
|---|---|
| 1 | Apps organizadas por dominio, no por capa |
| 2 | Sin lógica de negocio en vistas ni en modelos |
| 3 | Operaciones multi-tabla dentro de `@transaction.atomic` |
| 4 | Un serializer por caso de uso |
| 5 | Todo listado paginado |
| 6 | Errores con forma consistente y sin detalles internos |
| 7 | Tests de camino feliz, caso borde y permiso denegado |
