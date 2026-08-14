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
import { BookOpen, Activity, Stethoscope, Pill, CalendarClock, Wallet, ListChecks, FileHeart } from 'lucide-react'
import type { PatientOut } from '../../types/paciente'
import { useDiagnoses, useEvolutionNotes, useVitalSigns } from '../../hooks/expediente'
import { usePrescriptions } from '../../hooks/recetas'
import { useAppointmentsForPatient } from '../../hooks/agenda'
import { useAuth } from '../../auth/AuthContext'

/** Identificador de cada sección del expediente. */
export type SeccionId =
  | 'historia' | 'libro' | 'signos' | 'diagnosticos' | 'recetas' | 'citas' | 'cuenta' | 'calendarizacion'

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
  // Además del rol, el PLAN: un módulo no contratado responde 404, así que ni
  // se pregunta por él (y la sección no se ofrece).
  const { tieneModulo } = useAuth()
  const verRecetas = accesoClinico && tieneModulo('recetas')
  const verCalendarizacion = puedeCalendarizar && tieneModulo('calendarizacion')
  const verCuenta = verEstadoCuenta && tieneModulo('cobranza')
  const verCitas = tieneModulo('agenda')

  // Los contadores solo se consultan si el rol puede ver esa sección: pasar
  // null deshabilita la query (evita 403 y peticiones de más).
  const clinicoId = accesoClinico ? paciente.id : null
  const evoluciones = useEvolutionNotes(clinicoId)
  const signos = useVitalSigns(clinicoId)
  const diagnosticos = useDiagnoses(clinicoId)
  const recetas = usePrescriptions(verRecetas ? paciente.id : null)
  const citas = useAppointmentsForPatient(verCitas ? paciente.id : null)

  const items: {
    id: SeccionId
    titulo: string
    descripcion: string
    icon: LucideIcon
    total: number | null
  }[] = [
    /*
     * Orden por USO, no por jerarquía clínica.
     *
     * Antes mandaba el orden conceptual (historia → libro → signos → …), que es
     * como se explica el expediente pero no como se usa: en el día a día se
     * entra sobre todo a cobrar, recetar y ver mediciones. Esas tres van
     * arriba; el relato clínico y lo de agenda quedan detrás.
     */
    ...(verCuenta ? [{
      id: 'cuenta' as const,
      titulo: 'Estado de cuenta',
      descripcion: 'Cargos, pagos y saldo',
      icon: Wallet,
      total: null,
    }] : []),
    ...(verRecetas ? [{
      id: 'recetas' as const,
      titulo: 'Recetas',
      descripcion: 'Emitidas, PDF y anulación',
      icon: Pill,
      total: recetas.data?.count ?? null,
    }] : []),
    ...(accesoClinico ? [
      {
        id: 'signos' as const,
        titulo: 'Signos y mediciones',
        descripcion: 'Peso, presión, glucosa y tendencias',
        icon: Activity,
        total: signos.data?.count ?? null,
      },
      {
        id: 'libro' as const,
        titulo: 'Libro clínico',
        descripcion: 'Evoluciones y notas por visita',
        icon: BookOpen,
        total: evoluciones.data?.count ?? null,
      },
      {
        id: 'diagnosticos' as const,
        titulo: 'Diagnósticos',
        descripcion: 'Presuntivos y definitivos (CIE-10)',
        icon: Stethoscope,
        total: diagnosticos.data?.count ?? null,
      },
      {
        // Se consulta de vez en cuando (al abrir expediente nuevo o ante una
        // duda), no en cada visita: por eso deja de ir primera.
        id: 'historia' as const,
        titulo: 'Historia clínica',
        descripcion: 'Antecedentes, padecimiento actual y exploración basal',
        icon: FileHeart,
        total: null,
      },
    ] : []),
    ...(verCitas ? [{
      id: 'citas' as const,
      titulo: 'Citas',
      descripcion: 'Próxima cita e historial',
      icon: CalendarClock,
      total: citas.data?.count ?? null,
    }] : []),
    ...(verCalendarizacion ? [{
      id: 'calendarizacion' as const,
      titulo: 'Calendarización',
      descripcion: 'Sesiones de tratamiento programadas',
      icon: ListChecks,
      total: null,
    }] : []),
  ]

  return (
    <div>
      <h3 className="text-sm font-semibold uppercase tracking-wide text-suave mb-3">
        Secciones del expediente
      </h3>

      {/*
        Rejilla de iconos: el nombre aparece al pasar el cursor.
        
        El riesgo conocido de un menú solo-iconos es que "libro clínico",
        "signos" y "diagnósticos" no tienen icono convencional, así que hay que
        cazarlos hasta aprendérselos. Tres cosas lo amortiguan:
          · el CONTADOR se ve siempre — distingue las secciones con contenido de
            las vacías sin necesidad de leer nada;
          · el nombre está en `aria-label`, así que teclado y lectores de
            pantalla nunca dependen del hover;
          · en táctil el nombre se muestra SIEMPRE (`.solo-hover`), porque ahí
            no hay cursor que pasar por encima.
      */}
      <div className="grid grid-cols-3 sm:grid-cols-4 gap-2.5">
        {items.map(item => (
          <button
            key={item.id}
            type="button"
            onClick={() => onAbrir(item.id)}
            aria-label={`${item.titulo}${item.total !== null ? ` (${item.total})` : ''} — ${item.descripcion}`}
            className="group relative flex flex-col items-center justify-center gap-1 h-24 rounded-2xl
                       bg-superficie border border-borde
                       hover:border-accion-borde hover:bg-accion-tinte hover:-translate-y-0.5
                       focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accion focus-visible:ring-offset-1
                       transition-all duration-150"
          >
            {/* El contador SÍ se ve siempre: es lo que separa una sección con
                contenido de una vacía de un solo vistazo. */}
            {item.total !== null && (
              <span
                className="absolute top-1.5 right-1.5 min-w-[1.25rem] px-1 text-[11px] font-bold rounded-full leading-tight"
                style={
                  item.total > 0
                    ? { background: 'var(--accion-tinte)', color: 'var(--accion)' }
                    : { background: 'var(--superficie-sutil)', color: 'var(--tenue)' }
                }
              >
                {item.total}
              </span>
            )}

            <item.icon className="w-7 h-7 shrink-0 text-borde-fuerte group-hover:text-accion transition-colors" />

            {/* Alto reservado: la etiqueta aparece y desaparece sin mover nada. */}
            <span className="h-4 w-full px-1 flex items-end justify-center">
              <span className="solo-hover opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100
                               transition-opacity duration-150
                               text-[11px] font-semibold text-accion leading-none truncate max-w-full">
                {item.titulo}
              </span>
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}
