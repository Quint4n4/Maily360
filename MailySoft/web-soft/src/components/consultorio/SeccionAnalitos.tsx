/**
 * SeccionAnalitos — catálogo de analitos de laboratorio (Fase 3). El dueño/admin
 * define aquí los parámetros (nombre, unidad y rango de referencia) que luego el
 * médico elige al capturar los resultados de laboratorio del Plan Integral.
 *
 * Permisos (UX; el backend es la autoridad): gestión solo owner/admin → si el
 * usuario no puede, el backend responde 403 y la UI lo muestra sin romperse.
 *
 * Reúsa el patrón de SeccionServicios: listado, alta, edición inline, estados.
 */

import { useMemo, useState } from 'react'
import { FlaskConical, Loader2, Pencil, Plus, Power, Save, X } from 'lucide-react'

import {
  useActualizarAnalito,
  useAnalitos,
  useCrearAnalito,
  useEliminarAnalito,
} from '../../hooks/analitos'
import type { Analito, AnalitoCreateInput } from '../../types/analitos'
import { erroresDe } from '../../lib/apiErrors'
import { AlertaErrores, AvisoSoloLectura, Nota } from './Avisos'
import { useConfirm } from '../common/DialogProvider'

interface Props {
  editable: boolean
}

/** Borrador del formulario. Los rangos se capturan como texto (decimal opcional). */
interface Borrador {
  name: string
  unit: string
  ref_low: string
  ref_high: string
}

const BORRADOR_VACIO: Borrador = { name: '', unit: '', ref_low: '', ref_high: '' }

function borradorDe(a: Analito): Borrador {
  return {
    name: a.name,
    unit: a.unit,
    ref_low: a.ref_low ?? '',
    ref_high: a.ref_high ?? '',
  }
}

/**
 * Quita los ceros de relleno de un decimal ("70.0000" -> "70", "5.70" -> "5.7").
 * El backend guarda el rango con 4 decimales; se ve poco profesional mostrarlos.
 */
export function fmtRango(v: string | null): string | null {
  if (v == null || v.trim() === '') return null
  const n = Number(v)
  if (!Number.isFinite(n)) return v
  return String(n)
}

/** Muestra el rango de referencia legible (o "—" si no hay). */
export function rangoTexto(refLow: string | null, refHigh: string | null): string {
  const low = fmtRango(refLow)
  const high = fmtRango(refHigh)
  if (low != null && high != null) return `${low} – ${high}`
  if (low != null) return `≥ ${low}`
  if (high != null) return `≤ ${high}`
  return '—'
}

/** Valida el borrador (UX) y lo convierte al payload. Los rangos van string|null. */
function aPayload(b: Borrador): { input: AnalitoCreateInput } | { errores: string[] } {
  const errores: string[] = []
  const name = b.name.trim()
  if (!name) errores.push('Escribe el nombre del analito.')
  const low = b.ref_low.trim()
  const high = b.ref_high.trim()
  if (low !== '' && !Number.isFinite(Number(low))) errores.push('El límite inferior debe ser un número.')
  if (high !== '' && !Number.isFinite(Number(high))) errores.push('El límite superior debe ser un número.')
  if (low !== '' && high !== '' && Number.isFinite(Number(low)) && Number.isFinite(Number(high)) && Number(low) > Number(high)) {
    errores.push('El límite inferior no puede ser mayor que el superior.')
  }
  if (errores.length) return { errores }
  return {
    input: {
      name,
      unit: b.unit.trim(),
      ref_low: low === '' ? null : low,
      ref_high: high === '' ? null : high,
    },
  }
}

export default function SeccionAnalitos({ editable }: Props) {
  // Incluye inactivos para poder reactivarlos desde el panel de gestión.
  const analitosQ = useAnalitos({ onlyActive: false })
  const crear = useCrearAnalito()
  const actualizar = useActualizarAnalito()
  const eliminar = useEliminarAnalito()
  const confirmar = useConfirm()

  const [errores, setErrores] = useState<string[]>([])
  const [agregando, setAgregando] = useState(false)
  const [nuevo, setNuevo] = useState<Borrador>(BORRADOR_VACIO)
  const [editId, setEditId] = useState<string | null>(null)
  const [edicion, setEdicion] = useState<Borrador>(BORRADOR_VACIO)

  const analitos = useMemo(() => analitosQ.data?.results ?? [], [analitosQ.data])

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

  const iniciarEdicion = (a: Analito) => {
    setErrores([])
    setEditId(a.id)
    setEdicion(borradorDe(a))
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

  const onDesactivar = async (a: Analito) => {
    if (!(await confirmar({
      titulo: 'Desactivar analito',
      mensaje: `¿Desactivar “${a.name}”? Ya no aparecerá al capturar resultados de laboratorio, pero podrás reactivarlo.`,
      peligro: true,
      textoConfirmar: 'Desactivar',
    }))) return
    setErrores([])
    try {
      await actualizar.mutateAsync({ id: a.id, input: { is_active: false } })
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const onReactivar = async (a: Analito) => {
    setErrores([])
    try {
      await actualizar.mutateAsync({ id: a.id, input: { is_active: true } })
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const onEliminar = async (a: Analito) => {
    if (!(await confirmar({
      titulo: 'Eliminar analito',
      mensaje: `¿Eliminar el analito “${a.name}”? Esta acción no se puede deshacer.`,
      peligro: true,
      textoConfirmar: 'Eliminar',
    }))) return
    setErrores([])
    try {
      await eliminar.mutateAsync(a.id)
      if (editId === a.id) setEditId(null)
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  return (
    <div className="space-y-5">
      {!editable && <AvisoSoloLectura texto="Puedes ver los analitos, pero solo Dueño/Administrador los edita." />}
      <Nota>
        Define aquí los parámetros de laboratorio (p. ej. “Glucosa”, “Colesterol total”) con su unidad
        y rango de referencia. Al capturar el Plan Integral, el médico elige un analito y el resultado se
        marca en rojo si cae fuera del rango.
      </Nota>

      <AlertaErrores errores={errores} />

      {editable && !agregando && editId === null && (
        <button className="btn-primary" onClick={() => { setAgregando(true); setErrores([]) }}>
          <Plus className="w-4 h-4" /> Agregar analito
        </button>
      )}

      {/* Formulario de alta */}
      {editable && agregando && (
        <EditorAnalito
          borrador={nuevo}
          setBorrador={setNuevo}
          guardando={crear.isPending}
          onGuardar={onCrear}
          onCancelar={() => { setAgregando(false); setNuevo(BORRADOR_VACIO); setErrores([]) }}
          textoGuardar="Crear analito"
        />
      )}

      {/* Listado */}
      {analitosQ.isLoading ? (
        <div className="flex items-center justify-center py-10 text-gray-400">
          <Loader2 className="w-5 h-5 animate-spin mr-2" /> Cargando analitos…
        </div>
      ) : analitosQ.isError ? (
        <AlertaErrores errores={erroresDe(analitosQ.error)} />
      ) : analitos.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-10 text-gray-400">
          <FlaskConical className="w-8 h-8 mb-2 opacity-50" />
          <p className="text-sm">Aún no hay analitos en el catálogo.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {analitos.map((a) =>
            editId === a.id ? (
              <EditorAnalito
                key={a.id}
                borrador={edicion}
                setBorrador={setEdicion}
                guardando={actualizar.isPending}
                onGuardar={onGuardarEdicion}
                onCancelar={() => { setEditId(null); setErrores([]) }}
                textoGuardar="Guardar cambios"
              />
            ) : (
              <FilaAnalito
                key={a.id}
                analito={a}
                editable={editable}
                onEditar={() => iniciarEdicion(a)}
                onDesactivar={() => onDesactivar(a)}
                onReactivar={() => onReactivar(a)}
                onEliminar={() => onEliminar(a)}
                ocupado={actualizar.isPending || eliminar.isPending}
              />
            ),
          )}
        </div>
      )}
    </div>
  )
}

// ── Fila de un analito (modo lectura) ────────────────────────────────────────

function FilaAnalito({
  analito, editable, onEditar, onDesactivar, onReactivar, onEliminar, ocupado,
}: {
  analito: Analito
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
        background: analito.is_active ? 'rgba(255,255,255,0.72)' : 'rgba(245,245,244,0.7)',
        border: '1px solid rgba(201,162,39,0.18)',
        opacity: analito.is_active ? 1 : 0.7,
      }}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium text-gray-800">{analito.name}</span>
          {analito.unit && <span className="text-xs text-gray-400">{analito.unit}</span>}
          {!analito.is_active && <span className="badge badge-warning">Inactivo</span>}
        </div>
        <p className="text-[11px] text-gray-400 mt-0.5">
          Rango de referencia: {rangoTexto(analito.ref_low, analito.ref_high)}
          {analito.unit ? ` ${analito.unit}` : ''}
        </p>
      </div>
      {editable && (
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={onEditar}
            className="p-1.5 rounded-lg text-amber-700 hover:bg-amber-50 transition-colors"
            aria-label="Editar analito"
          >
            <Pencil className="w-4 h-4" />
          </button>
          {analito.is_active ? (
            <button
              onClick={onDesactivar}
              disabled={ocupado}
              className="p-1.5 rounded-lg text-amber-700 hover:bg-amber-50 transition-colors disabled:opacity-50"
              aria-label="Desactivar analito"
              title="Desactivar"
            >
              <Power className="w-4 h-4" />
            </button>
          ) : (
            <button
              onClick={onReactivar}
              disabled={ocupado}
              className="p-1.5 rounded-lg text-emerald-700 hover:bg-emerald-50 transition-colors disabled:opacity-50"
              aria-label="Reactivar analito"
              title="Reactivar"
            >
              <Power className="w-4 h-4" />
            </button>
          )}
          <button
            onClick={onEliminar}
            disabled={ocupado}
            className="p-1.5 rounded-lg text-red-600 hover:bg-red-50 transition-colors disabled:opacity-50"
            aria-label="Eliminar analito"
            title="Eliminar"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  )
}

// ── Editor de un analito (alta o edición) ────────────────────────────────────

function EditorAnalito({
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
        <div className="sm:col-span-full">
          <label className="label">Nombre del analito</label>
          <input
            className="input"
            maxLength={150}
            placeholder="Ej. Glucosa"
            value={borrador.name}
            onChange={e => set('name', e.target.value)}
          />
        </div>
        <div>
          <label className="label">Unidad</label>
          <input
            className="input"
            maxLength={50}
            placeholder="Ej. mg/dL"
            value={borrador.unit}
            onChange={e => set('unit', e.target.value)}
          />
        </div>
        <div>
          <label className="label">Límite inferior</label>
          <input
            className="input"
            type="number"
            step="any"
            placeholder="Ej. 70"
            value={borrador.ref_low}
            onChange={e => set('ref_low', e.target.value)}
          />
        </div>
        <div>
          <label className="label">Límite superior</label>
          <input
            className="input"
            type="number"
            step="any"
            placeholder="Ej. 100"
            value={borrador.ref_high}
            onChange={e => set('ref_high', e.target.value)}
          />
        </div>
      </div>
      <p className="text-[11px] text-gray-400">
        Los límites son opcionales: deja vacío el que no aplique (p. ej. solo un tope máximo).
      </p>

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
