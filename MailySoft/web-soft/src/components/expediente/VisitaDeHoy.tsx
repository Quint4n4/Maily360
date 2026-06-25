/**
 * VisitaDeHoy — tarjeta CENTRAL del expediente rediseñado ("centrado en la visita").
 *
 * Reúne en un solo lugar, con pocos clics, los 3 pasos de una consulta:
 *   ① Enfermería — signos vitales de la cita (VisitaSignos). Al guardar, resumen ✓.
 *   ② Evolución (SOAP) — botón "Escribir" que abre el editor SOAP guiado paso a paso.
 *   ③ Receta — botón directo "+ Receta" que monta el MISMO formulario de NuevaReceta
 *      (reusado de RecetasTab), sin acordeón.
 *
 * No reescribe la lógica clínica: delega en los componentes/hook existentes. Solo
 * define el layout de "la visita de hoy" y respeta los permisos (UX) que recibe.
 */

import { useState } from 'react'
import { Activity, Stethoscope, Pill, CalendarHeart, Pencil, Plus } from 'lucide-react'
import type { PatientOut } from '../../types/paciente'
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

export default function VisitaDeHoy({
  paciente, puedeCapturarSignos, puedeEditarClinico, puedeEmitirReceta,
}: VisitaDeHoyProps) {
  const [soapAbierto, setSoapAbierto] = useState(false)
  const [recetaAbierta, setRecetaAbierta] = useState(false)

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
        className="px-5 py-4 flex items-center gap-3"
        style={{ background: 'linear-gradient(135deg, rgba(201,162,39,0.16), rgba(255,255,255,0.4))', borderBottom: '1px solid rgba(201,162,39,0.2)' }}
      >
        <div
          className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
          style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
        >
          <CalendarHeart className="w-5 h-5 text-white" />
        </div>
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-widest text-amber-700/70">Visita de hoy</p>
          <h3 className="text-base font-bold text-gray-900 leading-tight">{hoy}</h3>
        </div>
      </div>

      <div className="p-5 space-y-3">
        {/* ① Enfermería */}
        <PasoVisita numero={1} titulo="Enfermería" icon={Activity} color="#0E7C7B">
          <VisitaSignos paciente={paciente} puedeCapturar={puedeCapturarSignos} />
        </PasoVisita>

        {/* ② Evolución (SOAP) */}
        <PasoVisita numero={2} titulo="Evolución (SOAP)" icon={Stethoscope} color="#185FA5">
          {soapAbierto ? (
            <EvolucionSoapStepper paciente={paciente} onClose={() => setSoapAbierto(false)} />
          ) : puedeEditarClinico ? (
            <button
              type="button"
              onClick={() => setSoapAbierto(true)}
              className="inline-flex items-center gap-1.5 text-sm font-semibold transition-colors"
              style={{ color: '#185FA5' }}
            >
              <Pencil className="w-4 h-4" /> Escribir evolución
            </button>
          ) : (
            <p className="text-sm text-gray-400 italic">Solo el personal clínico puede escribir evoluciones.</p>
          )}
        </PasoVisita>

        {/* ③ Receta */}
        <PasoVisita numero={3} titulo="Receta" icon={Pill} color="#9A7B1E">
          {recetaAbierta ? (
            <NuevaReceta paciente={paciente} prefill={null} onClose={() => setRecetaAbierta(false)} />
          ) : puedeEmitirReceta ? (
            <button
              type="button"
              onClick={() => setRecetaAbierta(true)}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110"
              style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
            >
              <Plus className="w-4 h-4" /> Receta
            </button>
          ) : (
            <p className="text-sm text-gray-400 italic">Solo el personal clínico puede emitir recetas.</p>
          )}
        </PasoVisita>
      </div>
    </div>
  )
}

/** Un paso de la visita: badge numerado + título con icono + contenido. */
function PasoVisita({
  numero, titulo, icon: Icon, color, children,
}: {
  numero: number
  titulo: string
  icon: typeof Activity
  color: string
  children: React.ReactNode
}) {
  return (
    <div className="rounded-2xl p-4" style={{ background: 'rgba(255,255,255,0.5)', border: '1px solid rgba(201,162,39,0.15)' }}>
      <div className="flex items-center gap-2.5 mb-3">
        <span
          className="shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-sm font-bold text-white"
          style={{ background: color }}
        >
          {numero}
        </span>
        <Icon className="w-4 h-4" style={{ color }} />
        <h4 className="text-sm font-semibold text-gray-800">{titulo}</h4>
      </div>
      <div className="pl-1">{children}</div>
    </div>
  )
}
