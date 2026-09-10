/**
 * Caja — «¿Qué cobro hoy y cómo cerró el día?»
 *
 * Junta lo que antes eran dos pestañas separadas, "Cobros y pagos" y "Cierre
 * diario". No son dos trabajos: son el mismo momento del día. Cobras durante la
 * jornada y al final cierras; separarlas obligaba a recepción a saltar de
 * pestaña para hacer una sola tarea.
 *
 * Orden deliberado: primero COBRAR (lo que se hace muchas veces al día), y el
 * corte al final (una vez, al cerrar). Lo más frecuente arriba.
 *
 * Control interno que conviene no perder de vista: recepción puede REGISTRAR
 * PAGOS pero no crear ni cancelar cargos (`registerPayment` vs `createCharge`
 * en la matriz de permisos). Quien recibe el dinero no decide cuánto se debe.
 * El backend es la autoridad; esto solo refleja lo mismo en la UI.
 */

import { useState } from 'react'
import { ChevronDown, Wallet, CalendarClock } from 'lucide-react'
import CobrosPagosTab from './CobrosPagosTab'
import CierreDiarioTab from './CierreDiarioTab'
import { can, type ClinicRole } from '../../auth/permisos'

export default function CajaTab({ role }: { role: ClinicRole }) {
  // El corte se consulta una vez al día: arranca plegado para no empujar el
  // cobro —que es lo que se usa a cada rato— fuera de la pantalla.
  const [cierreAbierto, setCierreAbierto] = useState(false)

  const puedeCerrarCaja = can(role, 'registerPayment')

  return (
    <div className="space-y-4">
      <section>
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-suave mb-3">
          <Wallet className="w-4 h-4 text-borde-fuerte" /> Cobros del día
        </h2>
        <CobrosPagosTab role={role} />
      </section>

      {puedeCerrarCaja && (
        <section>
          <button
            type="button"
            onClick={() => setCierreAbierto(v => !v)}
            aria-expanded={cierreAbierto}
            className="w-full flex items-center gap-2 rounded-2xl px-4 py-3 bg-superficie border border-borde
                       hover:border-accion-borde hover:bg-accion-tinte transition-colors text-left"
          >
            <CalendarClock className="w-4 h-4 shrink-0 text-borde-fuerte" />
            <span className="flex-1 text-sm font-semibold text-tinta">Cierre de caja</span>
            <span className="text-xs text-suave">
              {cierreAbierto ? 'Ocultar' : 'Ver el corte del día'}
            </span>
            <ChevronDown
              className={`w-4 h-4 shrink-0 text-suave transition-transform ${cierreAbierto ? 'rotate-180' : ''}`}
            />
          </button>

          {cierreAbierto && (
            <div className="mt-3">
              <CierreDiarioTab role={role} />
            </div>
          )}
        </section>
      )}
    </div>
  )
}
