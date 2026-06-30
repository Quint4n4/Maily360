import { useState } from 'react'
import { createPortal } from 'react-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { Loader2, Save, X } from 'lucide-react'
import { useCreateTemplate, useUpdateTemplate } from '../../hooks/clinica'
import { erroresDe } from '../../lib/apiErrors'
import { TEMPLATE_BODY_MAX } from '../../types/clinica'
import type { ClinicTemplateOut, TemplateKind } from '../../types/clinica'
import { AlertaErrores } from './Avisos'

interface Props {
  open: boolean
  /** Tipo fijo de la plantilla (la pestaña activa). */
  kind: TemplateKind
  /** Plantilla a editar; null = creación. */
  editing: ClinicTemplateOut | null
  onClose: () => void
}

const KIND_LABEL: Record<TemplateKind, string> = {
  recipe: 'receta',
  document: 'documento',
  consent: 'consentimiento',
}

/** Modal para crear/editar una plantilla clínica. */
export default function PlantillaModal({ open, kind, editing, onClose }: Props) {
  const crear = useCreateTemplate()
  const actualizar = useUpdateTemplate()
  const [name, setName] = useState(editing?.name ?? '')
  const [group, setGroup] = useState(editing?.group ?? '')
  const [body, setBody] = useState(editing?.body ?? '')
  const [errores, setErrores] = useState<string[]>([])

  const guardando = crear.isPending || actualizar.isPending

  const guardar = async () => {
    setErrores([])
    if (!name.trim()) {
      setErrores(['El nombre de la plantilla es obligatorio.'])
      return
    }
    if (body.length > TEMPLATE_BODY_MAX) {
      setErrores([`El cuerpo supera el límite de ${TEMPLATE_BODY_MAX.toLocaleString()} caracteres.`])
      return
    }
    try {
      if (editing) {
        await actualizar.mutateAsync({
          id: editing.id,
          input: { name: name.trim(), group: group.trim(), body },
        })
      } else {
        await crear.mutateAsync({ kind, name: name.trim(), group: group.trim(), body })
      }
      onClose()
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const contador = `${body.length.toLocaleString()} / ${TEMPLATE_BODY_MAX.toLocaleString()}`
  const cercaDelLimite = body.length > TEMPLATE_BODY_MAX * 0.9

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-start justify-center px-4 py-10 overflow-y-auto"
          style={{ background: 'rgba(40,28,8,0.4)', backdropFilter: 'blur(6px)' }}
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            className="relative w-full max-w-2xl rounded-3xl overflow-hidden"
            style={{ background: 'rgba(255,255,255,0.92)', backdropFilter: 'blur(30px) saturate(160%)' }}
            initial={{ y: 24, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 24, opacity: 0 }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
              <h3 className="text-lg font-semibold text-gray-800">
                {editing ? 'Editar' : 'Nueva'} plantilla de {KIND_LABEL[kind]}
              </h3>
              <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-black/5">
                <X className="w-5 h-5 text-gray-500" />
              </button>
            </div>

            <div className="p-6 space-y-4">
              <AlertaErrores errores={errores} />

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="label" htmlFor="tpl-name">Nombre</label>
                  <input id="tpl-name" className="input" maxLength={150} value={name} onChange={(e) => setName(e.target.value)} />
                </div>
                <div>
                  <label className="label" htmlFor="tpl-group">Grupo (opcional)</label>
                  <input id="tpl-group" className="input" maxLength={150} value={group} onChange={(e) => setGroup(e.target.value)} />
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between">
                  <label className="label" htmlFor="tpl-body">Cuerpo</label>
                  <span className={`text-xs ${cercaDelLimite ? 'text-red-500' : 'text-gray-400'}`}>{contador}</span>
                </div>
                <textarea
                  id="tpl-body"
                  className="input min-h-[220px] font-mono text-sm"
                  value={body}
                  maxLength={TEMPLATE_BODY_MAX}
                  onChange={(e) => setBody(e.target.value)}
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 px-6 py-4 border-t border-gray-100">
              <button className="btn-secondary" onClick={onClose}>Cancelar</button>
              <button className="btn-primary" onClick={guardar} disabled={guardando}>
                {guardando ? (
                  <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</>
                ) : (
                  <><Save className="w-4 h-4" /> Guardar</>
                )}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  )
}
