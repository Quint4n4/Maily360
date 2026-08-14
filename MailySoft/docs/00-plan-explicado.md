# El plan, explicado con escenas

> Compañero de `00-plan-de-ataque.md`. Ese documento tiene los nombres de archivo y las líneas —lo
> que necesita Claude Code para arreglar. **Este cuenta qué está pasando de verdad**, con la clínica
> enfrente.
>
> Para leerlo todo usa la misma clínica imaginaria: **Vida Sana**, dos sedes (Norte y Centro).
> La **Dra. Ana** pasa consulta. **Karla** está en recepción. **Sofía** administra la sede Norte.
> **Luis** es paciente.

---

# TANDA 1 · Que no se pierda nada

## 1.1 · La nota que se guarda, dice "listo", y no existe

### La escena

La Dra. Ana atiende a Luis. Escribe su nota de evolución: el motivo, la exploración, el diagnóstico.
Le da guardar. La pantalla le confirma que se guardó. Ana cierra el expediente y llama al siguiente
paciente.

Tres semanas después Luis regresa. Ana abre el expediente y **esa consulta no está**. No está la
nota, no está el diagnóstico, y tampoco hay ningún registro de que alguien intentó guardarla. Para el
sistema, esa consulta nunca ocurrió.

Ana va a jurar que la escribió. Y tiene razón.

### Por qué pasa

Cuando el sistema guarda algo importante hace dos cosas a la vez: guarda el dato y anota en la
bitácora "Ana guardó una nota a las 10:15". Las dos van **en el mismo paquete**: o se guardan las dos,
o no se guarda ninguna. Eso está bien, es lo correcto.

El problema es qué pasa cuando falla la segunda.

En la bitácora hay un campo pequeño —una especie de número de folio de la petición— que solo acepta
64 caracteres. El sistema lo copia tal cual de lo que le manda el navegador, **sin cortarlo**. Si por
lo que sea llega uno más largo, la base de datos rechaza la anotación.

Ahí viene lo grave. Alguien programó que un fallo de bitácora **nunca** tumbe la operación principal.
La intención era buenísima: que no se pierda una nota clínica solo porque falló un registro
administrativo. Pero al capturar el error y seguir como si nada, el paquete ya quedó marcado como
dañado. Al final, en lugar de guardarse, **se tira entero**. Y como nadie le avisó a la pantalla, la
pantalla dice "guardado".

Es como un notario que redacta la escritura y debe anotarla en el libro de registro. La anotación
falla, él decide que eso no debe arruinarle el día al cliente… pero el procedimiento ya condenó todo
el trámite. Rompe la escritura, no anota nada, y te entrega el acuse de recibo.

### Cómo se arregla

Dos cosas pequeñas, y hay que hacer las dos:

1. **Cortar ese folio a 64 caracteres antes de guardarlo.** Curiosamente el campo de al lado —el que
   guarda qué navegador usó— sí se corta. A este se le olvidó. Es una línea, en tres lugares.
2. **Aislar la anotación de la bitácora del resto del paquete.** Que si falla, falle sola y no
   contamine lo demás. Técnicamente se llama *savepoint*: un punto de retorno intermedio, para que el
   error se quede encerrado ahí.

### Cómo sabes que quedó

Una prueba automática que mande a propósito un folio de 200 caracteres al guardar una nota, y después
compruebe que **la nota está en la base de datos**. Si esa prueba no existe, el arreglo no está
cerrado: solo está hecho hoy.

> **Para Claude Code:** CR-19 — truncar `request_id` a `[:64]` en `core/views.py:184`,
> `plataforma/views.py:160` y `authn/views.py:190`; envolver el `log.save()` de `audit_record` en su
> propio `transaction.atomic()`.

---

## 1.2 · Las llaves de la demo están puestas en la puerta de producción

### La escena

Estás en la consola de Railway —la misma que acabas de usar para revisar el rol de la base de
datos— y quieres montar rápido una demo para enseñarle el sistema a un prospecto. Corres el comando
de siembra de datos de ejemplo.

Ese comando no pregunta dónde está parado. Busca la clínica más antigua que encuentre y le escribe
encima usuarios de prueba. La clínica más antigua es **Vida Sana**, tu cliente real.

### Por qué pasa

Los comandos que crean datos de ejemplo se escribieron para tu computadora, donde no hay nada que
perder. Nadie les puso un candado que diga "si esto es producción, no corras".

Y para rematar, la contraseña que usan esos comandos está guardada como variable **en el servicio de
producción**, lista para usarse. O sea: el comando peligroso tiene la munición cargada en el lugar
equivocado.

No es que alguien vaya a hacerlo a propósito. Es que un martes a las 11 de la noche, cansado, en la
consola equivocada, un comando de dos palabras te borra la configuración de un cliente.

### Cómo se arregla

- Un candado al inicio de esos comandos: si detecta que está en producción, se niega y explica por
  qué. Cinco líneas.
- Quitar esa contraseña del servicio de producción. Si de verdad se usa ahí para algo, cambiarla.

> **Para Claude Code:** CR-16 — guardia de entorno en `seed_e2e_user` y `seed_demo`; retirar o rotar
> `DEMO_OWNER_PASSWORD` del servicio de producción.

---

## 1.3 · El sistema arranca en "modo taller" sin avisarte

### La escena

Dentro de un mes le vendes Maily360 a una segunda clínica y le montas su propia instalación. Copias
la configuración, despliegas, todo arranca sin un solo error. Se ve perfecto.

Tres semanas después esa clínica te llama: **las fotos de los pacientes salen rotas**. Todas. Y los
PDFs de recetas viejas también.

Lo que pasó: en esa instalación se te olvidó una variable de configuración. Y sin esa variable, el
sistema no se detiene ni protesta: guarda los archivos dentro del propio servidor. Cada vez que subes
una versión nueva, Railway reemplaza ese servidor por uno limpio y **los archivos se van con él**. La
base de datos conserva las direcciones, pero las direcciones apuntan a la nada.

### Por qué pasa

El sistema lee **53 opciones de configuración** del entorno. De esas, solo **5** son obligatorias: si
faltan, el sistema no arranca y te enteras al instante.

Las otras **48 tienen un valor de respaldo** pensado para que funcione en tu computadora sin
configurar nada. Es cómodo para desarrollar. En producción, esos valores de respaldo son decisiones
silenciosas:

| Si falta esta configuración… | El sistema decide por su cuenta… | Y el resultado es |
|---|---|---|
| Dónde se guardan los archivos | Guardarlos dentro del servidor | Fotos y PDFs desaparecen en cada actualización |
| Con qué llave se firman los QR de recetas | Usar la llave general del sistema | El día que rotes esa llave, **todas** las recetas impresas dejan de validar |
| A qué dirección apunta el QR | `localhost` | Cada receta impresa lleva un código que solo funciona en tu computadora |
| Dónde está la memoria rápida (Redis) | Buscarla en la máquina local y **ignorar el error si no está** | El límite de 5 intentos de login por minuto **desaparece**, sin dejar rastro |

Ese último merece una lectura extra. El límite de intentos de contraseña funciona consultando un
historial guardado en memoria rápida. Si esa memoria no responde, la consulta devuelve "no hay
historial" y **cada intento pasa como si fuera el primero**. Alguien puede probar contraseñas sin
límite y el sistema ni se entera. Es un candado que se abre solo cuando falla la luz.

Hoy, en tu producción, esas cuatro están bien puestas — lo verifiqué. **El problema no es cómo está
hoy: es que nada obliga a que siga así.**

### Cómo se arregla

Sumar esas cuatro a la lista de obligatorias. Así, si algún día faltan, el sistema **no arranca** y
te enteras en el momento del despliegue, no tres semanas después por una llamada del cliente.

Es cambiar "confío en que estará puesta" por "no puede arrancar sin ella". Esa es toda la diferencia
entre una configuración correcta y una garantía.

> **Para Claude Code:** CR-02 — agregar `DJANGO_DEFAULT_FILE_STORAGE`, `PRESCRIPTION_VERIFY_SECRET`,
> `PRESCRIPTION_VERIFY_BASE_URL` y `REDIS_URL` a las variables obligatorias de `production.py`, y
> actualizar el bloque de variables de `DEPLOY-RAILWAY.md`.

---

## 1.4 · La alarma está instalada pero sin baterías

### La escena

Un jueves, Karla intenta agendar y le sale un error. Lo intenta tres veces, se rinde, y agenda en el
cuaderno. El viernes le pasa a otra persona. El lunes te llaman molestos.

Para ti, el problema empezó el lunes. Para el sistema, empezó el jueves. Nadie te avisó, porque no
hay nadie escuchando.

### Por qué pasa

Sentry es un servicio que recibe cada error de tu aplicación y te lo manda. Tu código está **bien
escrito** para usarlo: alguien lo integró correctamente, y lo verificamos línea por línea.

Pero Sentry solo se enciende si existe una variable con su dirección. Esa variable **no está puesta
en Railway**. Sin ella, el código simplemente no lo inicializa, y no protesta.

Llevas meses creyendo que tienes visibilidad de errores. No la tienes. Es un detector de humo
atornillado a la pared, con el hueco de las baterías vacío.

Lo mismo con el correo: falta la configuración del proveedor, así que **todo correo que el sistema
manda se imprime en el registro de Railway** y nadie lo recibe. Sin error, sin aviso.

### Cómo se arregla

Poner las variables en Railway. Es entrar al panel, agregar dos líneas por servicio, y redesplegar.
Diez minutos.

Y una más que vale oro: hacer que el despliegue verifique automáticamente el rol de la base de datos.
Ese comando que corriste hoy a mano —el que te dijo `SUPERUSER: False`— existe justamente para eso y
**hoy no lo ejecuta nadie**. Ponerlo en el arranque significa que si algún día alguien cambia esa
configuración, el despliegue falla en vez de dejarte sin protección en silencio.

---

# TANDA 2 · El dinero, y un orden que no se puede invertir

## 2.1 · Doble clic, doble deuda

### La escena

Karla arma la cotización de un tratamiento de Luis: seis sesiones, $18,000. Luis acepta. Karla da
clic en "Aceptar cotización". La pantalla tarda, ella cree que no registró, **da clic otra vez**.

Ahora Luis debe **$36,000**. Doce cargos en vez de seis.

Peor: si en lugar de Karla son dos personas —Karla en Norte y Sofía en Centro— aceptando la misma
cotización con segundos de diferencia, pasa igual y sin doble clic de nadie.

### Por qué pasa

El código sí revisa antes de actuar: "¿esta cotización ya está aceptada? Si sí, no hago nada". El
problema es **cuándo** revisa.

Revisa **antes** de abrir la operación protegida, y sin bloquear el registro. Entonces dos clics que
llegan casi juntos hacen esto:

```
Clic 1 → ¿ya está aceptada? No.  ┐
Clic 2 → ¿ya está aceptada? No.  ┘  (ninguno ve al otro todavía)
Clic 1 → genera 6 cargos
Clic 2 → genera 6 cargos
```

Es la escena de dos cajeros que miran la misma libreta al mismo tiempo, los dos ven el renglón vacío,
y los dos escriben. En bases de datos esto tiene nombre: *comprobar-luego-actuar*, y la solución es
tan vieja como el problema.

Lo irónico es que el comentario del código **promete** que la operación es segura contra repeticiones.
No lo es.

### Cómo se arregla

Dos medidas, y conviene poner las dos:

1. **Bloquear el registro mientras se decide.** Que el primer clic ponga el renglón "en uso"; el
   segundo espera, vuelve a mirar, ve que ya está aceptada y no hace nada. Es una instrucción, no un
   rediseño.
2. **Una regla en la base de datos** que impida físicamente dos aceptaciones de la misma cotización.
   El cinturón además del airbag: aunque el código falle, la base no lo permite.

Lo mismo aplica en otros tres lugares donde se decide sobre dinero: registrar un pago, cancelar un
cargo, y asignar el folio de una receta.

> **Para Claude Code:** CR-20 — `select_for_update` dentro del `atomic()` en `quote_accept`,
> `payment_register`, `charge_cancel` y el folio de receta, más la constraint que lo respalde.

---

## 2.2 · La puerta que hay que abrir antes de cerrar la otra

### La escena

Decides endurecer la seguridad de la base de datos, que suena a buena idea. Al día siguiente **ningún
PDF se genera**. Ni recetas, ni libro clínico, ni estados de cuenta. Todo lo que se produce en
segundo plano deja de funcionar, al mismo tiempo, sin explicación clara.

### Por qué pasa

Tu sistema tiene dos candados para que una clínica no vea datos de otra. El segundo, el de la base de
datos, dice más o menos esto:

> "Solo muestro las filas de la clínica activa. **Pero si nadie me dijo cuál es la clínica activa,
> muestro todo.**"

Esa última frase es el hueco. Y resulta que los procesos que corren en segundo plano —los que generan
los PDFs y mandan los recordatorios— **nunca dicen cuál es la clínica activa**. O sea: funcionan
gracias al hueco.

Es el repartidor que entra por la puerta trasera porque nunca le dieron llave de la principal. Todo
marcha… hasta el día que cierras la trasera.

### Cómo se arregla

**El orden importa más que el arreglo**, y por eso esto está en el plan como una regla y no como una
tarea:

1. Primero, que cada proceso de segundo plano **declare** sobre qué clínica está trabajando.
2. Después, una prueba que lo exija, para que nadie escriba uno nuevo sin declararlo.
3. **Y hasta entonces**, cerrar el hueco de la base de datos.

Si lo haces al revés, tumbas los PDFs de todos tus clientes el mismo día.

Hay un detalle final con gracia amarga: la prueba automática que hoy vigila la seguridad de la base
**exige que el hueco exista**. Se escribió cuando el hueco era el comportamiento normal, así que hoy
protege lo que hay que quitar. También hay que cambiarla, y en ese mismo orden.

> **Para Claude Code:** CR-24 antes de tocar las policies; el guardián `test_rls_coverage.py` exige
> hoy el fallback `IS NULL` y hay que actualizarlo en el mismo paso.

---

# TANDA 3 · El módulo · Los dos caros

Estos dos no son bugs. Son **cosas que nunca se construyeron**, y por eso se hacen con contrato antes
del código.

## 3.1 · La sede se respeta en la lista, y se olvida en el detalle

### La escena

Sofía administra la sede **Norte**. Entra a "Personal" y ve solo a los médicos de Norte: perfecto,
el sistema la está acotando bien.

Pero Sofía tiene el enlace directo a la ficha de un médico de **Centro** —lo vio una vez, se lo pasó
alguien, o simplemente cambió el número en la dirección del navegador. Abre ese enlace y **el sistema
se lo muestra**. Y no solo eso: puede editarle la cédula profesional y puede darlo de baja.

Lo mismo con las recetas de un paciente de Centro: las lee completas, con diagnóstico y medicamentos,
y puede anularlas.

### Por qué pasa

Cuando pides una **lista**, el sistema pregunta "¿de qué sedes es esta persona?" y filtra. Funciona.

Cuando pides **una cosa concreta por su número**, el sistema solo pregunta "¿es de tu clínica?".
Nunca pregunta "¿es de tu sede?".

Y aquí está el detalle que lo convierte en un cambio de forma y no en un parche: **no es que la
pregunta esté mal hecha — es que no existe.** Hay 34 funciones que buscan cosas por su número, y
ninguna tiene siquiera un espacio donde recibir "y además, de estas sedes". Hay que agregárselo a las
34.

Es una biblioteca con dos sucursales donde el catálogo por sucursal funciona perfecto, pero si llegas
al mostrador con el código de un libro te lo entregan sin preguntar de dónde es.

### Cómo se arregla

Agregar el alcance de sede a esas 34 funciones y usarlo en todos los lugares donde se pide algo por
su número. No es difícil pieza por pieza: es que son 34 piezas y hay que hacerlas todas, porque
dejar cinco sin hacer es dejar el problema completo.

Por eso va como módulo: se diseña una vez, se escribe el contrato de cómo queda, y se aplica en
bloque.

---

## 3.2 · Las reglas de "esto es tuyo" están escritas a mano en cada mostrador

### La escena

La Dra. Ana emitió una receta y se equivocó. Quiere anularla. El botón no aparece.

En otra clínica, el Dr. Beto ve el botón de anular sobre una receta que emitió **su colega** — le da
clic y recibe un error que no explica nada.

Los dos casos son el mismo problema visto por sus dos lados.

### Por qué pasa

El sistema decide los permisos en dos niveles distintos:

- **Por puesto:** "los médicos pueden anular recetas". Esto está bien hecho y el frontend lo conoce.
- **Por pertenencia:** "…pero solo las suyas". Esto está escrito **a mano, dentro de cada operación**,
  en vez de estar declarado en un lugar donde el resto del sistema lo pueda consultar.

Django trae un mecanismo justo para esto — un lugar formal donde se declara "este objeto es de este
usuario". En todo tu backend **no se usa ni una sola vez**.

Consecuencia directa: el frontend solo puede preguntar "¿qué puesto tiene esta persona?". No tiene
forma de preguntar "¿esta receta es suya?". Así que o muestra el botón de más —y el usuario se topa
con un error— o lo esconde de más y una función que sí existe queda invisible.

Es como si el reglamento de la clínica dijera "los médicos pueden anular recetas", y la regla de que
solo las propias estuviera anotada en un post-it pegado en cada mostrador. Quien atiende la conoce.
El folleto que le das al paciente, no.

### Cómo se arregla

Sacar esas reglas de dentro de cada operación y declararlas en el lugar formal. Con eso, el frontend
puede preguntar por cada objeto concreto si el usuario puede actuar sobre él, y deja de adivinar.

Va junto con el anterior porque los dos contestan la misma pregunta desde dos ángulos:
**¿de quién es esto, y desde dónde me lo estás pidiendo?**

---

# Cómo leer esto cuando estés trabajando

Cuando abras una sesión para arreglar algo, el orden es:

1. **Aquí** entiendes qué se está rompiendo y por qué.
2. En `00-plan-de-ataque.md` está el orden, el plazo y el archivo:línea.
3. En `00-deuda.md` está el detalle completo de la causa raíz y todos los hallazgos que cierra.

Y una regla que vale para las tres tandas: **ningún arreglo está cerrado sin una prueba que falle si
alguien lo deshace.** Si no, no arreglaste el problema — lo dejaste bien por hoy.
