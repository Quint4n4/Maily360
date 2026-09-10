import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Search, Plus, Phone, CalendarDays, CalendarPlus, Loader2, AlertCircle, AlertTriangle, Star, Crown, CalendarRange, Tag, LayoutGrid, List } from 'lucide-react'
import Topbar from '../components/Topbar'
import NuevoPacienteDrawer from '../components/contactos/NuevoPacienteDrawer'
import ExpedienteDrawer from '../components/contactos/ExpedienteDrawer'
import EtiquetasQuickMenu from '../components/contactos/EtiquetasQuickMenu'
import MiniCalendario from '../components/agenda/MiniCalendario'
import CrearEventoModal from '../components/agenda/CrearEventoModal'
import {
  usePatient, usePatients, useDeactivatePatient, useSetPatientClassification,
} from '../hooks/pacientes'
import { useCategories } from '../hooks/clinica'
import { initialsOf } from '../lib/paciente'
import { formatFechaCorta, formatLargo, toDayKey } from '../lib/fecha'
import type { PatientOut, PatientSegment } from '../types/paciente'
import { useRole } from '../auth/RoleContext'
import { puedeEditar, puedeVerExpedienteClinico } from '../auth/permisos'
import { useConfirm } from '../components/common/DialogProvider'

/** Segmentos de filtrado (reflejan el selector del backend). */
const SEGMENTOS: { key: PatientSegment; label: string }[] = [
  { key: 'all', label: 'Todos' },
  { key: 'recent', label: 'Recientes' },
  { key: 'week', label: 'Esta semana' },
  { key: 'month', label: 'Este mes' },
  { key: 'date', label: 'Por fecha' },
  { key: 'potential', label: 'Clientes potenciales' },
  { key: 'favorites', label: 'Favoritos' },
  { key: 'vip', label: 'VIP' },
]

/** Mensaje de "sin resultados" según el segmento activo. */
function mensajeVacio(segment: PatientSegment, hayBusqueda: boolean): string {
  if (hayBusqueda) return 'No encontramos pacientes con ese criterio.'
  switch (segment) {
    case 'recent': return 'Aún no hay pacientes atendidos recientemente.'
    case 'week': return 'Nadie ha sido atendido esta semana.'
    case 'month': return 'Nadie ha sido atendido este mes.'
    case 'date': return 'Nadie fue atendido en el rango de fechas elegido.'
    case 'potential': return 'No hay clientes potenciales por ahora (pacientes que cancelaron o reagendaron y nunca se atendieron).'
    case 'favorites': return 'Aún no marcas pacientes favoritos. Usa la ⭐ en cada tarjeta.'
    case 'vip': return 'Aún no marcas pacientes VIP. Usa la 👑 en cada tarjeta.'
    default: return 'Aún no hay pacientes registrados. Crea el primero con “Nuevo paciente”.'
  }
}

/** Clave de la preferencia de vista (tarjetas vs lista) en localStorage. */
const VISTA_KEY = 'maily.pacientes.vista'

export default function ContactosPage() {
  const [query, setQuery]         = useState('')
  const [debounced, setDebounced] = useState('')
  const [segment, setSegment]     = useState<PatientSegment>('all')
  const [categoryId, setCategoryId] = useState<string | null>(null)
  const [dateFrom, setDateFrom]   = useState('')
  const [dateTo, setDateTo]       = useState('')
  // Vista de la lista de pacientes: tarjetas (por defecto) o lista compacta.
  // La preferencia se recuerda entre sesiones, como el selector de sucursal.
  const [vista, setVistaState] = useState<'cards' | 'lista'>(() => {
    const guardada = localStorage.getItem(VISTA_KEY)
    return guardada === 'lista' ? 'lista' : 'cards'
  })
  const setVista = (v: 'cards' | 'lista') => {
    setVistaState(v)
    localStorage.setItem(VISTA_KEY, v)
  }
  const [nuevoOpen, setNuevo]     = useState(false)
  const [verPaciente, setVer]     = useState<PatientOut | null>(null)
  // Paciente para "Volver a agendar" (abre CrearEventoModal precargado). Null = cerrado.
  const [reagendar, setReagendar] = useState<PatientOut | null>(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const { role } = useRole()

  // Deep-link: /contactos?paciente=<id> abre directo el expediente (p. ej. desde la campana).
  const pacienteParam = searchParams.get('paciente')
  const { data: pacienteDeepLink } = usePatient(verPaciente ? null : pacienteParam)
  // El paciente mostrado: el abierto desde la lista, o el del query param.
  const pacienteMostrado = verPaciente ?? pacienteDeepLink ?? null

  /** Quita ?paciente=<id> de la URL sin perder los demás query params. */
  const limpiarParam = () => {
    if (!pacienteParam) return
    const next = new URLSearchParams(searchParams)
    next.delete('paciente')
    setSearchParams(next, { replace: true })
  }

  const cerrarExpediente = () => {
    setVer(null)
    limpiarParam()
  }

  const editar = puedeEditar(role, 'contactos')
  const puedeAgendar = puedeEditar(role, 'agenda')
  const verClinico = puedeVerExpedienteClinico(role)

  // Slot por defecto para "Volver a agendar": hoy, próxima media hora dentro de
  // horario de oficina (9:00–17:30). El usuario ajusta el resto en el modal.
  const hoy = new Date()
  const dayKeyHoy = toDayKey(hoy)
  const horaDefault = (() => {
    const rounded = Math.ceil((hoy.getHours() * 60 + hoy.getMinutes()) / 30) * 30
    const clamped = Math.min(Math.max(rounded, 9 * 60), 17 * 60 + 30)
    return `${String(Math.floor(clamped / 60)).padStart(2, '0')}:${String(clamped % 60).padStart(2, '0')}`
  })()
  const baja = useDeactivatePatient()
  const clasificar = useSetPatientClassification()
  const confirmar = useConfirm()

  const darDeBaja = async () => {
    if (!pacienteMostrado) return
    const ok = await confirmar({
      titulo: 'Dar de baja al paciente',
      mensaje: `¿Dar de baja a ${pacienteMostrado.full_name}? Dejará de aparecer en la lista (no se borra de la base de datos).`,
      peligro: true,
      textoConfirmar: 'Dar de baja',
    })
    if (!ok) return
    baja.mutate(pacienteMostrado.id, { onSuccess: cerrarExpediente })
  }

  const toggleFavorito = (p: PatientOut) =>
    clasificar.mutate({ id: p.id, input: { is_favorite: !p.is_favorite } })
  const toggleVip = (p: PatientOut) =>
    clasificar.mutate({ id: p.id, input: { is_vip: !p.is_vip } })

  // Debounce de la búsqueda: 350 ms tras dejar de teclear → menos llamadas al backend.
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 350)
    return () => clearTimeout(t)
  }, [query])

  // Catálogo de etiquetas para los chips de filtro. Favorito/VIP son etiquetas
  // del sistema que ya tienen su propio chip arriba, así que aquí solo van las
  // personalizadas (kind='custom').
  const { data: categoriasData } = useCategories()
  const categorias = (categoriasData?.results ?? []).filter(c => c.kind === 'custom')

  // Los chips son mutuamente excluyentes: elegir un segmento limpia la etiqueta
  // activa y viceversa. Volver a tocar la etiqueta activa la deselecciona.
  const elegirSegmento = (key: PatientSegment) => {
    setSegment(key)
    setCategoryId(null)
  }
  const elegirCategoria = (id: string) => {
    setCategoryId((prev) => (prev === id ? null : id))
    setSegment('all')
  }

  const esperandoFechas = segment === 'date' && (!dateFrom || !dateTo)
  const { data, isLoading, isError, error } = usePatients({
    search: debounced,
    segment,
    dateFrom,
    dateTo,
    categoryId: categoryId ?? undefined,
  })
  const lista = data?.results ?? []
  const total = data?.count ?? 0

  return (
    <div className="min-h-screen relative">

      {/* Fondo plano: la foto de seda dorada quedaba DEBAJO de los datos
          (tarjetas, filas) y les restaba legibilidad. */}
      <div className="fixed inset-0 -z-10 bg-fondo" />

      <Topbar active="contactos" />

      <div className="p-5 max-w-[1300px] mx-auto">

        {/* ════ Cabecera: título + buscador + filtros ════ */}
        <div className="glass-card rounded-2xl px-6 py-5">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold text-tinta">Pacientes</h1>
              <p className="text-sm text-suave">
                {isLoading ? 'Cargando…' : `${total} paciente${total === 1 ? '' : 's'}`}
              </p>
            </div>
            {editar && (
              <button
                onClick={() => setNuevo(true)}
                className="btn-primary"
              >
                <Plus className="w-4 h-4" /> Nuevo paciente
              </button>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-3 mt-4">
            <div className="relative flex-1 min-w-[240px]">
              <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-tenue pointer-events-none" />
              <input
                value={query} onChange={e => setQuery(e.target.value)}
                placeholder="Buscar por nombre, apellido, teléfono o expediente"
                className="input pl-10"
              />
            </div>
          </div>

          {/* Chips de segmento (dorado) + etiquetas del catálogo (verde) */}
          <div className="flex flex-wrap items-center gap-2 mt-4">
            {/* Selector de vista: tarjetas o lista (se recuerda entre sesiones) */}
            <div className="order-last ml-auto flex items-center rounded-full p-0.5 bg-superficie-sutil border border-borde">
              <button type="button" onClick={() => setVista('cards')} title="Ver en tarjetas"
                aria-pressed={vista === 'cards'}
                className={`w-8 h-8 rounded-full flex items-center justify-center transition-all ${
                  vista === 'cards' ? 'bg-accion text-white shadow-accion' : 'text-suave hover:bg-accion-tinte'}`}>
                <LayoutGrid className="w-4 h-4" />
              </button>
              <button type="button" onClick={() => setVista('lista')} title="Ver en lista"
                aria-pressed={vista === 'lista'}
                className={`w-8 h-8 rounded-full flex items-center justify-center transition-all ${
                  vista === 'lista' ? 'bg-accion text-white shadow-accion' : 'text-suave hover:bg-accion-tinte'}`}>
                <List className="w-4 h-4" />
              </button>
            </div>

            {SEGMENTOS.map(s => {
              const activo = categoryId === null && segment === s.key
              return (
                <button key={s.key} type="button" onClick={() => elegirSegmento(s.key)}
                  className={`inline-flex items-center gap-1.5 px-4 py-1.5 rounded-full text-sm font-semibold transition-all ${
                    activo
                      ? 'bg-accion text-white shadow-accion'
                      : 'bg-superficie text-suave border border-borde hover:border-accion-borde hover:text-tinta'}`}>
                  {s.key === 'date' && <CalendarRange className="w-3.5 h-3.5" />}
                  {s.key === 'favorites' && <Star className="w-3.5 h-3.5" />}
                  {s.key === 'vip' && <Crown className="w-3.5 h-3.5" />}
                  {s.label}
                </button>
              )
            })}

            {/* Separador entre segmentos fijos y las etiquetas configurables */}
            {categorias.length > 0 && (
              <span className="self-center mx-1 h-5 w-px bg-borde" aria-hidden />
            )}

            {/* Etiquetas del catálogo (las que crea el doctor en Mi Consultorio) */}
            {categorias.map(c => {
              const activo = categoryId === c.id
              return (
                <button key={c.id} type="button" onClick={() => elegirCategoria(c.id)}
                  className={`inline-flex items-center gap-1.5 px-4 py-1.5 rounded-full text-sm font-semibold transition-all ${
                    activo
                      ? 'bg-accion text-white shadow-accion'
                      : 'bg-superficie text-suave border border-borde hover:border-accion-borde hover:text-tinta'}`}>
                  <Tag className="w-3.5 h-3.5" />
                  {c.name}
                </button>
              )
            })}
          </div>
        </div>

        {/* ════ Panel de rango de fechas (solo segmento "Por fecha") ════ */}
        {segment === 'date' && (
          <div className="glass-card rounded-2xl mt-4 px-6 py-5">
            <p className="text-sm text-cuerpo mb-3">
              Elige un <strong>rango de fechas</strong>: verás los pacientes atendidos entre esos días.
            </p>
            <div className="flex flex-wrap gap-5">
              <div>
                <label className="label mb-1.5 block">Desde</label>
                <MiniCalendario value={dateFrom || null} onPick={setDateFrom}
                  footer={<div className="text-center text-[11px] font-medium text-suave">
                    {dateFrom ? formatFechaCorta(dateFrom) : 'Sin elegir'}
                  </div>} />
              </div>
              <div>
                <label className="label mb-1.5 block">Hasta</label>
                <MiniCalendario value={dateTo || null} onPick={setDateTo} min={dateFrom || undefined}
                  footer={<div className="text-center text-[11px] font-medium text-suave">
                    {dateTo ? formatFechaCorta(dateTo) : 'Sin elegir'}
                  </div>} />
              </div>
            </div>
            {esperandoFechas && (
              <p className="text-xs mt-3 text-aviso">
                Elige <strong>ambas</strong> fechas para ver los resultados.
              </p>
            )}
          </div>
        )}

        {/* ════ Estado de error ════ */}
        {isError && (
          <div className="glass-card rounded-2xl mt-7 py-10 px-6 flex items-center justify-center gap-3 text-center">
            <AlertCircle className="w-5 h-5 text-peligro shrink-0" />
            <p className="text-sm text-peligro">
              No se pudieron cargar los pacientes. {error instanceof Error ? error.message : ''}
            </p>
          </div>
        )}

        {/* ════ Estado de carga ════ */}
        {isLoading && !isError && !esperandoFechas && (
          <div className="flex items-center justify-center gap-2 mt-16 text-accion">
            <Loader2 className="w-5 h-5 animate-spin" /> Cargando pacientes…
          </div>
        )}

        {/* ════ Cuadrícula de carpetas (folders) ════ */}
        {!isLoading && !isError && !esperandoFechas && (
          vista === 'lista' ? (
          /* ════ Vista LISTA: filas compactas (más pacientes a la vista) ════ */
          /* Los datos van en COLUMNAS alineadas, no en una frase corrida.
             Antes cada fila era "EXP · teléfono · fecha · falta completar" y
             eso obliga a LEER; en columnas el ojo ESCANEA en vertical (bajas
             por la columna de teléfonos sin mirar nada más). Con 14 pacientes
             se nota; con 200 es la diferencia entre usable e inservible. */
          <div className="glass-card rounded-2xl mt-7 overflow-hidden">
            {lista.length === 0 && (
              <div className="py-16 text-center">
                <p className="text-suave text-sm">{mensajeVacio(segment, !!debounced)}</p>
              </div>
            )}

            {/* Cabecera de columnas (solo en pantallas anchas: en móvil la fila
                se apila y una cabecera fija mentiría sobre lo que hay debajo). */}
            {lista.length > 0 && (
              <div className="hidden md:grid items-center gap-3 px-4 py-2 bg-superficie-sutil border-b border-borde
                              text-[10px] font-semibold uppercase tracking-wide text-suave"
                style={{ gridTemplateColumns: '1fr 8.5rem 9rem 7rem 6rem' }}>
                <span>Paciente</span>
                <span>Expediente</span>
                <span>Teléfono</span>
                <span>Última cita</span>
                <span className="text-right">Acciones</span>
              </div>
            )}

            {lista.map((p, i) => (
              <div
                key={p.id}
                className="group grid items-center gap-3 px-4 py-2.5 transition-colors hover:bg-accion-tinte
                           grid-cols-1 md:grid-cols-[1fr_8.5rem_9rem_7rem_6rem]"
                style={{ borderTop: i === 0 ? 'none' : '1px solid var(--borde)' }}
              >
                {/* Columna 1 — identidad (lo único pulsable para entrar) */}
                <button onClick={() => setVer(p)} aria-label={`Abrir expediente de ${p.full_name}`}
                  className="flex items-center gap-3 min-w-0 text-left">
                  <span className="w-9 h-9 rounded-full overflow-hidden flex items-center justify-center text-xs font-bold shrink-0"
                    style={{
                      background: 'var(--accion-tinte)',
                      color: 'var(--aviso)',
                      outline: p.is_vip ? '2px solid var(--tinta)' : 'none',
                      outlineOffset: 1,
                    }}>
                    {p.avatar ? <img src={p.avatar} alt="" className="w-full h-full object-cover" /> : initialsOf(p)}
                  </span>
                  <span className="flex items-center gap-2 min-w-0 flex-wrap">
                    <span className="text-sm font-semibold text-tinta truncate">{p.full_name}</span>
                    {p.is_provisional && (
                      <span title="Falta completar datos personales" className="inline-flex shrink-0">
                        <AlertTriangle className="w-3.5 h-3.5 text-aviso-icono"
                          aria-label="Falta completar datos personales" />
                      </span>
                    )}
                    {p.is_vip && <span className="badge badge-vip shrink-0">VIP</span>}
                    {p.categories.map(c => (
                      <span key={c.id}
                        className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-superficie-sutil text-suave ring-1 ring-borde">
                        <Tag className="w-2.5 h-2.5" />{c.name}
                      </span>
                    ))}
                  </span>
                </button>

                {/* Columnas de datos. En móvil se apilan bajo el nombre y
                    recuperan su etiqueta, que ahí no hay cabecera. */}
                <span className="text-[11px] font-medium text-tenue tabular-nums truncate pl-12 md:pl-0">
                  {p.record_number}
                </span>
                <span className="flex items-center gap-1.5 text-xs text-cuerpo truncate pl-12 md:pl-0">
                  <Phone className="w-3 h-3 text-tenue shrink-0 md:hidden" />{p.phone || '—'}
                </span>
                <span className="flex items-center gap-1.5 text-xs text-cuerpo truncate pl-12 md:pl-0">
                  <CalendarDays className="w-3 h-3 text-tenue shrink-0 md:hidden" />
                  {p.last_seen_at ? formatFechaCorta(p.last_seen_at) : 'Sin citas'}
                </span>

                {/* Acciones — misma regla que en las tarjetas: el ESTADO siempre,
                    la ACCIÓN de marcar solo al pasar el cursor por la fila. */}
                <span className="flex items-center justify-end gap-1 pl-12 md:pl-0">
                  {editar && (
                    <>
                      <button type="button" title={p.is_favorite ? 'Quitar de favoritos' : 'Marcar como favorito'}
                        onClick={() => toggleFavorito(p)}
                        className={`w-7 h-7 rounded-full flex items-center justify-center transition-all hover:bg-superficie
                          ${p.is_favorite ? '' : 'acciones-hover opacity-0 group-hover:opacity-100 focus:opacity-100'}`}>
                        <Star className="w-4 h-4" style={{ fill: p.is_favorite ? 'var(--accion)' : 'transparent', color: p.is_favorite ? 'var(--accion)' : 'var(--tenue)' }} />
                      </button>
                      <button type="button" title={p.is_vip ? 'Quitar VIP' : 'Marcar como VIP'}
                        onClick={() => toggleVip(p)}
                        className={`w-7 h-7 rounded-full flex items-center justify-center transition-all hover:bg-superficie
                          ${p.is_vip ? '' : 'acciones-hover opacity-0 group-hover:opacity-100 focus:opacity-100'}`}>
                        <Crown className="w-4 h-4" style={{ fill: p.is_vip ? 'var(--tinta)' : 'transparent', color: p.is_vip ? 'var(--tinta)' : 'var(--tenue)' }} />
                      </button>
                      <span className="acciones-hover opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
                        <EtiquetasQuickMenu patient={p} categorias={categorias} />
                      </span>
                    </>
                  )}
                  {segment === 'potential' && puedeAgendar && (
                    <button type="button" onClick={() => setReagendar(p)}
                      title={p.last_reason ? `A qué venía: ${p.last_reason}` : undefined}
                      className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-white bg-accion hover:bg-accion-hover transition-colors">
                      <CalendarPlus className="w-3.5 h-3.5" /> Reagendar
                    </button>
                  )}
                </span>
              </div>
            ))}
          </div>
          ) : (
          <div className="grid gap-5 mt-7" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}>
            {lista.map(p => (
              <div key={p.id} className="group relative transition-transform duration-200 hover:-translate-y-1">

                {/* Pestaña de la carpeta (lengüeta con el número de expediente) */}
                {/* ── Acciones rápidas ──────────────────────────────────────
                    El ESTADO se ve siempre (estrella/corona doradas si está
                    marcado); la ACCIÓN de marcar solo aparece al pasar el cursor.
                    Antes los tres iconos estaban siempre en las 14 tarjetas: 42
                    controles compitiendo con 14 nombres. */}
                {editar && (
                  <div className="absolute top-2.5 right-2.5 z-20 flex gap-1">
                    <button type="button" title={p.is_favorite ? 'Quitar de favoritos' : 'Marcar como favorito'}
                      onClick={e => { e.stopPropagation(); toggleFavorito(p) }}
                      className={`w-7 h-7 rounded-full flex items-center justify-center transition-all bg-superficie border border-borde hover:bg-accion-tinte
                        ${p.is_favorite ? '' : 'acciones-hover opacity-0 group-hover:opacity-100 focus:opacity-100'}`}>
                      <Star className="w-4 h-4" style={{ fill: p.is_favorite ? 'var(--accion)' : 'transparent', color: p.is_favorite ? 'var(--accion)' : 'var(--tenue)' }} />
                    </button>
                    <button type="button" title={p.is_vip ? 'Quitar VIP' : 'Marcar como VIP'}
                      onClick={e => { e.stopPropagation(); toggleVip(p) }}
                      className={`w-7 h-7 rounded-full flex items-center justify-center transition-all bg-superficie border border-borde hover:bg-accion-tinte
                        ${p.is_vip ? '' : 'acciones-hover opacity-0 group-hover:opacity-100 focus:opacity-100'}`}>
                      <Crown className="w-4 h-4" style={{ fill: p.is_vip ? 'var(--tinta)' : 'transparent', color: p.is_vip ? 'var(--tinta)' : 'var(--tenue)' }} />
                    </button>
                    <span className="acciones-hover opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
                      <EtiquetasQuickMenu patient={p} categorias={categorias} />
                    </span>
                  </div>
                )}

                {/* ── Cuerpo: reconocer y entrar ────────────────────────────
                    Alto FIJO. La banda de etiquetas existe siempre aunque esté
                    vacía: si apareciera y desapareciera, unas tarjetas medirían
                    más que otras (antes había 31 px de diferencia). */}
                <button
                  onClick={() => setVer(p)}
                  aria-label={`Abrir expediente de ${p.full_name}`}
                  className="relative z-10 glass-card rounded-2xl p-5 w-full h-[15.5rem] flex flex-col items-center text-center transition-shadow duration-200 group-hover:shadow-card-alto"
                  style={{ outline: p.is_vip ? '2px solid var(--tinta)' : 'none', outlineOffset: 2 }}
                >
                  <div className="w-20 h-20 rounded-full overflow-hidden flex items-center justify-center text-xl font-bold shrink-0"
                    style={{ background: 'var(--accion-tinte)', color: 'var(--accion)' }}>
                    {p.avatar ? <img src={p.avatar} alt="" className="w-full h-full object-cover" /> : initialsOf(p)}
                  </div>

                  <h3 className="mt-3 text-base font-semibold text-tinta leading-snug line-clamp-2">
                    {p.full_name}
                  </h3>

                  <p className="mt-1 flex items-center justify-center gap-1.5 text-[11px] font-medium text-tenue">
                    {p.record_number}
                    {/* Solo el icono; el texto llega al pasar el cursor. */}
                    {p.is_provisional && (
                      <span title="Falta completar datos personales" className="inline-flex">
                        <AlertTriangle className="w-3.5 h-3.5 shrink-0 text-aviso-icono"
                          aria-label="Falta completar datos personales" />
                      </span>
                    )}
                  </p>

                  {/* Banda de etiquetas: alto reservado, vacía si no tiene. */}
                  <div className="mt-auto w-full flex flex-wrap justify-center items-end gap-1 min-h-[1.5rem]">
                    {p.categories.map(c => (
                      <span key={c.id}
                        className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-superficie-sutil text-suave ring-1 ring-borde">
                        <Tag className="w-2.5 h-2.5" />{c.name}
                      </span>
                    ))}
                  </div>
                </button>

                {/* Clientes potenciales: acción directa para reagendarlos. */}
                {segment === 'potential' && puedeAgendar && (
                  <button
                    type="button"
                    onClick={() => setReagendar(p)}
                    title={p.last_reason ? `A qué venía: ${p.last_reason}` : undefined}
                    className="btn-primary relative z-10 mt-2 w-full"
                  >
                    <CalendarPlus className="w-4 h-4" /> Volver a agendar
                  </button>
                )}
              </div>
            ))}

            {/* Estado vacío */}
            {lista.length === 0 && (
              <div className="col-span-full glass-card rounded-2xl py-16 text-center">
                <p className="text-gray-500 text-sm">{mensajeVacio(segment, !!debounced)}</p>
              </div>
            )}
          </div>
          )
        )}
      </div>

      {/* "Volver a agendar" un cliente potencial: modal de agendar precargado con
          el paciente y el motivo de su última cita cancelada/reagendada. */}
      <CrearEventoModal
        open={!!reagendar}
        onClose={() => setReagendar(null)}
        dayKey={dayKeyHoy}
        fechaLarga={formatLargo(hoy)}
        horaInicio={horaDefault}
        initialPatient={reagendar
          ? { id: reagendar.id, full_name: reagendar.full_name, record_number: reagendar.record_number }
          : undefined}
        initialReason={reagendar?.last_reason ?? undefined}
      />

      <NuevoPacienteDrawer open={nuevoOpen} onClose={() => setNuevo(false)} />
      <ExpedienteDrawer
        paciente={pacienteMostrado}
        onClose={cerrarExpediente}
        verClinico={verClinico}
        puedeEditar={editar}
        onDarDeBaja={darDeBaja}
        dandoDeBaja={baja.isPending}
      />
    </div>
  )
}
