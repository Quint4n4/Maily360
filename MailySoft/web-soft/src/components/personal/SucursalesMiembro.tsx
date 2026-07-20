/**
 * Editor de SUCURSALES ASIGNADAS a un miembro de la clínica (multi-sede, Fase 4).
 *
 * Asignar sedes a un usuario es lo que lo acota: las sucursales marcadas son las
 * únicas que ese usuario puede ver y operar (agenda, personal, finanzas). Un
 * ADMINISTRADOR con una sola sede asignada = "administrador de esa sucursal".
 * El Dueño ve todas las sedes siempre (el backend no lo acota).
 *
 * Permisos: solo owner/admin ven este editor (esto es UX; el BACKEND es la
 * autoridad). Un admin solo puede otorgar/quitar sedes que él mismo tiene
 * permitidas: si intenta otra, el backend responde 400/403 y aquí se muestra su
 * mensaje tal cual.
 */

import { useEffect, useState } from 'react'
import { AlertCircle, Building2, Check, Loader2 } from 'lucide-react'

import { useAuth } from '../../auth/AuthContext'
import { useGuardarMembershipSucursales, useMembershipSucursales, useSucursales } from '../../hooks/sucursales'
import { erroresDe } from '../../lib/apiErrors'
import { ApiError } from '../../lib/http'
import type { Member } from '../../types/personal'

interface Props {
  miembro: Member
  /** true si la membresía mostrada es la del usuario actual (cambia sus propias sedes). */
  esYoMismo: boolean
}

/**
 * Mensajes de error a mostrar. A diferencia de `erroresDe`, un 403 con `detail`
 * del backend se muestra TAL CUAL (el backend explica por qué: p. ej. un admin
 * intentando otorgar una sede que él no tiene).
 */
function mensajesDe(err: unknown): string[] {
  if (err instanceof ApiError && err.status === 403) {
    const detail = err.body?.detail
    if (detail) return Array.isArray(detail) ? detail : [String(detail)]
  }
  return erroresDe(err, 'No se pudieron guardar las sucursales.')
}

export default function SucursalesMiembro({ miembro, esYoMismo }: Props) {
  const { clinicRole } = useAuth()
  const puedeAsignar = clinicRole === 'owner' || clinicRole === 'admin'

  const { data: sucData, isLoading: cargandoSucs } = useSucursales()
  const { data: asignadas, isLoading: cargandoAsig, isError } = useMembershipSucursales(
    miembro.id,
    puedeAsignar,
  )
  const guardar = useGuardarMembershipSucursales()

  const [sel, setSel] = useState<string[]>([])
  const [errores, setErrores] = useState<string[]>([])
  const [okMsg, setOkMsg] = useState('')

  // Sembrar la selección con lo que el backend tiene asignado hoy. Depende del
  // id del miembro + de la respuesta del GET, no del objeto, para no pisar lo
  // que el usuario está marcando en un refetch.
  useEffect(() => {
    setErrores([])
    setOkMsg('')
    setSel((asignadas?.sucursales ?? []).map(s => s.id))
  }, [miembro.id, asignadas])

  if (!puedeAsignar) return null

  const disponibles = (sucData?.results ?? []).filter(s => s.is_active)

  const toggle = (id: string) => {
    setOkMsg('')
    setSel(v => (v.includes(id) ? v.filter(x => x !== id) : [...v, id]))
  }

  const onGuardar = async () => {
    setErrores([])
    setOkMsg('')
    try {
      await guardar.mutateAsync({
        membershipId: miembro.id,
        input: { sucursal_ids: sel },
        esYoMismo,
      })
      setOkMsg('Sucursales actualizadas.')
    } catch (err) {
      setErrores(mensajesDe(err))
    }
  }

  const cargando = cargandoSucs || cargandoAsig

  return (
    <div className="mt-4 pt-4 border-t border-amber-900/10">
      <p className="text-xs font-semibold uppercase tracking-wide text-amber-700/80 mb-2 flex items-center gap-2">
        <Building2 className="w-4 h-4" /> Sucursales de este usuario
      </p>
      <p className="text-[11px] text-gray-500 leading-relaxed mb-3">
        Las sucursales que asignes definen qué sedes puede <strong>ver y operar</strong> este usuario.
        Un administrador asignado a una sola sede = <strong>administrador de esa sucursal</strong>.
        {miembro.role === 'owner' && ' El Dueño siempre ve todas las sedes.'}
      </p>

      {errores.length > 0 && (
        <div
          className="flex items-start gap-2.5 rounded-xl px-4 py-3 mb-3"
          style={{ background: 'rgba(190,40,40,0.10)', border: '1px solid rgba(190,40,40,0.25)' }}
        >
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-500" />
          <ul className="text-xs text-red-700 space-y-0.5 list-disc list-inside">
            {errores.map((e, i) => <li key={i}>{e}</li>)}
          </ul>
        </div>
      )}
      {okMsg && (
        <div
          className="flex items-center gap-2 rounded-xl px-4 py-3 mb-3 text-sm"
          style={{ background: '#E7F6EE', color: '#1F6E47' }}
        >
          <Check className="w-4 h-4 shrink-0" /> {okMsg}
        </div>
      )}

      {cargando ? (
        <div className="flex items-center gap-2 text-xs text-amber-700">
          <Loader2 className="w-4 h-4 animate-spin" /> Cargando sucursales…
        </div>
      ) : isError ? (
        <p className="text-xs text-red-600">No se pudieron cargar las sucursales de este usuario.</p>
      ) : disponibles.length === 0 ? (
        <p className="text-xs text-gray-400">
          No hay sucursales activas. Créalas en Mi Consultorio → Sucursales.
        </p>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            {disponibles.map(s => {
              const on = sel.includes(s.id)
              return (
                <button
                  key={s.id}
                  type="button"
                  role="checkbox"
                  aria-checked={on}
                  onClick={() => toggle(s.id)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold transition-all"
                  style={on
                    ? { background: '#C9A227', color: '#fff' }
                    : { background: 'rgba(255,255,255,0.6)', color: '#7A756C', border: '1px solid rgba(201,162,39,0.3)' }}
                >
                  {on && <Check className="w-3.5 h-3.5" />} {s.name}
                  {s.is_default && <span className="opacity-70">(principal)</span>}
                </button>
              )
            })}
          </div>
          {sel.length === 0 && (
            <p className="text-[11px] text-gray-400 mt-1.5">
              Sin sedes asignadas: el usuario solo verá la sucursal principal de la clínica.
            </p>
          )}
          <button
            onClick={onGuardar}
            disabled={guardar.isPending}
            className="w-full mt-3 inline-flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-60"
            style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
          >
            {guardar.isPending
              ? <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</>
              : 'Guardar sucursales del usuario'}
          </button>
        </>
      )}
    </div>
  )
}
