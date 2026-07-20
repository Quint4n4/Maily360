# Guía de pruebas — Multisucursal (todo lo que toca)

> Para el dueño. Local (`:5173`), NADA en producción. Marca ✅/❌ y anota lo que falle.
> Actualizada 2026-07-16 con TODO lo construido en la iniciativa.

## La idea de fondo (esto explica casi todo)
Dos tipos de cosas, y se prueban por separado:
- **COMPARTIDO entre sedes** → el paciente y su dinero: expediente completo, estado de cuenta,
  recetas, catálogos (servicios/paquetes/plantillas). Se ve desde cualquier sede, a propósito.
- **PRIVADO por sede** → la operación de cada sucursal: agenda, personal/equipo, consultorios,
  horarios, caja/reportes, avisos de sucursal.

**Un error es:** algo compartido que NO se ve, o algo privado que SÍ se ve/toca desde otra sede.

## Preparación (una vez)
1. Crea **2 sucursales** (ej. Acapulco y Norte), con datos en ambas.
2. Crea un **admin asignado solo a una sede** (el protagonista de las pruebas de seguridad).
3. Usa **dos sesiones**: tú (Dueño) y el admin en **ventana de incógnito**.

---

## 1. Selector de sucursal (barra de arriba)
- [ ] Aparece el selector con las sedes + "Todas las sedes".
- [ ] Cambias de sede y **recargas (F5)** → se queda en la que elegiste.

## 2. COMPARTIDO — igual desde cualquier sede
Párate en una sede, míralo; cambia a la otra, míralo. Debe verse **lo mismo**:
- [ ] Un **paciente** creado en una sede aparece en la otra.
- [ ] Su **expediente / libro clínico** se ve completo e idéntico.
- [ ] Su **estado de cuenta** muestra cargos y pagos de **ambas sedes juntos** (a propósito).
- [ ] **Recetas** se ven/descargan desde cualquier sede.
- [ ] **Catálogos** (servicios, paquetes, plantillas) — iguales en todas.

## 3. PRIVADO — cada sede ve solo lo suyo
- [ ] **Agenda**: las citas de una sede NO aparecen en la otra.
- [ ] **Consultorios / Personal / Horarios**: solo los de la sede activa.
- [ ] **Finanzas** (dashboard, cierre de caja, reporte de periodo): solo cifras de la sede activa.
- [ ] En **"Todas las sedes"** (como dueño): cifras **consolidadas**.

## 4. Disponibilidad del médico = GLOBAL
- [ ] Agenda al Dr. X en una sede mañana 10:00; intenta agendarlo en OTRA sede a la misma hora →
  **debe salir ocupado** (una persona no se clona, aunque las agendas sean privadas).

## 5. El "admin de sucursal" — LO MÁS IMPORTANTE (aquí estaban las fugas)
Entra como el **admin de una sede**. Todo esto lo blindamos:

### 5.a — Lo que NO debe poder (falla o dice "no encontrado")
- [ ] Ver el selector con OTRA sede (solo debe ver la suya).
- [ ] Finanzas: dashboard/cierre/reportes de otra sede.
- [ ] Abrir/anular un **cargo**, ver un **pago**, bajar el **PDF de una cotización**, ver/cancelar
  una **factura (CFDI)** de OTRA sede (aunque el id salga del estado de cuenta compartido).
- [ ] **Reagendar** una cita de otra sede, o **mover** una cita a otra sede.
- [ ] **Auto-ascenderse a Dueño**, o **crear** un Dueño/Administrador.
- [ ] **Restablecer la contraseña del Dueño** (o de otro admin).
- [ ] Ver, en el **Equipo**, a los **Dueños** o a **otros administradores** (solo ve equipo operativo de su sede).
- [ ] Asignar a un médico un **consultorio o una sede** de otra sucursal.
- [ ] **Editar/dar de alta/borrar sucursales**.

### 5.b — Lo que SÍ debe poder (no lo apretamos de más)
- [ ] Dentro de SU sede: cobrar, cotizar, agendar/reagendar, gestionar consultorios/horarios.
- [ ] Gestionar a **su equipo operativo** (médicos/enfermería/recepción): cambiar rol operativo,
  resetear su contraseña. Y dar de alta equipo operativo (cae en SU sede).

## 6. Equipo / personal por sede (jerarquía de roles)
- [ ] Como **admin**: en Personal → Equipo, cambia de sede → la lista cambia; ya NO aparece el
  grupo "Dueño"; al dar de alta, el selector de rol solo ofrece equipo operativo (no admin/dueño).
- [ ] Como **dueño**: ves y gestionas a TODOS; en "Todas las sedes" ves al equipo completo.

## 7. Avisos (Notas) por sede
- [ ] Como **admin**: creas un aviso → queda solo para **tu sucursal** (en otra sede no aparece).
  El formulario te dice "solo para tu sucursal". No puedes marcar "importante".
- [ ] Como **dueño**: al crear un aviso eliges la **sede** (una o "todas") y puedes marcarlo
  **Importante** (se ve con borde rojo y etiqueta).
- [ ] Cada aviso muestra a **qué sede** va.
- [ ] **Campana**: un aviso de sucursal le suena solo al personal de esa sede — al **dueño NO le
  suena** (lo ve en la lista si entra a Notas). Un aviso "Todas las sedes" sí le suena a todos.
- [ ] Tus **notas personales** siguen privadas (solo tú).

## 8. Servicios y precios / Paquetes por sede
- [ ] Como **dueño**: al crear un servicio/paquete marcas con **casillas** en qué sedes está
  (o "Todas"). Cada uno muestra un **badge** de sus sedes. El precio es el mismo en todas.
- [ ] **Cotizando o calendarizando** en una sede → solo aparecen los servicios/paquetes de esa
  sede (o los de "Todas"). En otra sede, otros.
- [ ] Como **admin**: puedes ver el catálogo (para cobrar/cotizar) pero NO editarlo.

## 9. Menú del admin (Mi Consultorio) — limpio
- [ ] Como **admin**: en Mi Consultorio ya NO aparecen "Sucursales", "Servicios y precios" ni
  "Mi perfil médico".
- [ ] Como **dueño**: las tres siguen ahí. Un **médico** sí ve "Mi perfil médico".

## 10. Bitácora (historial de acciones)
- [ ] Como **admin**: ya no puede ver la bitácora (403 / no aparece).
- [ ] Como **dueño**: la ve completa.

## 11. Casos borde
- [ ] Como **dueño**: siempre ves todo, sin restricción.
- [ ] **Desactiva** una sede y vuelve a entrar como admin de otra → NO debe empezar a ver la caja
  histórica de la sede desactivada.
- [ ] Clínica de **una sola sede** → todo funciona igual que antes.

---

## Cómo reportarme un fallo
Dime: **(1)** con qué usuario estabas (dueño / admin de qué sede), **(2)** en qué sede estaba el
selector, **(3)** qué intentaste, **(4)** qué esperabas, **(5)** qué pasó. Si sale un error en
pantalla, pásame el texto tal cual (y si es un 500, casi seguro es una migración — me avisas).

## Nota
La UI **no** es la autoridad de permisos: el backend sí. Por eso las pruebas del bloque 5 valen
más que lo que veas escondido en pantalla. Estado del código: TODO local, sin push; suite backend
3236 tests en verde. Pendiente aparte (feature nueva, no bloquea): el aviso de **mantenimiento de
Maily a todas las clínicas** (portal de plataforma).
