import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, AlertCircle, Loader2, CheckSquare, Bell, Pin, Megaphone } from 'lucide-react'
import { useCreateNote, useUpdateNote } from '../../hooks/notas'
import { useRole } from '../../auth/RoleContext'
import { ROLES } from '../../auth/permisos'
import { combineToISO, toDayKey, localHHMM } from '../../lib/fecha'
import { ApiError } from '../../lib/http'
import type { Note, NoteScope } from '../../types/nota'

interface Props {
  open: boolean
  onClose: () => void
  editing?: Note | null
}

const INPUT = 'w-full rounded-xl border border-white/60 bg-white/70 px-4 py-2.5 text-sm text-gray-800 outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-500/20'
const LABEL = 'block text-xs font-medium text-gray-500 mb-1'

function erroresDe(err: unknown): string[] {
  if (!(err instanceof ApiError)) return ['No se pudo guardar la nota.']
  if (err.isNetwork) return ['No se pudo conectar con el servidor.']
  const body = err.body
  if (!body) return [`Error ${err.status}.`]
  const msgs: string[] = []
  for (const [campo, valor] of Object.entries(body)) {
    const txt = Array.isArray(valor) ? valor.join(' ') : String(valor)
    msgs.push(campo === 'detail' ? txt : `${campo}: ${txt}`)
  }
  return msgs.length ? msgs : [`Error ${err.status}.`]
}

const Toggle = ({ on, onClick, icon: Icon, label }: { on: boolean; onClick: () => void; icon: typeof Bell; label: string }) => (
  <button type="button" onClick={onClick}
    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold transition-all"
    style={on ? { background: '#C9A227', color: '#fff' } : { background: 'rgba(255,255,255,0.6)', color: '#7A756C', border: '1px solid rgba(201,162,39,0.3)' }}>
    <Icon className="w-3.5 h-3.5" /> {label}
  </button>
)

export default function NuevaNotaModal({ open, onClose, editing }: Props) {
  const { role } = useRole()
  const esOwner = role === 'owner'
  const esEdicion = !!editing

  const [titulo, setTitulo] = useState('')
  const [cuerpo, setCuerpo] = useState('')
  const [esTarea, setEsTarea] = useState(false)
  const [fijada, setFijada] = useState(false)
  const [conRecordatorio, setConRecordatorio] = useState(false)
  const [fecha, setFecha] = useState('')
  const [hora, setHora] = useState('09:00')
  const [scope, setScope] = useState<NoteScope>('personal')
  const [targetRole, setTargetRole] = useState('doctor')
  const [errores, setErrores] = useState<string[]>([])

  const crear = useCreateNote()
  const actualizar = useUpdateNote()
  const guardando = crear.isPending || actualizar.isPending

  useEffect(() => {
    if (!open) return
    setErrores([])
    if (editing) {
      setTitulo(editing.title); setCuerpo(editing.body); setEsTarea(editing.is_task); setFijada(editing.pinned)
      setScope(editing.scope); setTargetRole(editing.target_role || 'doctor')
      if (editing.remind_at) {
        setConRecordatorio(true); setFecha(toDayKey(new Date(editing.remind_at))); setHora(localHHMM(editing.remind_at))
      } else { setConRecordatorio(false); setFecha(''); setHora('09:00') }
    } else {
      setTitulo(''); setCuerpo(''); setEsTarea(false); setFijada(false)
      setConRecordatorio(false); setFecha(''); setHora('09:00'); setScope('personal'); setTargetRole('doctor')
    }
  }, [open, editing])

  const guardar = async () => {
    setErrores([])
    if (!titulo.trim() && !cuerpo.trim()) { setErrores(['Escribe un título o un texto.']); return }
    if (conRecordatorio && !fecha) { setErrores(['Elige la fecha del recordatorio.']); return }

    const input = {
      title: titulo.trim(),
      body: cuerpo.trim(),
      is_task: esTarea,
      pinned: fijada,
      scope,
      target_role: scope === 'role' ? targetRole : '',
      remind_at: conRecordatorio ? combineToISO(fecha, hora) : null,
    }
    try {
      if (editing) await actualizar.mutateAsync({ id: editing.id, input })
      else await crear.mutateAsync(input)
      onClose()
    } catch (err) { setErrores(erroresDe(err)) }
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-start justify-center px-4 py-10 overflow-y-auto"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          style={{ background: 'rgba(40,28,8,0.4)', backdropFilter: 'blur(6px)' }}
          onClick={onClose}
        >
          <motion.div
            className="relative w-full max-w-lg rounded-3xl overflow-hidden"
            style={{ background: 'rgba(255,255,255,0.85)', backdropFilter: 'blur(30px) saturate(160%)', border: '1px solid rgba(255,255,255,0.7)', boxShadow: '0 20px 60px rgba(60,42,12,0.25)' }}
            initial={{ opacity: 0, y: 20, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 20, scale: 0.97 }}
            transition={{ duration: 0.25, ease: [0.25, 0.46, 0.45, 0.94] }}
            onClick={e => e.stopPropagation()}
          >
            <div className="px-7 py-5 flex items-center justify-between border-b border-white/40">
              <h2 className="text-gray-900 text-xl font-bold">{esEdicion ? 'Editar nota' : 'Nueva nota'}</h2>
              <button onClick={onClose} className="text-gray-400 hover:text-gray-700 transition-colors"><X className="w-6 h-6" /></button>
            </div>

            <div className="px-7 py-6 space-y-5">
              {errores.length > 0 && (
                <div className="flex items-start gap-2.5 rounded-xl px-4 py-3" style={{ background: 'rgba(190,40,40,0.10)', border: '1px solid rgba(190,40,40,0.25)' }}>
                  <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-500" />
                  <ul className="text-xs text-red-700 space-y-0.5 list-disc list-inside">{errores.map((e, i) => <li key={i}>{e}</li>)}</ul>
                </div>
              )}

              <div>
                <label className={LABEL}>Título</label>
                <input className={INPUT} value={titulo} onChange={e => setTitulo(e.target.value)} placeholder="Título de la nota…" />
              </div>
              <div>
                <label className={LABEL}>Texto</label>
                <textarea className={`${INPUT} resize-none`} rows={4} value={cuerpo} onChange={e => setCuerpo(e.target.value)} placeholder="Escribe aquí…" />
              </div>

              <div className="flex flex-wrap gap-2">
                <Toggle on={esTarea} onClick={() => setEsTarea(v => !v)} icon={CheckSquare} label="Es tarea" />
                <Toggle on={fijada} onClick={() => setFijada(v => !v)} icon={Pin} label="Fijar" />
                <Toggle on={conRecordatorio} onClick={() => setConRecordatorio(v => !v)} icon={Bell} label="Recordatorio" />
              </div>

              {conRecordatorio && (
                <div className="flex items-center gap-3 rounded-xl p-3" style={{ background: 'rgba(201,162,39,0.08)' }}>
                  <div className="flex-1"><label className={LABEL}>Fecha</label><input type="date" className={INPUT} value={fecha} onChange={e => setFecha(e.target.value)} /></div>
                  <div><label className={LABEL}>Hora</label><input type="time" className={INPUT} value={hora} onChange={e => setHora(e.target.value)} /></div>
                </div>
              )}

              {esOwner && (
                <div className="rounded-xl p-3" style={{ background: 'rgba(58,110,165,0.06)', border: '1px solid rgba(58,110,165,0.18)' }}>
                  <label className={LABEL}><Megaphone className="inline w-3.5 h-3.5 mr-1 -mt-0.5" />Alcance (como Dueño)</label>
                  <select className={INPUT} value={scope} onChange={e => setScope(e.target.value as NoteScope)}>
                    <option value="personal">Personal (solo yo)</option>
                    <option value="all">Global — todos los roles</option>
                    <option value="role">Global — un rol específico</option>
                  </select>
                  {scope === 'role' && (
                    <select className={`${INPUT} mt-2`} value={targetRole} onChange={e => setTargetRole(e.target.value)}>
                      {ROLES.filter(r => r.key !== 'owner').map(r => <option key={r.key} value={r.key}>{r.label}</option>)}
                    </select>
                  )}
                </div>
              )}
            </div>

            <div className="px-7 py-4 flex items-center justify-between border-t border-white/40" style={{ background: 'rgba(255,255,255,0.25)' }}>
              <button onClick={onClose} disabled={guardando} className="btn-secondary disabled:opacity-60">Cancelar</button>
              <button onClick={guardar} disabled={guardando}
                className="px-8 py-2.5 inline-flex items-center gap-2 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-50"
                style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}>
                {guardando ? <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</> : (esEdicion ? 'Guardar cambios' : 'Crear nota')}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
