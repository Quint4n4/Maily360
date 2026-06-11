import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, AlertCircle, Loader2, Search, Info, Users, Ban, CalendarPlus, Check, Building2, Phone, Video, MapPin } from 'lucide-react'
import { usePatients } from '../../hooks/pacientes'
import { useDoctors, useConsultorios, useCreateAppointment, useAppointmentTypes, useCreateAgendaBlock } from '../../hooks/agenda'
import { combineToISO } from '../../lib/fecha'
import { ApiError } from '../../lib/http'
import { useAuth } from '../../auth/AuthContext'
import type { AppointmentModality } from '../../types/agenda'

type Modo = 'cita' | 'block' | 'meeting'

const MODALIDADES: { key: AppointmentModality; label: string; icon: typeof Phone }[] = [
  { key: 'office', label: 'Consultorio u Oficina', icon: Building2 },
  { key: 'phone', label: 'Telefónica', icon: Phone },
  { key: 'video', label: 'Video Llamada', icon: Video },
  { key: 'offsite', label: 'Fuera de la Instalación', icon: MapPin },
]
type ModoPaciente = 'existente' | 'nuevo'
type Alcance = 'clinica' | 'consultorios' | 'doctores'

interface CrearEventoModalProps {
  open: boolean
  onClose: () => void
  dayKey: string
  fechaLarga: string
  horaInicio: string
  consultorioId?: string | null
  consultorioName?: string
  /** Modo inicial al abrir (cita por defecto). */
  initialMode?: Modo
  /** Modalidad inicial de la cita (office por defecto; 'video' al abrir desde Telemedicina). */
  initialModality?: AppointmentModality
}

const INPUT = 'w-full rounded-xl border border-white/60 bg-white/70 px-4 py-2.5 text-sm text-gray-800 outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-500/20'
const LABEL = 'block text-xs font-medium text-gray-500 mb-1'
const DURACIONES = [30, 45, 60, 90]

function erroresDe(err: unknown): string[] {
  if (!(err instanceof ApiError)) return ['No se pudo guardar.']
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

function partirNombre(texto: string): { nombre: string; paterno: string; materno: string } {
  const w = texto.trim().split(/\s+/).filter(Boolean)
  return { nombre: w[0] ?? '', paterno: w[1] ?? '', materno: w.slice(2).join(' ') }
}
function addMin(hhmm: string, mins: number): string {
  const [h, m] = hhmm.split(':').map(Number)
  const total = h * 60 + m + mins
  const hh = Math.floor((total % (24 * 60)) / 60)
  const mm = total % 60
  return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`
}
function toggle(list: string[], id: string): string[] {
  return list.includes(id) ? list.filter(x => x !== id) : [...list, id]
}

function Pill({ label, selected, onClick }: { label: string; selected: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick}
      className="px-4 py-2 rounded-full text-sm font-semibold transition-all duration-150 active:scale-[0.98]"
      style={selected
        ? { background: '#C9A227', color: '#fff', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }
        : { background: 'rgba(255,255,255,0.55)', color: '#9A7B1E', border: '1px solid rgba(255,255,255,0.7)' }}>
      {label}
    </button>
  )
}

export default function CrearEventoModal({
  open, onClose, dayKey, fechaLarga, horaInicio, consultorioId, consultorioName, initialMode = 'cita', initialModality = 'office',
}: CrearEventoModalProps) {
  const [modo, setModo] = useState<Modo>(initialMode)

  // ── Estado de la CITA ──
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [pacienteId, setPacienteId] = useState('')
  const [modoPaciente, setModoPaciente] = useState<ModoPaciente>('existente')
  const [npNombre, setNpNombre] = useState('')
  const [npPaterno, setNpPaterno] = useState('')
  const [npMaterno, setNpMaterno] = useState('')
  const [npTel, setNpTel] = useState('')
  const [doctorId, setDoctorId] = useState('')
  const [consId, setConsId] = useState('')
  const [modalidad, setModalidad] = useState<AppointmentModality>('office')
  const [duracion, setDuracion] = useState(30)
  const [tipoId, setTipoId] = useState('')
  const [notas, setNotas] = useState('')

  // ── Estado del EVENTO (bloqueo/reunión) ──
  const [evTitulo, setEvTitulo] = useState('')
  const [evAlcance, setEvAlcance] = useState<Alcance>('clinica')
  const [evDoctores, setEvDoctores] = useState<string[]>([])
  const [evCons, setEvCons] = useState<string[]>([])
  const [evTodoDia, setEvTodoDia] = useState(false)
  const [evIni, setEvIni] = useState('09:00')
  const [evFin, setEvFin] = useState('10:00')
  const [evNotas, setEvNotas] = useState('')

  const [errores, setErrores] = useState<string[]>([])
  const [enviando, setEnviando] = useState(false)

  const { data: pacData, isLoading: loadingPac } = usePatients(debounced)
  const { data: docData } = useDoctors()
  const { data: consData } = useConsultorios()
  const { data: tipos } = useAppointmentTypes()
  const crearCita = useCreateAppointment()
  const crearEvento = useCreateAgendaBlock()

  const { user } = useAuth()
  const soyDoctor = !!user?.doctor_id
  const pacientes = pacData?.results ?? []
  const doctores = (docData?.results ?? []).filter(d => d.is_active)
  const consultorios = (consData?.results ?? []).filter(c => c.is_active)
  // Consultorios permitidos: si el médico seleccionado tiene asignados, solo esos.
  const docSel = doctores.find(d => d.id === doctorId)
  const consPermitidos = (docSel && docSel.consultorios.length > 0) ? docSel.consultorios : consultorios
  const guardando = crearCita.isPending || enviando

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 300)
    return () => clearTimeout(t)
  }, [search])

  useEffect(() => {
    if (!open) return
    setModo(initialMode)
    setErrores([]); setEnviando(false)
    // cita
    setSearch(''); setDebounced(''); setModoPaciente('existente'); setPacienteId('')
    setNpNombre(''); setNpPaterno(''); setNpMaterno(''); setNpTel('')
    setDoctorId(user?.doctor_id ?? ''); setConsId(consultorioId ?? ''); setModalidad(initialModality); setDuracion(30); setTipoId(''); setNotas('')
    // evento (prefill desde el slot clicado)
    setEvTitulo(''); setEvNotas(''); setEvDoctores([]); setEvTodoDia(false)
    setEvAlcance(consultorioId ? 'consultorios' : 'clinica')
    setEvCons(consultorioId ? [consultorioId] : [])
    setEvIni(horaInicio); setEvFin(addMin(horaInicio, 60))
  }, [open, initialMode, initialModality, consultorioId, horaInicio])

  // Si el médico cambia y el consultorio elegido ya no le pertenece, lo limpiamos.
  useEffect(() => {
    if (consId && docSel && docSel.consultorios.length > 0 && !docSel.consultorios.some(c => c.id === consId)) {
      setConsId('')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doctorId])

  const activarNuevoPaciente = () => {
    if (!npNombre && !npPaterno && search.trim()) {
      const p = partirNombre(search)
      setNpNombre(p.nombre); setNpPaterno(p.paterno); setNpMaterno(p.materno)
    }
    setModoPaciente('nuevo')
  }

  const guardarCita = async () => {
    setErrores([])
    const faltan: string[] = []
    if (modoPaciente === 'existente') {
      if (!pacienteId) faltan.push('Selecciona un paciente.')
    } else {
      if (!npNombre.trim()) faltan.push('El nombre del paciente es obligatorio.')
      if (!npPaterno.trim()) faltan.push('El apellido paterno es obligatorio.')
    }
    if (!doctorId) faltan.push('Selecciona un doctor.')
    if (faltan.length) { setErrores(faltan); return }

    try {
      const startISO = combineToISO(dayKey, horaInicio)
      const endISO = new Date(new Date(startISO).getTime() + duracion * 60_000).toISOString()
      const doctorSel = doctores.find(d => d.id === doctorId)
      // Paciente existente → patient_id; nuevo → new_patient (paciente + cita en UNA transacción).
      const pacienteRef = modoPaciente === 'nuevo'
        ? { new_patient: { first_name: npNombre.trim(), paternal_surname: npPaterno.trim(), maternal_surname: npMaterno.trim(), phone: npTel.trim() } }
        : { patient_id: pacienteId }
      await crearCita.mutateAsync({
        ...pacienteRef,
        doctor_id: doctorId,
        consultorio_id: modalidad === 'office' ? (consPermitidos.some(c => c.id === consId) ? consId : null) : null,
        modality: modalidad,
        appointment_type_id: tipoId || null, starts_at: startISO, ends_at: endISO,
        specialty: doctorSel?.specialty ?? '', notes: notas.trim(),
      })
      onClose()
    } catch (err) { setErrores(erroresDe(err)) }
  }

  const guardarEvento = async () => {
    setErrores([])
    const faltan: string[] = []
    if (modo === 'meeting' && !evTitulo.trim()) faltan.push('La reunión necesita un título.')
    if (evAlcance === 'doctores' && evDoctores.length === 0) faltan.push('Selecciona al menos un doctor.')
    if (evAlcance === 'consultorios' && evCons.length === 0) faltan.push('Selecciona al menos un consultorio.')
    if (!evTodoDia && evFin <= evIni) faltan.push('La hora de fin debe ser posterior a la de inicio.')
    if (faltan.length) { setErrores(faltan); return }

    const startISO = evTodoDia ? combineToISO(dayKey, '00:00') : combineToISO(dayKey, evIni)
    const endISO = evTodoDia ? combineToISO(dayKey, '23:59') : combineToISO(dayKey, evFin)
    const base = { kind: modo as 'block' | 'meeting', title: evTitulo.trim(), starts_at: startISO, ends_at: endISO, all_day: evTodoDia, notes: evNotas.trim() }
    let objetivos: Array<{ doctor_id: string | null; consultorio_id: string | null }>
    if (evAlcance === 'clinica') objetivos = [{ doctor_id: null, consultorio_id: null }]
    else if (evAlcance === 'doctores') objetivos = evDoctores.map(id => ({ doctor_id: id, consultorio_id: null }))
    else objetivos = evCons.map(id => ({ consultorio_id: id, doctor_id: null }))

    setEnviando(true)
    try {
      await Promise.all(objetivos.map(o => crearEvento.mutateAsync({ ...base, ...o })))
      onClose()
    } catch (err) { setErrores(erroresDe(err)) } finally { setEnviando(false) }
  }

  const guardar = () => (modo === 'cita' ? guardarCita() : guardarEvento())

  const Chip = ({ on, label, onClick }: { on: boolean; label: string; onClick: () => void }) => (
    <button type="button" onClick={onClick}
      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold transition-all"
      style={on ? { background: '#C9A227', color: '#fff' } : { background: 'rgba(255,255,255,0.6)', color: '#7A756C', border: '1px solid rgba(201,162,39,0.3)' }}>
      {on && <Check className="w-3.5 h-3.5" />} {label}
    </button>
  )
  const ModoPill = ({ m, label, icon: Icon }: { m: Modo; label: string; icon: typeof Ban }) => (
    <button type="button" onClick={() => { setModo(m); setErrores([]) }}
      className="flex-1 inline-flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-semibold transition-all"
      style={modo === m
        ? { background: '#C9A227', color: '#fff', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }
        : { background: 'rgba(255,255,255,0.6)', color: '#7A756C', border: '1px solid rgba(255,255,255,0.7)' }}>
      <Icon className="w-4 h-4" /> {label}
    </button>
  )

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
            className="relative w-full max-w-2xl rounded-3xl overflow-hidden"
            style={{ background: 'rgba(255,255,255,0.82)', backdropFilter: 'blur(30px) saturate(160%)', border: '1px solid rgba(255,255,255,0.65)', boxShadow: '0 20px 60px rgba(60,42,12,0.25)' }}
            initial={{ opacity: 0, y: 20, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 20, scale: 0.97 }}
            transition={{ duration: 0.25, ease: [0.25, 0.46, 0.45, 0.94] }}
            onClick={e => e.stopPropagation()}
          >
            {/* Encabezado */}
            <div className="px-7 py-5 flex items-start justify-between border-b border-white/40">
              <div>
                <h2 className="text-gray-900 text-xl font-bold">{modo === 'cita' ? 'Agendar cita' : 'Nuevo evento'}</h2>
                <p className="text-gray-500 text-sm italic mt-0.5">
                  {fechaLarga}{modo === 'cita' ? ` · ${horaInicio} hrs${consultorioName ? ` · ${consultorioName}` : ''}` : ''}
                </p>
              </div>
              <button onClick={onClose} className="text-gray-400 hover:text-gray-700 transition-colors"><X className="w-6 h-6" /></button>
            </div>

            <div className="px-7 py-6 space-y-5">
              {/* Selector de tipo de registro */}
              <div className="flex gap-2.5">
                <ModoPill m="cita" label="Cita" icon={CalendarPlus} />
                <ModoPill m="block" label="Bloqueo" icon={Ban} />
                <ModoPill m="meeting" label="Reunión" icon={Users} />
              </div>

              {errores.length > 0 && (
                <div className="flex items-start gap-2.5 rounded-xl px-4 py-3" style={{ background: 'rgba(190,40,40,0.10)', border: '1px solid rgba(190,40,40,0.25)' }}>
                  <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-500" />
                  <ul className="text-xs text-red-700 space-y-0.5 list-disc list-inside">{errores.map((e, i) => <li key={i}>{e}</li>)}</ul>
                </div>
              )}

              {/* ════════ FORM DE CITA ════════ */}
              {modo === 'cita' && (
                <>
                  <div>
                    <label className={LABEL}>Paciente</label>
                    <div className="flex gap-2 mb-3">
                      <Pill label="Paciente existente" selected={modoPaciente === 'existente'} onClick={() => setModoPaciente('existente')} />
                      <Pill label="Paciente nuevo" selected={modoPaciente === 'nuevo'} onClick={activarNuevoPaciente} />
                    </div>
                    {modoPaciente === 'existente' ? (
                      <>
                        <div className="relative mb-2">
                          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
                          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Buscar paciente…" className={`${INPUT} pl-10`} />
                        </div>
                        <select value={pacienteId} onChange={e => setPacienteId(e.target.value)} className={INPUT}>
                          <option value="">{loadingPac ? 'Cargando…' : 'Selecciona un paciente…'}</option>
                          {pacientes.map(p => <option key={p.id} value={p.id}>{p.full_name} · {p.record_number}</option>)}
                        </select>
                        {!loadingPac && debounced && pacientes.length === 0 && (
                          <button type="button" onClick={activarNuevoPaciente} className="mt-2 text-xs font-medium hover:underline" style={{ color: '#B8860B' }}>
                            ¿No aparece? Crea «{search.trim()}» como paciente nuevo →
                          </button>
                        )}
                      </>
                    ) : (
                      <div className="rounded-xl p-3 space-y-3" style={{ background: 'rgba(201,162,39,0.08)', border: '1px solid rgba(201,162,39,0.25)' }}>
                        <div className="flex items-start gap-2">
                          <Info className="w-4 h-4 mt-0.5 shrink-0" style={{ color: '#C9A227' }} />
                          <p className="text-xs text-amber-800">Se creará un <b>expediente provisional</b>. Completa sus datos después en Pacientes.</p>
                        </div>
                        <input value={npNombre} onChange={e => setNpNombre(e.target.value)} placeholder="Nombre(s)" className={INPUT} />
                        <div className="grid grid-cols-2 gap-3">
                          <input value={npPaterno} onChange={e => setNpPaterno(e.target.value)} placeholder="Apellido paterno" className={INPUT} />
                          <input value={npMaterno} onChange={e => setNpMaterno(e.target.value)} placeholder="Apellido materno" className={INPUT} />
                        </div>
                        <input value={npTel} onChange={e => setNpTel(e.target.value)} placeholder="Teléfono (opcional)" className={INPUT} />
                      </div>
                    )}
                  </div>

                  <div>
                    <label className={LABEL}>Doctor</label>
                    {soyDoctor ? (
                      <div className={`${INPUT} flex items-center justify-between`} style={{ background: 'rgba(255,255,255,0.4)' }}>
                        <span>{docSel?.full_name || user?.full_name}</span>
                        <span className="text-xs font-semibold" style={{ color: '#C9A227' }}>Tú</span>
                      </div>
                    ) : (
                      <select value={doctorId} onChange={e => setDoctorId(e.target.value)} className={INPUT}>
                        <option value="">Selecciona…</option>
                        {doctores.map(d => <option key={d.id} value={d.id}>{d.full_name}</option>)}
                      </select>
                    )}
                  </div>

                  <div>
                    <label className={LABEL}>Modalidad</label>
                    <div className="grid grid-cols-2 gap-2">
                      {MODALIDADES.map(({ key, label, icon: Icon }) => {
                        const sel = modalidad === key
                        return (
                          <button key={key} type="button" onClick={() => setModalidad(key)}
                            className="inline-flex items-center gap-2 px-3 py-2.5 rounded-xl text-sm font-semibold transition-all text-left"
                            style={sel
                              ? { background: '#4FB0DA', color: '#fff', boxShadow: '0 4px 14px rgba(79,176,218,0.4)' }
                              : { background: 'rgba(255,255,255,0.6)', color: '#5A6B73', border: '1px solid rgba(79,176,218,0.35)' }}>
                            <Icon className="w-4 h-4 shrink-0" /> <span className="truncate">{label}</span>
                          </button>
                        )
                      })}
                    </div>
                    {modalidad === 'office' && (
                      <select value={consId} onChange={e => setConsId(e.target.value)} className={`${INPUT} mt-2`}>
                        <option value="">Sin consultorio</option>
                        {consPermitidos.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                      </select>
                    )}
                  </div>

                  <div className="flex flex-wrap items-end gap-4">
                    <div>
                      <label className={LABEL}>Inicia</label>
                      <input value={`${horaInicio} hrs`} disabled className="w-28 rounded-xl border border-white/50 bg-white/40 px-4 py-2.5 text-sm text-gray-600" />
                    </div>
                    <div>
                      <label className={LABEL}>Duración</label>
                      <select value={duracion} onChange={e => setDuracion(Number(e.target.value))} className={`${INPUT} w-36`}>
                        {DURACIONES.map(d => <option key={d} value={d}>{d} min</option>)}
                      </select>
                    </div>
                  </div>

                  <div>
                    <label className={LABEL}>Tipo de cita <span className="text-gray-400 font-normal">(opcional)</span></label>
                    {(tipos ?? []).length === 0 ? (
                      <p className="text-xs text-gray-400">No hay tipos configurados. Créalos en Personal → Tipos de cita.</p>
                    ) : (
                      <div className="flex flex-wrap gap-2.5">
                        {(tipos ?? []).map(t => {
                          const sel = tipoId === t.id
                          const color = t.color_hex || '#C9A227'
                          return (
                            <button key={t.id} type="button" onClick={() => setTipoId(sel ? '' : t.id)}
                              className="inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm font-semibold transition-all active:scale-[0.98]"
                              style={sel ? { background: color, color: '#fff', boxShadow: `0 4px 14px ${color}66` } : { background: `${color}1A`, color, border: `1px solid ${color}55` }}>
                              <span className="w-2.5 h-2.5 rounded-full" style={{ background: sel ? '#fff' : color }} />{t.name}
                            </button>
                          )
                        })}
                      </div>
                    )}
                  </div>

                  <div>
                    <label className={LABEL}>Observaciones <span className="text-gray-400 font-normal">(opcional)</span></label>
                    <textarea value={notas} onChange={e => setNotas(e.target.value)} rows={3} className={`${INPUT} resize-none`} placeholder="Notas de la cita…" />
                  </div>
                </>
              )}

              {/* ════════ FORM DE EVENTO (bloqueo/reunión) ════════ */}
              {modo !== 'cita' && (
                <>
                  <div>
                    <label className={LABEL}>Título {modo === 'block' && <span className="text-gray-400 font-normal">(opcional)</span>}</label>
                    <input className={INPUT} value={evTitulo} onChange={e => setEvTitulo(e.target.value)}
                      placeholder={modo === 'block' ? 'Día festivo, vacaciones…' : 'Junta de equipo'} />
                  </div>
                  <div>
                    <label className={LABEL}>¿A qué aplica?</label>
                    <select className={INPUT} value={evAlcance} onChange={e => setEvAlcance(e.target.value as Alcance)}>
                      <option value="clinica">Toda la clínica</option>
                      <option value="consultorios">Uno o varios consultorios</option>
                      <option value="doctores">Uno o varios doctores</option>
                    </select>
                    {evAlcance === 'consultorios' && (
                      <div className="flex flex-wrap gap-2 mt-2">
                        {consultorios.length === 0 ? <p className="text-xs text-gray-400">No hay consultorios.</p>
                          : consultorios.map(c => <Chip key={c.id} on={evCons.includes(c.id)} label={c.name} onClick={() => setEvCons(s => toggle(s, c.id))} />)}
                      </div>
                    )}
                    {evAlcance === 'doctores' && (
                      <div className="flex flex-wrap gap-2 mt-2">
                        {doctores.length === 0 ? <p className="text-xs text-gray-400">No hay doctores.</p>
                          : doctores.map(d => <Chip key={d.id} on={evDoctores.includes(d.id)} label={d.full_name} onClick={() => setEvDoctores(s => toggle(s, d.id))} />)}
                      </div>
                    )}
                  </div>
                  <div>
                    <label className="flex items-center gap-2 cursor-pointer select-none mb-2">
                      <input type="checkbox" checked={evTodoDia} onChange={e => setEvTodoDia(e.target.checked)} className="w-4 h-4 accent-amber-600" />
                      <span className="text-sm text-gray-700">Todo el día</span>
                    </label>
                    {!evTodoDia && (
                      <div className="flex items-center gap-3">
                        <div><label className={LABEL}>Desde</label><input type="time" className={INPUT} value={evIni} onChange={e => setEvIni(e.target.value)} /></div>
                        <div><label className={LABEL}>Hasta</label><input type="time" className={INPUT} value={evFin} onChange={e => setEvFin(e.target.value)} /></div>
                      </div>
                    )}
                  </div>
                  <div>
                    <label className={LABEL}>Notas <span className="text-gray-400 font-normal">(opcional)</span></label>
                    <textarea className={`${INPUT} resize-none`} rows={2} value={evNotas} onChange={e => setEvNotas(e.target.value)} />
                  </div>
                </>
              )}
            </div>

            {/* Pie */}
            <div className="px-7 py-4 flex items-center justify-between border-t border-white/40" style={{ background: 'rgba(255,255,255,0.25)' }}>
              <button onClick={onClose} disabled={guardando} className="btn-secondary disabled:opacity-60">Cancelar</button>
              <button onClick={guardar} disabled={guardando}
                className="px-8 py-2.5 inline-flex items-center gap-2 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-50"
                style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}>
                {guardando ? <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</> : (modo === 'cita' ? 'Agendar cita' : 'Guardar evento')}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
