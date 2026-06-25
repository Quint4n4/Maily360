import { useState, useRef, useEffect } from 'react'
import { Tag, Check } from 'lucide-react'
import type { PatientOut } from '../../types/paciente'
import type { PatientCategoryOut } from '../../types/clinica'
import { useUpdatePatient } from '../../hooks/pacientes'

/**
 * Botón rápido de etiquetas para la tarjeta del paciente (junto a ⭐/👑).
 * Abre un mini-menú con las etiquetas personalizadas del catálogo (checkboxes)
 * para marcar/desmarcar al instante, sin abrir el editor del paciente.
 *
 * Reusa `PATCH /pacientes/<id>/` con `category_ids` (gestiona solo las custom;
 * el backend conserva Favorito/VIP). La lista se refresca por invalidación.
 */
export default function EtiquetasQuickMenu({
  patient,
  categorias,
}: {
  patient: PatientOut
  /** Etiquetas personalizadas (kind='custom') del catálogo del tenant. */
  categorias: PatientCategoryOut[]
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const actualizar = useUpdatePatient()

  // Cerrar al hacer clic fuera del menú.
  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const asignadas = new Set(patient.categories.map((c) => c.id))

  const toggle = (catId: string) => {
    const next = new Set(asignadas)
    if (next.has(catId)) next.delete(catId)
    else next.add(catId)
    actualizar.mutate({ id: patient.id, input: { category_ids: [...next] } })
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        title="Etiquetas"
        onClick={(e) => { e.stopPropagation(); setOpen((o) => !o) }}
        className="w-7 h-7 rounded-full flex items-center justify-center transition-colors hover:bg-emerald-50"
        style={{ background: 'rgba(255,255,255,0.7)' }}
      >
        <Tag className="w-4 h-4" style={{ color: asignadas.size > 0 ? '#1D6F5C' : '#9aa0a6' }} />
      </button>

      {open && (
        <div
          onClick={(e) => e.stopPropagation()}
          className="absolute right-0 mt-1 w-52 rounded-xl shadow-xl border border-black/5 p-2 z-30"
          style={{ background: '#fff' }}
        >
          <p className="text-[11px] font-semibold text-gray-500 px-2 py-1">Etiquetas</p>
          {categorias.length === 0 ? (
            <p className="text-xs text-gray-400 px-2 py-1.5 leading-snug">
              No hay etiquetas. Créalas en Mi Consultorio → Categorías de pacientes.
            </p>
          ) : (
            <div className="max-h-56 overflow-auto">
              {categorias.map((c) => {
                const activo = asignadas.has(c.id)
                return (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => toggle(c.id)}
                    disabled={actualizar.isPending}
                    className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-sm text-left hover:bg-gray-50 disabled:opacity-50"
                  >
                    <span
                      className="w-4 h-4 rounded flex items-center justify-center shrink-0"
                      style={activo
                        ? { background: '#1D6F5C' }
                        : { border: '1.5px solid #cbd5e1' }}
                    >
                      {activo && <Check className="w-3 h-3 text-white" />}
                    </span>
                    {c.name}
                  </button>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
