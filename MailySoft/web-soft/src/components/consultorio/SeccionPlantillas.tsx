import { useState } from 'react'
import { FileText, Loader2, Pencil, Plus, Trash2 } from 'lucide-react'
import { useDeleteTemplate, useTemplates } from '../../hooks/clinica'
import { erroresDe } from '../../lib/apiErrors'
import type { ClinicTemplateOut, TemplateKind } from '../../types/clinica'
import PlantillaModal from './PlantillaModal'
import { AlertaErrores, AvisoSoloLectura } from './Avisos'
import { useConfirm } from '../common/DialogProvider'

interface Props {
  /** Si false, oculta crear/editar/borrar (solo lectura). */
  editable: boolean
}

const KINDS: { key: TemplateKind; label: string }[] = [
  { key: 'recipe', label: 'Recetas' },
  { key: 'document', label: 'Documentos' },
  { key: 'consent', label: 'Consentimientos' },
]

/** Sección 4: CRUD de plantillas agrupado por tipo. */
export default function SeccionPlantillas({ editable }: Props) {
  const [kind, setKind] = useState<TemplateKind>('recipe')
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<ClinicTemplateOut | null>(null)
  const [errores, setErrores] = useState<string[]>([])

  const templatesQ = useTemplates(kind)
  const borrar = useDeleteTemplate()
  const confirmar = useConfirm()
  const plantillas = templatesQ.data?.results ?? []

  const abrirNueva = () => {
    setEditing(null)
    setModalOpen(true)
  }
  const abrirEditar = (t: ClinicTemplateOut) => {
    setEditing(t)
    setModalOpen(true)
  }
  const onBorrar = async (t: ClinicTemplateOut) => {
    if (!(await confirmar({ titulo: 'Eliminar plantilla', mensaje: `¿Eliminar la plantilla “${t.name}”?`, peligro: true, textoConfirmar: 'Eliminar' }))) return
    setErrores([])
    try {
      await borrar.mutateAsync(t.id)
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  return (
    <div className="space-y-5">
      {!editable && <AvisoSoloLectura texto="Puedes ver las plantillas, pero no editarlas." />}
      <AlertaErrores errores={errores} />

      {/* Sub-pestañas por tipo */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="inline-flex rounded-xl bg-white/60 border border-gray-100 p-1">
          {KINDS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setKind(key)}
              className="px-3.5 py-1.5 rounded-lg text-sm font-medium transition-colors"
              style={{
                background: kind === key ? 'rgba(201,162,39,0.16)' : 'transparent',
                color: kind === key ? '#B8860B' : '#7A756C',
              }}
            >
              {label}
            </button>
          ))}
        </div>
        {editable && (
          <button className="btn-primary" onClick={abrirNueva}>
            <Plus className="w-4 h-4" /> Nueva plantilla
          </button>
        )}
      </div>

      {/* Lista */}
      {templatesQ.isLoading ? (
        <div className="flex items-center justify-center py-12 text-gray-400">
          <Loader2 className="w-5 h-5 animate-spin mr-2" /> Cargando plantillas…
        </div>
      ) : templatesQ.isError ? (
        <AlertaErrores errores={erroresDe(templatesQ.error)} />
      ) : plantillas.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 text-gray-400">
          <FileText className="w-8 h-8 mb-2 opacity-50" />
          <p className="text-sm">No hay plantillas en esta categoría.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {plantillas.map((t) => (
            <div
              key={t.id}
              className="flex items-center justify-between gap-3 rounded-2xl border border-gray-100 bg-white/70 px-4 py-3"
            >
              <div className="min-w-0">
                <p className="text-sm font-medium text-gray-800 truncate">{t.name}</p>
                <p className="text-xs text-gray-400 truncate">
                  {t.group ? `${t.group} · ` : ''}{t.body.length.toLocaleString()} caracteres
                </p>
              </div>
              {editable && (
                <div className="flex items-center gap-1 shrink-0">
                  <button
                    onClick={() => abrirEditar(t)}
                    className="p-2 rounded-lg text-gray-500 hover:bg-amber-50 hover:text-amber-700 transition-colors"
                    aria-label="Editar"
                  >
                    <Pencil className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => onBorrar(t)}
                    className="p-2 rounded-lg text-red-500 hover:bg-red-50 transition-colors"
                    aria-label="Eliminar"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {modalOpen && (
        <PlantillaModal
          open={modalOpen}
          kind={kind}
          editing={editing}
          onClose={() => setModalOpen(false)}
        />
      )}
    </div>
  )
}
