---
name: multitenancy
description: Reglas de aislamiento de datos entre tenants en Django, con el patrón de manager filtrado por defecto, middleware de contexto y los tests de fuga obligatorios. Úsala en cualquier proyecto donde varios clientes comparten la misma base de datos, al diseñar el modelo, al implementar endpoints y al revisar código.
---

# Aislamiento entre tenants

**Por qué existe esta skill:** una sola consulta sin filtro expone los datos de una clínica a otra.
No es un bug de interfaz, es una fuga de datos sensibles con consecuencias legales y con el
potencial de terminar el negocio. Es el riesgo más grave del proyecto.

## Principio

> El aislamiento no puede depender de que el programador se acuerde de filtrar.

Cualquier diseño cuya seguridad se apoye en la disciplina humana falla el día que alguien tiene
prisa. El mecanismo debe hacer que *olvidar* el filtro sea imposible o que rompa ruidosamente.

## Patrón obligatorio

**1. Contexto de tenant por request.** Un middleware resuelve el tenant (subdominio, cabecera o
claim del token) y lo deja en un contextvar. Si no puede resolverlo, la petición se rechaza —
nunca "sigue sin tenant".

**2. Manager filtrado por defecto.** El manager por defecto del modelo (`objects`) ya trae el
filtro puesto:

```python
class TenantManager(models.Manager):
    def get_queryset(self):
        tenant = get_current_tenant()
        if tenant is None:
            raise TenantNotSet("Acceso a datos de tenant sin contexto establecido")
        return super().get_queryset().filter(tenant_id=tenant.id)


class Patient(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, db_index=True)
    # ...
    objects = TenantManager()          # filtrado, el que se usa siempre
    all_tenants = models.Manager()     # sin filtro, solo para migraciones y tareas de admin
```

Con esto, `Patient.objects.all()` ya está acotado al tenant actual. El olvido deja de ser posible
en el camino normal.

**3. `all_tenants` es la excepción vigilada.** Solo en migraciones, comandos de administración y
tareas programadas. Cada uso lleva un comentario explicando por qué. En revisión, todo `all_tenants`
fuera de esos lugares es BLOQUEA.

**4. El tenant nunca viene del cliente.** Ni del body, ni de un query param, ni de un campo del
formulario. Si el usuario puede escribir el `tenant_id`, puede escribir el de otro.

**5. `on_delete=PROTECT` en la FK al tenant.** Borrar un tenant no debe arrastrar datos en cascada
por accidente.

## Reglas de revisión

| # | Punto |
|---|---|
| 1 | Todo modelo con datos de cliente tiene FK a tenant, indexada |
| 2 | Todo modelo con tenant usa `TenantManager` como `objects` |
| 3 | Ningún uso de `all_tenants` fuera de migraciones, comandos o tareas, y cada uno comentado |
| 4 | El `tenant_id` no se acepta jamás desde entrada del usuario |
| 5 | El middleware rechaza la petición si no puede resolver el tenant |
| 6 | Las consultas crudas (`raw`, `extra`, `cursor.execute`) filtran por tenant explícitamente |
| 7 | Los archivos subidos se guardan en una ruta que incluye el tenant |
| 8 | Existe el test de fuga y está pasando |

## Test de fuga (obligatorio, no negociable)

Sin este test, el módulo no pasa revisión:

```python
def test_no_puede_leer_datos_de_otro_tenant(api_client, tenant_a, tenant_b):
    paciente_b = PatientFactory(tenant=tenant_b)
    api_client.force_authenticate(UserFactory(tenant=tenant_a))

    respuesta = api_client.get(f"/api/patients/{paciente_b.id}/")

    assert respuesta.status_code == 404  # 404, no 403
```

**Por qué 404 y no 403:** un 403 confirma que ese registro existe. Es una fuga pequeña, pero real:
permite a un competidor descubrir qué IDs existen en otra clínica. El recurso simplemente no existe
para quien no es su dueño.

Escribe una variante de este test por cada endpoint que devuelva datos de tenant. Es repetitivo y
por eso vale la pena parametrizarlo — pero no lo omitas.
