/**
 * IndiceSecciones — índice de la columna derecha del expediente.
 *
 * Sustituye a la pila vertical infinita (libro clínico + recetas + …) por una
 * lista de secciones con su contador: se ve DE UN VISTAZO qué tiene el paciente
 * y se entra solo a lo que se necesita.
 *
 * El contador es la razón de ser de esta pantalla: "Recetas 0" y "Recetas 12"
 * son decisiones clínicas distintas, y antes había que bajar hasta el bloque
 * para saberlo.
 *
 * Las secciones se filtran por rol (el backend es la autoridad y responde 403).
 */

import type { LucideIcon } from 'lucide-react'
import { BookOpen, Activity, Stethoscope, Pill, CalendarClock, Wallet, ListChecks, ChevronRight } from 'lucide-react'
import type { PatientOut } from '../../types/paciente'
import { useDiagnoses, useEvolutionNotes, useVitalSigns } from '../../hooks/expediente'
import { usePrescriptions } from '../../hooks/recetas'
import { useAppointmentsForPatient } from '../../hooks/agenda'

/** Identificador de cada sección del expediente. */
export type SeccionId =
  | 'libro' | 'signos' | 'diagnosticos' | 'recetas' | 'citas' | 'cuenta' | 'calendarizacion'

interface IndiceSeccionesProps {
  paciente: PatientOut
  /** Rol con acceso clínico: ve libro, signos, diagnósticos y recetas. */
  accesoClinico: boolean
  /** Rol que ve costos: sección de estado de cuenta. */
  verEstadoCuenta: boolean
  /** Rol que puede calendarizar tratamientos. */
  puedeCalendarizar: boolean
  onAbrir: (seccion: SeccionId) => void
}

export default function IndiceSecciones({
  paciente, accesoClinico, verEstadoCuenta, puedeCalendarizar, onAbrir,
}: IndiceSeccionesProps) {
  // Los contadores solo se consultan si el rol puede ver esa sección: pasar
  // null deshabilita la query (evita 403 y peticiones de más).
  const clinicoId = accesoClinico ? paciente.id : null
  const evoluciones = useEvolutionNotes(clinicoId)
  const signos = useVitalSigns(clinicoId)
  const diagnosticos = useDiagnoses(clinicoId)
  const recetas = usePrescriptions(clinicoId)
  const citas = useAppointmentsForPatient(paciente.id)

  const items: {
    id: SeccionId
    titulo: string
    descripcion: string
    icon: LucideIcon
    color: string
    total: number | null
  }[] = [
    ...(accesoClinico ? [
      {
        id: 'libro' as const,
        titulo: 'Libro clínico',
        descripcion: 'Evoluciones y notas por visita',
        icon: BookOpen,
        color: '#C9A227',
        total: evoluciones.data?.count ?? null,
      },
      {
        id: 'signos' as const,
        titulo: 'Signos y mediciones',
        descripcion: 'Peso, presión, glucosa y tendencias',
        icon: Activity,
        color: '#0E7C7B',
        total: signos.data?.count ?? null,
      },
      {
        id: 'diagnosticos' as const,
        titulo: 'Diagnósticos',
        descripcion: 'Presuntivos y definitivos (CIE-10)',
        icon: Stethoscope,
        color: '#4f46e5',
        total: diagnosticos.data?.count ?? null,
      },
      {
        id: 'recetas' as const,
        titulo: 'Recetas',
        descripcion: 'Emitidas, PDF y anulación',
        icon: Pill,
        color: '#db2777',
        total: recetas.data?.count ?? null,
      },
    ] : []),
    {
      id: 'citas' as const,
      titulo: 'Citas',
      descripcion: 'Próxima cita e historial',
      icon: CalendarClock,
      color: '#0284c7',
      total: citas.data?.count ?? null,
    },
    ...(verEstadoCuenta ? [{
      id: 'cuenta' as const,
      titulo: 'Estado de cuenta',
      descripcion: 'Cargos, pagos y saldo',
      icon: Wallet,
      color: '#b45309',
      total: null,
    }] : []),
    ...(puedeCalendarizar ? [{
      id: 'calendarizacion' as const,
      titulo: 'Calendarización',
      descripcion: 'Sesiones de tratamiento programadas',
      icon: ListChecks,
      color: '#059669',
      total: null,
    }] : []),
  ]

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-amber-700/80 mb-3">
        Secciones del expediente
      </h3>

      {items.map(item => (
        <button
          key={item.id}
          type="button"
          onClick={() => onAbrir(item.id)}
          className="w-full flex items-center gap-3 rounded-2xl px-4 py-3.5 text-left transition-colors hover:bg-white/70"
          style={{
            background: 'rgba(255,255,255,0.55)',
            border: '1px solid rgba(201,162,39,0.18)',
          }}
        >
          <span
            className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0"
            style={{ background: `${item.color}1A` }}
          >
            <item.icon className="w-[18px] h-[18px]" style={{ color: item.color }} />
          </span>

          <span className="flex-1 min-w-0">
            <span className="block text-sm font-semibold text-gray-800">{item.titulo}</span>
            <span className="block text-xs text-gray-400 truncate">{item.descripcion}</span>
          </span>

          {item.total !== null && (
            <span
              className="text-xs font-bold px-2 py-0.5 rounded-full shrink-0"
              style={
                item.total > 0
                  ? { background: `${item.color}1A`, color: item.color }
                  : { background: 'rgba(0,0,0,0.04)', color: '#9ca3af' }
              }
            >
              {item.total}
            </span>
          )}

          <ChevronRight className="w-4 h-4 shrink-0 text-gray-300" />
        </button>
      ))}
    </div>
  )
}
