/**
 * Tarjeta flotante que aparece al pasar el cursor sobre una cita de la agenda.
 *
 * Sirve para RECONOCER de un vistazo, no para consultar el expediente: foto,
 * nombre, edad, a qué viene y sus etiquetas. Todo lo demás (historial, saldo,
 * alergias, contacto) sigue estando a un clic, en el modal de la cita — una
 * tarjeta flotante que intenta ser el expediente estorba más de lo que ayuda.
 *
 * Decisiones que la hacen usable:
 *
 *  · Va en un PORTAL. La rejilla tiene `overflow: auto`, así que una tarjeta
 *    posicionada dentro se recortaría contra el borde del calendario.
 *
 *  · Se VOLTEA sola. En la última columna (Telemedicina) o en las citas de la
 *    tarde se saldría de la pantalla, así que se mide y se coloca del lado que
 *    quepa. Es el fallo clásico de este patrón.
 *
 *  · NO lleva botones. Una tarjeta a la que hay que meter el ratón para pulsar
 *    algo se cierra a medio camino. Es solo de lectura.
 *
 *  · Solo pide `usePatient`: el motivo y el tipo de cita ya vienen con la cita.
 *    TanStack cachea, así que un paciente con tres citas en el día se consulta
 *    una sola vez, y el segundo hover es instantáneo.
 */

import { useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Crown, Tag } from 'lucide-react'
import { usePatient } from '../../hooks/pacientes'
import { edad, initialsOf } from '../../lib/paciente'
import type { Appointment } from '../../types/agenda'

const ANCHO = 268
/** Separación con la cita y margen mínimo contra el borde de la ventana. */
const HUECO = 10
const BORDE = 8

export default function TarjetaPacienteHover({
  cita, ancla,
}: {
  cita: Appointment
  /**
   * La tarjeta de la cita sobre la que está el cursor. Se guarda el ELEMENTO,
   * no su rectángulo: con un rectángulo congelado la tarjeta se quedaba donde
   * estaba al abrirse y se despegaba de la cita al desplazar o redimensionar.
   */
  ancla: HTMLElement
}) {
  const { data: paciente, isLoading } = usePatient(cita.patient.id)
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null)

  // Se coloca DESPUÉS de medir el alto real: el número de etiquetas cambia
  // cuánto ocupa, y sin medir no se sabe si cabe abajo.
  useLayoutEffect(() => {
    const colocar = () => {
      const el = ref.current
      if (!el) return
      const r = ancla.getBoundingClientRect()
      const alto = el.offsetHeight

      // Lado preferido: a la derecha de la cita. Si no cabe, se voltea.
      let left = r.right + HUECO
      if (left + ANCHO > window.innerWidth - BORDE) left = r.left - ANCHO - HUECO
      if (left < BORDE) left = BORDE

      let top = r.top
      if (top + alto > window.innerHeight - BORDE) top = window.innerHeight - BORDE - alto
      if (top < BORDE) top = BORDE

      setPos({ left, top })
    }

    colocar()
    // `true` = fase de captura, para enterarse también del scroll DENTRO de la
    // rejilla, que no burbujea hasta window.
    window.addEventListener('scroll', colocar, true)
    window.addEventListener('resize', colocar)
    return () => {
      window.removeEventListener('scroll', colocar, true)
      window.removeEventListener('resize', colocar)
    }
  }, [ancla, paciente, isLoading])

  const años = paciente?.date_of_birth ? edad(paciente.date_of_birth) : null
  // Mientras carga ya se puede pintar el nombre: viaja con la cita.
  const nombre = paciente?.full_name ?? cita.patient.full_name
  /*
   * El motivo REAL de la cita (`reason`, el "¿a qué viene?" que se captura al
   * agendar), no el tipo de cita.
   *
   * Antes se mostraba `appointment_type.name` y era información muerta: el tipo
   * ya se lee en la propia cita de la rejilla, así que la tarjeta repetía lo que
   * ya estaba a la vista. Lo que no se ve en ningún sitio de la agenda es la
   * nota — "dolor de rodilla" — y es justo lo que hace falta para saber a qué
   * viene alguien sin abrir la cita.
   */
  const motivo = cita.reason?.trim() ?? ''
  const etiquetas = paciente?.categories ?? []

  return createPortal(
    <div
      ref={ref}
      role="tooltip"
      className="fixed z-[70] rounded-2xl bg-superficie border border-borde shadow-card-alto p-3.5 pointer-events-none transition-opacity duration-100"
      style={{
        width: ANCHO,
        left: pos?.left ?? -9999,
        top: pos?.top ?? -9999,
        opacity: pos ? 1 : 0,
      }}
    >
      <div className="flex items-start gap-3">
        {/* Foto (o iniciales mientras no hay). El aro dorado marca al VIP. */}
        <div
          className="w-14 h-14 rounded-full overflow-hidden shrink-0 flex items-center justify-center text-sm font-bold"
          style={{
            background: 'var(--accion-tinte)',
            color: 'var(--accion)',
            outline: paciente?.is_vip ? '2px solid var(--tinta)' : 'none',
            outlineOffset: 2,
          }}
        >
          {paciente?.avatar
            ? <img src={paciente.avatar} alt="" className="w-full h-full object-cover" />
            : paciente ? initialsOf(paciente) : ''}
        </div>

        <div className="min-w-0 flex-1">
          <p className="text-sm font-bold text-tinta leading-tight break-words">{nombre}</p>
          <p className="text-xs text-suave mt-0.5">
            {isLoading ? 'Cargando…' : años !== null ? `${años} años` : 'Edad sin registrar'}
          </p>
          {paciente?.is_vip && (
            <span className="badge badge-vip mt-1.5">
              <Crown className="w-3 h-3" /> VIP
            </span>
          )}
        </div>
      </div>

      <div className="mt-3 pt-3 border-t border-borde">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-suave">A qué viene</p>
        {/* Si nadie anotó el motivo, se dice: un hueco en blanco parece un fallo
            de la tarjeta, y aquí lo que falta es el dato. */}
        {motivo
          ? <p className="text-sm text-cuerpo leading-snug break-words">{motivo}</p>
          : <p className="text-sm text-suave italic leading-snug">Sin motivo registrado</p>}
      </div>

      {etiquetas.length > 0 && (
        <div className="mt-2.5 flex flex-wrap gap-1">
          {etiquetas.map(e => (
            <span
              key={e.id}
              className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-superficie-sutil text-suave ring-1 ring-borde"
            >
              <Tag className="w-2.5 h-2.5" />{e.name}
            </span>
          ))}
        </div>
      )}
    </div>,
    document.body,
  )
}
