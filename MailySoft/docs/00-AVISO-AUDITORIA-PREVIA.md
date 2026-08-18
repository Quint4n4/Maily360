# Aviso: cómo leer la auditoría previa a la biblioteca

> Escrito el **2026-08-18**, el día que este repo pasó a usar el plugin `biblioteca-de-skills`.
> **Léeme antes de confiar en cualquier `PASA` de un documento anterior a esta fecha.**

## Lo que sigue valiendo

Todo hallazgo con `archivo:línea`. Un `BLOQUEA` encontró algo real y lo citó: el bug sigue en el
código, y cambiar de herramienta no lo arregla. Los documentos de contrato, brechas, deuda y
análisis son **descripciones verificadas de este sistema** y se conservan enteros.

Cambió el proceso de revisar. **No cambió la verdad sobre el código.**

## Lo que NO vale, y hay que rehacer

**Todos los `PASA` emitidos antes del 2026-08-18.**

Las skills locales que los produjeron tenían un defecto de forma: admitían puntos que se contestan
**abriendo un archivo y mirando un valor**. Un punto así siempre gana al punto difícil que exige
provocar el efecto, y siempre responde que todo está bien.

El caso documentado: una skill mandaba comprobar que `BLACKLIST_AFTER_ROTATION` estuviera en `True`.
Lo estaba. Y no servía de nada, porque `token_blacklist` no estaba en `INSTALLED_APPS`. **Ese `PASA`
tapó el P0 más grave del proyecto.** Dos renglones antes, la misma skill pedía cerrar sesión y
reintentar con el refresh viejo — el punto correcto. Según cuál leyera el auditor, salía `PASA` o
`BLOQUEA`.

Por eso, y por la regla de la biblioteca *la ausencia de evidencia nunca es `PASA`*:

> **Un `PASA` anterior a esta fecha se trata como `NO VERIFICADO`, no como aprobado.**
> No significa que esté mal. Significa que nadie lo comprobó provocando el efecto.

## Antes de volver a revisar

`.claude/PERFIL-DEL-REPO.md` tiene que estar completo. Una clave vacía no hace que la skill revise
mal: hace que **no revise** — cada punto que depende de ella sale `NO VERIFICABLE`.

## Lo que este repo aportó a la biblioteca

Tres de sus skills locales —`frontend-audit`, `react-frontend-connect` y
`django-clean-architecture`— eran el mejor material del conjunto y **nunca subieron a ninguna
plantilla**: nacieron aquí y aquí se quedaron, mejorando en privado mientras los demás proyectos
escribían su propia versión peor.

Su contenido ya está en el plugin (`auditoria-frontend`, `react-frontend`, `django-backend`),
verificado concepto por concepto antes de archivarlas el 2026-08-18.

**Que no vuelva a pasar:** un punto nuevo se escribe en el plugin y se publica en el mismo
movimiento. No en `.claude/skills/` de este repo.

## Lo que este repo tiene bien y conviene no romper

El aislamiento entre clínicas **está verificado**: RLS en todas las tablas, test guardián en CI, y
el rol de conexión sin SUPERUSER ni BYPASSRLS confirmado en producción el 2026-08-13. Es el patrón
de referencia de todo el portafolio.

⚠ **Consecuencia de secuencia, anotada porque es cara:** los workers de Celery nunca fijan el tenant
y funcionan gracias al fallback `OR current_tenant_id() IS NULL` de las políticas de RLS. **Cerrar
ese fallback antes de arreglar los workers tumba todos los PDFs asíncronos el mismo día.**
