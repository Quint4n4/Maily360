---
name: security-checklist
description: Checklist falsable de seguridad para APIs Django y REST Framework — autenticación, permisos por objeto, validación de entrada, secretos, CORS, rate limiting, logs sin datos personales y cabeceras. Úsala al diseñar el contrato, al implementar endpoints y obligatoriamente al revisar un módulo antes de fusionar.
---

# Checklist de seguridad

Cada punto se responde con **BLOQUEA**, **PASA** o **N/A**, siempre con `archivo:línea`.
"Se ve bien" no es una respuesta. Un punto que no puedas verificar se marca `NO VERIFICABLE` y se
explica qué faltó.

## Autenticación y sesión

| # | Punto | Por qué |
|---|---|---|
| 1 | Todo endpoint declara `permission_classes` explícitamente | Heredar el default no es una decisión, es un olvido con suerte |
| 2 | El default global es `IsAuthenticated`, no `AllowAny` | Si algo se escapa, que se escape cerrado |
| 3 | Si hay sesión: cookie con `HttpOnly`, `Secure` y `SameSite` | Un XSS no debe poder robar la sesión |
| 4 | Si hay JWT: **nunca** en `localStorage` | Cualquier script en la página lo lee |
| 5 | Contraseñas con los validadores de Django activos | — |
| 6 | Endpoints de login y recuperación con rate limiting | Sin esto, la fuerza bruta es cuestión de tiempo |

## Autorización

| # | Punto | Por qué |
|---|---|---|
| 7 | Permisos **por objeto**, no solo por endpoint | Estar autenticado no te hace dueño del registro 42 |
| 8 | El rol se lee del servidor, jamás del payload | El cliente miente |
| 9 | Cada rol de la matriz del contrato tiene su test | Una matriz sin tests es una intención |
| 10 | Los IDs de otros usuarios devuelven 404, no 403 | Un 403 confirma que el recurso existe |

## Entrada y salida

| # | Punto | Por qué |
|---|---|---|
| 11 | Toda entrada valida en el serializer, incluida longitud máxima | Un campo de texto sin tope es un vector de saturación |
| 12 | Sin SQL construido por concatenación de strings | Inyección SQL |
| 13 | Archivos subidos: tipo y tamaño validados, nombre saneado | Un `.php` renombrado sigue siendo un `.php` |
| 14 | Los errores al cliente no exponen trazas ni SQL | Un stack trace es un mapa del sistema |
| 15 | `DEBUG = False` en producción, `ALLOWED_HOSTS` acotado | `DEBUG=True` publica variables de entorno en cada error |

## Secretos e infraestructura

| # | Punto | Por qué |
|---|---|---|
| 16 | Ningún secreto en el repo; `.env` en `.gitignore` | Un secreto commiteado ya es público aunque lo borres |
| 17 | `SECRET_KEY` desde variable de entorno | — |
| 18 | CORS con lista explícita de orígenes, nunca `*` | — |
| 19 | HTTPS forzado; `SECURE_SSL_REDIRECT` y HSTS activos | — |
| 20 | Backups configurados **y una restauración probada** | Un backup nunca restaurado no es un backup |

## Datos personales (aplica a pacientes y clientes)

| # | Punto | Por qué |
|---|---|---|
| 21 | Ningún dato personal en logs ni en Sentry | Los logs se leen, se exportan y se comparten |
| 22 | Bitácora de auditoría: quién vio o modificó qué y cuándo | En salud es requisito, no adorno |
| 23 | Borrado lógico en registros clínicos, no `DELETE` físico | Un borrado accidental es irreversible |
| 24 | Los datos de sesión no se cachean en el navegador | — |

## Nota sobre cumplimiento legal

Los requisitos legales aplicables a datos de salud en México **no se deducen de esta skill ni se
le preguntan a un modelo**: se consultan una vez con un abogado y el resultado se convierte en
puntos fijos de esta lista. Si aquí no hay puntos legales anotados, es que la consulta sigue
pendiente — no que no aplique.

## Cuando algo falle en producción

El arreglo no termina en el commit. Termina cuando la causa se agrega como punto nuevo de esta
lista, para que el revisor lo detecte la próxima vez.
