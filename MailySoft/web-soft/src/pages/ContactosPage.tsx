import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Search, Plus, Phone, CalendarDays, Loader2, AlertCircle, AlertTriangle, Star, Crown, CalendarRange, Tag } from 'lucide-react'
import Topbar from '../components/Topbar'
import NuevoPacienteDrawer from '../components/contactos/NuevoPacienteDrawer'
import ExpedienteDrawer from '../components/contactos/ExpedienteDrawer'
import MiniCalendario from '../components/agenda/MiniCalendario'
import {
  usePatient, usePatients, useDeactivatePatient, useSetPatientClassification,
} from '../hooks/pacientes'
import { useCategories } from '../hooks/clinica'
import { initialsOf } from '../lib/paciente'
import { formatFechaCorta } from '../lib/fecha'
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

export default function ContactosPage() {
  const [query, setQuery]         = useState('')
  const [debounced, setDebounced] = useState('')
  const [segment, setSegment]     = useState<PatientSegment>('all')
  const [categoryId, setCategoryId] = useState<string | null>(null)
  const [dateFrom, setDateFrom]   = useState('')
  const [dateTo, setDateTo]       = useState('')
  const [nuevoOpen, setNuevo]     = useState(false)
  const [verPaciente, setVer]     = useState<PatientOut | null>(null)
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
  const verClinico = puedeVerExpedienteClinico(role)
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

      {/* Fondo */}
      <div className="fixed inset-0 -z-10" style={{ background: 'linear-gradient(135deg, #b89a52 0%, #d8c690 45%, #f1e8cf 100%)' }} />
      <div className="fixed inset-0 -z-10 bg-cover bg-center" style={{ backgroundImage: "url('/fondo-agenda.jpg')" }} />
      <div className="fixed inset-0 -z-10" style={{ background: 'rgba(255,255,255,0.20)' }} />

      <Topbar active="contactos" />

      <div className="p-5 max-w-[1300px] mx-auto">

        {/* ════ Cabecera: título + buscador + filtros ════ */}
        <div className="glass-card rounded-2xl px-6 py-5">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">Pacientes</h1>
              <p className="text-sm text-gray-500">
                {isLoading ? 'Cargando…' : `${total} paciente${total === 1 ? '' : 's'}`}
              </p>
            </div>
            {editar && (
              <button
                onClick={() => setNuevo(true)}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110"
                style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
              >
                <Plus className="w-4 h-4" /> Nuevo paciente
              </button>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-3 mt-4">
            <div className="relative flex-1 min-w-[240px]">
              <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
              <input
                value={query} onChange={e => setQuery(e.target.value)}
                placeholder="Buscar por nombre, apellido, teléfono o expediente"
                className="input pl-10"
                style={{ background: 'rgba(255,255,255,0.7)' }}
              />
            </div>
          </div>

          {/* Chips de segmento (dorado) + etiquetas del catálogo (verde) */}
          <div className="flex flex-wrap gap-2 mt-4">
            {SEGMENTOS.map(s => {
              const activo = categoryId === null && segment === s.key
              return (
                <button key={s.key} type="button" onClick={() => elegirSegmento(s.key)}
                  className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-full text-sm font-semibold transition-all"
                  style={activo
                    ? { background: '#C9A227', color: '#fff', boxShadow: '0 2px 8px rgba(201,162,39,0.35)' }
                    : { background: 'rgba(255,255,255,0.6)', color: '#7A756C' }}>
                  {s.key === 'date' && <CalendarRange className="w-3.5 h-3.5" />}
                  {s.key === 'favorites' && <Star className="w-3.5 h-3.5" />}
                  {s.key === 'vip' && <Crown className="w-3.5 h-3.5" />}
                  {s.label}
                </button>
              )
            })}

            {/* Separador entre segmentos fijos y las etiquetas configurables */}
            {categorias.length > 0 && (
              <span className="self-center mx-1 h-5 w-px bg-black/10" aria-hidden />
            )}

            {/* Etiquetas del catálogo (las que crea el doctor en Mi Consultorio) */}
            {categorias.map(c => {
              const activo = categoryId === c.id
              return (
                <button key={c.id} type="button" onClick={() => elegirCategoria(c.id)}
                  className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-full text-sm font-semibold transition-all"
                  style={activo
                    ? { background: '#1D6F5C', color: '#fff', boxShadow: '0 2px 8px rgba(29,111,92,0.35)' }
                    : { background: 'rgba(255,255,255,0.6)', color: '#7A756C' }}>
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
            <p className="text-sm text-gray-600 mb-3">
              Elige un <strong>rango de fechas</strong>: verás los pacientes atendidos entre esos días.
            </p>
            <div className="flex flex-wrap gap-5">
              <div>
                <label className="label mb-1.5 block">Desde</label>
                <MiniCalendario value={dateFrom || null} onPick={setDateFrom} accent="gold"
                  footer={<div className="text-center text-[11px] font-medium" style={{ color: '#9A7B1E' }}>
                    {dateFrom ? formatFechaCorta(dateFrom) : 'Sin elegir'}
                  </div>} />
              </div>
              <div>
                <label className="label mb-1.5 block">Hasta</label>
                <MiniCalendario value={dateTo || null} onPick={setDateTo} min={dateFrom || undefined} accent="gold"
                  footer={<div className="text-center text-[11px] font-medium" style={{ color: '#9A7B1E' }}>
                    {dateTo ? formatFechaCorta(dateTo) : 'Sin elegir'}
                  </div>} />
              </div>
            </div>
            {esperandoFechas && (
              <p className="text-xs mt-3" style={{ color: '#9A7B1E' }}>
                Elige <strong>ambas</strong> fechas para ver los resultados.
              </p>
            )}
          </div>
        )}

        {/* ════ Estado de error ════ */}
        {isError && (
          <div className="glass-card rounded-2xl mt-7 py-10 px-6 flex items-center justify-center gap-3 text-center">
            <AlertCircle className="w-5 h-5 text-red-500 shrink-0" />
            <p className="text-sm text-red-600">
              No se pudieron cargar los pacientes. {error instanceof Error ? error.message : ''}
            </p>
          </div>
        )}

        {/* ════ Estado de carga ════ */}
        {isLoading && !isError && !esperandoFechas && (
          <div className="flex items-center justify-center gap-2 mt-16 text-amber-700">
            <Loader2 className="w-5 h-5 animate-spin" /> Cargando pacientes…
          </div>
        )}

        {/* ════ Cuadrícula de carpetas (folders) ════ */}
        {!isLoading && !isError && !esperandoFechas && (
          <div className="grid gap-5 mt-7" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}>
            {lista.map(p => (
              <div key={p.id} className="group relative pt-6 transition-transform duration-200 hover:-translate-y-1.5">

                {/* Pestaña de la carpeta (lengüeta con el número de expediente) */}
                <div
                  className="absolute top-0 left-6 z-0 px-4 pt-1.5 pb-3 rounded-t-xl text-[11px] font-bold tracking-wide"
                  style={{
                    background: 'rgba(255,255,255,0.58)',
                    backdropFilter: 'blur(18px)',
                    borderTop: '1px solid rgba(255,255,255,0.7)',
                    borderLeft: '1px solid rgba(255,255,255,0.7)',
                    borderRight: '1px solid rgba(255,255,255,0.7)',
                    color: '#B8860B',
                  }}
                >
                  {p.record_number}
                </div>

                {/* Acciones rápidas: favorito / VIP (overlay, fuera del botón del cuerpo) */}
                {editar && (
                  <div className="absolute top-7 right-3 z-20 flex gap-1">
                    <button type="button" title={p.is_favorite ? 'Quitar de favoritos' : 'Marcar como favorito'}
                      onClick={e => { e.stopPropagation(); toggleFavorito(p) }}
                      className="w-7 h-7 rounded-full flex items-center justify-center transition-colors hover:bg-amber-50"
                      style={{ background: 'rgba(255,255,255,0.7)' }}>
                      <Star className="w-4 h-4" style={{ fill: p.is_favorite ? '#C9A227' : 'transparent', color: p.is_favorite ? '#C9A227' : '#9aa0a6' }} />
                    </button>
                    <button type="button" title={p.is_vip ? 'Quitar VIP' : 'Marcar como VIP'}
                      onClick={e => { e.stopPropagation(); toggleVip(p) }}
                      className="w-7 h-7 rounded-full flex items-center justify-center transition-colors hover:bg-amber-50"
                      style={{ background: 'rgba(255,255,255,0.7)' }}>
                      <Crown className="w-4 h-4" style={{ fill: p.is_vip ? '#C9A227' : 'transparent', color: p.is_vip ? '#B8860B' : '#9aa0a6' }} />
                    </button>
                  </div>
                )}

                {/* Cuerpo de la carpeta */}
                <button
                  onClick={() => setVer(p)}
                  className="relative z-10 glass-card rounded-2xl p-5 w-full text-left transition-shadow duration-200 group-hover:shadow-xl"
                  style={{ outline: p.is_vip ? '2px solid #C9A227' : 'none', outlineOffset: 2 }}
                >
                  <div className="mb-3">
                    <div className="w-12 h-12 rounded-full overflow-hidden flex items-center justify-center text-sm font-bold shrink-0"
                      style={{ background: 'rgba(201,162,39,0.16)', color: '#B8860B' }}>
                      {p.avatar ? <img src={p.avatar} alt="" className="w-full h-full object-cover" /> : initialsOf(p)}
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <h3 className="text-base font-semibold text-gray-900 leading-tight truncate">{p.full_name}</h3>
                    {p.is_vip && (
                      <span className="badge shrink-0" style={{ background: '#FBF1D9', color: '#9A7B1E' }}>VIP</span>
                    )}
                  </div>
                  {p.is_provisional ? (
                    <div className="flex items-center gap-1 text-[11px] mb-3" style={{ color: '#9A7B1E' }}>
                      <AlertTriangle className="w-3 h-3 shrink-0" /> Falta completar datos personales
                    </div>
                  ) : (
                    <p className="text-xs text-gray-400 mb-3">{p.sex_display || '—'}</p>
                  )}

                  {p.categories.length > 0 && (
                    <div className="flex flex-wrap gap-1 mb-3">
                      {p.categories.map(c => (
                        <span key={c.id}
                          className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full"
                          style={{ background: 'rgba(29,111,92,0.12)', color: '#1D6F5C' }}>
                          <Tag className="w-2.5 h-2.5" />{c.name}
                        </span>
                      ))}
                    </div>
                  )}

                  <div className="space-y-1.5 pt-3 border-t border-white/50">
                    <div className="flex items-center gap-2 text-xs text-gray-600">
                      <Phone className="w-3.5 h-3.5 text-gray-400 shrink-0" /> {p.phone || '—'}
                    </div>
                    <div className="flex items-center gap-2 text-xs text-gray-600">
                      <CalendarDays className="w-3.5 h-3.5 text-gray-400 shrink-0" />
                      {p.last_seen_at ? `Última: ${formatFechaCorta(p.last_seen_at)}` : 'Sin citas atendidas'}
                    </div>
                  </div>
                </button>
              </div>
            ))}

            {/* Estado vacío */}
            {lista.length === 0 && (
              <div className="col-span-full glass-card rounded-2xl py-16 text-center">
                <p className="text-gray-500 text-sm">{mensajeVacio(segment, !!debounced)}</p>
              </div>
            )}
          </div>
        )}
      </div>

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
