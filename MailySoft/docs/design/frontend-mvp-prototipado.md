# Frontend MVP — Guía de prototipado (Maily Soft)

> Documento de trabajo para prototipar el frontend de la **app de clínica** (`web-soft/`)
> a partir del backend real. Cada sección trae un **prompt listo para copiar y pegar**
> en Claude (artifacts / diseño). El objetivo es un MVP visual para mostrar al cliente
> y validar aceptación.
>
> **Enfoque del MVP:** la app que ve la clínica (recepción, doctores, admin). El panel
> interno de Maily (`web-platform/`, gestión de tenants) queda para una fase posterior.

---

## 🎨 Sistema de diseño — "Oro & Blanco"

Tema premium, elegante, sensación de salud + lujo. Mucho espacio en blanco, dorado
brillante como acento, nunca recargado.

### Paleta

| Uso | Color | Hex |
|---|---|---|
| Oro principal (botones, acentos) | Oro metálico | `#D4AF37` |
| Oro oscuro (hover, bordes) | Oro profundo | `#C9A227` |
| Degradado dorado (botones premium, encabezados) | `linear-gradient(135deg, #BF953F, #FCF6BA, #B38728, #FBF5B7, #AA771C)` | |
| Fondo principal | Blanco | `#FFFFFF` |
| Fondo de página | Blanco cálido | `#FAFAF8` |
| Fondo tinte oro suave (tarjetas activas) | Crema | `#FDF9EE` |
| Texto principal | Negro cálido | `#1C1B1A` |
| Texto secundario | Gris cálido | `#7A756C` |
| Bordes / divisores | Beige claro | `#ECE8DD` |
| Éxito (confirmada / atendida) | Verde | `#2E7D5B` |
| Advertencia (pendiente) | Oro | `#C9A227` |
| Peligro (cancelada / no asistió) | Rojo apagado | `#B23A48` |
| Info | Azul | `#3A6EA5` |

### Tipografía
- **Títulos:** serif elegante — `Playfair Display` o `Fraunces` (da el aire premium/lujo).
- **Cuerpo y datos:** sans limpia — `Inter`.

### Estilo de componentes
- Esquinas redondeadas (12–16 px), sombras muy suaves.
- Botón primario: degradado dorado, texto oscuro o blanco, leve brillo al hover.
- Botón secundario: blanco con borde dorado fino.
- Tarjetas blancas sobre fondo crema, con un acento dorado (línea superior o ícono).
- Navegación lateral (sidebar) blanca con ítem activo resaltado en dorado.
- Íconos lineales finos.
- Etiquetas de estado (chips) con color semántico + texto.

### Prompt BASE de estilo (pégalo al inicio de cada sesión de diseño)

```
Diseña una interfaz web para "Maily Soft", un sistema de gestión clínica premium.
Estilo: elegante, limpio, sensación de salud + lujo. Mucho espacio en blanco.
Paleta: fondo blanco (#FFFFFF) y crema (#FAFAF8), acentos en oro brillante (#D4AF37)
con degradado dorado para botones principales y encabezados, texto negro cálido
(#1C1B1A) y gris (#7A756C). Estados: verde #2E7D5B (éxito), oro #C9A227 (pendiente),
rojo apagado #B23A48 (cancelado). Títulos con tipografía serif elegante (Playfair
Display), cuerpo con Inter. Esquinas redondeadas, sombras suaves, botones con
degradado dorado, sidebar blanco con ítem activo en dorado, chips de estado de color.
La app está en español (México).
```

---

## 🗺️ Orden de pantallas (prioridad MVP)

Prototipa en este orden — cada una se apoya en la anterior:

- [ ] 0. Sistema de diseño / componentes base
- [x] 1. Login (hecho — pendiente quitar Google/Crear cuenta, botón "Entrar", título serif)
- [x] 2. Dashboard (inicio) — hecho. Nota integración: las 4 métricas requieren endpoint de agregación.
- [x] 3. Agenda — calendario semanal estilo BARBERS + popover de detalle (pendiente captura)
- [x] 4. Crear / editar cita — panel lateral con anti-empalme (pendiente captura)
- [x] 5. Detalle de cita — línea de estados + recordatorios WhatsApp (pendiente captura)
- [x] 6. Pacientes — lista + búsqueda (pendiente captura)
- [ ] 7. Crear / editar paciente
- [ ] 8. Detalle de paciente (expediente)
- [ ] 9. Personal — doctores + horarios
- [ ] 10. Consultorios
- [ ] 11. Configuración de agenda

---

## 1. Login

**Backend:** `POST /api/v1/auth/login/` → email + password → devuelve tokens JWT.

```
[Pega el prompt BASE de estilo primero]

Diseña la pantalla de LOGIN de Maily Soft.
Layout de dos columnas: a la izquierda un panel con degradado dorado suave, el logo
"Maily Soft" y una frase corta ("Gestión clínica, simple y elegante"); a la derecha,
sobre fondo blanco, el formulario centrado:
- Título "Inicia sesión"
- Campo Email
- Campo Contraseña (con ícono de ojo para mostrar/ocultar)
- Enlace "¿Olvidaste tu contraseña?"
- Botón primario "Entrar" con degradado dorado, ancho completo
- Texto pequeño de pie: "© Maily Soft"
Incluye el estado de error (credenciales inválidas) en rojo apagado bajo el formulario.
```

---

## 2. Dashboard (inicio)

Vista compuesta (resume datos de agenda y pacientes). Es lo primero que ve el usuario
al entrar.

```
[Pega el prompt BASE de estilo primero]

Diseña el DASHBOARD de inicio de Maily Soft.
Estructura general de toda la app (reutilízala en las demás pantallas):
- Sidebar izquierdo blanco con logo arriba y navegación: Inicio, Agenda, Pacientes,
  Personal, Consultorios, Configuración. Ítem activo resaltado en dorado.
- Barra superior con buscador, nombre de la clínica, campana de notificaciones y avatar
  del usuario con su rol.
Contenido del dashboard:
- Saludo "Buenos días, Dra. [Nombre]".
- 4 tarjetas-métrica arriba (con acento dorado): "Citas de hoy", "Confirmadas",
  "Pacientes nuevos esta semana", "Pendientes por confirmar".
- Sección "Próximas citas de hoy": lista con hora, nombre del paciente, doctor,
  consultorio y un chip de estado (confirmada=verde, pendiente=oro, cancelada=rojo).
- Botón primario dorado "Agendar cita".
La app está en español (México).
```

---

## 3. Agenda — calendario + lista de citas

> **Referencia visual elegida por el usuario:** estilo app "BARBERS" — calendario
> semanal con columnas por día, horas a la izquierda, citas como bloques de color, y un
> popover de detalle al hacer clic (con botón "Confirmar"). Adaptado al tema oro/blanco
> y conservando el sidebar + barra superior del dashboard.

**Backend:** `GET /api/v1/agenda/citas/` con filtros: `doctor_id`, `patient_id`,
`consultorio_id`, `status`, `date_from`, `date_to`.
Estados de una cita: `scheduled` (agendada), `confirmed` (confirmada), `arrived`
(llegó), `in_progress` (en consulta), `attended` (atendida), `cancelled` (cancelada),
`no_show` (no asistió).

```
[Pega el prompt BASE de estilo primero, con el mismo sidebar + barra superior]

Diseña la pantalla de AGENDA de Maily Soft.
Arriba: pestañas de vista (Día / Semana / Lista) y selector de fecha.
Barra de filtros: por doctor, por consultorio y por estado.
Vista calendario semanal: columnas por día, filas por hora, las citas se muestran como
bloques de color (el color del consultorio asignado) con la hora, el paciente y un
chip de estado. Los bloques no se empalman (cada doctor no puede tener dos citas a la
misma hora).
Vista lista (alternativa): tabla con Hora, Paciente, Doctor, Consultorio, Motivo,
Estado (chip) y acciones.
Botón flotante/primario dorado "+ Nueva cita".
Estados con color: agendada=gris, confirmada=verde, llegó=azul, en consulta=oro,
atendida=verde oscuro, cancelada=rojo, no asistió=rojo apagado.
La app está en español (México).
```

---

## 4. Crear / editar cita

**Backend:** `POST /api/v1/agenda/citas/`. Campos: `patient_id`, `doctor_id`,
`consultorio_id` (opcional), `starts_at`, `ends_at` (opcional, se calcula por duración),
`reason` (motivo, requerido), `specialty` (opcional), `notes` (opcional).
Regla: el sistema rechaza empalmes (mismo doctor o mismo consultorio a la misma hora).

```
[Pega el prompt BASE de estilo primero]

Diseña el formulario "NUEVA CITA" de Maily Soft como un modal/panel lateral sobre la
agenda. Campos:
- Paciente (buscador con autocompletado por nombre)
- Doctor (selector)
- Consultorio (selector, opcional — muestra su color)
- Fecha y hora de inicio
- Duración (la hora de fin se calcula sola, editable)
- Motivo de la consulta (texto, requerido)
- Especialidad (opcional)
- Notas (opcional)
Muestra una advertencia en oro si el horario elegido choca con otra cita del doctor o
consultorio ("Este horario ya está ocupado").
Botones: "Cancelar" (secundario) y "Agendar cita" (primario dorado).
La app está en español (México).
```

---

## 5. Detalle de cita (estados + recordatorios)

**Backend:** `GET /api/v1/agenda/citas/<id>/`; cambiar estado en
`POST /agenda/citas/<id>/estado/`; reagendar en `POST /agenda/citas/<id>/reagendar/`.
Recordatorios WhatsApp anidados, con estado `PENDING` / `SENT` / `FAILED` / `SKIPPED` /
`CANCELLED`. Flujo de estados: agendada → confirmada → llegó → en consulta → atendida.

```
[Pega el prompt BASE de estilo primero]

Diseña el DETALLE DE UNA CITA de Maily Soft (modal o panel).
Arriba: nombre del paciente, fecha/hora, doctor, consultorio y un chip grande de estado.
Cuerpo:
- Datos de la cita: motivo, especialidad, notas.
- Una "línea de tiempo" del estado: Agendada → Confirmada → Llegó → En consulta →
  Atendida (los pasos completados en dorado, el actual resaltado).
- Sección "Recordatorios por WhatsApp": lista con canal, fecha programada y estado
  (Pendiente=oro, Enviado=verde, Falló=rojo).
Acciones (botones): "Confirmar", "Marcar llegada", "Iniciar consulta", "Marcar atendida",
y secundarios "Reagendar" y "Cancelar cita" (este último en rojo).
La app está en español (México).
```

---

## 6. Pacientes — lista + búsqueda

**Backend:** `GET /api/v1/pacientes/` con búsqueda por nombre, CURP y número de
expediente. Cada paciente tiene número de expediente consecutivo automático.

```
[Pega el prompt BASE de estilo primero, mismo sidebar + barra superior]

Diseña la pantalla de PACIENTES de Maily Soft.
Arriba: título "Pacientes", buscador grande (por nombre, CURP o número de expediente) y
botón primario dorado "+ Nuevo paciente".
Tabla de pacientes: N.º de expediente, Nombre completo, Sexo, Teléfono, Última cita,
Estado (Activo/Inactivo como chip) y un botón de acción "Ver expediente".
Paginación abajo. Estado vacío amigable cuando no hay resultados de búsqueda.
La app está en español (México).
```

---

## 7. Crear / editar paciente

**Backend:** `POST /api/v1/pacientes/`. Campos: `first_name`, `paternal_surname`
(apellido paterno), `maternal_surname` (opcional), `date_of_birth`, `sex`, `phone`,
`curp` (opcional, 18 caracteres), `email` (opcional), `notes` (opcional).
El número de expediente se genera solo.

```
[Pega el prompt BASE de estilo primero]

Diseña el formulario "NUEVO PACIENTE" de Maily Soft (modal o pantalla).
Agrupa los campos en secciones:
Datos personales: Nombre(s), Apellido paterno, Apellido materno (opcional),
Fecha de nacimiento, Sexo (Femenino/Masculino/Otro).
Contacto: Teléfono, Email (opcional).
Identificación: CURP (opcional, 18 caracteres, con validación de formato).
Notas: campo de texto libre.
Nota informativa: "El número de expediente se asignará automáticamente".
Botones "Cancelar" (secundario) y "Guardar paciente" (primario dorado).
La app está en español (México).
```

---

## 8. Detalle de paciente (expediente)

**Backend:** `GET /api/v1/pacientes/<id>/` + sus citas vía agenda filtrada por
`patient_id`.

```
[Pega el prompt BASE de estilo primero]

Diseña el EXPEDIENTE de un paciente en Maily Soft.
Encabezado: avatar con iniciales, nombre completo, N.º de expediente, edad, sexo,
teléfono, chip Activo/Inactivo, y botones "Editar" y "Agendar cita".
Pestañas: "Datos generales" (todos los campos del paciente, notas) e "Historial de
citas" (lista con fecha, doctor, motivo y estado).
Diseño tipo ficha médica elegante, con acentos dorados.
La app está en español (México).
```

---

## 9. Personal — doctores + horarios

**Backend:** `GET/POST /api/v1/personal/doctores/`. Campos del doctor:
`cedula_profesional`, `specialty` (especialidad), `default_appointment_duration`
(duración default), `bio_short` (bio corta). Horarios:
`/personal/doctores/<id>/horarios/` con día de la semana, hora inicio, hora fin y
consultorio.

```
[Pega el prompt BASE de estilo primero, mismo sidebar + barra superior]

Diseña la pantalla de PERSONAL (Doctores) de Maily Soft.
Lista en tarjetas: cada doctor con foto/iniciales, nombre, especialidad,
cédula profesional y un chip Activo/Inactivo. Botón "+ Nuevo doctor".
Al abrir un doctor: panel con sus datos (cédula, especialidad, duración default de cita,
bio corta) y una sección "Horarios de atención": tabla por día de la semana con hora de
inicio, hora de fin y consultorio asignado, con botón "+ Agregar horario".
La app está en español (México).
```

---

## 10. Consultorios

**Backend:** `GET/POST /api/v1/personal/consultorios/`. Campos: `name`, `location`
(ubicación), `color_hex` (color para la agenda).

```
[Pega el prompt BASE de estilo primero]

Diseña la pantalla de CONSULTORIOS de Maily Soft.
Cuadrícula de tarjetas: cada consultorio con su nombre, ubicación y una muestra de su
color (el que se usa en la agenda). Chip Activo/Inactivo. Botón "+ Nuevo consultorio".
Formulario de alta (modal): Nombre, Ubicación y un selector de color.
La app está en español (México).
```

---

## 11. Configuración de agenda

**Backend:** `GET/PATCH /api/v1/agenda/config/`. Campos: `record_number_format`
(formato del número de expediente), `record_number_reset_yearly` (reiniciar cada año),
`default_appointment_duration` (duración default en minutos),
`reminder_offsets_minutes` (con cuánta anticipación mandar recordatorios),
`reminders_enabled` (activar/desactivar recordatorios).

```
[Pega el prompt BASE de estilo primero, mismo sidebar + barra superior]

Diseña la pantalla de CONFIGURACIÓN de la agenda en Maily Soft.
Tarjetas de ajustes:
- "Citas": duración default de una cita (minutos).
- "Expedientes": formato del número de expediente y un switch "Reiniciar numeración
  cada año".
- "Recordatorios por WhatsApp": switch maestro "Activar recordatorios" y una lista
  editable de tiempos de anticipación (ej. 24 horas antes, 2 horas antes) con chips
  que se pueden quitar/agregar.
Botón primario dorado "Guardar cambios".
La app está en español (México).
```

---

## Notas para el armado final con el backend

- **Roles:** la UI debe adaptarse al rol (recepción no ve finanzas, solo-lectura no edita,
  etc.). Para el MVP visual puedes prototipar el caso "admin" (ve todo).
- **Multi-tenant:** cada clínica solo ve sus propios datos; en el frontend esto es
  transparente (el token ya trae el tenant). No hay que diseñar nada especial para el MVP.
- **Idioma:** todo en español (México). Las etiquetas legibles (`status_display`,
  `sex_display`, etc.) ya vienen listas desde el backend.
- **Recordatorios WhatsApp:** en desarrollo no se envían de verdad (adapter simulado);
  para la demo se pueden mostrar como "Enviado" sin enviar nada real.
</content>
</invoke>
