/**
 * CalendarizacionTab — pestaña "Calendarización" DENTRO del expediente del
 * paciente (Fase 1: calendarización de tratamientos).
 *
 * El médico arma una TABLA de tratamientos (elegidos del catálogo de servicios o
 * escritos a mano), cada uno con N sesiones. Por sesión captura la fecha
 * programada y marca cuándo se aplicó. Ve el total en vivo, guarda (PUT con el
 * estado completo) y descarga un PDF con membrete.
 *
 * Gating: la pestaña solo se muestra a owner/admin/doctor (lo decide el
 * ExpedienteDrawer con puedeEditarClinico). El backend es la autoridad (403).
 *
 * Modelo de edición (estado local):
 *   - Cada tratamiento tiene una lista de sesiones; la "cantidad de sesiones" ES
 *     el número de sesiones (sessions.length). El importe = nº sesiones × precio.
 *   - Los montos se editan como string (input controlado) y se envían como string
 *     al backend (decimal sin pérdida). Se convierten a number SOLO para sumar.
 *   - Las fechas se guardan como '' (vacío) en la UI y se mandan como null al PUT.
 */

import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Plus, Loader2, Trash2, FileDown, CalendarClock, Save, AlertTriangle, Check,
  CalendarPlus, CalendarX, CalendarCheck, Receipt, ExternalLink, Package, X,
} from 'lucide-react'

import type { PatientOut } from '../../types/paciente'
import type { ServiceConcept } from '../../api/finanzas'
import type {
  CalendarizacionResumen,
  PlanStatus,
  SessionStatus,
  Calendarizacion,
  CalendarizacionUpdateInput,
  SessionAppointment,
  TreatmentSession,
} from '../../types/calendarizacion'
import { useConcepts } from '../../hooks/finanzas'
import {
  useCalendarizaciones,
  useCalendarizacion,
  useCrearCalendarizacion,
  useGuardarCalendarizacion,
  useEliminarCalendarizacion,
  useQuitarAgendaSesion,
  useGenerarCotizacion,
  useCrearDesdePaquete,
} from '../../hooks/calendarizacion'
import { usePaquetes } from '../../hooks/paquetes'
import { useDoctors, useConsultorios } from '../../hooks/agenda'
import { getCalendarizacionPdf } from '../../api/calendarizacion'
import { errorMsg } from '../../lib/apiErrors'
import { formatMoney, formatDate } from '../../lib/format'
import { toDayKey, to12h, formatFechaHora } from '../../lib/fecha'
import { useAuth } from '../../auth/AuthContext'
import { useRole } from '../../auth/RoleContext'
import { useAviso, useConfirm } from '../common/DialogProvider'
import VisorPdf from '../VisorPdf'
import AgendarSesionModal from './AgendarSesionModal'

const ORO = '#C9A227'
const MAX_SESIONES = 52

const STATUS_LABEL: Record<PlanStatus, string> = {
  borrador: 'Borrador',
  activa: 'Activa',
  completada: 'Completada',
}

const STATUS_BADGE: Record<PlanStatus, { bg: string; color: string }> = {
  borrador: { bg: 'rgba(0,0,0,0.05)', color: '#7A756C' },
  activa: { bg: 'rgba(201,162,39,0.12)', color: '#9A7B1E' },
  completada: { bg: 'rgba(15,118,110,0.12)', color: '#0F766E' },
}

/* ── Estado editable (espejo del detalle, pero con montos/fechas como string) ── */

interface EditSession {
  /** Id de la sesión persistida, o null si es nueva (aún sin guardar). */
  id: string | null
  number: number
  scheduled_date: string
  /** Hora programada 'HH:MM' o '' (default de la cita). */
  scheduled_time: string
  /** Duración en minutos de la cita, o null. */
  duration_minutes: number | null
  applied_date: string
  status: SessionStatus
  /** Cita real vinculada, o null si no se ha agendado. */
  appointment: SessionAppointment | null
}

interface EditItem {
  /** Id del renglón persistido, o null si es nuevo. */
  id: string | null
  concept_id: string | null
  description: string
  unit_price: string
  sessions: EditSession[]
}

interface EditState {
  title: string
  notes: string
  status: PlanStatus
  /** Médico por defecto del plan (para agendar sus sesiones). */
  doctor_id: string
  /** Consultorio por defecto del plan. */
  consultorio_id: string
  items: EditItem[]
}

/** 'HH:MM:SS' | 'HH:MM' | null → 'HH:MM' | ''. */
function hhmm(time: string | null): string {
  return time ? time.slice(0, 5) : ''
}

/** Convierte el detalle del backend a estado editable (null → '' en fechas). */
function fromDetail(d: Calendarizacion): EditState {
  return {
    title: d.title,
    notes: d.notes,
    status: d.status,
    doctor_id: d.doctor_id ?? '',
    consultorio_id: d.consultorio_id ?? '',
    items: d.items.map((it) => ({
      id: it.id,
      concept_id: it.concept_id,
      description: it.description,
      unit_price: it.unit_price,
      sessions: it.sessions.map((s) => ({
        id: s.id,
        number: s.number,
        scheduled_date: s.scheduled_date ?? '',
        scheduled_time: hhmm(s.scheduled_time),
        duration_minutes: s.duration_minutes,
        applied_date: s.applied_date ?? '',
        status: s.status,
        appointment: s.appointment,
      })),
    })),
  }
}

/**
 * Construye el cuerpo del PUT (estado completo). Manda SIEMPRE los `id` de items y
 * sesiones existentes para que el backend conserve las citas agendadas y el estado
 * aplicado. El `appointment` NO se manda (lo gestiona el endpoint de agendar).
 */
function toUpdateInput(s: EditState): CalendarizacionUpdateInput {
  return {
    title: s.title.trim() || 'Plan de tratamiento',
    notes: s.notes,
    status: s.status,
    doctor_id: s.doctor_id || null,
    consultorio_id: s.consultorio_id || null,
    items: s.items.map((it) => ({
      ...(it.id ? { id: it.id } : {}),
      concept_id: it.concept_id,
      description: it.description.trim(),
      unit_price: it.unit_price === '' ? '0' : it.unit_price,
      quantity: it.sessions.length,
      sessions: it.sessions.map((se, i) => ({
        ...(se.id ? { id: se.id } : {}),
        number: i + 1,
        scheduled_date: se.scheduled_date || null,
        scheduled_time: se.scheduled_time || null,
        duration_minutes: se.duration_minutes,
        applied_date: se.applied_date || null,
        status: se.status,
      })),
    })),
  }
}

/** Importe de un tratamiento: nº de sesiones × precio unitario. */
function itemTotal(it: EditItem): number {
  return it.sessions.length * Number(it.unit_price || 0)
}

function emptySession(number: number): EditSession {
  return {
    id: null, number, scheduled_date: '', scheduled_time: '',
    duration_minutes: null, applied_date: '', status: 'programada', appointment: null,
  }
}

function emptyItem(): EditItem {
  return { id: null, concept_id: null, description: '', unit_price: '', sessions: [emptySession(1)] }
}

/** Reemplaza en el estado editable una sesión (por id) con lo que devolvió el backend. */
function mergeSession(state: EditState, s: TreatmentSession): EditState {
  return {
    ...state,
    items: state.items.map((it) => ({
      ...it,
      sessions: it.sessions.map((se) =>
        se.id && se.id === s.id
          ? {
              ...se,
              scheduled_date: s.scheduled_date ?? '',
              scheduled_time: hhmm(s.scheduled_time),
              duration_minutes: s.duration_minutes,
              status: s.status,
              appointment: s.appointment,
            }
          : se,
      ),
    })),
  }
}

/**
 * Aplica los campos persistidos de una sesión al cuerpo-baseline (snapshot) sin
 * arrastrar otros cambios sin guardar: agendar/quitar escribe en el backend al
 * instante, así que esa sesión deja de contar como "sucia".
 */
function mergeSessionIntoInput(
  input: CalendarizacionUpdateInput,
  s: TreatmentSession,
): CalendarizacionUpdateInput {
  return {
    ...input,
    items: input.items.map((it) => ({
      ...it,
      sessions: it.sessions.map((se) =>
        se.id && se.id === s.id
          ? {
              ...se,
              scheduled_date: s.scheduled_date ?? null,
              scheduled_time: hhmm(s.scheduled_time) || null,
              duration_minutes: s.duration_minutes,
              status: s.status,
            }
          : se,
      ),
    })),
  }
}

interface Props {
  paciente: PatientOut
}

export default function CalendarizacionTab({ paciente }: Props) {
  const patientId = paciente.id
  const aviso = useAviso()
  const confirmar = useConfirm()
  const navigate = useNavigate()

  const lista = useCalendarizaciones(patientId)
  const conceptsQuery = useConcepts()
  const concepts: ServiceConcept[] = conceptsQuery.data?.results ?? []
  const paquetesQuery = usePaquetes()
  const paquetes = useMemo(() => paquetesQuery.data?.results ?? [], [paquetesQuery.data])

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [verPdf, setVerPdf] = useState(false)
  // Selector "Nueva desde paquete" (Fase 3c): abierto + paquete elegido.
  const [desdePaqueteOpen, setDesdePaqueteOpen] = useState(false)
  const [pkgId, setPkgId] = useState('')

  const planes: CalendarizacionResumen[] = useMemo(
    () => lista.data?.results ?? [],
    [lista.data],
  )

  // Auto-selecciona el plan más reciente cuando aún no hay uno elegido.
  useEffect(() => {
    if (!selectedId && planes.length > 0) {
      setSelectedId(planes[0].id)
    }
  }, [planes, selectedId])

  const detalle = useCalendarizacion(selectedId, Boolean(selectedId))
  const crear = useCrearCalendarizacion(patientId)
  const guardar = useGuardarCalendarizacion(selectedId ?? '', patientId)
  const eliminar = useEliminarCalendarizacion(patientId)
  const quitarAgenda = useQuitarAgendaSesion(selectedId ?? '')
  const generarCot = useGenerarCotizacion(selectedId ?? '')
  const crearDesdePaquete = useCrearDesdePaquete(patientId)

  const { user } = useAuth()
  const { role } = useRole()
  // Acciones de cotización/paquete: owner/admin/doctor (el backend es la autoridad).
  const puedeAcciones = role === 'owner' || role === 'admin' || role === 'doctor'
  // Un médico solo puede calendarizar/agendar para sí mismo y en sus consultorios
  // (misma regla que la agenda). El administrador (owner/admin) calendariza para
  // cualquier médico y consultorio de toda la clínica.
  const soloPropio = role === 'doctor'
  const { data: docData } = useDoctors()
  const { data: consData } = useConsultorios()
  const doctores = useMemo(() => (docData?.results ?? []).filter((d) => d.is_active), [docData])
  const consultorios = useMemo(() => (consData?.results ?? []).filter((c) => c.is_active), [consData])

  // Estado editable local + "snapshot" guardado (para detectar cambios sin guardar).
  const [edit, setEdit] = useState<EditState | null>(null)
  const [loadedId, setLoadedId] = useState<string | null>(null)
  const [savedSnapshot, setSavedSnapshot] = useState<string>('')
  // Sesión (item, sesión) que se está agendando/reagendando en el modal.
  const [agendando, setAgendando] = useState<{ i: number; si: number } | null>(null)

  // Carga el editor cuando se abre un plan distinto (no en cada refetch del mismo).
  useEffect(() => {
    if (detalle.data && detalle.data.id !== loadedId) {
      const e = fromDetail(detalle.data)
      // Médico del plan: un doctor queda fijo en sí mismo; el resto conserva
      // el que trae el plan (o el usuario si es doctor y aún no hay uno).
      if (soloPropio && user?.doctor_id) e.doctor_id = user.doctor_id
      else if (!e.doctor_id && user?.doctor_id) e.doctor_id = user.doctor_id
      setEdit(e)
      setLoadedId(detalle.data.id)
      setSavedSnapshot(JSON.stringify(toUpdateInput(e)))
    }
  }, [detalle.data, loadedId, user, soloPropio])

  const dirty = edit ? JSON.stringify(toUpdateInput(edit)) !== savedSnapshot : false
  const total = edit ? edit.items.reduce((acc, it) => acc + itemTotal(it), 0) : 0

  // Médico del plan y sus consultorios permitidos (si tiene asignados, solo esos;
  // si no, todos). Mismo criterio que la agenda (Regla B).
  const planDoctor = doctores.find((d) => d.id === edit?.doctor_id)
  const consPermitidosPlan =
    planDoctor && planDoctor.consultorios.length > 0 ? planDoctor.consultorios : consultorios

  // Si el consultorio elegido ya no pertenece al médico del plan, se limpia.
  useEffect(() => {
    if (
      edit?.consultorio_id &&
      planDoctor &&
      planDoctor.consultorios.length > 0 &&
      !planDoctor.consultorios.some((c) => c.id === edit.consultorio_id)
    ) {
      setEdit((p) => (p ? { ...p, consultorio_id: '' } : p))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [edit?.doctor_id])

  /* ── Mutaciones de estructura del editor ─────────────────────────────────── */

  const patchItem = (i: number, patch: Partial<EditItem>): void =>
    setEdit((prev) =>
      prev
        ? { ...prev, items: prev.items.map((x, j) => (j === i ? { ...x, ...patch } : x)) }
        : prev,
    )

  const patchSession = (i: number, si: number, patch: Partial<EditSession>): void =>
    setEdit((prev) =>
      prev
        ? {
            ...prev,
            items: prev.items.map((x, j) =>
              j === i
                ? { ...x, sessions: x.sessions.map((s, k) => (k === si ? { ...s, ...patch } : s)) }
                : x,
            ),
          }
        : prev,
    )

  const addItem = (): void =>
    setEdit((prev) => (prev ? { ...prev, items: [...prev.items, emptyItem()] } : prev))

  const removeItem = (i: number): void =>
    setEdit((prev) => (prev ? { ...prev, items: prev.items.filter((_, j) => j !== i) } : prev))

  /** Elige un servicio del catálogo: rellena descripción + precio (editables). */
  const pickConcept = (i: number, conceptId: string): void => {
    if (!conceptId) {
      patchItem(i, { concept_id: null })
      return
    }
    const c = concepts.find((x) => x.id === conceptId)
    if (!c) return
    patchItem(i, { concept_id: c.id, description: c.name, unit_price: String(c.base_price) })
  }

  /** Ajusta el nº de sesiones de un tratamiento manteniendo las existentes. */
  const setSessionCount = (i: number, raw: number): void => {
    const n = Math.max(1, Math.min(MAX_SESIONES, Math.floor(raw || 1)))
    setEdit((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        items: prev.items.map((x, j) => {
          if (j !== i) return x
          const cur = x.sessions
          if (n === cur.length) return x
          if (n < cur.length) return { ...x, sessions: cur.slice(0, n) }
          const extra = Array.from({ length: n - cur.length }, (_, k) =>
            emptySession(cur.length + k + 1),
          )
          return { ...x, sessions: [...cur, ...extra] }
        }),
      }
    })
  }

  /** Marca/desmarca una sesión como aplicada (aplicada → fecha de hoy + estado). */
  const toggleAplicada = (i: number, si: number, aplicada: boolean): void => {
    if (aplicada) {
      patchSession(i, si, { status: 'aplicada', applied_date: toDayKey(new Date()) })
    } else {
      patchSession(i, si, { status: 'programada', applied_date: '' })
    }
  }

  /* ── Agenda por sesión (agendar / reagendar / quitar) ────────────────────── */

  /** Aplica la sesión que devolvió el backend al editor y avanza el snapshot. */
  const aplicarSesionAgendada = (s: TreatmentSession): void => {
    setEdit((prev) => (prev ? mergeSession(prev, s) : prev))
    setSavedSnapshot((prev) => {
      if (!prev) return prev
      try {
        return JSON.stringify(mergeSessionIntoInput(JSON.parse(prev) as CalendarizacionUpdateInput, s))
      } catch {
        return prev
      }
    })
  }

  const onQuitarAgenda = (sessionId: string): void => {
    quitarAgenda.mutate(sessionId, {
      onSuccess: (s) => {
        aplicarSesionAgendada(s)
        void aviso({ mensaje: 'Sesión quitada de la agenda.', tipo: 'exito' })
      },
      onError: (e) => void aviso({ mensaje: errorMsg(e), tipo: 'error' }),
    })
  }

  /* ── Acciones de plan (crear / guardar / eliminar / PDF) ─────────────────── */

  const nuevaCalendarizacion = (): void => {
    crear.mutate(
      { title: 'Plan de tratamiento', status: 'borrador' },
      {
        onSuccess: (data) => setSelectedId(data.id),
        onError: (e) => void aviso({ mensaje: errorMsg(e), tipo: 'error' }),
      },
    )
  }

  /** Fase 3c: crea una calendarización nueva expandiendo el paquete elegido. */
  const nuevaDesdePaquete = (): void => {
    if (!pkgId) return
    crearDesdePaquete.mutate(pkgId, {
      onSuccess: (plan) => {
        setSelectedId(plan.id)
        setDesdePaqueteOpen(false)
        setPkgId('')
        void aviso({ mensaje: 'Calendarización creada desde el paquete.', tipo: 'exito' })
      },
      onError: (e) => void aviso({ mensaje: errorMsg(e), tipo: 'error' }),
    })
  }

  /** Fase 2: genera una cotización (borrador) desde el plan seleccionado. */
  const onGenerarCotizacion = (): void => {
    if (!selectedId) return
    if (dirty) {
      void aviso({
        mensaje: 'Guarda los cambios antes de generar la cotización para que se reflejen.',
        tipo: 'info',
      })
      return
    }
    generarCot.mutate(undefined, {
      onSuccess: () => void aviso({ mensaje: 'Cotización creada (borrador).', tipo: 'exito' }),
      onError: (e) => void aviso({ mensaje: errorMsg(e), tipo: 'error' }),
    })
  }

  const onGuardar = (): void => {
    if (!edit || !selectedId) return
    guardar.mutate(toUpdateInput(edit), {
      onSuccess: (data) => {
        const e = fromDetail(data)
        setEdit(e)
        setLoadedId(data.id)
        setSavedSnapshot(JSON.stringify(toUpdateInput(e)))
        void aviso({ mensaje: 'Calendarización guardada.', tipo: 'exito' })
      },
      onError: (e) => void aviso({ mensaje: errorMsg(e), tipo: 'error' }),
    })
  }

  const onEliminar = async (): Promise<void> => {
    if (!selectedId) return
    const ok = await confirmar({
      titulo: 'Eliminar calendarización',
      mensaje: '¿Seguro que quieres eliminar este plan de tratamiento? Esta acción no se puede deshacer.',
      textoConfirmar: 'Eliminar',
      peligro: true,
    })
    if (!ok) return
    eliminar.mutate(selectedId, {
      onSuccess: () => {
        setSelectedId(null)
        setEdit(null)
        setLoadedId(null)
      },
      onError: (e) => void aviso({ mensaje: errorMsg(e), tipo: 'error' }),
    })
  }

  const onVerPdf = (): void => {
    if (dirty) {
      void aviso({
        mensaje: 'Guarda los cambios antes de descargar el PDF para que se reflejen.',
        tipo: 'info',
      })
      return
    }
    setVerPdf(true)
  }

  /* ── Render ───────────────────────────────────────────────────────────────── */

  if (lista.isLoading) {
    return (
      <div className="flex items-center justify-center py-16" style={{ color: '#9A958C' }}>
        <Loader2 className="w-6 h-6 animate-spin" />
      </div>
    )
  }

  if (lista.isError) {
    return <ErrorBox mensaje={errorMsg(lista.error)} />
  }

  return (
    <div className="space-y-4">
      {/* Encabezado + selector de planes */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h3 className="text-base font-bold flex items-center gap-2" style={{ color: '#2A241B' }}>
            <CalendarClock className="w-4 h-4" style={{ color: ORO }} />
            Calendarización de tratamientos
          </h3>
          <p className="text-sm" style={{ color: '#7A756C' }}>
            Planea los tratamientos y sus sesiones para {paciente.full_name}.
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {puedeAcciones && (
            <button
              className="inline-flex items-center gap-2 px-3 py-2.5 rounded-xl text-sm font-semibold transition-colors hover:bg-black/5"
              style={{ color: '#854F0B', border: '1px solid rgba(201,162,39,0.35)' }}
              onClick={() => setDesdePaqueteOpen((v) => !v)}
            >
              <Package className="w-4 h-4" /> Nueva desde paquete
            </button>
          )}
          <button
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-60"
            style={{ background: ORO, boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
            onClick={nuevaCalendarizacion}
            disabled={crear.isPending}
          >
            {crear.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
            Nueva calendarización
          </button>
        </div>
      </div>

      {/* Selector "Nueva desde paquete" (Fase 3c) */}
      {desdePaqueteOpen && puedeAcciones && (
        <div
          className="rounded-2xl p-4 flex items-end gap-2 flex-wrap"
          style={{ background: 'rgba(255,255,255,0.7)', border: '1px solid rgba(201,162,39,0.18)' }}
        >
          <div className="flex-1 min-w-[200px]">
            <label className="text-[11px] font-medium" style={{ color: '#9A958C' }}>Paquete</label>
            <select
              className="input"
              value={pkgId}
              onChange={(e) => setPkgId(e.target.value)}
              disabled={paquetesQuery.isLoading || crearDesdePaquete.isPending}
            >
              <option value="">Elige un paquete…</option>
              {paquetes.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} · {formatMoney(p.price)}
                </option>
              ))}
            </select>
          </div>
          <button
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-60"
            style={{ background: ORO, boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
            onClick={nuevaDesdePaquete}
            disabled={!pkgId || crearDesdePaquete.isPending}
          >
            {crearDesdePaquete.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
            Crear
          </button>
          <button
            className="p-2 rounded-xl hover:bg-black/5"
            onClick={() => { setDesdePaqueteOpen(false); setPkgId('') }}
            title="Cancelar"
          >
            <X className="w-4 h-4" style={{ color: '#7A756C' }} />
          </button>
          {paquetes.length === 0 && !paquetesQuery.isLoading && (
            <p className="text-xs w-full" style={{ color: '#7A756C' }}>
              No hay paquetes disponibles. Créalos en la sección «Paquetes».
            </p>
          )}
        </div>
      )}

      {planes.length === 0 ? (
        /* Estado vacío */
        <div
          className="rounded-2xl px-6 py-10 text-center"
          style={{ background: 'rgba(255,255,255,0.7)', border: '1px dashed rgba(201,162,39,0.35)' }}
        >
          <CalendarClock className="w-8 h-8 mx-auto mb-2" style={{ color: ORO }} />
          <p className="text-sm font-medium" style={{ color: '#2A241B' }}>
            Este paciente aún no tiene calendarizaciones.
          </p>
          <p className="text-xs mt-1" style={{ color: '#7A756C' }}>
            Crea una con «Nueva calendarización» para empezar a planear sus tratamientos.
          </p>
        </div>
      ) : (
        <>
          {/* Lista de planes (chips por fecha) */}
          <div className="flex flex-wrap gap-2">
            {planes.map((p) => (
              <PlanChip
                key={p.id}
                plan={p}
                activo={p.id === selectedId}
                onClick={() => setSelectedId(p.id)}
              />
            ))}
          </div>

          {/* Editor del plan elegido */}
          {detalle.isLoading || !edit ? (
            <div className="flex items-center justify-center py-16" style={{ color: '#9A958C' }}>
              <Loader2 className="w-6 h-6 animate-spin" />
            </div>
          ) : detalle.isError ? (
            <ErrorBox mensaje={errorMsg(detalle.error)} />
          ) : (
            <div
              className="rounded-2xl p-4 space-y-4"
              style={{ background: 'rgba(255,255,255,0.7)', border: '1px solid rgba(201,162,39,0.18)' }}
            >
              {/* Título + estado */}
              <div className="grid gap-3 sm:grid-cols-[1fr_180px]">
                <div>
                  <label className="text-[11px] font-medium" style={{ color: '#9A958C' }}>Título</label>
                  <input
                    className="input"
                    placeholder="Título del plan"
                    maxLength={200}
                    value={edit.title}
                    onChange={(e) => setEdit((p) => (p ? { ...p, title: e.target.value } : p))}
                  />
                </div>
                <div>
                  <label className="text-[11px] font-medium" style={{ color: '#9A958C' }}>Estado</label>
                  <select
                    className="input"
                    value={edit.status}
                    onChange={(e) =>
                      setEdit((p) => (p ? { ...p, status: e.target.value as PlanStatus } : p))
                    }
                  >
                    {(Object.keys(STATUS_LABEL) as PlanStatus[]).map((s) => (
                      <option key={s} value={s}>{STATUS_LABEL[s]}</option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Médico + consultorio por defecto (para agendar las sesiones) */}
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="text-[11px] font-medium" style={{ color: '#9A958C' }}>Médico del plan</label>
                  {soloPropio ? (
                    <div className="input flex items-center justify-between" style={{ background: 'rgba(255,255,255,0.4)' }}>
                      <span>{planDoctor?.full_name || user?.full_name}</span>
                      <span className="text-xs font-semibold" style={{ color: '#C9A227' }}>Tú</span>
                    </div>
                  ) : (
                    <select
                      className="input"
                      value={edit.doctor_id}
                      onChange={(e) =>
                        setEdit((p) => (p ? { ...p, doctor_id: e.target.value } : p))
                      }
                    >
                      <option value="">Sin asignar</option>
                      {doctores.map((d) => (
                        <option key={d.id} value={d.id}>{d.full_name}</option>
                      ))}
                    </select>
                  )}
                </div>
                <div>
                  <label className="text-[11px] font-medium" style={{ color: '#9A958C' }}>Consultorio del plan</label>
                  <select
                    className="input"
                    value={edit.consultorio_id}
                    onChange={(e) =>
                      setEdit((p) => (p ? { ...p, consultorio_id: e.target.value } : p))
                    }
                  >
                    <option value="">Sin consultorio</option>
                    {consPermitidosPlan.map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Tabla de tratamientos */}
              <div className="space-y-3">
                {edit.items.map((it, i) => (
                  <TreatmentRow
                    key={i}
                    item={it}
                    index={i}
                    concepts={concepts}
                    conceptsLoading={conceptsQuery.isLoading}
                    canRemove={edit.items.length > 1}
                    onPickConcept={(cid) => pickConcept(i, cid)}
                    onPatch={(patch) => patchItem(i, patch)}
                    onSetSessionCount={(n) => setSessionCount(i, n)}
                    onPatchSession={(si, patch) => patchSession(i, si, patch)}
                    onToggleAplicada={(si, val) => toggleAplicada(i, si, val)}
                    onAgendar={(si) => setAgendando({ i, si })}
                    onQuitarAgenda={onQuitarAgenda}
                    quitarPending={quitarAgenda.isPending}
                    onRemove={() => removeItem(i)}
                  />
                ))}

                <button
                  className="inline-flex items-center gap-1.5 text-sm font-medium px-3 py-2 rounded-xl transition-colors hover:bg-black/5"
                  style={{ color: '#854F0B', border: '1px dashed rgba(201,162,39,0.4)' }}
                  onClick={addItem}
                >
                  <Plus className="w-4 h-4" /> Agregar tratamiento
                </button>
              </div>

              {/* Notas */}
              <div>
                <label className="text-[11px] font-medium" style={{ color: '#9A958C' }}>Notas</label>
                <textarea
                  className="input"
                  rows={2}
                  placeholder="Notas para el paciente o el equipo (opcional)"
                  maxLength={2000}
                  value={edit.notes}
                  onChange={(e) => setEdit((p) => (p ? { ...p, notes: e.target.value } : p))}
                />
              </div>

              {/* Total + acciones */}
              <div className="flex items-center justify-between flex-wrap gap-3 pt-2 border-t" style={{ borderColor: 'rgba(0,0,0,0.06)' }}>
                <span className="text-base font-bold" style={{ color: '#2A241B' }}>
                  Total: {formatMoney(total)}
                </span>
                <div className="flex items-center gap-2 flex-wrap">
                  <button
                    className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-sm font-medium transition-colors hover:bg-black/5"
                    style={{ color: '#B91C1C', border: '1px solid rgba(185,28,28,0.25)' }}
                    onClick={onEliminar}
                    disabled={eliminar.isPending}
                  >
                    {eliminar.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
                    Eliminar
                  </button>
                  <button
                    className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-sm font-medium transition-colors hover:bg-black/5"
                    style={{ color: '#854F0B', border: '1px solid rgba(201,162,39,0.3)' }}
                    onClick={onVerPdf}
                  >
                    <FileDown className="w-4 h-4" /> Descargar PDF
                  </button>
                  {puedeAcciones && (
                    <button
                      className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-sm font-medium transition-colors hover:bg-black/5"
                      style={{ color: '#854F0B', border: '1px solid rgba(201,162,39,0.3)' }}
                      onClick={onGenerarCotizacion}
                      disabled={generarCot.isPending}
                    >
                      {generarCot.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Receipt className="w-4 h-4" />}
                      Generar cotización
                    </button>
                  )}
                  {detalle.data?.quote_id && (
                    <button
                      className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-sm font-medium transition-colors hover:bg-black/5"
                      style={{ color: '#0F766E', border: '1px solid rgba(15,118,110,0.3)' }}
                      onClick={() => navigate('/cotizaciones')}
                      title="Ir a Cotizaciones"
                    >
                      <ExternalLink className="w-4 h-4" /> Ver cotización
                    </button>
                  )}
                  <button
                    className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-60"
                    style={{ background: ORO, boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
                    onClick={onGuardar}
                    disabled={guardar.isPending}
                  >
                    {guardar.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                    Guardar
                  </button>
                </div>
              </div>
              {dirty && (
                <p className="text-xs text-right" style={{ color: '#B45309' }}>
                  Tienes cambios sin guardar.
                </p>
              )}
            </div>
          )}
        </>
      )}

      {verPdf && selectedId && (
        <VisorPdf
          titulo="Calendarización de tratamientos"
          nombreArchivo={`calendarizacion-${selectedId}.pdf`}
          cargar={() => getCalendarizacionPdf(selectedId)}
          onClose={() => setVerPdf(false)}
        />
      )}

      {/* Modal de agendar/reagendar una sesión (con disponibilidad) */}
      {agendando && selectedId && edit && (() => {
        const ses = edit.items[agendando.i]?.sessions[agendando.si]
        if (!ses || !ses.id) return null
        return (
          <AgendarSesionModal
            open
            onClose={() => setAgendando(null)}
            planId={selectedId}
            sessionId={ses.id}
            sessionNumber={agendando.si + 1}
            treatmentLabel={edit.items[agendando.i]?.description ?? ''}
            appointment={ses.appointment}
            scheduledDate={ses.scheduled_date}
            scheduledTime={ses.scheduled_time}
            durationMinutes={ses.duration_minutes}
            defaultDoctorId={edit.doctor_id}
            defaultConsultorioId={edit.consultorio_id}
            onAgendada={aplicarSesionAgendada}
          />
        )
      })()}
    </div>
  )
}

/* ── Subcomponentes ─────────────────────────────────────────────────────────── */

function ErrorBox({ mensaje }: { mensaje: string }) {
  return (
    <div
      className="flex items-start gap-3 rounded-2xl px-5 py-4"
      style={{ background: 'rgba(192,57,43,0.08)', border: '1px solid rgba(192,57,43,0.28)' }}
    >
      <AlertTriangle className="w-5 h-5 mt-0.5 shrink-0 text-red-500" />
      <p className="text-sm font-semibold text-red-700">{mensaje}</p>
    </div>
  )
}

function PlanChip({
  plan, activo, onClick,
}: {
  plan: CalendarizacionResumen
  activo: boolean
  onClick: () => void
}) {
  const badge = STATUS_BADGE[plan.status]
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-left rounded-xl px-3 py-2 transition-all"
      style={{
        background: activo ? 'rgba(201,162,39,0.12)' : 'rgba(255,255,255,0.7)',
        border: activo ? '1px solid #C9A227' : '1px solid rgba(201,162,39,0.25)',
        boxShadow: activo ? '0 2px 10px rgba(201,162,39,0.2)' : 'none',
      }}
    >
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold" style={{ color: '#2A241B' }}>
          {plan.title || 'Plan de tratamiento'}
        </span>
        <span
          className="px-2 py-0.5 rounded-full text-[10px] font-semibold"
          style={{ background: badge.bg, color: badge.color }}
        >
          {plan.status_display}
        </span>
      </div>
      <div className="text-[11px] mt-0.5" style={{ color: '#7A756C' }}>
        {formatDate(plan.created_at)} · {plan.applied_count}/{plan.sessions_count} sesiones · {formatMoney(plan.total)}
      </div>
    </button>
  )
}

function TreatmentRow({
  item, index, concepts, conceptsLoading, canRemove,
  onPickConcept, onPatch, onSetSessionCount, onPatchSession, onToggleAplicada,
  onAgendar, onQuitarAgenda, quitarPending, onRemove,
}: {
  item: EditItem
  index: number
  concepts: ServiceConcept[]
  conceptsLoading: boolean
  canRemove: boolean
  onPickConcept: (conceptId: string) => void
  onPatch: (patch: Partial<EditItem>) => void
  onSetSessionCount: (n: number) => void
  onPatchSession: (si: number, patch: Partial<EditSession>) => void
  onToggleAplicada: (si: number, val: boolean) => void
  onAgendar: (si: number) => void
  onQuitarAgenda: (sessionId: string) => void
  quitarPending: boolean
  onRemove: () => void
}) {
  const importe = itemTotal(item)
  return (
    <div className="rounded-xl p-3" style={{ background: 'rgba(0,0,0,0.03)' }}>
      {/* Cabecera del tratamiento */}
      <div className="flex items-start gap-2 justify-between">
        <span className="text-[11px] font-semibold pt-2" style={{ color: '#9A958C' }}>
          #{index + 1}
        </span>
        {canRemove && (
          <button
            className="p-1 rounded hover:bg-red-50 shrink-0"
            onClick={onRemove}
            title="Quitar tratamiento"
          >
            <Trash2 className="w-4 h-4" style={{ color: '#B91C1C' }} />
          </button>
        )}
      </div>

      <div className="grid gap-2 md:grid-cols-[1.2fr_2fr_80px_120px_110px] items-end">
        {/* Selector de tratamiento del catálogo */}
        <div>
          <label className="text-[10px] font-medium" style={{ color: '#9A958C' }}>Tratamiento</label>
          <select
            className="input"
            value={item.concept_id ?? ''}
            onChange={(e) => onPickConcept(e.target.value)}
            disabled={conceptsLoading}
          >
            <option value="">Manual…</option>
            {concepts.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>
        {/* Descripción */}
        <div>
          <label className="text-[10px] font-medium" style={{ color: '#9A958C' }}>Descripción</label>
          <input
            className="input"
            placeholder="Descripción del tratamiento"
            maxLength={255}
            value={item.description}
            onChange={(e) => onPatch({ description: e.target.value })}
          />
        </div>
        {/* Nº de sesiones */}
        <div>
          <label className="text-[10px] font-medium" style={{ color: '#9A958C' }}>Sesiones</label>
          <input
            className="input text-right"
            type="number"
            min={1}
            max={MAX_SESIONES}
            value={item.sessions.length}
            onChange={(e) => onSetSessionCount(Number(e.target.value))}
          />
        </div>
        {/* Precio unitario */}
        <div>
          <label className="text-[10px] font-medium" style={{ color: '#9A958C' }}>Precio</label>
          <input
            className="input text-right"
            type="number"
            min={0}
            step="0.01"
            placeholder="0.00"
            value={item.unit_price}
            onChange={(e) => onPatch({ unit_price: e.target.value })}
          />
        </div>
        {/* Importe */}
        <div className="text-right">
          <label className="text-[10px] font-medium block" style={{ color: '#9A958C' }}>Importe</label>
          <span className="text-sm font-semibold" style={{ color: '#2A241B' }}>
            {formatMoney(importe)}
          </span>
        </div>
      </div>

      {/* Sub-filas por sesión */}
      <div className="mt-3 space-y-2">
        {item.sessions.map((s, si) => {
          const aplicada = s.status === 'aplicada'
          const appt = s.appointment
          const guardada = !!s.id
          return (
            <div
              key={si}
              className="rounded-lg p-2.5"
              style={{ background: 'rgba(255,255,255,0.6)', border: '1px solid rgba(0,0,0,0.06)' }}
            >
              {/* Cabecera de la sesión: nº + badges + marcar aplicada */}
              <div className="flex flex-wrap items-center gap-2 justify-between">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs font-semibold" style={{ color: '#7A756C' }}>
                    Sesión {si + 1}
                  </span>
                  <SessionBadge status={s.status} />
                  {appt && (
                    <span
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold"
                      style={{ background: 'rgba(15,118,110,0.12)', color: '#0F766E' }}
                    >
                      <CalendarCheck className="w-3 h-3" /> Agendada · {formatFechaHora(appt.starts_at)}
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => onToggleAplicada(si, !aplicada)}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-semibold transition-colors"
                  style={
                    aplicada
                      ? { background: 'rgba(15,118,110,0.12)', color: '#0F766E' }
                      : { background: 'rgba(201,162,39,0.12)', color: '#9A7B1E' }
                  }
                  title={aplicada ? 'Marcar como no aplicada' : 'Marcar como aplicada (hoy)'}
                >
                  <Check className="w-3.5 h-3.5" /> {aplicada ? 'Aplicada' : 'Marcar aplicada'}
                </button>
              </div>

              {/* Zona de agenda */}
              {appt ? (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <span className="text-[11px]" style={{ color: '#7A756C' }}>
                    {appt.doctor_name}{appt.consultorio_name ? ` · ${appt.consultorio_name}` : ''}
                  </span>
                  <div className="flex-1" />
                  <button
                    type="button"
                    onClick={() => onAgendar(si)}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-semibold transition-colors hover:bg-black/5"
                    style={{ color: '#854F0B', border: '1px solid rgba(201,162,39,0.35)' }}
                  >
                    <CalendarPlus className="w-3.5 h-3.5" /> Reagendar
                  </button>
                  <button
                    type="button"
                    onClick={() => onQuitarAgenda(s.id as string)}
                    disabled={quitarPending}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-semibold transition-colors hover:bg-red-50 disabled:opacity-60"
                    style={{ color: '#B91C1C', border: '1px solid rgba(185,28,28,0.25)' }}
                  >
                    {quitarPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CalendarX className="w-3.5 h-3.5" />} Quitar de agenda
                  </button>
                </div>
              ) : (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <label className="flex items-center gap-1.5 text-[11px]" style={{ color: '#9A958C' }}>
                    <span className="whitespace-nowrap">Programada</span>
                    <input
                      className="input"
                      type="date"
                      value={s.scheduled_date}
                      onChange={(e) => onPatchSession(si, { scheduled_date: e.target.value })}
                    />
                  </label>
                  {s.scheduled_time && (
                    <span className="text-[11px]" style={{ color: '#7A756C' }}>· {to12h(s.scheduled_time)}</span>
                  )}
                  <div className="flex-1" />
                  <button
                    type="button"
                    onClick={() => onAgendar(si)}
                    disabled={!guardada}
                    title={guardada ? 'Agendar como cita (con disponibilidad)' : 'Guarda el plan antes de agendar'}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-semibold text-white transition-all hover:brightness-110 disabled:opacity-50"
                    style={{ background: ORO }}
                  >
                    <CalendarPlus className="w-3.5 h-3.5" /> Agendar
                  </button>
                </div>
              )}

              {/* Fecha de aplicación (solo si está aplicada) */}
              {aplicada && (
                <label className="mt-2 flex items-center gap-1.5 text-[11px]" style={{ color: '#0F766E' }}>
                  <span className="whitespace-nowrap">Aplicada</span>
                  <input
                    className="input"
                    type="date"
                    value={s.applied_date}
                    onChange={(e) => onPatchSession(si, { applied_date: e.target.value })}
                  />
                </label>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function SessionBadge({ status }: { status: SessionStatus }) {
  const aplicada = status === 'aplicada'
  return (
    <span
      className="px-2 py-0.5 rounded-full text-[10px] font-semibold"
      style={
        aplicada
          ? { background: 'rgba(15,118,110,0.12)', color: '#0F766E' }
          : { background: 'rgba(0,0,0,0.05)', color: '#7A756C' }
      }
    >
      {aplicada ? 'Aplicada' : 'Programada'}
    </span>
  )
}
