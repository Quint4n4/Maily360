/**
 * Selector (casillas) y badge de SUCURSALES para servicios y paquetes (multi-sede).
 *
 * Convención de negocio (definida por el dueño): cada servicio/paquete lleva la
 * lista de sedes DONDE está disponible. **Lista vacía = "Todas las sedes"** (toda
 * la clínica). El precio es único — no hay precio por sede. Solo el dueño edita:
 * esto es UX, el backend es la autoridad de permisos.
 *
 * Se comparte entre SeccionServicios (Mi Consultorio) y PaquetesPage para no
 * duplicar la misma UI/convención en dos lugares.
 */

import type { SucursalBrief, SucursalRef } from '../../types/sucursal'

/**
 * Casillas para elegir en qué sedes está disponible un servicio/paquete.
 * Devuelve `null` si la clínica no usa sucursales (lista de permitidas vacía).
 */
export function SelectorSedes({
  sucursales,
  seleccion,
  onChange,
  disabled = false,
}: {
  /** Sedes permitidas del usuario (de `useSucursalActiva().sucursales`). */
  sucursales: SucursalBrief[]
  /** Ids marcados. Vacío = "Todas las sedes". */
  seleccion: string[]
  onChange: (ids: string[]) => void
  disabled?: boolean
}) {
  // Clínica de una sola sede (no usa multi-sede): no mostrar el selector.
  if (sucursales.length === 0) return null

  const todas = seleccion.length === 0

  const toggle = (id: string): void =>
    onChange(seleccion.includes(id) ? seleccion.filter((x) => x !== id) : [...seleccion, id])

  return (
    <div>
      <label className="label">Sucursales donde está disponible</label>
      <div className="flex flex-wrap items-center gap-2 mt-1">
        <button
          type="button"
          onClick={() => onChange([])}
          disabled={disabled || todas}
          className={`px-3 py-1.5 rounded-lg text-xs font-medium ring-1 transition-colors disabled:opacity-100 ${
            todas
              ? 'bg-amber-50 text-amber-800 ring-amber-300'
              : 'bg-white/60 text-gray-600 ring-gray-200 hover:bg-amber-50'
          }`}
        >
          Todas las sedes
        </button>
        {sucursales.map((s) => {
          const marcada = seleccion.includes(s.id)
          return (
            <label
              key={s.id}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium ring-1 cursor-pointer transition-colors ${
                marcada
                  ? 'bg-amber-50 text-amber-800 ring-amber-300'
                  : 'bg-white/60 text-gray-600 ring-gray-200 hover:bg-amber-50'
              } ${disabled ? 'opacity-60 pointer-events-none' : ''}`}
            >
              <input
                type="checkbox"
                className="accent-amber-600"
                checked={marcada}
                disabled={disabled}
                onChange={() => toggle(s.id)}
              />
              {s.name}
            </label>
          )
        })}
      </div>
      <p className="text-[11px] text-gray-400 mt-1">
        Si no marcas ninguna, estará disponible en <strong>todas las sedes</strong>. El precio es el
        mismo en todas.
      </p>
    </div>
  )
}

/** Badge que resume en qué sedes está disponible (o "Todas las sedes" si viene vacío). */
export function BadgeSedes({ sucursales }: { sucursales: SucursalRef[] }) {
  if (sucursales.length === 0) {
    return <span className="badge badge-neutral">Todas las sedes</span>
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {sucursales.map((s) => (
        <span key={s.id} className="badge badge-neutral">
          {s.name}
        </span>
      ))}
    </span>
  )
}
