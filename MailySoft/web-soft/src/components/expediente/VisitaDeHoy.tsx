/**
 * VisitaDeHoy — tarjeta CENTRAL del expediente ("centrado en la visita").
 *
 * Reúne en un solo lugar, con pocos clics, los 3 pasos de una consulta:
 *   ① Enfermería — signos vitales de la cita (VisitaSignos).
 *   ② Evolución (SOAP) — abre el editor SOAP guiado paso a paso.
 *   ③ Receta — monta el MISMO formulario de NuevaReceta (reusado de RecetasTab).
 *
 * Cada paso es un RENGLÓN: badge + título + acción a la derecha, con un resumen
 * corto debajo (los signos del día siguen visibles sin abrir nada). Solo un paso
 * puede estar abierto a la vez —es el orden natural de la consulta—, de modo que
 * la tarjeta comparte pantalla con el índice de secciones en vez de empujarlo
 * fuera del scroll, que es lo que pasaba cuando los tres pasos venían expandidos.
 *
 * No reescribe la lógica clínica: delega en los componentes/hook existentes. Solo
 * define el layout de "la visita de hoy" y respeta los permisos (UX) que recibe.
 */

import { useState } from 'react'
import { Activity, Stethoscope, Pill, CalendarHeart, Pencil, Plus } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { PatientOut } from '../../types/paciente'
import { useVitalSigns } from '../../hooks/expediente'
import { formatLargo } from '../../lib/fecha'
import VisitaSignos from './VisitaSignos'
import EvolucionSoapStepper from './EvolucionSoapStepper'
import { NuevaReceta } from './RecetasTab'

interface VisitaDeHoyProps {
  paciente: PatientOut
  /** owner/admin/doctor/nurse pueden capturar signos (UX). */
  puedeCapturarSignos: boolean
  /** owner/admin/doctor pueden escribir evoluciones (UX). */
  puedeEditarClinico: boolean
  /** owner/admin/doctor pueden emitir recetas (UX). */
  puedeEmitirReceta: boolean
}

/** Paso abierto de la visita; null = los tres plegados. */
type PasoAbierto = 1 | 2 | 3 | null

export default function VisitaDeHoy({
  paciente, puedeCapturarSignos, puedeEditarClinico, puedeEmitirReceta,
}: VisitaDeHoyProps) {
  // Un solo paso abierto a la vez: es el orden natural de la consulta
  // (enfermería → evolución → receta) y mantiene la tarjeta compacta para que
  // el índice de secciones quepa en la misma pantalla.
  const [abierto, setAbierto] = useState<PasoAbierto>(null)
  const cerrar = () => setAbierto(null)

  // Misma query que usa VisitaSignos (caché compartida): solo sirve para saber
  // si el botón dice "Capturar signos" o "Nueva toma".
  const { data: tomasData } = useVitalSigns(paciente.id)
  const hayToma = (tomasData?.results?.length ?? 0) > 0

  const hoy = formatLargo(new Date())

  return (
    <div
      className="rounded-3xl overflow-hidden"
      style={{
        background: 'rgba(255,255,255,0.72)',
        backdropFilter: 'blur(14px)',
        border: '1px solid rgba(255,255,255,0.7)',
        boxShadow: '0 8px 28px rgba(60,42,12,0.12)',
      }}
    >
      {/* Encabezado de la visita */}
      <div
        className="px-4 py-3 flex items-center gap-3"
        style={{ background: 'linear-gradient(135deg, rgba(201,162,39,0.16), rgba(255,255,255,0.4))', borderBottom: '1px solid rgba(201,162,39,0.2)' }}
      >
        <div
          className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0"
          style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
        >
          <CalendarHeart className="w-[18px] h-[18px] text-white" />
        </div>
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-widest text-amber-700/70">Visita de hoy</p>
          <h3 className="text-sm font-bold text-gray-900 leading-tight">{hoy}</h3>
        </div>
      </div>

      <div className="p-3 space-y-2">
        {/* ① Enfermería */}
        <PasoVisita
          numero={1} titulo="Enfermería" icon={Activity} color="#0E7C7B" activo={abierto === 1}
          accion={puedeCapturarSignos && (
            <AccionPaso color="#0E7C7B" icon={Plus} onClick={() => setAbierto(1)}>
              {hayToma ? 'Nueva toma' : 'Capturar signos'}
            </AccionPaso>
          )}
        >
          <VisitaSignos paciente={paciente} abierto={abierto === 1} onCerrar={cerrar} />
        </PasoVisita>

        {/* ② Evolución (SOAP) */}
        <PasoVisita
          numero={2} titulo="Evolución (SOAP)" icon={Stethoscope} color="#185FA5" activo={abierto === 2}
          accion={puedeEditarClinico
            ? (
              <AccionPaso color="#185FA5" icon={Pencil} onClick={() => setAbierto(2)}>
                Escribir evolución
              </AccionPaso>
            )
            : <span className="text-xs text-gray-400 italic">Solo personal clínico</span>}
        >
          {abierto === 2 && <EvolucionSoapStepper paciente={paciente} onClose={cerrar} />}
        </PasoVisita>

        {/* ③ Receta */}
        <PasoVisita
          numero={3} titulo="Receta" icon={Pill} color="#9A7B1E" activo={abierto === 3}
          accion={puedeEmitirReceta
            ? (
              <AccionPaso color="#9A7B1E" icon={Plus} onClick={() => setAbierto(3)}>
                Receta
              </AccionPaso>
            )
            : <span className="text-xs text-gray-400 italic">Solo personal clínico</span>}
        >
          {abierto === 3 && <NuevaReceta paciente={paciente} prefill={null} onClose={cerrar} />}
        </PasoVisita>
      </div>
    </div>
  )
}

/**
 * Un paso de la visita en un solo renglón: badge numerado + título + acción a
 * la derecha. El contenido (resumen corto o formulario abierto) va debajo, y
 * solo ocupa alto cuando realmente hay algo que mostrar.
 */
function PasoVisita({
  numero, titulo, icon: Icon, color, accion, activo, children,
}: {
  numero: number
  titulo: string
  icon: LucideIcon
  color: string
  accion: React.ReactNode
  /** Paso abierto: su formulario ya está en pantalla y la acción sobra. */
  activo: boolean
  children: React.ReactNode
}) {
  return (
    <div className="rounded-2xl px-3.5 py-2.5" style={{ background: 'rgba(255,255,255,0.5)', border: '1px solid rgba(201,162,39,0.15)' }}>
      <div className="flex items-center gap-2.5">
        <span
          className="shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold text-white"
          style={{ background: color }}
        >
          {numero}
        </span>
        <Icon className="w-4 h-4 shrink-0" style={{ color }} />
        <h4 className="text-sm font-semibold text-gray-800 flex-1 min-w-0 truncate">{titulo}</h4>
        {!activo && accion}
      </div>
      {children && <div className="mt-2 pl-[34px]">{children}</div>}
    </div>
  )
}

/** Botón de acción de un paso (abre el formulario correspondiente). */
function AccionPaso({
  color, icon: Icon, onClick, children,
}: {
  color: string
  icon: LucideIcon
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="shrink-0 inline-flex items-center gap-1 text-xs font-semibold transition-colors hover:brightness-110"
      style={{ color }}
    >
      <Icon className="w-3.5 h-3.5" /> {children}
    </button>
  )
}
