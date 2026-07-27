/**
 * EditorModulos — selección de módulos, límites y roles de un plan.
 *
 * Lo que hace distinto a una lista de casillas suelta: aplica las dependencias
 * EN VIVO. Marcar "Cotizaciones" enciende "Servicios" solo; desmarcar
 * "Servicios" apaga lo que dependía de él y lo dice. Así es imposible guardar
 * un plan roto — el backend también lo valida, pero para entonces ya sería un
 * error en pantalla en vez de una corrección amable.
 *
 * Los ROLES no se capturan: se derivan de los módulos. Un rol sin su módulo es
 * un usuario que no puede trabajar (finanzas sin cobranza no administra nada).
 */

import { useState } from 'react'
import { Check, Info, Lock } from 'lucide-react'
import {
  MODULO_GRUPOS, MODULO_LABEL, MODULO_REQUIERE,
  dependientesDe, expandirDependencias, rolesDisponibles,
} from '../../lib/modulos'
import type { ModuloId } from '../../lib/modulos'
import { ROLE_LABEL } from '../../auth/permisos'
import type { ClinicRole } from '../../auth/permisos'

interface Props {
  modulos: ModuloId[]
  onChange: (modulos: ModuloId[]) => void
  maxSucursales: number | null
  maxConsultorios: number | null
  maxUsuarios: number | null
  onLimite: (campo: 'max_sucursales' | 'max_consultorios' | 'max_usuarios', valor: number | null) => void
  /** Roles que el plan ofrece (allow-list). Vacío = todos los que los módulos permitan. */
  rolesOfrecidos: ClinicRole[]
  onRolesChange: (roles: ClinicRole[]) => void
}

export default function EditorModulos({
  modulos, onChange, maxSucursales, maxConsultorios, maxUsuarios, onLimite,
  rolesOfrecidos, onRolesChange,
}: Props) {
  // Explicación del último ajuste automático, para que el cambio no sorprenda.
  const [aviso, setAviso] = useState('')

  const activos = new Set(modulos)

  const alternar = (id: ModuloId) => {
    if (activos.has(id)) {
      const arrastrados = dependientesDe(id, modulos)
      onChange(modulos.filter(m => m !== id && !arrastrados.includes(m)))
      setAviso(
        arrastrados.length
          ? `Se apagó también ${arrastrados.map(m => MODULO_LABEL[m]).join(', ')}: depende de ${MODULO_LABEL[id]}.`
          : '',
      )
    } else {
      const conDeps = expandirDependencias([...modulos, id])
      const agregados = conDeps.filter(m => !activos.has(m) && m !== id)
      onChange(conDeps)
      setAviso(
        agregados.length
          ? `Se encendió también ${agregados.map(m => MODULO_LABEL[m]).join(', ')}: ${MODULO_LABEL[id]} lo requiere.`
          : '',
      )
    }
  }

  const roles = rolesDisponibles(modulos)

  return (
    <div className="space-y-5">
      {/* ── Módulos ── */}
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-amber-700/80 mb-1">
          Módulos incluidos
        </p>
        <p className="text-[11px] text-gray-400 mb-3">
          Esto define qué ve la clínica. Las «características» de arriba son solo texto de venta.
        </p>

        <div className="space-y-4">
          {MODULO_GRUPOS.map(grupo => (
            <div key={grupo.titulo}>
              <p className="text-[11px] font-semibold text-gray-500 mb-1.5">{grupo.titulo}</p>
              <div className="grid gap-1.5" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))' }}>
                {grupo.modulos.map(id => {
                  const on = activos.has(id)
                  const requiere = MODULO_REQUIERE[id] ?? []
                  return (
                    <button
                      key={id}
                      type="button"
                      onClick={() => alternar(id)}
                      className="flex items-start gap-2 rounded-xl px-3 py-2 text-left transition-colors"
                      style={{
                        background: on ? 'rgba(201,162,39,0.10)' : 'rgba(255,255,255,0.6)',
                        border: `1px solid ${on ? 'rgba(201,162,39,0.45)' : 'rgba(0,0,0,0.08)'}`,
                      }}
                    >
                      <span
                        className="mt-0.5 w-4 h-4 rounded flex items-center justify-center shrink-0"
                        style={{
                          background: on ? '#C9A227' : 'transparent',
                          border: on ? '1px solid #C9A227' : '1px solid rgba(0,0,0,0.25)',
                        }}
                      >
                        {on && <Check className="w-3 h-3 text-white" />}
                      </span>
                      <span className="min-w-0">
                        <span className="block text-sm text-gray-800">{MODULO_LABEL[id]}</span>
                        {requiere.length > 0 && (
                          <span className="block text-[10px] text-gray-400">
                            requiere {requiere.map(r => MODULO_LABEL[r]).join(', ')}
                          </span>
                        )}
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>
          ))}
        </div>

        {aviso && (
          <p className="flex items-start gap-1.5 text-[11px] mt-3" style={{ color: '#854F0B' }}>
            <Info className="w-3.5 h-3.5 shrink-0 mt-px" /> {aviso}
          </p>
        )}
      </div>

      {/* ── Límites ── */}
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-amber-700/80 mb-3">Límites</p>
        <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))' }}>
          <CampoLimite
            label="Sucursales" valor={maxSucursales}
            onChange={v => onLimite('max_sucursales', v)}
            nota={maxSucursales === 1 ? 'Modo sede única' : undefined}
          />
          <CampoLimite
            label="Consultorios" valor={maxConsultorios}
            onChange={v => onLimite('max_consultorios', v)}
          />
          <CampoLimite
            label="Usuarios" valor={maxUsuarios}
            onChange={v => onLimite('max_usuarios', v)}
          />
        </div>
      </div>

      {/* ── Roles que ofrece el plan ── */}
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-amber-700/80 mb-1">
          Roles que ofrece el plan
        </p>
        <p className="text-[11px] text-gray-400 mb-2">
          Marca los que la clínica podrá asignar. Solo aparecen los que los módulos
          permiten (Finanzas necesita Cobranza). Sin nada marcado = todos.
        </p>
        <div className="flex flex-wrap gap-1.5">
          {(Object.keys(ROLE_LABEL) as ClinicRole[]).map(rol => {
            const derivable = roles.includes(rol)  // habilitado por los módulos
            // owner siempre va (toda clínica tiene dueño); no se puede desmarcar.
            const forzado = rol === 'owner'
            const marcado = forzado || rolesOfrecidos.includes(rol)
            if (!derivable) {
              return (
                <span key={rol} title="Requiere activar su módulo"
                  className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full"
                  style={{ background: 'rgba(0,0,0,0.04)', color: '#9ca3af' }}>
                  <Lock className="w-3 h-3" /> {ROLE_LABEL[rol]}
                </span>
              )
            }
            return (
              <button
                key={rol} type="button" disabled={forzado}
                onClick={() => onRolesChange(
                  marcado ? rolesOfrecidos.filter(r => r !== rol) : [...rolesOfrecidos, rol],
                )}
                className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full transition-colors disabled:opacity-100"
                style={{
                  background: marcado ? 'rgba(201,162,39,0.16)' : 'rgba(0,0,0,0.04)',
                  color: marcado ? '#854F0B' : '#9ca3af',
                  border: `1px solid ${marcado ? 'rgba(201,162,39,0.4)' : 'transparent'}`,
                }}
              >
                {marcado && <Check className="w-3 h-3" />}
                {ROLE_LABEL[rol]}
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}

/** Campo numérico con casilla de "ilimitado" (null). */
function CampoLimite({
  label, valor, onChange, nota,
}: {
  label: string
  valor: number | null
  onChange: (v: number | null) => void
  nota?: string
}) {
  const ilimitado = valor === null
  return (
    <div>
      <label className="label">{label}</label>
      <input
        className="input"
        type="number" min={1} inputMode="numeric"
        value={ilimitado ? '' : String(valor)}
        disabled={ilimitado}
        placeholder="Ilimitado"
        onChange={e => {
          const n = parseInt(e.target.value, 10)
          onChange(Number.isNaN(n) || n < 1 ? null : n)
        }}
      />
      <label className="flex items-center gap-1.5 mt-1 text-[11px] text-gray-500 cursor-pointer">
        <input
          type="checkbox"
          checked={ilimitado}
          onChange={e => onChange(e.target.checked ? null : 1)}
        />
        Ilimitado
      </label>
      {nota && <p className="text-[10px] mt-0.5" style={{ color: '#854F0B' }}>{nota}</p>}
    </div>
  )
}
