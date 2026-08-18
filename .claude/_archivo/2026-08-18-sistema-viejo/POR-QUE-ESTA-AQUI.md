# Por qué estas skills y agentes están archivados

Archivado el **2026-08-18**, al instalar el plugin `biblioteca-de-skills`.

**No se borraron, se archivaron**, por si hace falta entender una decisión vieja. Pero **no se
cargan y no deben volver**: dos definiciones de "cómo se revisa aquí" producen revisiones que se
contradicen, y siempre gana la que es más fácil de contestar.

El caso que lo demuestra: una de estas skills mandaba comprobar que una bandera de configuración
estuviera en `True`. Estaba en `True`. Y no servía de nada, porque la app que la hace funcionar no
estaba instalada. **Con eso aprobaba el P0 más grave del proyecto**, en diez segundos, mientras el
punto correcto —el de dos renglones antes— exigía levantar el sistema y provocar el efecto.

Lo bueno de estas skills **ya subió al plugin** antes de archivarlas; se verificó concepto por
concepto. Lo que no subió es lo que mezclaba la regla universal con el hecho local de este repo —
y ese hecho ahora vive en `.claude/PERFIL-DEL-REPO.md`, donde le toca.

De aquí en adelante: si este proyecto corrige o agrega un punto a una skill, **el cambio se hace en
el plugin y se publica en el mismo movimiento.** Un punto que se queda aquí abajo está garantizado
que se repite en el siguiente proyecto — ya pasó tres veces.
