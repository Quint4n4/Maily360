/**
 * SeccionSucursales — gestión de las sucursales (sedes) de la clínica (multi-sede,
 * Fase 1). El dueño/admin crea/edita/elimina sedes (nombre, dirección, teléfono,
 * color). La sucursal principal se marca como informativo (no se cambia desde
 * aquí en F1: el backend la administra con acciones dedicadas).
 *
 * Permisos (UX; el backend es la autoridad): gestión solo owner/admin → si el
 * usuario no puede, el backend responde 403 y la UI lo muestra sin romperse.
 *
 * Reúsa el patrón de SeccionEquipo: listado, alta, edición inline, estados.
 */

import { useMemo, useState } from 'react'
import { Building2, Check, Loader2, MapPin, Pencil, Phone, Plus, Save, X } from 'lucide-react'

import {
  useActualizarSucursal,
  useCrearSucursal,
  useEliminarSucursal,
  useSucursales,
} from '../../hooks/sucursales'
import type { Sucursal, SucursalCreateInput } from '../../types/sucursal'
import { erroresDe } from '../../lib/apiErrors'
import { AlertaErrores, AvisoSoloLectura, Nota } from './Avisos'
import { useConfirm } from '../common/DialogProvider'

interface Props {
  editable: boolean
}

/** Borrador del formulario (todos texto; se limpian al enviar). */
interface Borrador {
  name: string
  address: string
  phone: string
  color_hex: string
}

const COLORES = ['#C9A227', '#3A6EA5', '#2E7D5B', '#B23A48', '#7E57C2', '#E8924E', '#0E9594', '#8A6A14']

const BORRADOR_VACIO: Borrador = { name: '', address: '', phone: '', color_hex: COLORES[0] }

function borradorDe(s: Sucursal): Borrador {
  return { name: s.name, address: s.address, phone: s.phone, color_hex: s.color_hex || COLORES[0] }
}

/** Valida el borrador (UX) y lo convierte al payload. */
function aPayload(b: Borrador): { input: SucursalCreateInput } | { errores: string[] } {
  const errores: string[] = []
  const name = b.name.trim()
  if (!name) errores.push('Escribe el nombre de la sucursal.')
  if (errores.length) return { errores }
  return {
    input: {
      name,
      address: b.address.trim(),
      phone: b.phone.trim(),
      color_hex: b.color_hex,
    },
  }
}

export default function SeccionSucursales({ editable }: Props) {
  const sucursalesQ = useSucursales()
  const crear = useCrearSucursal()
  const actualizar = useActualizarSucursal()
  const eliminar = useEliminarSucursal()
  const confirmar = useConfirm()

  const [errores, setErrores] = useState<string[]>([])
  const [agregando, setAgregando] = useState(false)
  const [nuevo, setNuevo] = useState<Borrador>(BORRADOR_VACIO)
  const [editId, setEditId] = useState<string | null>(null)
  const [edicion, setEdicion] = useState<Borrador>(BORRADOR_VACIO)

  // La principal primero, luego por nombre.
  const sucursales = useMemo(() => {
    const rows = sucursalesQ.data?.results ?? []
    return [...rows].sort(
      (a, b) => Number(b.is_default) - Number(a.is_default) || a.name.localeCompare(b.name),
    )
  }, [sucursalesQ.data])

  const onCrear = async () => {
    setErrores([])
    const r = aPayload(nuevo)
    if ('errores' in r) { setErrores(r.errores); return }
    try {
      await crear.mutateAsync(r.input)
      setNuevo(BORRADOR_VACIO)
      setAgregando(false)
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const iniciarEdicion = (s: Sucursal) => {
    setErrores([])
    setEditId(s.id)
    setEdicion(borradorDe(s))
  }

  const onGuardarEdicion = async () => {
    if (!editId) return
    setErrores([])
    const r = aPayload(edicion)
    if ('errores' in r) { setErrores(r.errores); return }
    try {
      await actualizar.mutateAsync({ id: editId, input: r.input })
      setEditId(null)
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const onEliminar = async (s: Sucursal) => {
    if (s.is_default) {
      setErrores(['No se puede eliminar la sucursal principal.'])
      return
    }
    if (!(await confirmar({
      titulo: 'Eliminar sucursal',
      mensaje: `¿Eliminar la sucursal “${s.name}”? Esta acción no se puede deshacer.`,
      peligro: true,
      textoConfirmar: 'Eliminar',
    }))) return
    setErrores([])
    try {
      await eliminar.mutateAsync(s.id)
      if (editId === s.id) setEditId(null)
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  return (
    <div className="space-y-5">
      {!editable && <AvisoSoloLectura texto="Puedes ver las sucursales, pero solo el Dueño las da de alta o edita." />}
      <Nota>
        Registra las sedes de tu clínica. La sucursal activa (selector del encabezado) determina
        qué personal y consultorios se muestran. La sede principal es la predeterminada al entrar.
      </Nota>

      <AlertaErrores errores={errores} />

      {editable && !agregando && editId === null && (
        <button className="btn-primary" onClick={() => { setAgregando(true); setErrores([]) }}>
          <Plus className="w-4 h-4" /> Agregar sucursal
        </button>
      )}

      {/* Formulario de alta */}
      {editable && agregando && (
        <EditorSucursal
          borrador={nuevo}
          setBorrador={setNuevo}
          guardando={crear.isPending}
          onGuardar={onCrear}
          onCancelar={() => { setAgregando(false); setNuevo(BORRADOR_VACIO); setErrores([]) }}
          textoGuardar="Agregar sucursal"
        />
      )}

      {/* Listado */}
      {sucursalesQ.isLoading ? (
        <div className="flex items-center justify-center py-10 text-gray-400">
          <Loader2 className="w-5 h-5 animate-spin mr-2" /> Cargando sucursales…
        </div>
      ) : sucursalesQ.isError ? (
        <AlertaErrores errores={erroresDe(sucursalesQ.error)} />
      ) : sucursales.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-10 text-gray-400">
          <Building2 className="w-8 h-8 mb-2 opacity-50" />
          <p className="text-sm">Aún no hay sucursales registradas.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {sucursales.map((s) =>
            editId === s.id ? (
              <EditorSucursal
                key={s.id}
                borrador={edicion}
                setBorrador={setEdicion}
                guardando={actualizar.isPending}
                onGuardar={onGuardarEdicion}
                onCancelar={() => { setEditId(null); setErrores([]) }}
                textoGuardar="Guardar cambios"
              />
            ) : (
              <FilaSucursal
                key={s.id}
                sucursal={s}
                editable={editable}
                onEditar={() => iniciarEdicion(s)}
                onEliminar={() => onEliminar(s)}
                ocupado={actualizar.isPending || eliminar.isPending}
              />
            ),
          )}
        </div>
      )}
    </div>
  )
}

// ── Fila de una sucursal (modo lectura) ──────────────────────────────────────

function FilaSucursal({
  sucursal, editable, onEditar, onEliminar, ocupado,
}: {
  sucursal: Sucursal
  editable: boolean
  onEditar: () => void
  onEliminar: () => void
  ocupado: boolean
}) {
  const color = sucursal.color_hex || '#C9A227'
  return (
    <div
      className="flex items-center gap-3 rounded-xl px-3.5 py-3"
      style={{
        background: sucursal.is_active ? 'rgba(255,255,255,0.72)' : 'rgba(245,245,244,0.7)',
        border: '1px solid rgba(201,162,39,0.18)',
        opacity: sucursal.is_active ? 1 : 0.7,
      }}
    >
      <span className="w-9 h-9 rounded-xl shrink-0" style={{ background: color }} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-semibold text-gray-800">{sucursal.name}</span>
          {sucursal.is_default && <span className="badge badge-success">Principal</span>}
          {!sucursal.is_active && <span className="badge badge-warning">Inactiva</span>}
        </div>
        <div className="flex items-center gap-4 text-xs text-gray-500 mt-0.5 flex-wrap">
          {sucursal.address && (
            <span className="inline-flex items-center gap-1"><MapPin className="w-3.5 h-3.5 shrink-0" /> {sucursal.address}</span>
          )}
          {sucursal.phone && (
            <span className="inline-flex items-center gap-1"><Phone className="w-3.5 h-3.5 shrink-0" /> {sucursal.phone}</span>
          )}
        </div>
      </div>
      {editable && (
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={onEditar}
            className="p-1.5 rounded-lg text-amber-700 hover:bg-amber-50 transition-colors"
            aria-label="Editar sucursal"
          >
            <Pencil className="w-4 h-4" />
          </button>
          {!sucursal.is_default && (
            <button
              onClick={onEliminar}
              disabled={ocupado}
              className="p-1.5 rounded-lg text-red-600 hover:bg-red-50 transition-colors disabled:opacity-50"
              aria-label="Eliminar sucursal"
              title="Eliminar"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      )}
    </div>
  )
}

// ── Editor de una sucursal (alta o edición) ──────────────────────────────────

function EditorSucursal({
  borrador, setBorrador, guardando, onGuardar, onCancelar, textoGuardar,
}: {
  borrador: Borrador
  setBorrador: (b: Borrador) => void
  guardando: boolean
  onGuardar: () => void
  onCancelar: () => void
  textoGuardar: string
}) {
  const set = <K extends keyof Borrador>(key: K, value: Borrador[K]) =>
    setBorrador({ ...borrador, [key]: value })

  const swatches = borrador.color_hex && !COLORES.includes(borrador.color_hex)
    ? [borrador.color_hex, ...COLORES]
    : COLORES

  return (
    <div
      className="rounded-2xl p-4 space-y-3"
      style={{ background: 'rgba(255,255,255,0.85)', border: '1px solid rgba(201,162,39,0.3)' }}
    >
      <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))' }}>
        <div>
          <label className="label">Nombre</label>
          <input
            className="input"
            maxLength={150}
            placeholder="Ej. Sucursal Centro"
            value={borrador.name}
            onChange={e => set('name', e.target.value)}
          />
        </div>
        <div>
          <label className="label">Dirección</label>
          <input
            className="input"
            maxLength={255}
            placeholder="Calle, número, colonia"
            value={borrador.address}
            onChange={e => set('address', e.target.value)}
          />
        </div>
        <div>
          <label className="label">Teléfono</label>
          <input
            className="input"
            maxLength={40}
            inputMode="tel"
            placeholder="Ej. 744 123 4567"
            value={borrador.phone}
            onChange={e => set('phone', e.target.value)}
          />
        </div>
      </div>

      <div>
        <label className="label">Color</label>
        <div className="flex flex-wrap gap-2.5 mt-1">
          {swatches.map(c => (
            <button
              key={c}
              type="button"
              onClick={() => set('color_hex', c)}
              className="w-9 h-9 rounded-full flex items-center justify-center transition-transform hover:scale-110"
              style={{ background: c, boxShadow: borrador.color_hex === c ? `0 0 0 3px #fff, 0 0 0 5px ${c}` : 'none' }}
            >
              {borrador.color_hex === c && <Check className="w-4 h-4 text-white" />}
            </button>
          ))}
        </div>
      </div>

      <div className="flex items-center justify-end gap-2 pt-1">
        <button className="btn-secondary" onClick={onCancelar} disabled={guardando}>
          <X className="w-4 h-4" /> Cancelar
        </button>
        <button className="btn-primary" onClick={onGuardar} disabled={guardando}>
          {guardando ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          {textoGuardar}
        </button>
      </div>
    </div>
  )
}
