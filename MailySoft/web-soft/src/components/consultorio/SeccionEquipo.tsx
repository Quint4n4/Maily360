/**
 * SeccionEquipo — equipo / departamentos de la clínica (Fase 4). El dueño/admin
 * registra los integrantes por departamento (p. ej. “Nutrición — Dra. Pérez”)
 * que se muestran en el Plan Integral del paciente (el backend los snapshotea).
 *
 * Permisos (UX; el backend es la autoridad): gestión solo owner/admin → si el
 * usuario no puede, el backend responde 403 y la UI lo muestra sin romperse.
 *
 * Reúsa el patrón de SeccionServicios: listado, alta, edición inline, estados.
 */

import { useMemo, useState } from 'react'
import { Loader2, Pencil, Plus, Power, Save, Users, X } from 'lucide-react'

import {
  useActualizarEquipoMiembro,
  useCrearEquipoMiembro,
  useEliminarEquipoMiembro,
  useEquipo,
} from '../../hooks/equipo'
import type { EquipoMiembro, EquipoMiembroCreateInput } from '../../types/equipo'
import { erroresDe } from '../../lib/apiErrors'
import { AlertaErrores, AvisoSoloLectura, Nota } from './Avisos'
import { useConfirm } from '../common/DialogProvider'

interface Props {
  editable: boolean
}

/** Borrador del formulario. `order` se captura como texto (entero opcional). */
interface Borrador {
  departamento: string
  nombre: string
  order: string
}

const BORRADOR_VACIO: Borrador = { departamento: '', nombre: '', order: '' }

function borradorDe(m: EquipoMiembro): Borrador {
  return { departamento: m.departamento, nombre: m.nombre, order: String(m.order) }
}

/** Valida el borrador (UX) y lo convierte al payload. */
function aPayload(b: Borrador): { input: EquipoMiembroCreateInput } | { errores: string[] } {
  const errores: string[] = []
  const departamento = b.departamento.trim()
  const nombre = b.nombre.trim()
  if (!departamento) errores.push('Escribe el departamento.')
  if (!nombre) errores.push('Escribe el nombre del integrante.')
  const orderNum = b.order.trim() === '' ? undefined : Math.floor(Number(b.order))
  if (orderNum !== undefined && !Number.isFinite(orderNum)) errores.push('El orden debe ser un número.')
  if (errores.length) return { errores }
  return { input: { departamento, nombre, ...(orderNum !== undefined ? { order: orderNum } : {}) } }
}

export default function SeccionEquipo({ editable }: Props) {
  const equipoQ = useEquipo({ onlyActive: false })
  const crear = useCrearEquipoMiembro()
  const actualizar = useActualizarEquipoMiembro()
  const eliminar = useEliminarEquipoMiembro()
  const confirmar = useConfirm()

  const [errores, setErrores] = useState<string[]>([])
  const [agregando, setAgregando] = useState(false)
  const [nuevo, setNuevo] = useState<Borrador>(BORRADOR_VACIO)
  const [editId, setEditId] = useState<string | null>(null)
  const [edicion, setEdicion] = useState<Borrador>(BORRADOR_VACIO)

  // Ordena por `order` y luego por departamento (coherente con el Plan Integral).
  const miembros = useMemo(() => {
    const rows = equipoQ.data?.results ?? []
    return [...rows].sort((a, b) => a.order - b.order || a.departamento.localeCompare(b.departamento))
  }, [equipoQ.data])

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

  const iniciarEdicion = (m: EquipoMiembro) => {
    setErrores([])
    setEditId(m.id)
    setEdicion(borradorDe(m))
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

  const onDesactivar = async (m: EquipoMiembro) => {
    if (!(await confirmar({
      titulo: 'Desactivar integrante',
      mensaje: `¿Desactivar a “${m.nombre}” (${m.departamento})? Ya no aparecerá en el Plan Integral, pero podrás reactivarlo.`,
      peligro: true,
      textoConfirmar: 'Desactivar',
    }))) return
    setErrores([])
    try {
      await actualizar.mutateAsync({ id: m.id, input: { is_active: false } })
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const onReactivar = async (m: EquipoMiembro) => {
    setErrores([])
    try {
      await actualizar.mutateAsync({ id: m.id, input: { is_active: true } })
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const onEliminar = async (m: EquipoMiembro) => {
    if (!(await confirmar({
      titulo: 'Eliminar integrante',
      mensaje: `¿Eliminar a “${m.nombre}” (${m.departamento})? Esta acción no se puede deshacer.`,
      peligro: true,
      textoConfirmar: 'Eliminar',
    }))) return
    setErrores([])
    try {
      await eliminar.mutateAsync(m.id)
      if (editId === m.id) setEditId(null)
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  return (
    <div className="space-y-5">
      {!editable && <AvisoSoloLectura texto="Puedes ver el equipo, pero solo Dueño/Administrador lo edita." />}
      <Nota>
        Registra a los integrantes de tu clínica por departamento (p. ej. “Nutrición — Dra. Pérez”). Este
        equipo se muestra en el Plan Integral del paciente. El orden controla cómo se listan.
      </Nota>

      <AlertaErrores errores={errores} />

      {editable && !agregando && editId === null && (
        <button className="btn-primary" onClick={() => { setAgregando(true); setErrores([]) }}>
          <Plus className="w-4 h-4" /> Agregar integrante
        </button>
      )}

      {/* Formulario de alta */}
      {editable && agregando && (
        <EditorMiembro
          borrador={nuevo}
          setBorrador={setNuevo}
          guardando={crear.isPending}
          onGuardar={onCrear}
          onCancelar={() => { setAgregando(false); setNuevo(BORRADOR_VACIO); setErrores([]) }}
          textoGuardar="Agregar integrante"
        />
      )}

      {/* Listado */}
      {equipoQ.isLoading ? (
        <div className="flex items-center justify-center py-10 text-gray-400">
          <Loader2 className="w-5 h-5 animate-spin mr-2" /> Cargando equipo…
        </div>
      ) : equipoQ.isError ? (
        <AlertaErrores errores={erroresDe(equipoQ.error)} />
      ) : miembros.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-10 text-gray-400">
          <Users className="w-8 h-8 mb-2 opacity-50" />
          <p className="text-sm">Aún no has registrado integrantes del equipo.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {miembros.map((m) =>
            editId === m.id ? (
              <EditorMiembro
                key={m.id}
                borrador={edicion}
                setBorrador={setEdicion}
                guardando={actualizar.isPending}
                onGuardar={onGuardarEdicion}
                onCancelar={() => { setEditId(null); setErrores([]) }}
                textoGuardar="Guardar cambios"
              />
            ) : (
              <FilaMiembro
                key={m.id}
                miembro={m}
                editable={editable}
                onEditar={() => iniciarEdicion(m)}
                onDesactivar={() => onDesactivar(m)}
                onReactivar={() => onReactivar(m)}
                onEliminar={() => onEliminar(m)}
                ocupado={actualizar.isPending || eliminar.isPending}
              />
            ),
          )}
        </div>
      )}
    </div>
  )
}

// ── Fila de un integrante (modo lectura) ─────────────────────────────────────

function FilaMiembro({
  miembro, editable, onEditar, onDesactivar, onReactivar, onEliminar, ocupado,
}: {
  miembro: EquipoMiembro
  editable: boolean
  onEditar: () => void
  onDesactivar: () => void
  onReactivar: () => void
  onEliminar: () => void
  ocupado: boolean
}) {
  return (
    <div
      className="flex items-center gap-3 rounded-xl px-3.5 py-2.5"
      style={{
        background: miembro.is_active ? 'rgba(255,255,255,0.72)' : 'rgba(245,245,244,0.7)',
        border: '1px solid rgba(201,162,39,0.18)',
        opacity: miembro.is_active ? 1 : 0.7,
      }}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-semibold uppercase tracking-wide" style={{ color: '#B8860B' }}>
            {miembro.departamento}
          </span>
          <span className="text-sm font-medium text-gray-800">{miembro.nombre}</span>
          {!miembro.is_active && <span className="badge badge-warning">Inactivo</span>}
        </div>
      </div>
      {editable && (
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={onEditar}
            className="p-1.5 rounded-lg text-amber-700 hover:bg-amber-50 transition-colors"
            aria-label="Editar integrante"
          >
            <Pencil className="w-4 h-4" />
          </button>
          {miembro.is_active ? (
            <button
              onClick={onDesactivar}
              disabled={ocupado}
              className="p-1.5 rounded-lg text-amber-700 hover:bg-amber-50 transition-colors disabled:opacity-50"
              aria-label="Desactivar integrante"
              title="Desactivar"
            >
              <Power className="w-4 h-4" />
            </button>
          ) : (
            <button
              onClick={onReactivar}
              disabled={ocupado}
              className="p-1.5 rounded-lg text-emerald-700 hover:bg-emerald-50 transition-colors disabled:opacity-50"
              aria-label="Reactivar integrante"
              title="Reactivar"
            >
              <Power className="w-4 h-4" />
            </button>
          )}
          <button
            onClick={onEliminar}
            disabled={ocupado}
            className="p-1.5 rounded-lg text-red-600 hover:bg-red-50 transition-colors disabled:opacity-50"
            aria-label="Eliminar integrante"
            title="Eliminar"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  )
}

// ── Editor de un integrante (alta o edición) ─────────────────────────────────

function EditorMiembro({
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

  return (
    <div
      className="rounded-2xl p-4 space-y-3"
      style={{ background: 'rgba(255,255,255,0.85)', border: '1px solid rgba(201,162,39,0.3)' }}
    >
      <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))' }}>
        <div>
          <label className="label">Departamento</label>
          <input
            className="input"
            maxLength={120}
            placeholder="Ej. Nutrición"
            value={borrador.departamento}
            onChange={e => set('departamento', e.target.value)}
          />
        </div>
        <div>
          <label className="label">Nombre del integrante</label>
          <input
            className="input"
            maxLength={200}
            placeholder="Ej. Dra. Pérez"
            value={borrador.nombre}
            onChange={e => set('nombre', e.target.value)}
          />
        </div>
        <div>
          <label className="label">Orden</label>
          <input
            className="input"
            type="number"
            step="1"
            placeholder="0"
            value={borrador.order}
            onChange={e => set('order', e.target.value)}
          />
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
