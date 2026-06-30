import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, AlertCircle, Loader2, Users, Ban, Trash2, Calendar } from 'lucide-react'
import { useUpdateAgendaBlock, useDeleteAgendaBlock } from '../../hooks/agenda'
import NotasHilo from './NotasHilo'
import { toDayKey, localHHMM, combineToISO } from '../../lib/fecha'
import { erroresDe } from '../../lib/apiErrors'
import { INPUT, LABEL } from '../../lib/estilosForm'
import type { AgendaBlock } from '../../types/agenda'

interface Props {
  evento: AgendaBlock | null
  onClose: () => void
  soloLectura?: boolean
}

export default function EventoDetalleModal({ evento, onClose, soloLectura = false }: Props) {
  const [titulo, setTitulo] = useState('')
  const [fecha, setFecha] = useState('')
  const [todoDia, setTodoDia] = useState(false)
  const [horaIni, setHoraIni] = useState('09:00')
  const [horaFin, setHoraFin] = useState('10:00')
  const [notas, setNotas] = useState('')
  const [errores, setErrores] = useState<string[]>([])
  const [confirmando, setConfirmando] = useState(false)

  const actualizar = useUpdateAgendaBlock()
  const borrar = useDeleteAgendaBlock()
  const ocupado = actualizar.isPending || borrar.isPending

  useEffect(() => {
    if (!evento) return
    setTitulo(evento.title)
    setFecha(toDayKey(new Date(evento.starts_at)))
    setTodoDia(evento.all_day)
    setHoraIni(localHHMM(evento.starts_at))
    setHoraFin(localHHMM(evento.ends_at))
    setNotas(evento.notes)
    setErrores([]); setConfirmando(false)
  }, [evento])

  if (!evento) return null

  const esBloqueo = evento.kind === 'block'
  const alcance = evento.doctor ? evento.doctor.full_name : (evento.consultorio ? evento.consultorio.name : 'Toda la clínica')
  const color = esBloqueo ? '#6B7280' : '#3A6EA5'

  const guardar = async () => {
    setErrores([])
    if (esBloqueo === false && !titulo.trim()) { setErrores(['La reunión necesita un título.']); return }
    if (!todoDia && horaFin <= horaIni) { setErrores(['La hora de fin debe ser posterior a la de inicio.']); return }
    const startISO = todoDia ? combineToISO(fecha, '00:00') : combineToISO(fecha, horaIni)
    const endISO = todoDia ? combineToISO(fecha, '23:59') : combineToISO(fecha, horaFin)
    try {
      await actualizar.mutateAsync({ id: evento.id, input: { title: titulo.trim(), starts_at: startISO, ends_at: endISO, all_day: todoDia, notes: notas.trim() } })
      onClose()
    } catch (err) { setErrores(erroresDe(err, 'No se pudo guardar.')) }
  }

  const eliminar = async () => {
    try { await borrar.mutateAsync(evento.id); onClose() }
    catch (err) { setErrores(erroresDe(err, 'No se pudo guardar.')) }
  }

  return (
    <AnimatePresence>
      {evento && (
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
            <div className="px-7 py-5 flex items-start justify-between border-b border-white/40">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: `${color}22` }}>
                  {esBloqueo ? <Ban className="w-5 h-5" style={{ color }} /> : <Users className="w-5 h-5" style={{ color }} />}
                </div>
                <div>
                  <h2 className="text-gray-900 text-xl font-bold">{esBloqueo ? 'Bloqueo' : 'Reunión'}</h2>
                  <p className="text-gray-500 text-xs">Aplica a: <b>{alcance}</b></p>
                </div>
              </div>
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
                <label className={LABEL}>Título {esBloqueo && <span className="text-gray-400 font-normal">(opcional)</span>}</label>
                <input className={INPUT} maxLength={150} value={titulo} disabled={soloLectura} onChange={e => setTitulo(e.target.value)} placeholder={esBloqueo ? 'Día festivo…' : 'Junta de equipo'} />
              </div>

              <div>
                <label className={LABEL}><Calendar className="inline w-3.5 h-3.5 mr-1 -mt-0.5" />Fecha</label>
                <input type="date" className={INPUT} value={fecha} disabled={soloLectura} onChange={e => setFecha(e.target.value)} />
              </div>

              <div>
                <label className="flex items-center gap-2 cursor-pointer select-none mb-2">
                  <input type="checkbox" checked={todoDia} disabled={soloLectura} onChange={e => setTodoDia(e.target.checked)} className="w-4 h-4 accent-amber-600" />
                  <span className="text-sm text-gray-700">Todo el día</span>
                </label>
                {!todoDia && (
                  <div className="flex items-center gap-3">
                    <div><label className={LABEL}>Desde</label><input type="time" className={INPUT} value={horaIni} disabled={soloLectura} onChange={e => setHoraIni(e.target.value)} /></div>
                    <div><label className={LABEL}>Hasta</label><input type="time" className={INPUT} value={horaFin} disabled={soloLectura} onChange={e => setHoraFin(e.target.value)} /></div>
                  </div>
                )}
              </div>

              <div>
                <label className={LABEL}>Notas <span className="text-gray-400 font-normal">(opcional)</span></label>
                <textarea className={`${INPUT} resize-none`} rows={2} maxLength={4000} value={notas} disabled={soloLectura} onChange={e => setNotas(e.target.value)} />
              </div>

              <div className="pt-3 border-t border-white/40">
                <NotasHilo kind="evento" itemId={evento.id} />
              </div>
            </div>

            {!soloLectura && (
              <div className="px-7 py-4 border-t border-white/40" style={{ background: 'rgba(255,255,255,0.25)' }}>
                {confirmando ? (
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm text-red-700 font-medium">¿Eliminar este evento? No se puede deshacer.</span>
                    <div className="flex gap-2 shrink-0">
                      <button onClick={() => setConfirmando(false)} disabled={ocupado} className="btn-secondary text-sm disabled:opacity-60">No</button>
                      <button onClick={eliminar} disabled={ocupado}
                        className="px-5 py-2 inline-flex items-center gap-2 rounded-xl text-sm font-semibold text-white transition-all disabled:opacity-60"
                        style={{ background: '#C0392B' }}>
                        {ocupado ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />} Sí, eliminar
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="flex items-center justify-between gap-3">
                    <button onClick={() => setConfirmando(true)} disabled={ocupado}
                      className="inline-flex items-center gap-1.5 text-sm font-semibold text-red-600 hover:text-red-700 transition-colors disabled:opacity-60">
                      <Trash2 className="w-4 h-4" /> Eliminar
                    </button>
                    <button onClick={guardar} disabled={ocupado}
                      className="px-8 py-2.5 inline-flex items-center gap-2 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-50"
                      style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}>
                      {actualizar.isPending ? <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</> : 'Guardar cambios'}
                    </button>
                  </div>
                )}
              </div>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
