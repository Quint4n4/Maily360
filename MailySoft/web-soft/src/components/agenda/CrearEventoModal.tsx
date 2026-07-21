import { useState, useEffect, useMemo, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, AlertCircle, Loader2, Search, Info, Users, Ban, CalendarPlus, Check, Building2, Phone, Video, MapPin, ChevronLeft, ChevronRight, Repeat, Plus, ScrollText } from 'lucide-react'
import { usePatients } from '../../hooks/pacientes'
import { useDoctors, useConsultorios, useCreateAppointment, useCreateAppointmentSeries, useAppointmentTypes, useCreateAgendaBlock, useAgendaDisponibilidad } from '../../hooks/agenda'
import { useQuotes } from '../../hooks/finanzas'
import { useAgendaConfig } from '../../hooks/agendaConfig'
import { combineToISO, to12h, formatFechaHora, fromDayKey, toDayKey, addDays, seriesDates } from '../../lib/fecha'
import { formatMoney } from '../../lib/format'
import MiniCalendario from './MiniCalendario'
import { erroresDe } from '../../lib/apiErrors'
import { INPUT, LABEL } from '../../lib/estilosForm'
import { useAuth } from '../../auth/AuthContext'
import { useSucursalActiva } from '../../auth/SucursalContext'
import type { AppointmentModality, AppointmentSeriesResult, SeriesFrequency } from '../../types/agenda'

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
  /** Paciente existente precargado (p. ej. "Volver a agendar" desde Clientes potenciales). */
  initialPatient?: { id: string; full_name: string; record_number: string }
  /** Motivo ("¿a qué viene?") precargado (p. ej. el de la última cita cancelada). */
  initialReason?: string
}

/**
 * Duraciones ofrecidas al agendar. Antes eran fijas [30,45,60,90], lo que impedía
 * agendar consultas cortas. Ahora se ofrece un abanico amplio y, además, se le
 * suma la duración propia del médico si no está en la lista (p. ej. 14 min),
 * porque `Doctor.default_appointment_duration` manda sobre la de la clínica.
 */
const DURACIONES_BASE = [10, 15, 20, 30, 40, 45, 60, 90, 120]

/** Lista final de duraciones: las comunes + la del médico, ordenadas y sin repetir. */
function duracionesPara(duracionMedico: number): number[] {
  return Array.from(new Set([...DURACIONES_BASE, duracionMedico])).sort((a, b) => a - b)
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

/**
 * Errores del backend, con el 400 de multi-sede traducido a algo accionable.
 * El backend responde "El médico no atiende en esa sucursal" (regla de negocio F2);
 * aquí le decimos al usuario QUÉ hacer (cambiar de médico o de sede).
 */
function erroresConSede(err: unknown, sede: string): string[] {
  return erroresDe(err, 'No se pudo guardar.').map(m =>
    /no atiende/i.test(m) && /sucursal|sede/i.test(m)
      ? `El médico seleccionado no atiende en ${sede ? `la sucursal «${sede}»` : 'esta sucursal'}. Elige otro médico o cambia de sucursal en la barra superior.`
      : m,
  )
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

function Chip({ on, label, onClick }: { on: boolean; label: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick}
      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold transition-all"
      style={on ? { background: '#C9A227', color: '#fff' } : { background: 'rgba(255,255,255,0.6)', color: '#7A756C', border: '1px solid rgba(201,162,39,0.3)' }}>
      {on && <Check className="w-3.5 h-3.5" />} {label}
    </button>
  )
}

function ModoPill({ label, icon: Icon, active, onClick }: { label: string; icon: typeof Ban; active: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick}
      className="flex-1 inline-flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-semibold transition-all"
      style={active
        ? { background: '#C9A227', color: '#fff', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }
        : { background: 'rgba(255,255,255,0.6)', color: '#7A756C', border: '1px solid rgba(255,255,255,0.7)' }}>
      <Icon className="w-4 h-4" /> {label}
    </button>
  )
}

export default function CrearEventoModal({
  open, onClose, dayKey, fechaLarga, horaInicio, consultorioId, consultorioName, initialMode = 'cita', initialModality = 'office',
  initialPatient, initialReason,
}: CrearEventoModalProps) {
  const [modo, setModo] = useState<Modo>(initialMode)
  const [paso, setPaso] = useState<1 | 2>(1) // asistente de la cita (1: quién · 2: cómo/cuándo)

  // ── Estado de la CITA ──
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [pacienteId, setPacienteId] = useState('')
  // Paciente elegido en el combobox (para mostrarlo como chip). Con `pacienteId`.
  const [pacienteSel, setPacienteSel] = useState<{ id: string; full_name: string; record_number: string } | null>(null)
  const [pickerOpen, setPickerOpen] = useState(false) // dropdown del combobox abierto
  const comboRef = useRef<HTMLDivElement>(null)

  // Cerrar el dropdown del combobox al hacer clic fuera de él.
  useEffect(() => {
    if (!pickerOpen) return
    const alClicFuera = (e: MouseEvent): void => {
      if (comboRef.current && !comboRef.current.contains(e.target as Node)) setPickerOpen(false)
    }
    document.addEventListener('mousedown', alClicFuera)
    return () => document.removeEventListener('mousedown', alClicFuera)
  }, [pickerOpen])
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
  const [notas, setNotas] = useState('') // "¿A qué viene?" → se manda como reason
  const [quoteId, setQuoteId] = useState('') // cotización aceptada vinculada (opcional)

  // ── Repetición (multi-cita) ──
  const [repetir, setRepetir] = useState(false)
  const [frecuencia, setFrecuencia] = useState<SeriesFrequency>('weekly') // 'custom' = Personalizado (manual)
  const [topeTipo, setTopeTipo] = useState<'count' | 'until'>('count')
  const [topeCount, setTopeCount] = useState(4)
  const [topeUntil, setTopeUntil] = useState('') // 'yyyy-mm-dd'
  const [ocurrencias, setOcurrencias] = useState<{ date: string; time: string }[]>([]) // citas de la serie (editables)
  const [resultado, setResultado] = useState<AppointmentSeriesResult | null>(null)

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

  const { data: pacData, isLoading: loadingPac } = usePatients({ search: debounced })
  const { data: docData } = useDoctors()
  const { data: consData } = useConsultorios()
  const { data: tipos } = useAppointmentTypes()
  const crearCita = useCreateAppointment()
  const crearSerie = useCreateAppointmentSeries()
  const crearEvento = useCreateAgendaBlock()

  // Cotizaciones ACEPTADAS del paciente existente seleccionado (para vincular a la cita).
  // Solo aplica con paciente existente: un paciente nuevo (inline) aún no tiene cotizaciones.
  const cotizarPacienteId = modoPaciente === 'existente' ? pacienteId : ''
  const { data: cotsData, isLoading: loadingCots } = useQuotes(
    cotizarPacienteId ? { patient_id: cotizarPacienteId, status: 'accepted' } : {},
  )
  const cotizaciones = cotizarPacienteId ? cotsData?.results ?? [] : []

  const { user } = useAuth()
  // Sede activa (multi-sede F2): se agenda SIEMPRE en ella. No mandamos sucursal_id:
  // el backend la deriva del consultorio o del header X-Sucursal-Id (él es la autoridad).
  const { activeSucursal, activeSucursalId } = useSucursalActiva()
  const sedeNombre = activeSucursal?.name ?? ''
  const soyDoctor = !!user?.doctor_id
  const pacientes = pacData?.results ?? []
  // Los catálogos YA vienen filtrados por sede desde el backend (header X-Sucursal-Id).
  // Este segundo filtro es solo un cinturón de seguridad de UX: un médico sin sedes
  // asignadas atiende en todas; uno con sedes, solo en las suyas. Igual para consultorios.
  const doctores = (docData?.results ?? [])
    .filter(d => d.is_active)
    .filter(d => !activeSucursalId || d.sucursales.length === 0 || d.sucursales.some(s => s.id === activeSucursalId))
  const consultorios = (consData?.results ?? [])
    .filter(c => c.is_active)
    .filter(c => !activeSucursalId || c.sucursal === null || c.sucursal.id === activeSucursalId)
  // Consultorios permitidos: si el médico seleccionado tiene asignados, solo esos.
  const docSel = doctores.find(d => d.id === doctorId)
  const consPermitidos = (docSel && docSel.consultorios.length > 0) ? docSel.consultorios : consultorios

  // Horario/rejilla de la clínica (Mi Consultorio → Horario de la agenda).
  const { data: agendaCfg } = useAgendaConfig()
  const cfgInicio = agendaCfg?.agenda_start_hour ?? 9
  const cfgFin = agendaCfg?.agenda_end_hour ?? 18
  const cfgPaso = agendaCfg?.slot_interval_minutes ?? 30
  // Duración: la propia del médico manda sobre la de la clínica.
  const duracionMedico = docSel?.default_appointment_duration
    ?? agendaCfg?.default_appointment_duration ?? 30
  const duraciones = useMemo(() => duracionesPara(duracionMedico), [duracionMedico])
  const guardando = crearCita.isPending || crearSerie.isPending || enviando

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 300)
    return () => clearTimeout(t)
  }, [search])

  useEffect(() => {
    if (!open) return
    setModo(initialMode); setPaso(1)
    setErrores([]); setEnviando(false)
    // cita
    setSearch(''); setDebounced(''); setModoPaciente('existente'); setPickerOpen(false)
    setPacienteId(initialPatient?.id ?? ''); setPacienteSel(initialPatient ?? null)
    setNpNombre(''); setNpPaterno(''); setNpMaterno(''); setNpTel('')
    setDoctorId(user?.doctor_id ?? ''); setConsId(consultorioId ?? ''); setModalidad(initialModality); setDuracion(30); setTipoId(''); setNotas(initialReason ?? ''); setQuoteId('')
    // repetición
    setRepetir(false); setFrecuencia('weekly'); setTopeTipo('count'); setTopeCount(4); setTopeUntil(''); setOcurrencias([]); setResultado(null)
    // evento (prefill desde el slot clicado)
    setEvTitulo(''); setEvNotas(''); setEvDoctores([]); setEvTodoDia(false)
    setEvAlcance(consultorioId ? 'consultorios' : 'clinica')
    setEvCons(consultorioId ? [consultorioId] : [])
    setEvIni(horaInicio); setEvFin(addMin(horaInicio, 60))
  }, [open, initialMode, initialModality, consultorioId, horaInicio, initialPatient?.id, initialReason])

  // Si el médico cambia y el consultorio elegido ya no le pertenece, lo limpiamos.
  useEffect(() => {
    if (consId && docSel && docSel.consultorios.length > 0 && !docSel.consultorios.some(c => c.id === consId)) {
      setConsId('')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doctorId])

  // Al elegir médico, precargar SU duración de consulta (manda sobre la de la
  // clínica). Así no hay que corregirla a mano en cada cita.
  useEffect(() => {
    if (docSel) setDuracion(duracionMedico)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doctorId, duracionMedico])

  // La cotización pertenece a UN paciente: si cambia el paciente (o el modo), se deselecciona.
  useEffect(() => { setQuoteId('') }, [pacienteId, modoPaciente])

  // ── Repetición: una sola lista de ocurrencias editables (con disponibilidad) ──
  // Consultorio que usaría la cita (null en telemedicina/fuera).
  const consultorioCita = modalidad === 'office' ? (consPermitidos.some(c => c.id === consId) ? consId : null) : null

  // En modos automáticos, regenera la lista al cambiar la regla.
  useEffect(() => {
    if (!repetir || frecuencia === 'custom') return
    const base = fromDayKey(dayKey)
    const [hh, mm] = horaInicio.split(':').map(Number)
    base.setHours(hh, mm, 0, 0)
    const fechas = seriesDates({
      start: base,
      frequency: frecuencia,
      count: topeTipo === 'count' ? topeCount : null,
      until: topeTipo === 'until' && topeUntil ? fromDayKey(topeUntil) : null,
    })
    setOcurrencias(fechas.map(d => ({ date: toDayKey(d), time: horaInicio })))
  }, [repetir, frecuencia, topeTipo, topeCount, topeUntil, dayKey, horaInicio])

  const editarOcc = (i: number, patch: Partial<{ date: string; time: string }>) =>
    setOcurrencias(prev => prev.map((c, j) => (j === i ? { ...c, ...patch } : c)))
  const quitarOcc = (i: number) => setOcurrencias(prev => prev.filter((_, j) => j !== i))
  const agregarOcc = () => setOcurrencias(prev => {
    const last = prev[prev.length - 1]
    const next = last ? toDayKey(addDays(fromDayKey(last.date), 7)) : dayKey
    return [...prev, { date: next, time: last?.time ?? horaInicio }]
  })

  // Disponibilidad (horarios ocupados) del médico en el rango de las ocurrencias.
  const diasOrden = [...ocurrencias.map(o => o.date)].sort()
  const dispFrom = diasOrden.length ? combineToISO(diasOrden[0], '00:00') : ''
  const dispTo = diasOrden.length ? combineToISO(diasOrden[diasOrden.length - 1], '23:59') : ''
  const { data: dispData } = useAgendaDisponibilidad({
    doctorId, consultorioId: consultorioCita, from: dispFrom, to: dispTo,
    enabled: repetir && modo === 'cita' && !!doctorId,
  })
  const busy = dispData?.busy ?? []
  const slotOcupado = (startISO: string, endISO: string) =>
    busy.some(b => new Date(startISO).getTime() < new Date(b.end).getTime() && new Date(endISO).getTime() > new Date(b.start).getTime())
  const ocupadoEn = (date: string, time: string) => {
    const sISO = combineToISO(date, time)
    const eISO = new Date(new Date(sISO).getTime() + duracion * 60_000).toISOString()
    return slotOcupado(sISO, eISO)
  }
  // Horas de inicio del día: salen de la configuración de la clínica (Mi
  // Consultorio → Horario de la agenda). Antes estaban fijas a 9:00–17:30/30min,
  // así que no respetaban el horario configurado.
  const SLOTS_HORA = useMemo(() => {
    const total = Math.max(0, (cfgFin - cfgInicio) * 60)
    const n = Math.max(1, Math.ceil(total / cfgPaso))
    return Array.from({ length: n }, (_, i) => {
      const mins = cfgInicio * 60 + i * cfgPaso
      return `${String(Math.floor(mins / 60)).padStart(2, '0')}:${String(mins % 60).padStart(2, '0')}`
    })
  }, [cfgInicio, cfgFin, cfgPaso])
  const horaCorta = (t: string) => {
    const [h, m] = t.split(':').map(Number)
    const h12 = h % 12 === 0 ? 12 : h % 12
    return m === 0 ? `${h12}` : `${h12}:${String(m).padStart(2, '0')}`
  }

  const activarNuevoPaciente = () => {
    if (!npNombre && !npPaterno && search.trim()) {
      const p = partirNombre(search)
      setNpNombre(p.nombre); setNpPaterno(p.paterno); setNpMaterno(p.materno)
    }
    setPickerOpen(false)
    setModoPaciente('nuevo')
  }

  // Combobox de paciente existente: elegir del dropdown / limpiar la selección.
  const elegirPaciente = (p: { id: string; full_name: string; record_number: string }) => {
    setPacienteId(p.id)
    setPacienteSel({ id: p.id, full_name: p.full_name, record_number: p.record_number })
    setPickerOpen(false); setSearch(''); setDebounced('')
  }
  const limpiarPaciente = () => {
    setPacienteId(''); setPacienteSel(null); setSearch(''); setDebounced(''); setPickerOpen(true)
  }

  // Paso 1 del asistente: paciente + médico.
  const validarPaciente = (): string[] => {
    const faltan: string[] = []
    if (modoPaciente === 'existente') {
      if (!pacienteId) faltan.push('Selecciona un paciente.')
    } else {
      if (!npNombre.trim()) faltan.push('El nombre del paciente es obligatorio.')
      if (!npPaterno.trim()) faltan.push('El apellido paterno es obligatorio.')
    }
    if (!doctorId) faltan.push('Selecciona un doctor.')
    return faltan
  }

  const irPaso2 = () => {
    const faltan = validarPaciente()
    if (faltan.length) { setErrores(faltan); return }
    setErrores([]); setPaso(2)
  }

  const guardarCita = async () => {
    setErrores([])
    const faltan = validarPaciente()
    if (faltan.length) { setErrores(faltan); setPaso(1); return }

    if (repetir && ocurrencias.length < 2) {
      setErrores(['La serie necesita al menos 2 citas (ajusta o agrega fechas).'])
      return
    }

    try {
      const startISO = combineToISO(dayKey, horaInicio)
      const endISO = new Date(new Date(startISO).getTime() + duracion * 60_000).toISOString()
      const doctorSel = doctores.find(d => d.id === doctorId)
      const pacienteRef = modoPaciente === 'nuevo'
        ? { new_patient: { first_name: npNombre.trim(), paternal_surname: npPaterno.trim(), maternal_surname: npMaterno.trim(), phone: npTel.trim() } }
        : { patient_id: pacienteId }
      const base = {
        ...pacienteRef,
        doctor_id: doctorId,
        consultorio_id: modalidad === 'office' ? (consPermitidos.some(c => c.id === consId) ? consId : null) : null,
        modality: modalidad,
        appointment_type_id: tipoId || null,
        starts_at: startISO,
        ends_at: endISO,
        specialty: doctorSel?.specialty ?? '',
        reason: notas.trim(), // "¿a qué viene?" → reason (se ve en la tarjeta)
      }
      if (repetir) {
        // La serie NO vincula cotización: una cotización aceptada es de una sola visita.
        const explicit = ocurrencias.map(o => combineToISO(o.date, o.time))
        const res = await crearSerie.mutateAsync({
          ...base,
          starts_at: explicit[0],
          ends_at: new Date(new Date(explicit[0]).getTime() + duracion * 60_000).toISOString(),
          explicit_starts: explicit,
        })
        setResultado(res) // muestra el resumen; no cierra el modal
      } else {
        await crearCita.mutateAsync({ ...base, quote_id: quoteId || null })
        onClose()
      }
    } catch (err) { setErrores(erroresConSede(err, sedeNombre)) }
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
    } catch (err) { setErrores(erroresConSede(err, sedeNombre)) } finally { setEnviando(false) }
  }

  const guardar = () => (modo === 'cita' ? guardarCita() : guardarEvento())

  const selectModo = (m: Modo) => { setModo(m); setPaso(1); setErrores([]) }

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
                  {fechaLarga}{modo === 'cita' ? ` · ${to12h(horaInicio)}${consultorioName ? ` · ${consultorioName}` : ''}` : ''}
                </p>
                {/* Sede activa: se agenda AQUÍ (el backend deriva la sucursal). */}
                {sedeNombre && (
                  <span className="mt-1.5 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold"
                    style={{ background: 'rgba(201,162,39,0.12)', color: '#9A7B1E' }}>
                    <Building2 className="w-3.5 h-3.5" />
                    {modo === 'cita' ? 'Se agenda en' : 'Aplica en'} {sedeNombre}
                  </span>
                )}
              </div>
              <button onClick={onClose} className="text-gray-400 hover:text-gray-700 transition-colors"><X className="w-6 h-6" /></button>
            </div>

            <div className="px-7 py-6 space-y-5">
              {resultado ? (
                <div className="text-center py-2">
                  <div className="w-14 h-14 mx-auto rounded-full flex items-center justify-center mb-3" style={{ background: 'rgba(46,125,91,0.15)' }}>
                    <Check className="w-7 h-7" style={{ color: '#2E7D5B' }} />
                  </div>
                  <h3 className="text-lg font-bold text-gray-900">
                    {resultado.created_count} {resultado.created_count === 1 ? 'cita agendada' : 'citas agendadas'}
                  </h3>
                  {resultado.skipped_count > 0 ? (
                    <>
                      <p className="text-sm text-gray-600 mt-1">
                        {resultado.skipped_count === 1 ? '1 no se pudo' : `${resultado.skipped_count} no se pudieron`} (horario ocupado o bloqueado):
                      </p>
                      <div className="mt-3 rounded-xl p-3 text-left space-y-1.5 max-h-52 overflow-y-auto" style={{ background: 'rgba(192,57,43,0.07)', border: '1px solid rgba(192,57,43,0.2)' }}>
                        {resultado.skipped.map((s, i) => (
                          <div key={i} className="flex items-start gap-2 text-xs" style={{ color: '#A32D2D' }}>
                            <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                            <span>{formatFechaHora(s.starts_at)}</span>
                          </div>
                        ))}
                      </div>
                      <p className="text-[11px] text-gray-400 mt-2">Puedes agendar esas a mano en otro horario.</p>
                    </>
                  ) : (
                    <p className="text-sm text-gray-600 mt-1">Todas se agendaron correctamente.</p>
                  )}
                </div>
              ) : (
              <>
              {/* Selector de tipo de registro */}
              <div className="flex gap-2.5">
                <ModoPill label="Cita" icon={CalendarPlus} active={modo === 'cita'} onClick={() => selectModo('cita')} />
                <ModoPill label="Bloqueo" icon={Ban} active={modo === 'block'} onClick={() => selectModo('block')} />
                <ModoPill label="Reunión" icon={Users} active={modo === 'meeting'} onClick={() => selectModo('meeting')} />
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
                  {/* Barra de progreso del asistente */}
                  <div>
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-xs font-bold" style={{ color: '#9A7B1E' }}>Paso {paso} de 2</span>
                      <span className="text-xs text-gray-500">{paso === 1 ? '¿A quién y con quién?' : '¿Cómo, cuándo y detalles?'}</span>
                    </div>
                    <div className="flex gap-1.5">
                      <span className="h-1.5 flex-1 rounded-full" style={{ background: '#C9A227' }} />
                      <span className="h-1.5 flex-1 rounded-full" style={{ background: paso >= 2 ? '#C9A227' : 'rgba(201,162,39,0.25)' }} />
                    </div>
                  </div>

                  {paso === 1 && (
                  <>
                  <div>
                    <label className={LABEL}>Paciente</label>
                    <div className="flex gap-2 mb-3">
                      <Pill label="Paciente existente" selected={modoPaciente === 'existente'} onClick={() => setModoPaciente('existente')} />
                      <Pill label="Paciente nuevo" selected={modoPaciente === 'nuevo'} onClick={activarNuevoPaciente} />
                    </div>
                    {modoPaciente === 'existente' ? (
                      pacienteSel ? (
                        // Paciente elegido: chip con opción de cambiarlo.
                        <div className="flex items-center justify-between gap-2 rounded-xl px-3.5 py-2.5 text-sm"
                          style={{ background: 'rgba(201,162,39,0.10)', border: '1px solid rgba(201,162,39,0.35)' }}>
                          <span style={{ color: '#2A241B' }}>
                            {pacienteSel.full_name}
                            {pacienteSel.record_number && <span style={{ color: '#9A958C' }}> · {pacienteSel.record_number}</span>}
                          </span>
                          <button type="button" onClick={limpiarPaciente} title="Cambiar paciente" className="p-0.5 rounded hover:bg-black/5">
                            <X className="w-4 h-4" style={{ color: '#7A756C' }} />
                          </button>
                        </div>
                      ) : (
                        // Combobox: escribir filtra y seleccionar ocurre en el mismo control.
                        <div className="relative" ref={comboRef}>
                          <div className="relative">
                            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
                            <input value={search} maxLength={255} autoComplete="off"
                              onChange={e => { setSearch(e.target.value); setPickerOpen(true) }}
                              onFocus={() => setPickerOpen(true)}
                              onKeyDown={e => {
                                // Escape cierra solo el dropdown, no el modal completo.
                                if (e.key === 'Escape' && pickerOpen) { e.stopPropagation(); setPickerOpen(false) }
                              }}
                              placeholder="Buscar paciente por nombre o expediente…" className={`${INPUT} pl-10`} />
                          </div>
                          {pickerOpen && debounced && (
                            <div className="absolute z-30 mt-1 w-full rounded-xl overflow-hidden shadow-lg max-h-60 overflow-y-auto"
                              style={{ background: 'rgba(255,255,255,0.97)', border: '1px solid rgba(0,0,0,0.08)' }}>
                              {loadingPac && <div className="px-3 py-2 text-xs" style={{ color: '#9A958C' }}>Buscando…</div>}
                              {!loadingPac && pacientes.length === 0 && (
                                <div className="px-3 py-2.5">
                                  <p className="text-xs mb-1.5" style={{ color: '#9A958C' }}>Sin resultados.</p>
                                  <button type="button" onClick={activarNuevoPaciente} className="text-xs font-medium hover:underline" style={{ color: '#B8860B' }}>
                                    Crea «{search.trim()}» como paciente nuevo →
                                  </button>
                                </div>
                              )}
                              {!loadingPac && pacientes.map(p => (
                                <button key={p.id} type="button" onClick={() => elegirPaciente(p)}
                                  className="w-full text-left px-3 py-2 text-sm hover:bg-amber-50 transition-colors">
                                  <span style={{ color: '#2A241B' }}>{p.full_name}</span>{' '}
                                  <span style={{ color: '#9A958C' }}>· {p.record_number}</span>
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      )
                    ) : (
                      <div className="rounded-xl p-3 space-y-3" style={{ background: 'rgba(201,162,39,0.08)', border: '1px solid rgba(201,162,39,0.25)' }}>
                        <div className="flex items-start gap-2">
                          <Info className="w-4 h-4 mt-0.5 shrink-0" style={{ color: '#C9A227' }} />
                          <p className="text-xs text-amber-800">Se creará un <b>expediente provisional</b>. Completa sus datos después en Pacientes.</p>
                        </div>
                        <input value={npNombre} maxLength={150} onChange={e => setNpNombre(e.target.value)} placeholder="Nombre(s)" className={INPUT} />
                        <div className="grid grid-cols-2 gap-3">
                          <input value={npPaterno} maxLength={150} onChange={e => setNpPaterno(e.target.value)} placeholder="Apellido paterno" className={INPUT} />
                          <input value={npMaterno} maxLength={150} onChange={e => setNpMaterno(e.target.value)} placeholder="Apellido materno" className={INPUT} />
                        </div>
                        <input value={npTel} maxLength={150} onChange={e => setNpTel(e.target.value)} placeholder="Teléfono (opcional)" className={INPUT} />
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
                  </>
                  )}

                  {paso === 2 && (
                  <>
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
                      <input value={to12h(horaInicio)} disabled className="w-28 rounded-xl border border-white/50 bg-white/40 px-4 py-2.5 text-sm text-gray-600" />
                    </div>
                    <div>
                      <label className={LABEL}>Duración</label>
                      <select value={duracion} onChange={e => setDuracion(Number(e.target.value))} className={`${INPUT} w-36`}>
                        {duraciones.map(d => (
                          <option key={d} value={d}>
                            {d} min{d === duracionMedico ? ' (del médico)' : ''}
                          </option>
                        ))}
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
                    <label className={LABEL}>¿A qué viene el paciente? <span className="text-amber-600 font-semibold">(recomendado)</span></label>
                    <textarea value={notas} onChange={e => setNotas(e.target.value)} rows={2} maxLength={255} className={`${INPUT} resize-none`} placeholder="Motivo de la consulta…" />
                  </div>

                  {/* ── Cotización aceptada del paciente (opcional, no para series) ── */}
                  {cotizarPacienteId && !repetir && (
                    <div>
                      <label className={`${LABEL} inline-flex items-center gap-1.5`}>
                        <ScrollText className="w-3.5 h-3.5" style={{ color: '#C9A227' }} />
                        Cotización <span className="text-gray-400 font-normal">(opcional)</span>
                      </label>
                      {loadingCots ? (
                        <p className="text-xs text-gray-400 inline-flex items-center gap-1.5"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Buscando cotizaciones…</p>
                      ) : cotizaciones.length === 0 ? (
                        <p className="text-xs text-gray-400">Este paciente no tiene cotizaciones aceptadas para vincular.</p>
                      ) : (
                        <select value={quoteId} onChange={e => setQuoteId(e.target.value)} className={INPUT}>
                          <option value="">Sin cotización</option>
                          {cotizaciones.map(c => (
                            <option key={c.id} value={c.id}>
                              {formatMoney(c.total)} · {c.status_display}
                            </option>
                          ))}
                        </select>
                      )}
                    </div>
                  )}

                  {/* ── Repetir esta cita (multi-cita) ── */}
                  <div className="rounded-xl p-3" style={{ background: repetir ? 'rgba(201,162,39,0.07)' : 'transparent', border: repetir ? '1px solid rgba(201,162,39,0.25)' : '1px solid rgba(0,0,0,0.06)' }}>
                    <label className="flex items-center gap-2 cursor-pointer select-none">
                      <input type="checkbox" checked={repetir} onChange={e => setRepetir(e.target.checked)} className="w-4 h-4 accent-amber-600" />
                      <span className="text-sm font-semibold text-gray-700 inline-flex items-center gap-1.5"><Repeat className="w-4 h-4" style={{ color: '#C9A227' }} /> Repetir esta cita (multi-cita)</span>
                    </label>
                    {repetir && (
                      <div className="mt-3 space-y-3">
                        <div>
                          <label className={LABEL}>Cada cuánto</label>
                          <div className="flex flex-wrap gap-2">
                            {([['weekly', 'Semanal'], ['biweekly', 'Quincenal'], ['monthly', 'Mensual'], ['custom', 'Personalizado']] as [SeriesFrequency, string][]).map(([v, l]) => (
                              <button key={v} type="button" onClick={() => setFrecuencia(v)}
                                className="px-3 py-1.5 rounded-full text-xs font-semibold transition-all"
                                style={frecuencia === v ? { background: '#C9A227', color: '#fff' } : { background: 'rgba(255,255,255,0.6)', color: '#9A7B1E', border: '1px solid rgba(201,162,39,0.3)' }}>
                                {l}
                              </button>
                            ))}
                          </div>
                        </div>

                        {frecuencia !== 'custom' && (
                          <div>
                            <label className={LABEL}>¿Hasta cuándo?</label>
                            <div className="flex gap-2 mb-2">
                              <Pill label="N veces" selected={topeTipo === 'count'} onClick={() => setTopeTipo('count')} />
                              <Pill label="Hasta una fecha" selected={topeTipo === 'until'} onClick={() => setTopeTipo('until')} />
                            </div>
                            {topeTipo === 'count' ? (
                              <div className="flex items-center gap-2">
                                <span className="text-sm text-gray-600">Repetir</span>
                                <input type="number" min={2} max={52} value={topeCount} onChange={e => setTopeCount(Number(e.target.value))} className={`${INPUT} w-20`} />
                                <span className="text-sm text-gray-600">veces (citas en total)</span>
                              </div>
                            ) : (
                              <input type="date" value={topeUntil} min={dayKey} onChange={e => setTopeUntil(e.target.value)} className={INPUT} />
                            )}
                          </div>
                        )}

                        <div>
                          <label className={LABEL}>
                            Citas de la serie <span className="text-gray-400 font-normal">({ocurrencias.length}) · los horarios <span style={{ color: '#C0392B' }}>ocupados</span> salen en rojo; toca uno libre para mover</span>
                          </label>
                          {ocurrencias.length === 0 ? (
                            <p className="text-xs text-gray-400">Ajusta la frecuencia para ver las citas.</p>
                          ) : (
                            <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(152px, 1fr))' }}>
                              {ocurrencias.map((c, i) => {
                                const ocupado = ocupadoEn(c.date, c.time)
                                return (
                                  <MiniCalendario key={i} value={c.date} min={dayKey}
                                    accent={ocupado ? 'red' : frecuencia === 'custom' ? 'gold' : 'green'}
                                    onPick={date => editarOcc(i, { date })}
                                    onRemove={ocurrencias.length > 2 ? () => quitarOcc(i) : undefined}
                                    footer={
                                      <div className="flex flex-wrap gap-1 justify-center">
                                        {SLOTS_HORA.map(t => {
                                          const ocup = ocupadoEn(c.date, t)
                                          const sel = c.time === t
                                          return (
                                            <button key={t} type="button" disabled={ocup}
                                              onClick={() => editarOcc(i, { time: t })}
                                              title={ocup ? 'Ocupado' : to12h(t)}
                                              className="text-[10px] px-1 py-0.5 rounded transition-colors"
                                              style={ocup
                                                ? { background: '#FDE8E8', color: '#C0392B', textDecoration: 'line-through', cursor: 'not-allowed' }
                                                : sel
                                                  ? { background: '#C9A227', color: '#fff', fontWeight: 600 }
                                                  : { background: 'rgba(255,255,255,0.7)', color: '#5A5246', border: '1px solid rgba(0,0,0,0.08)' }}>
                                              {horaCorta(t)}
                                            </button>
                                          )
                                        })}
                                      </div>
                                    } />
                                )
                              })}
                              {frecuencia === 'custom' && (
                                <button type="button" onClick={agregarOcc}
                                  className="rounded-2xl flex flex-col items-center justify-center gap-1 text-sm text-gray-500 transition-colors hover:bg-black/5"
                                  style={{ border: '1.5px dashed rgba(0,0,0,0.18)', minHeight: 150 }}>
                                  <Plus className="w-6 h-6" /> Agregar cita
                                </button>
                              )}
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                  </>
                  )}
                </>
              )}

              {/* ════════ FORM DE EVENTO (bloqueo/reunión) ════════ */}
              {modo !== 'cita' && (
                <>
                  <div>
                    <label className={LABEL}>Título {modo === 'block' && <span className="text-gray-400 font-normal">(opcional)</span>}</label>
                    <input className={INPUT} maxLength={150} value={evTitulo} onChange={e => setEvTitulo(e.target.value)}
                      placeholder={modo === 'block' ? 'Día festivo, vacaciones…' : 'Junta de equipo'} />
                  </div>
                  <div>
                    <label className={LABEL}>¿A qué aplica?</label>
                    <select className={INPUT} value={evAlcance} onChange={e => setEvAlcance(e.target.value as Alcance)}>
                      <option value="clinica">
                        {sedeNombre ? `Toda la sucursal ${sedeNombre}` : 'Toda la clínica'}
                      </option>
                      <option value="consultorios">Uno o varios consultorios</option>
                      <option value="doctores">Uno o varios doctores</option>
                    </select>
                    {/* Multi-sede (F2): un evento "de toda la clínica" aplica SOLO a la sede
                        activa; uno de doctor sigue al médico a TODAS sus sedes. */}
                    {evAlcance === 'clinica' && sedeNombre && (
                      <p className="text-[11px] text-gray-500 mt-1.5 inline-flex items-start gap-1.5">
                        <Building2 className="w-3.5 h-3.5 mt-px shrink-0" style={{ color: '#C9A227' }} />
                        Aplica solo a la sucursal <b>{sedeNombre}</b>. Las demás sedes no se ven afectadas.
                      </p>
                    )}
                    {evAlcance === 'doctores' && (
                      <p className="text-[11px] text-gray-500 mt-1.5">
                        Un bloqueo de doctor aplica a ese médico en <b>todas sus sedes</b>.
                      </p>
                    )}
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
                    <textarea className={`${INPUT} resize-none`} rows={2} maxLength={4000} value={evNotas} onChange={e => setEvNotas(e.target.value)} />
                  </div>
                </>
              )}
              </>
              )}
            </div>

            {/* Pie */}
            <div className="px-7 py-4 flex items-center justify-between border-t border-white/40" style={{ background: 'rgba(255,255,255,0.25)' }}>
              {resultado ? (
                <button onClick={onClose}
                  className="mx-auto px-10 py-2.5 rounded-xl text-sm font-bold text-white transition-all hover:brightness-110"
                  style={{ background: '#2E7D5B', boxShadow: '0 4px 14px rgba(46,125,91,0.4)' }}>
                  Listo
                </button>
              ) : (
                <>
                  {modo === 'cita' && paso === 2 ? (
                    <button onClick={() => { setErrores([]); setPaso(1) }} disabled={guardando}
                      className="btn-secondary disabled:opacity-60 inline-flex items-center gap-1.5">
                      <ChevronLeft className="w-4 h-4" /> Atrás
                    </button>
                  ) : (
                    <button onClick={onClose} disabled={guardando} className="btn-secondary disabled:opacity-60">Cancelar</button>
                  )}

                  {modo === 'cita' && paso === 1 ? (
                    <button onClick={irPaso2}
                      className="px-8 py-2.5 inline-flex items-center gap-2 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110"
                      style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}>
                      Siguiente <ChevronRight className="w-4 h-4" />
                    </button>
                  ) : (
                    <button onClick={guardar} disabled={guardando}
                      className="px-8 py-2.5 inline-flex items-center gap-2 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-50"
                      style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}>
                      {guardando ? <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</> : (modo === 'cita' ? (repetir ? 'Agendar serie' : 'Agendar cita') : 'Guardar evento')}
                    </button>
                  )}
                </>
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
