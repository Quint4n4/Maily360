---
name: django-clean-architecture
description: >
  Estándares y arquitectura limpia para escribir, revisar o testear código Python/Django/Django REST Framework
  en Maily Platform. Úsala SIEMPRE que se esté escribiendo, modificando, revisando o probando código Django/DRF:
  modelos, serializers, vistas, servicios, selectors, permisos, migraciones, tareas Celery o tests pytest.
  Hace cumplir: arquitectura por capas (thin views, service layer), tipado obligatorio con mypy,
  cero secretos hardcodeados, seguridad OWASP, multi-tenant y testing profesional.
---

# Django Clean Architecture — Estándares de Maily Platform

Eres un ingeniero senior de Python/Django/DRF. Aplica estas reglas SIN EXCEPCIÓN al escribir o revisar código.
Si el usuario pide algo que las viola, propón la alternativa correcta y explica por qué.

## Reglas innegociables (las 3 de oro)

1. **CERO secretos en el código o en git.** Nunca `SECRET_KEY`, contraseñas, tokens o API keys en archivos.
   Siempre `env("NOMBRE")` con `django-environ`. Si ves un secreto hardcodeado, es un bug crítico: detente y corrígelo.
   **Tampoco en los MENSAJES DE COMMIT** (ni credenciales de prueba): quedan permanentes en el historial de git. Si una credencial llega a git/commit, rótala de inmediato.
2. **NUNCA SQL armado con datos del usuario.** Siempre el ORM o queries parametrizadas. Cero f-strings/concatenación en SQL.
3. **NUNCA lógica de negocio en views o serializers.** La lógica vive en `services.py` (escrituras) y `selectors.py` (lecturas).

## Arquitectura por capas

```
URLs → Views (delgadas) → Serializers (validar/formatear) → Services/Selectors → Models → DB
```

| Capa | SÍ | NO |
|------|----|----|
| View/ViewSet | parsear request, llamar 1 servicio/selector, devolver Response | queries, reglas de negocio, cálculos |
| Serializer | validar entrada, dar forma a salida | guardar en BD, lógica de negocio, efectos secundarios |
| Service | casos de uso que escriben/modifican | tocar request HTTP, serializar |
| Selector | lecturas/queries complejas con filtros y permisos | modificar datos |
| Model | datos, `clean()`, propiedades simples, managers | casos de uso completos, llamadas externas |

### Patrón obligatorio de servicio

```python
def appointment_create(*, tenant: Clinic, user: User, patient_id: UUID, starts_at: datetime) -> Appointment:
    """Crea una cita validando disponibilidad. Lanza ValidationError si el horario está ocupado."""
    patient = patient_get(patient_id=patient_id)
    if _slot_taken(tenant=tenant, starts_at=starts_at):
        raise ValidationError("Ese horario ya está ocupado")
    appointment = Appointment.objects.create(
        tenant=tenant, patient=patient, starts_at=starts_at, created_by=user,
    )
    appointment_created.send(sender=Appointment, appointment=appointment)
    return appointment
```

- Servicios y selectors usan **argumentos keyword-only** (`*,`).
- Se nombran como acción + entidad: `appointment_create`, `patient_update`, `invoice_get`.

### Patrón obligatorio de API (DRF)

```python
class AppointmentCreateApi(APIView):
    permission_classes = [IsAuthenticated, HasAgendaAccess]

    class InputSerializer(serializers.Serializer):
        patient_id = serializers.UUIDField()
        starts_at = serializers.DateTimeField()

    class OutputSerializer(serializers.ModelSerializer):
        class Meta:
            model = Appointment
            fields = ["id", "patient_id", "starts_at", "status"]

    def post(self, request) -> Response:
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        appointment = appointment_create(tenant=request.tenant, user=request.user, **s.validated_data)
        return Response(self.OutputSerializer(appointment).data, status=status.HTTP_201_CREATED)
```

- **Serializers de entrada y salida separados.** Nunca uno solo para todo.
- Serializers NO tienen `create()`/`update()` con lógica. Eso va al servicio.

## Campos sensibles, inmutabilidad y CRUD seguro (LECCIONES REALES — no repetir)

Estos tres bugs aparecieron repetidamente en code review/security audit. Aplica las reglas SIEMPRE que escribas un modelo con CRUD.

### 1. Estado de activación NO se cambia por PATCH (la "puerta trasera del `is_active`")
`is_active` (y cualquier flag de estado: `status`, `is_verified`, `is_published`...) **NUNCA** se expone en el `InputSerializer` de un PATCH/update genérico. Cambiar estado tiene su propio endpoint/servicio explícito (`*_deactivate`, `*_reactivate`, `*_publish`).
- Quítalo del `InputSerializer` del PATCH.
- Inclúyelo en el `_IMMUTABLE_FIELDS` del servicio de update (junto con `id`, `tenant`, `tenant_id`, `created_at`, `updated_at`, `deleted_at`, y las FK de identidad como `membership`).
- Razón: si no, cualquier usuario reactiva/cambia estado de un registro saltándose la regla de negocio.

```python
# services.py
_IMMUTABLE_FIELDS: frozenset[str] = frozenset(
    {"id", "tenant", "tenant_id", "created_at", "updated_at", "deleted_at", "is_active"}
)
def x_update(*, obj: X, user: User, **fields: Any) -> X:
    bad = set(fields) & _IMMUTABLE_FIELDS
    if bad:
        raise ValidationError(f"No se pueden modificar los campos: {', '.join(sorted(bad))}.")
    ...
```

### 2. Toda lectura de un objeto por id pasa por un SELECTOR (nunca `Model.objects.get` en la view)
Un endpoint de detalle (`GET/PATCH/DELETE /x/<id>/`) que haga `X.objects.get(id=...)` **directo en la view** es un riesgo de IDOR. Crea siempre `x_get(*, x_id: UUID) -> X` en `selectors.py` y úsalo. El `TenantManager` filtra por tenant; un id de otro tenant → `DoesNotExist` → **404** (no 403, no revelar existencia). Sé consistente: TODOS los detail endpoints del módulo usan su selector.

### 3. FK que referencian otros objetos: validar que sean del MISMO tenant en el servicio
Cuando un servicio recibe un objeto/uuid relacionado (un `consultorio`, una `membership`, un `doctor`...), **valida explícitamente** `related.tenant_id == tenant.id` aunque la view ya lo haya resuelto por el manager. Es defensa en profundidad: el servicio puede llamarse desde Celery/commands/tests sin contexto de request.
```python
if consultorio is not None and consultorio.tenant_id != tenant.id:
    raise ValidationError("El recurso no pertenece a esta clínica.")
```

### Checklist al crear un modelo con CRUD
- [ ] `InputSerializer` de PATCH NO expone `is_active`/`status`/flags de estado ni campos de identidad.
- [ ] `_IMMUTABLE_FIELDS` en el servicio de update cubre id, tenant, timestamps, deleted_at, flags de estado y FK de identidad.
- [ ] Cada detail endpoint usa un selector `x_get`, nunca `Model.objects.get` inline en la view.
- [ ] Cada FK relacionada que entra a un servicio se valida `tenant_id == tenant.id`.
- [ ] Validación de formato de campos libres (CURP, teléfono, color hex, rangos de fecha) en el serializer.
- [ ] Unicidad por tenant con `UniqueConstraint(fields=["tenant", ...])`, no solo validación en código.
- [ ] `404` (no 403) para recursos de otro tenant.

## Tipado obligatorio

- **Type hints en TODA firma de función** (args + retorno). Locales solo si son ambiguos.
- `django-stubs` + plugin de mypy. mypy corre en CI; PR con errores de tipo NO se mergea.
- Prohibido `Any` por flojera. Si se necesita, justificar.
- Config mypy: `disallow_untyped_defs`, `disallow_any_generics`, `warn_return_any`, `warn_unused_ignores`.

```python
# ❌ def get_patient(id): ...
# ✅
def patient_get(*, patient_id: UUID) -> Patient:
    return Patient.objects.get(id=patient_id)
```

## Multi-tenant (Maily Platform)

- Todo modelo de negocio hereda de `TenantAwareModel` con `tenant_id` indexado.
- Las queries SIEMPRE filtran por tenant (manager por defecto). Verificar en selectors que no se filtren datos de otro tenant.
- Defensa en profundidad: Row Level Security en PostgreSQL además del filtro de Django.
- Identidad del paciente es GLOBAL (Master Patient Index); los datos clínicos son por tenant.

## Seguridad (OWASP, obligatorio)

- `DEBUG = False` en prod; `ALLOWED_HOSTS` explícito.
- HTTPS + HSTS; cookies `Secure` + `HttpOnly` + `SameSite`.
- Contraseñas con el password hasher de Django (Argon2/PBKDF2). NUNCA cifrado reversible.
- Permisos: `DEFAULT_PERMISSION_CLASSES = [IsAuthenticated]`. Devolver **404 (no 403)** cuando el recurso existe pero no pertenece al usuario.
- Validar toda entrada en el serializer antes de la lógica.
- `pip-audit` en CI para dependencias vulnerables.
- Bitácora de auditoría inmutable para accesos/cambios a expedientes (NOM-024).

## Performance

- `select_related` (FK) y `prefetch_related` (M2M/reverse) siempre que haya relaciones. Cero N+1.
- Paginación obligatoria en todo listado. Throttling configurado.

## Estructura de archivos por app

```
apps/<dominio>/
  models.py  selectors.py  services.py  serializers.py
  views.py  urls.py  permissions.py  signals.py  tasks.py
  tests/{test_services.py, test_selectors.py, test_apis.py}
  migrations/
```

## Testing (pytest + pytest-django + factory_boy)

- "Probado o no existe." Todo servicio y selector tiene pruebas.
- Patrón AAA (Arrange-Act-Assert). `factory_boy` para datos.
- Cobertura ≥ 80% en código de negocio; medida en CI.
- Probar: camino feliz, errores, reglas de negocio, y que el filtrado por tenant no fuga datos.

```python
def test_appointment_create_rejects_double_booking(db):
    clinic = ClinicFactory()
    AppointmentFactory(tenant=clinic, starts_at="2026-06-01T10:00Z")
    with pytest.raises(ValidationError):
        appointment_create(tenant=clinic, user=UserFactory(),
                            patient_id=PatientFactory().id, starts_at="2026-06-01T10:00Z")
```

## Herramientas y formato

- **Black** (formato) + **Ruff** (lint) + **isort** (imports). Corren en pre-commit y CI.
- **Conventional Commits**: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`.
- Migraciones reversibles; nunca editar una ya aplicada en producción.

## Definition of Done (verifica antes de aprobar)

- [ ] Lógica en services/selectors, no en views/serializers
- [ ] Type hints completos; mypy verde
- [ ] Black + Ruff verdes; sin código muerto
- [ ] Cero secretos hardcodeados
- [ ] Serializers entrada/salida separados y delgados
- [ ] Queries sin N+1; filtrado por tenant verificado
- [ ] Tests para los casos nuevos; cobertura ≥ 80% en negocio
- [ ] Migraciones reversibles
- [ ] Checklist OWASP relevante cumplido
- [ ] CI 100% verde

Referencias: OWASP Django/DRF Cheat Sheets · HackSoft Django Styleguide · django-stubs/mypy.
