# Resumen ejecutivo de `00-brechas.md`

> Producido al revisar los entregables de la fase A2 el **2026-08-12**, con dos auditorías
> independientes: una sobre `02-contrato.md` y otra sobre `00-brechas.md`, ambas verificando contra
> el código.
>
> **Para qué existe:** `00-brechas.md` tiene 167 hallazgos en 2,400 líneas y su escala de gravedad no
> es comparable entre bloques, porque cada subagente definió la suya. Este documento la corrige y
> agrupa. **Insumo directo para A3.**
>
> Lee esto antes de `00-brechas.md`. Si algo de aquí contradice al documento largo, gana esto.

---

## 1. Lo primero: la conclusión tranquilizadora del documento es falsa

`00-brechas.md` concluye que **no hay ninguna P0 de fuga de datos entre clínicas**. Eso es un
artefacto de clasificación: varios subagentes reservaron "P0" para una fuga *demostrada y
explotable*, así que las cuatro brechas que sí rompen la premisa de aislamiento quedaron archivadas
como P1.

| | Según `00-brechas.md` | Reclasificado |
|---|---:|---:|
| P0 | 4 | **10** |
| P1 | 48 | 41 |
| P2 | 115 | 62 |
| Ruido | — | 26 |
| Duplicados | — | 28 |

Las cuatro P0 que el documento declara (`B-REC-01`, `B-FIN-01`, `B-FIN-02`, `B-FIN-03`) son graves,
pero son integridad de dinero y de cumplimiento **dentro** de una clínica, no fuga entre clínicas.

**Lo bueno:** se verificaron 17 hallazgos contra el código, uno por uno, y **los 17 resultaron
ciertos con `archivo:línea` exacto. Cero invenciones.** El documento es fiable en los hechos; falla
en la priorización y en la agrupación.

## 2. Las 10 P0 reales

**Explotables hoy, sin condiciones:**

| ID | Qué es | Evidencia |
|---|---|---|
| `B-AUD-02` | Un rol de **ventas** lee la bitácora de **todas** las clínicas desde `/admin/`. La comprobación solo pregunta si es staff de plataforma y consulta con `all_objects`. La API sí lo excluye; el admin de Django no. | `audit/admin.py:90-98`, `:72` · `plataforma/services.py:1058` |
| `B-AUT-02` | Cualquiera con acceso a `/admin/` puede editar su propio `platform_role` e `is_superuser`. Las reglas anti-escalada viven solo en el portal. **El admin de Django no escribe en la bitácora**, así que no deja rastro. | `authn/admin.py:29-43` |
| `B-EXP-03` + `B-EXP-04` | Un `PUT` sin el campo `items` (que es opcional con default lista vacía) **cancela todas las citas** de una calendarización y **borra las sesiones físicamente**. Renombrar un tratamiento destruye 12 citas sin recuperación. | `expediente/serializers.py:1539-1541` · `services_calendarizacion.py:595-605`, `:331` |
| `B-REC-03` | El secreto que firma el QR de las recetas cae silenciosamente al `SECRET_KEY` de Django si la variable no está puesta, y `production.py` no la exige. Rotar el `SECRET_KEY` invalida de golpe **todos los QR ya impresos**. La firma cubre solo el id: sin caducidad, sin revocación. | `config/settings/base.py:540` · `recetas/verification.py:48`, `:66` |

**Estructurales — la premisa de aislamiento no se sostiene:**

| ID | Qué es | Evidencia |
|---|---|---|
| `B-T-02` | Las 95 políticas de RLS llevan `OR current_tenant_id() IS NULL`: **si nadie fijó la clínica activa, se ve todo.** Eso pasa en cada tarea de Celery, cada comando de consola y cada vista del portal interno. La segunda barrera está abierta por defecto, no cerrada. | `pacientes/migrations/0002_enable_rls.py:31` (×95) |
| `B-T-04` | Las tablas que deciden **quién pertenece a qué clínica** (`tenancy_memberships`, suscripciones, derechos) no tienen política RLS ninguna: heredan `BaseModel`, no `TenantAwareModel`. Un `TenantMembership.objects.filter(role="owner")` para un reporte devuelve los dueños y correos de todas las clínicas, y nada protesta. | `tenancy/models.py:78`, `:262`, `:325` |
| `B-PLA-01` | El portal interno hereda `permission_classes = [IsAuthenticated]`. Una vista nueva que alguien agregue sin declarar su permiso queda abierta a cualquier usuario autenticado de cualquier clínica. | `plataforma/views.py:132` |
| `B-AUD-03` | RLS es inerte si la conexión usa un rol con `SUPERUSER`/`BYPASSRLS`. El runbook para el rol sin privilegios existe (`docs/deploy-rol-app-nosuperuser.md`) pero **nunca se aplicó en Railway**. | `core/management/commands/check_db_role.py` |
| `B-PAC-02` | La foto del paciente en URL pública, sin firma y sin carpeta por clínica. El documento marca NO VERIFICADO el storage real: hay que confirmarlo en Cloudinary antes de descartarlo. | — |

**Corolario de las cuatro estructurales:** hoy el aislamiento entre clínicas depende de **una sola
barrera real** (el filtro de Django), no de dos. La segunda barrera funciona cuando el contexto está
fijado y se abre cuando no. Esto corrige lo que `01-analisis.md §6` afirma sobre la doble barrera y
lo que se escribió en `MEMORIA.md` el 2026-08-11.

## 3. Cinco causas raíz cierran ~40 hallazgos

El backlog parece ocho veces más grande de lo que es. Cinco arreglos cierran cerca de 40 entradas:

| # | Causa raíz | Cierra |
|---|---|---|
| 1 | El detalle-por-id no pasa por `sucursal_scope` aunque el listado sí | 12 hallazgos |
| 2 | `BaseModel` sin manager de borrado lógico y constraints sin `condition=Q(deleted_at__isnull=True)` | 8 |
| 3 | Identificadores con PII en bitácora y notificaciones | 7 |
| 4 | No existe ningún endpoint de reactivación, y el cupo del plan cuenta lo inactivo | 6 |
| 5 | FKs `CASCADE`/`PROTECT` incoherentes con el `SET_NULL` del modelo base | 5 |

Además: **28 de los 167 son duplicados** (el mismo bug hallado por dos subagentes; p. ej.
`B-T-05`≡`B-AGE-01`, `B-NOT-02`≡`B-NTF-01`) y **26 son ruido** — documentación vieja sin consecuencia
o código muerto.

## 4. P1 que muerden con un cliente real

Ordenadas por probabilidad de que pase esta semana:

1. **`B-FIN-02`** — doble clic en "Aceptar cotización" **duplica la deuda del paciente**. La guarda de
   idempotencia está *antes* del `atomic()` y sin `select_for_update`. Una cotización de $18,000
   genera $36,000. `finanzas/services.py:600` vs `:604`.
2. **`B-FIN-01` + `B-FIN-03`** — el mismo pago se puede **timbrar dos veces ante el SAT** (la relación
   es uno-a-muchos, no uno-a-uno, y nada comprueba un CFDI previo), y la llamada al PAC ocurre
   *dentro* de la transacción: si Postgres se cae después de timbrar, existe una factura ante el SAT
   que tu sistema no sabe que emitió. Hoy no muerde porque el PAC es simulado. **El día que lo
   conectes de verdad, muerde la primera semana.**
3. **`B-REC-01`** — una receta de un **controlado sale como receta común**: no hay ningún camino para
   marcar un medicamento como controlado (el catálogo se siembra sin el campo, el serializer lo
   rechaza). Sin folio de recetario especial, sin vigencia de 30 días, y la bitácora no distingue una
   benzodiacepina de un paracetamol. Los tests pasan porque llaman al servicio por dentro.
4. **`B-PER-08` + `B-PER-03`** — cambiar la contraseña de un empleado **no cierra su sesión**: la
   cookie de refresco vive 7 días. La recepcionista despedida sigue entrando una semana. Y al dar de
   alta a alguien nunca se le fuerza el cambio de contraseña inicial.
5. **`B-REC-13` + `B-PER-01`** — con dos sedes, la administradora de Norte **lee y anula las recetas
   de Centro** (el modelo de recetas no tiene campo `sucursal`) y puede hacer `PATCH`/`DELETE` sobre
   el médico de Centro (el detalle por id no filtra por sede).
6. **`B-NOT-01`** — una nota personal se puede convertir en aviso de "toda la clínica" con dos
   peticiones, saltándose el confinamiento por sede.
7. **`B-PAC-01`** — finanzas y solo-lectura paginan el **directorio completo** con CURP, domicilio,
   religión y tipo de sangre: el listado reutiliza el serializer del detalle.
8. **`B-AGE-05`** — la pantalla dice "Recordatorio · WhatsApp · Enviado" cuando no se envió nada, y
   recepción decide no llamar.
9. **`B-AGE-03`** — un médico puede cancelar citas ajenas por la vía de `/estado/`, que sí lo incluye
   aunque el `DELETE` no.

## 5. Correcciones al contrato `02-contrato.md`

El contrato **sirve como fuente de verdad, con reservas.** Lo bueno: 145 de 145 rutas documentadas
(cero huérfanas en ambos sentidos), las 15 apps cubiertas, 3,320 referencias `archivo:línea` con 13
de 18 verificaciones exactas al dígito. Hay que arreglar cinco cosas antes de construir sobre él:

1. **`405` debe ser `403`** en §1.3.2 #24 y §4.3.1 filas 2 y 9. Un método no declarado en la `policy`
   se rechaza en `check_permissions`, *antes* de resolver el handler. §1.3.1, §2.2 y §6.2 lo dicen
   bien; esas tres filas lo dicen mal. Un agente que lea §4 escribirá tests esperando 405 y fallarán.
   El origen es un docstring equivocado en `core/permissions.py:748-751` — corregirlo también.
2. **§1.5.5 contradice a §3.4.2** sobre la nota de agenda: el endpoint solo implementa `delete`, así
   que el riesgo es borrar, no leer. §3.4.2 es la correcta, y §1 —la sección que todas las demás
   citan— es la equivocada.
3. **Cuatro conteos falsos en preámbulos:** finanzas "nueve modelos" (son diez) y "19 rutas" (23);
   clínica "13 rutas" (17); plataforma "13 vistas" (15). Es el dato que un agente usa como checklist
   de completitud.
4. **La evidencia de la política RLS canónica está mal citada.** §1.1.1 presenta el patrón con
   `USING` + `WITH CHECK` citando `pacientes/migrations/0002_enable_rls.py:31`, que solo tiene
   `USING`. El `WITH CHECK` llegó en las migraciones `*_rls_with_check.py`. Quien copie el patrón
   desde esa cita creará una policy incompleta y el test guardián la rechazará.
5. **§8.5 y §9.4 son 95 líneas de matriz de permisos sin una sola cita.** Son las únicas tablas de
   decisión del documento que no se pueden falsar sin abrir el código.

## 6. Dos agujeros de método que A3 debe cubrir

`00-brechas.md` no revisó tres cosas, y ahí viven clases enteras de brecha que por definición no
podía encontrar:

1. **El frontend.** Siete menciones a `web-soft/` en 2,400 líneas, tres declaradas NO VERIFICADO.
   Toda la clase "el botón está visible y el backend responde 403" es invisible. Cierre barato: un
   pase que cruce cada `permission_classes` del backend contra el gating por rol de `web-soft/src`.
2. **`docs/design/`** — los 20 documentos de diseño vivos. Solo se comparó contra `01-analisis.md` y
   `_legacy/README.md`. Por eso la brecha de la bitácora quedó en P2: se creyó que el texto
   equivocado era un comentario, cuando `docs/design/audit-modelo-datos.md:93` y `:124` especifican
   owner+admin y son lo que un agente futuro tomará como contrato.
3. **Dependencias y configuración de despliegue.** Cero revisión de `pyproject.toml` (`xhtml2pdf`,
   `channels`, `channels-redis` declarados y sin importar) y ninguna revisión sistemática de qué
   variables `production.py` **omite** exigir. `B-REC-03` —una de las P0— se encontró por casualidad
   leyendo recetas, no por método.

## 7. Una brecha que el documento no reportó, y tuvo razón

Se sospechaba que el frontend mostraba al `admin` el botón de editar el catálogo de servicios, que
el backend responde con 403. **Refutado:** el frontend también lo gatea bien
(`MiConsultorioPage.tsx:85` con `editable={esOwner}`, `PaquetesPage.tsx:56`). Lo único desalineado es
un comentario obsoleto en `components/consultorio/SeccionServicios.tsx:7-8`. Queda anotado para que
no vuelva a levantarse como hallazgo.
