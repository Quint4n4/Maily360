/**
 * SeccionPlantillasDocumento — catálogo de "Plantillas de documento" (Fase 2).
 * El dueño/admin define textos reutilizables por sección (reporte médico,
 * seguimiento, interconsulta, estudios, condiciones a mejorar o general) que el
 * médico luego inserta al capturar el Plan Integral del paciente.
 *
 * Permisos (UX; el backend es la autoridad): gestión solo owner/admin → si el
 * usuario no puede, el backend responde 403 y la UI lo muestra sin romperse.
 *
 * Reúsa el patrón de las otras secciones de Mi Consultorio (ver SeccionServicios):
 * listado, alta, edición inline, estados de carga/vacío/error.
 */

import { useMemo, useState } from 'react'
import { FileText, Loader2, Pencil, Plus, Power, Save, X } from 'lucide-react'

import {
  useActualizarPlantillaDocumento,
  useCrearPlantillaDocumento,
  useEliminarPlantillaDocumento,
  usePlantillasDocumento,
} from '../../hooks/plantillasDocumento'
import type {
  PlantillaDocumento,
  PlantillaDocumentoSection,
} from '../../types/plantillasDocumento'
import { erroresDe } from '../../lib/apiErrors'
import { AlertaErrores, AvisoSoloLectura, Nota } from './Avisos'
import { useConfirm } from '../common/DialogProvider'

interface Props {
  editable: boolean
}

/** Etiqueta legible de cada sección (para el select y las filas). */
const SECTION_LABELS: Record<PlantillaDocumentoSection, string> = {
  reporte_medico: 'Reporte médico',
  seguimiento: 'Seguimiento y acompañamiento',
  interconsulta: 'Interconsulta de departamentos',
  estudios: 'Estudios de laboratorio y gabinete',
  condiciones_mejorar: 'Principales condiciones a mejorar',
  general: 'General',
}

const SECTION_KEYS = Object.keys(SECTION_LABELS) as PlantillaDocumentoSection[]

/** Borrador del formulario (alta o edición). */
interface Borrador {
  name: string
  section: PlantillaDocumentoSection
  body: string
}

const BORRADOR_VACIO: Borrador = { name: '', section: 'reporte_medico', body: '' }

function borradorDe(p: PlantillaDocumento): Borrador {
  return { name: p.name, section: p.section, body: p.body }
}

export default function SeccionPlantillasDocumento({ editable }: Props) {
  // Incluye inactivas para poder reactivarlas desde el panel de gestión.
  const plantillasQ = usePlantillasDocumento({ onlyActive: false })
  const crear = useCrearPlantillaDocumento()
  const actualizar = useActualizarPlantillaDocumento()
  const eliminar = useEliminarPlantillaDocumento()
  const confirmar = useConfirm()

  const [errores, setErrores] = useState<string[]>([])
  const [agregando, setAgregando] = useState(false)
  const [nuevo, setNuevo] = useState<Borrador>(BORRADOR_VACIO)
  const [editId, setEditId] = useState<string | null>(null)
  const [edicion, setEdicion] = useState<Borrador>(BORRADOR_VACIO)

  const plantillas = useMemo(() => plantillasQ.data?.results ?? [], [plantillasQ.data])

  const validar = (b: Borrador): string[] => {
    const e: string[] = []
    if (!b.name.trim()) e.push('Escribe el nombre de la plantilla.')
    if (!b.body.trim()) e.push('Escribe el contenido de la plantilla.')
    return e
  }

  const onCrear = async () => {
    setErrores([])
    const e = validar(nuevo)
    if (e.length) { setErrores(e); return }
    try {
      await crear.mutateAsync({
        name: nuevo.name.trim(),
        section: nuevo.section,
        body: nuevo.body.trim(),
      })
      setNuevo(BORRADOR_VACIO)
      setAgregando(false)
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const iniciarEdicion = (p: PlantillaDocumento) => {
    setErrores([])
    setEditId(p.id)
    setEdicion(borradorDe(p))
  }

  const onGuardarEdicion = async () => {
    if (!editId) return
    setErrores([])
    const e = validar(edicion)
    if (e.length) { setErrores(e); return }
    try {
      await actualizar.mutateAsync({
        id: editId,
        input: {
          name: edicion.name.trim(),
          section: edicion.section,
          body: edicion.body.trim(),
        },
      })
      setEditId(null)
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const onDesactivar = async (p: PlantillaDocumento) => {
    if (!(await confirmar({
      titulo: 'Desactivar plantilla',
      mensaje: `¿Desactivar “${p.name}”? Ya no se ofrecerá al capturar el Plan Integral, pero podrás reactivarla.`,
      peligro: true,
      textoConfirmar: 'Desactivar',
    }))) return
    setErrores([])
    try {
      await actualizar.mutateAsync({ id: p.id, input: { is_active: false } })
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const onReactivar = async (p: PlantillaDocumento) => {
    setErrores([])
    try {
      await actualizar.mutateAsync({ id: p.id, input: { is_active: true } })
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const onEliminar = async (p: PlantillaDocumento) => {
    if (!(await confirmar({
      titulo: 'Eliminar plantilla',
      mensaje: `¿Eliminar la plantilla “${p.name}”? Esta acción no se puede deshacer.`,
      peligro: true,
      textoConfirmar: 'Eliminar',
    }))) return
    setErrores([])
    try {
      await eliminar.mutateAsync(p.id)
      if (editId === p.id) setEditId(null)
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  return (
    <div className="space-y-5">
      {!editable && <AvisoSoloLectura texto="Puedes ver las plantillas, pero solo Dueño/Administrador las edita." />}
      <Nota>
        Crea textos reutilizables por sección (p. ej. un “Reporte médico” estándar). Al capturar el
        Plan Integral del paciente, el médico podrá insertarlos con un clic en la sección que corresponda.
      </Nota>

      <AlertaErrores errores={errores} />

      {editable && !agregando && editId === null && (
        <button className="btn-primary" onClick={() => { setAgregando(true); setErrores([]) }}>
          <Plus className="w-4 h-4" /> Agregar plantilla
        </button>
      )}

      {/* Formulario de alta */}
      {editable && agregando && (
        <EditorPlantilla
          borrador={nuevo}
          setBorrador={setNuevo}
          guardando={crear.isPending}
          onGuardar={onCrear}
          onCancelar={() => { setAgregando(false); setNuevo(BORRADOR_VACIO); setErrores([]) }}
          textoGuardar="Crear plantilla"
        />
      )}

      {/* Listado */}
      {plantillasQ.isLoading ? (
        <div className="flex items-center justify-center py-10 text-gray-400">
          <Loader2 className="w-5 h-5 animate-spin mr-2" /> Cargando plantillas…
        </div>
      ) : plantillasQ.isError ? (
        <AlertaErrores errores={erroresDe(plantillasQ.error)} />
      ) : plantillas.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-10 text-gray-400">
          <FileText className="w-8 h-8 mb-2 opacity-50" />
          <p className="text-sm">Aún no hay plantillas de documento.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {plantillas.map((p) =>
            editId === p.id ? (
              <EditorPlantilla
                key={p.id}
                borrador={edicion}
                setBorrador={setEdicion}
                guardando={actualizar.isPending}
                onGuardar={onGuardarEdicion}
                onCancelar={() => { setEditId(null); setErrores([]) }}
                textoGuardar="Guardar cambios"
              />
            ) : (
              <FilaPlantilla
                key={p.id}
                plantilla={p}
                editable={editable}
                onEditar={() => iniciarEdicion(p)}
                onDesactivar={() => onDesactivar(p)}
                onReactivar={() => onReactivar(p)}
                onEliminar={() => onEliminar(p)}
                ocupado={actualizar.isPending || eliminar.isPending}
              />
            ),
          )}
        </div>
      )}
    </div>
  )
}

// ── Fila de una plantilla (modo lectura) ─────────────────────────────────────

function FilaPlantilla({
  plantilla, editable, onEditar, onDesactivar, onReactivar, onEliminar, ocupado,
}: {
  plantilla: PlantillaDocumento
  editable: boolean
  onEditar: () => void
  onDesactivar: () => void
  onReactivar: () => void
  onEliminar: () => void
  ocupado: boolean
}) {
  return (
    <div
      className="flex items-start gap-3 rounded-xl px-3.5 py-2.5"
      style={{
        background: plantilla.is_active ? 'rgba(255,255,255,0.72)' : 'rgba(245,245,244,0.7)',
        border: '1px solid rgba(201,162,39,0.18)',
        opacity: plantilla.is_active ? 1 : 0.7,
      }}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium text-gray-800">{plantilla.name}</span>
          <span className="badge badge-success">{SECTION_LABELS[plantilla.section]}</span>
          {!plantilla.is_active && <span className="badge badge-warning">Inactiva</span>}
        </div>
        <p className="text-xs text-gray-400 mt-0.5 line-clamp-2 whitespace-pre-line">{plantilla.body}</p>
      </div>
      {editable && (
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={onEditar}
            className="p-1.5 rounded-lg text-amber-700 hover:bg-amber-50 transition-colors"
            aria-label="Editar plantilla"
          >
            <Pencil className="w-4 h-4" />
          </button>
          {plantilla.is_active ? (
            <button
              onClick={onDesactivar}
              disabled={ocupado}
              className="p-1.5 rounded-lg text-amber-700 hover:bg-amber-50 transition-colors disabled:opacity-50"
              aria-label="Desactivar plantilla"
              title="Desactivar"
            >
              <Power className="w-4 h-4" />
            </button>
          ) : (
            <button
              onClick={onReactivar}
              disabled={ocupado}
              className="p-1.5 rounded-lg text-emerald-700 hover:bg-emerald-50 transition-colors disabled:opacity-50"
              aria-label="Reactivar plantilla"
              title="Reactivar"
            >
              <Power className="w-4 h-4" />
            </button>
          )}
          <button
            onClick={onEliminar}
            disabled={ocupado}
            className="p-1.5 rounded-lg text-red-600 hover:bg-red-50 transition-colors disabled:opacity-50"
            aria-label="Eliminar plantilla"
            title="Eliminar"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  )
}

// ── Editor de una plantilla (alta o edición) ─────────────────────────────────

function EditorPlantilla({
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
      <div className="grid gap-3 sm:grid-cols-[1fr_240px]">
        <div>
          <label className="label">Nombre de la plantilla</label>
          <input
            className="input"
            maxLength={200}
            placeholder="Ej. Reporte médico estándar"
            value={borrador.name}
            onChange={e => set('name', e.target.value)}
          />
        </div>
        <div>
          <label className="label">Sección</label>
          <select
            className="input"
            value={borrador.section}
            onChange={e => set('section', e.target.value as PlantillaDocumentoSection)}
          >
            {SECTION_KEYS.map(k => (
              <option key={k} value={k}>{SECTION_LABELS[k]}</option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label className="label">Contenido</label>
        <textarea
          className="input resize-none w-full"
          rows={5}
          maxLength={8000}
          placeholder="Escribe el texto que se insertará en la sección…"
          value={borrador.body}
          onChange={e => set('body', e.target.value)}
        />
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
