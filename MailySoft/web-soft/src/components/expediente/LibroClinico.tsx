/**
 * LibroClinico — visor EN PANTALLA del libro clínico del paciente (Fase 2).
 *
 * "Carpeta clínica viva" que encuaderna la Historia Clínica viva + todas las
 * evoluciones (capítulos) en un documento navegable. Se COMPONE de datos que ya
 * existen; nada se duplica. Más reciente primero (D-LIB-3).
 *
 * Estructura:
 *   - Barra superior: título + nº de expediente + nº de capítulos + 3 botones que
 *     generan el PDF (libro completo / solo HC / solo último capítulo) + toggle de imágenes.
 *   - Índice horizontal (chips): Portada · Historia clínica · un chip por capítulo
 *     (con su fecha, más reciente primero). El chip activo se resalta en dorado.
 *   - Página activa: Portada / Historia clínica / Capítulo (evolución).
 *   - Paginación lazy: al llegar al último capítulo de la página, "Cargar más
 *     antiguos" trae page+1 (hacia el pasado).
 *
 * Permiso (solo UX): el acceso al visor lo decide el rol clínico desde fuera
 * (ExpedienteDrawer). El backend es la autoridad y responde 403 a recepción/
 * finanzas; aquí solo reflejamos ese 403 con un mensaje claro.
 *
 * Fase 3 (PDF): los 3 botones generan y abren el PDF del libro (descarga
 * autenticada Bearer), con un toggle para incluir u omitir las imágenes.
 */

import { useEffect, useState } from 'react'
import {
  BookOpen, Printer, FileText, Layers, Loader2, AlertTriangle,
  Building2, User, Stethoscope, Activity, ClipboardCheck, Pill, Image as ImageIcon,
  MessageSquare, BadgeCheck, X, FileHeart,
} from 'lucide-react'
import type { PatientOut } from '../../types/paciente'
import type {
  Allergy, BookCapitulo, BookClinica, EvolutionImage, MedicalHistory, PatientBook,
  VitalSignsRecord,
} from '../../types/expediente'
import { ApiError } from '../../lib/http'
import { usePatientBook } from '../../hooks/expediente'
import type { LibroModo } from '../../api/expediente'
import { getPatientBookPdf } from '../../api/expediente'
import { useOpenPrescriptionPdfWithFormat } from '../../hooks/recetas'
import { formatFechaHora, formatFechaCorta } from '../../lib/fecha'
import { edad } from '../../lib/paciente'
import { SISTEMA_LABEL } from './ui'
import EstadoCuentaVisita from './EstadoCuentaVisita'
import VisorPdf from '../VisorPdf'
import ResumenClinicoModal from './ResumenClinicoModal'
import { useRole } from '../../auth/RoleContext'

// ── Constantes de marca / SOAP ────────────────────────────────────────────────

const ORO = '#C9A227'
const ORO_OSCURO = '#854F0B'

/** Etiquetas de color del SOAP (S azul, O teal, A morado, P verde). */
const SOAP = {
  S: { label: 'Subjetivo', color: '#185FA5' },
  O: { label: 'Objetivo', color: '#0F6E56' },
  A: { label: 'Análisis', color: '#534AB7' },
  P: { label: 'Plan', color: '#3B6D11' },
} as const

interface LibroClinicoProps {
  paciente: PatientOut
  /**
   * Si el rol puede ver el estado de cuenta (costos) del paciente — refleja
   * puedeVerEstadoCuenta(role, doctors_see_costs). Cuando es true, cada capítulo
   * muestra el bloque "Estado de cuenta de la visita". Default false (médico sin
   * flag / enfermería NO ven costos).
   */
  verEstadoCuenta?: boolean
}

/** Página activa del visor: portada, historia clínica o un capítulo (por índice). */
type Pagina = 'portada' | 'historia' | { capituloIdx: number }

export default function LibroClinico({ paciente, verEstadoCuenta = false }: LibroClinicoProps) {
  const [page, setPage] = useState(1)
  const { data, isLoading, isError, error, isFetching } = usePatientBook(paciente.id, page)
  const [pagina, setPagina] = useState<Pagina>('portada')

  // Acumulamos los capítulos de todas las páginas cargadas (lazy hacia el pasado).
  // Mientras llega una página nueva, `keepPreviousData` mantiene la anterior visible.
  const [capitulos, setCapitulos] = useState<BookCapitulo[]>([])

  // Sincroniza los capítulos acumulados con la página recibida (sin duplicar por id).
  useEffect(() => {
    if (!data) return
    setCapitulos(prev => {
      if (data.page === 1) return data.capitulos
      const vistos = new Set(prev.map(c => c.id))
      const nuevos = data.capitulos.filter(c => !vistos.has(c.id))
      return nuevos.length === 0 ? prev : [...prev, ...nuevos]
    })
  }, [data])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-16 text-amber-700 text-sm">
        <Loader2 className="w-5 h-5 animate-spin" /> Encuadernando el libro clínico…
      </div>
    )
  }

  if (isError || !data) {
    const esPermiso = error instanceof ApiError && error.status === 403
    return (
      <div
        className="flex items-start gap-3 rounded-2xl px-5 py-4"
        style={{ background: 'rgba(192,57,43,0.08)', border: '1px solid rgba(192,57,43,0.28)' }}
      >
        <AlertTriangle className="w-5 h-5 mt-0.5 shrink-0 text-red-500" />
        <div>
          <p className="text-sm font-semibold text-red-700">
            {esPermiso ? 'No tienes permiso para ver el libro clínico.' : 'No se pudo cargar el libro clínico.'}
          </p>
          <p className="text-xs text-red-600/80 mt-0.5">
            {esPermiso
              ? 'El libro contiene el expediente completo y solo está disponible para roles clínicos.'
              : 'Intenta de nuevo en un momento.'}
          </p>
        </div>
      </div>
    )
  }

  const hayMas = data.page < data.total_pages

  const cargarMas = () => {
    if (hayMas && !isFetching) setPage(p => p + 1)
  }

  return (
    <div className="space-y-4">
      <BarraSuperior libro={data} paciente={paciente} />

      <IndiceCapitulos
        capitulos={capitulos}
        total={data.capitulos_count}
        pagina={pagina}
        onPagina={setPagina}
      />

      {/* Página activa */}
      {pagina === 'portada' && <PortadaPage libro={data} paciente={paciente} />}
      {pagina === 'historia' && (
        <HistoriaClinicaPage historia={data.historia_clinica} alergias={data.alergias} />
      )}
      {typeof pagina === 'object' && capitulos[pagina.capituloIdx] && (
        <CapituloPage
          capitulo={capitulos[pagina.capituloIdx]}
          // Más reciente primero: idx 0 = el último capítulo = capitulos_count.
          // Usamos el total absoluto (no la longitud cargada) para que la
          // numeración sea estable aunque falten páginas por traer.
          numero={data.capitulos_count - pagina.capituloIdx}
          total={data.capitulos_count}
          patientId={paciente.id}
          verEstadoCuenta={verEstadoCuenta}
        />
      )}

      {/* Paginación: cargar capítulos más antiguos (hacia el pasado) */}
      {hayMas && (
        <div className="flex justify-center pt-1">
          <button
            type="button"
            onClick={cargarMas}
            disabled={isFetching}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all hover:brightness-105 disabled:opacity-60"
            style={{
              background: 'rgba(255,255,255,0.72)',
              border: `1px solid ${ORO}73`,
              color: ORO_OSCURO,
              boxShadow: '0 4px 14px rgba(201,162,39,0.18)',
            }}
          >
            {isFetching
              ? <><Loader2 className="w-4 h-4 animate-spin" /> Cargando…</>
              : <><Layers className="w-4 h-4" /> Cargar capítulos más antiguos</>}
          </button>
        </div>
      )}
    </div>
  )
}

// ── Barra superior ─────────────────────────────────────────────────────────────

/** Botón de impresión del libro (genera y abre el PDF). */
function BotonImprimir({
  label,
  icon,
  onClick,
  loading,
}: {
  label: string
  icon: React.ReactNode
  onClick: () => void
  loading?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={loading}
      title={label}
      className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold transition-all hover:brightness-105 disabled:opacity-60"
      style={{
        background: 'rgba(255,255,255,0.7)',
        border: '1px solid rgba(201,162,39,0.45)',
        color: ORO_OSCURO,
      }}
    >
      {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : icon} {label}
    </button>
  )
}

/** Etiqueta legible de cada modo del libro (para el título del visor). */
const MODO_LABEL: Record<LibroModo, string> = {
  completo: 'Libro completo',
  hc: 'Historia clínica',
  ultimo: 'Último capítulo',
}

function BarraSuperior({ libro, paciente }: { libro: PatientBook; paciente: PatientOut }) {
  const [incluirImagenes, setIncluirImagenes] = useState(true)
  /** Modo cuyo PDF se previsualiza en el visor (null = cerrado). */
  const [pdfModo, setPdfModo] = useState<LibroModo | null>(null)
  const imprimir = (modo: LibroModo) => setPdfModo(modo)
  return (
    <div
      className="rounded-2xl p-4 sm:p-5"
      style={{
        background: 'linear-gradient(135deg, rgba(201,162,39,0.12), rgba(255,255,255,0.72))',
        backdropFilter: 'blur(14px)',
        border: `1px solid ${ORO}59`,
        boxShadow: '0 6px 20px rgba(60,42,12,0.10)',
      }}
    >
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div
            className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
            style={{ background: ORO, boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
          >
            <BookOpen className="w-6 h-6 text-white" />
          </div>
          <div className="min-w-0">
            <h3 className="text-base font-bold text-gray-900 truncate">
              Libro clínico · {paciente.full_name}
            </h3>
            <p className="text-xs text-gray-500">
              Exp. {paciente.record_number} · {libro.capitulos_count}{' '}
              {libro.capitulos_count === 1 ? 'capítulo' : 'capítulos'}
            </p>
          </div>
        </div>

        <div className="flex flex-col items-start lg:items-end gap-2 shrink-0">
          <div className="flex flex-wrap items-center gap-2">
            <BotonImprimir
              label="Imprimir libro"
              icon={<Printer className="w-3.5 h-3.5" />}
              onClick={() => imprimir('completo')}
            />
            <BotonImprimir
              label="Solo historia clínica"
              icon={<FileText className="w-3.5 h-3.5" />}
              onClick={() => imprimir('hc')}
            />
            <BotonImprimir
              label="Solo último capítulo"
              icon={<Layers className="w-3.5 h-3.5" />}
              onClick={() => imprimir('ultimo')}
            />
          </div>
          <label className="flex items-center gap-1.5 text-[11px] text-gray-600 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={incluirImagenes}
              onChange={e => setIncluirImagenes(e.target.checked)}
              className="w-3.5 h-3.5 accent-amber-600"
            />
            Incluir imágenes en el PDF
          </label>
        </div>
      </div>

      {pdfModo && (
        <VisorPdf
          titulo={`${MODO_LABEL[pdfModo]} · ${paciente.full_name}`}
          nombreArchivo={`libro-clinico-${pdfModo}.pdf`}
          cargar={() => getPatientBookPdf(paciente.id, pdfModo, incluirImagenes)}
          onClose={() => setPdfModo(null)}
        />
      )}
    </div>
  )
}

// ── Índice de capítulos (chips horizontales) ──────────────────────────────────

/** Chip del índice (activo en dorado). */
function ChipIndice({
  label, sub, activo, onClick,
}: {
  label: string
  sub?: string
  activo: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex flex-col items-start shrink-0 rounded-xl px-3 py-2 text-left transition-all hover:brightness-105"
      style={{
        background: activo ? ORO : 'rgba(255,255,255,0.72)',
        border: activo ? `1px solid ${ORO}` : '1px solid rgba(201,162,39,0.3)',
        boxShadow: activo ? '0 4px 14px rgba(201,162,39,0.4)' : '0 2px 8px rgba(60,42,12,0.06)',
      }}
    >
      <span
        className="text-xs font-semibold leading-tight"
        style={{ color: activo ? '#fff' : ORO_OSCURO }}
      >
        {label}
      </span>
      {sub && (
        <span
          className="text-[10px] leading-tight"
          style={{ color: activo ? 'rgba(255,255,255,0.85)' : '#9aa0a6' }}
        >
          {sub}
        </span>
      )}
    </button>
  )
}

function IndiceCapitulos({
  capitulos, total, pagina, onPagina,
}: {
  capitulos: BookCapitulo[]
  /** Total absoluto de capítulos (para numerar de forma estable). */
  total: number
  pagina: Pagina
  onPagina: (p: Pagina) => void
}) {
  return (
    <div className="flex items-stretch gap-2 overflow-x-auto pb-1.5 -mx-0.5 px-0.5">
      <ChipIndice
        label="Portada"
        activo={pagina === 'portada'}
        onClick={() => onPagina('portada')}
      />
      <ChipIndice
        label="Historia clínica"
        activo={pagina === 'historia'}
        onClick={() => onPagina('historia')}
      />
      {capitulos.map((c, idx) => (
        <ChipIndice
          key={c.id}
          label={`Capítulo ${total - idx}`}
          sub={formatFechaCorta(c.fecha)}
          activo={typeof pagina === 'object' && pagina.capituloIdx === idx}
          onClick={() => onPagina({ capituloIdx: idx })}
        />
      ))}
    </div>
  )
}

// ── Hoja de papel reutilizable ────────────────────────────────────────────────

/** Una "hoja" del libro: tarjeta blanca con sutil acento de papel. */
function Hoja({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="rounded-2xl p-5 sm:p-6"
      style={{
        background: 'rgba(255,255,255,0.85)',
        backdropFilter: 'blur(14px)',
        border: '1px solid rgba(255,255,255,0.8)',
        boxShadow: '0 8px 28px rgba(60,42,12,0.12)',
      }}
    >
      {children}
    </div>
  )
}

/** Título de bloque dentro de una hoja. */
function BloqueTitulo({ icon: Icon, children }: { icon: typeof User; children: React.ReactNode }) {
  return (
    <p className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-amber-700/80 mb-2">
      <Icon className="w-4 h-4" style={{ color: ORO }} /> {children}
    </p>
  )
}

/** Fila etiqueta–valor; no renderiza si el valor está vacío. */
function Dato({ label, value }: { label: string; value: string | number | null | undefined }) {
  if (value == null || value === '') return null
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wide text-gray-400">{label}</span>
      <span className="text-sm text-gray-800">{value}</span>
    </div>
  )
}

// ── Portada ────────────────────────────────────────────────────────────────────

function PortadaPage({ libro, paciente }: { libro: PatientBook; paciente: PatientOut }) {
  const clinica: BookClinica | null = libro.clinica
  const years = paciente.date_of_birth ? edad(paciente.date_of_birth) : null

  return (
    <Hoja>
      {/* Encabezado de marca / clínica */}
      <div className="flex items-center gap-4 pb-5 mb-5 border-b border-amber-900/10">
        {clinica?.logo ? (
          <img
            src={clinica.logo}
            alt={clinica.name}
            className="w-16 h-16 rounded-xl object-contain bg-white"
            style={{ border: '1px solid rgba(201,162,39,0.25)' }}
          />
        ) : (
          <div
            className="w-16 h-16 rounded-xl flex items-center justify-center shrink-0"
            style={{ background: 'rgba(201,162,39,0.12)', border: '1px solid rgba(201,162,39,0.25)' }}
          >
            <Building2 className="w-7 h-7" style={{ color: ORO }} />
          </div>
        )}
        <div className="min-w-0">
          <h2 className="text-xl font-bold text-gray-900 leading-tight truncate">
            {clinica?.name || 'Clínica'}
          </h2>
          {clinica?.address && <p className="text-sm text-gray-500">{clinica.address}</p>}
          {clinica?.phone && <p className="text-sm text-gray-500">Tel. {clinica.phone}</p>}
        </div>
      </div>

      <p className="text-[11px] font-semibold uppercase tracking-widest text-amber-700/70 mb-1">
        Libro clínico del paciente
      </p>
      <h1 className="text-2xl font-bold text-gray-900 mb-1">{paciente.full_name}</h1>
      <p className="text-sm text-gray-500 mb-5">Expediente {paciente.record_number}</p>

      <BloqueTitulo icon={User}>Datos del paciente</BloqueTitulo>
      <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))' }}>
        <Dato label="Sexo" value={paciente.sex_display} />
        <Dato label="Fecha de nacimiento" value={paciente.date_of_birth} />
        <Dato label="Edad" value={years !== null ? `${years} años` : null} />
        <Dato label="CURP" value={paciente.curp} />
        <Dato label="Teléfono" value={paciente.phone} />
        <Dato label="Correo" value={paciente.email} />
        <Dato label="Tipo de sangre" value={paciente.blood_type_display} />
        <Dato label="Estado civil" value={paciente.marital_status_display} />
        <Dato label="Ocupación" value={paciente.occupation} />
        <Dato
          label="Domicilio"
          value={[paciente.address_street, paciente.address_neighborhood, paciente.city, paciente.state]
            .filter(Boolean)
            .join(', ')}
        />
      </div>

      <div className="mt-6 pt-4 border-t border-amber-900/10 flex flex-wrap gap-4 text-xs text-gray-400">
        <span>{libro.capitulos_count} {libro.capitulos_count === 1 ? 'capítulo' : 'capítulos'}</span>
        <span>Generado en pantalla · {formatFechaCorta(new Date().toISOString())}</span>
      </div>
    </Hoja>
  )
}

// ── Historia clínica ────────────────────────────────────────────────────────────

/**
 * Render de un bloque JSON de la HC (clave→valor), saltando vacíos.
 * Acepta cualquier objeto-bloque de la HC (HeredoFamiliares, NoPatologicos, …);
 * los recorremos como pares dinámicos porque solo mostramos los campos con valor.
 */
function BloqueHistoria({
  titulo, datos,
}: {
  titulo: string
  datos: object | null | undefined
}) {
  const entradas = Object.entries(datos ?? {}).filter(
    ([, v]) => v != null && v !== '' && !(typeof v === 'object'),
  )
  if (entradas.length === 0) return null
  return (
    <div className="mb-4">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-700/70 mb-1.5">{titulo}</p>
      <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))' }}>
        {entradas.map(([k, v]) => (
          <Dato key={k} label={humanizar(k)} value={String(v)} />
        ))}
      </div>
    </div>
  )
}

/** 'numero_hermanos' → 'Numero hermanos'. */
function humanizar(key: string): string {
  const s = key.replace(/_/g, ' ')
  return s.charAt(0).toUpperCase() + s.slice(1)
}

function HistoriaClinicaPage({
  historia, alergias,
}: {
  historia: MedicalHistory | null
  alergias: Allergy[]
}) {
  if (!historia || !historia.id) {
    return (
      <Hoja>
        <BloqueTitulo icon={FileText}>Historia clínica</BloqueTitulo>
        <p className="text-sm text-gray-400 italic py-6 text-center">
          Este paciente aún no tiene historia clínica registrada.
        </p>
      </Hoja>
    )
  }

  const tieneExplorBasal = Object.values(historia.exploracion_fisica_basal ?? {}).some(
    c => c?.estado || c?.detalle,
  )

  return (
    <Hoja>
      <BloqueTitulo icon={FileText}>Historia clínica</BloqueTitulo>
      <p className="text-[11px] text-gray-400 mb-4">
        Versión viva · actualizada {historia.updated_at ? formatFechaCorta(historia.updated_at) : '—'}
      </p>

      {/* Alergias (banderas de seguridad) */}
      {alergias.length > 0 && (
        <div className="mb-5">
          <p className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-red-700 mb-1.5">
            <AlertTriangle className="w-3.5 h-3.5" /> Alergias ({alergias.length})
          </p>
          <div className="flex flex-wrap gap-2">
            {alergias.map(a => (
              <span
                key={a.id}
                className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-semibold"
                style={{ background: 'rgba(192,57,43,0.10)', border: '1px solid rgba(192,57,43,0.35)', color: '#C0392B' }}
              >
                {a.substance}
                {a.severity_display && <span className="text-[11px] font-medium">· {a.severity_display}</span>}
                {a.reaction && <span className="text-[11px] font-normal text-gray-500">· {a.reaction}</span>}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Campos de texto libres */}
      {historia.padecimiento_actual && (
        <TextoLibre titulo="Padecimiento actual" texto={historia.padecimiento_actual} />
      )}
      {historia.antecedentes_importancia && (
        <TextoLibre titulo="Antecedentes de importancia" texto={historia.antecedentes_importancia} />
      )}
      {historia.tratamientos_actuales && (
        <TextoLibre titulo="Tratamientos actuales" texto={historia.tratamientos_actuales} />
      )}
      {historia.prioridad_analisis && (
        <TextoLibre titulo="Prioridad de análisis" texto={historia.prioridad_analisis} />
      )}

      {/* Bloques estructurados */}
      <BloqueHistoria titulo="Antecedentes heredo-familiares" datos={historia.heredo_familiares} />
      <BloqueHistoria titulo="Antecedentes personales patológicos" datos={historia.personales_patologicos} />
      <BloqueHistoria titulo="Antecedentes no patológicos" datos={historia.no_patologicos} />
      <BloqueHistoria titulo="Hábitos alimenticios" datos={historia.habitos_alimenticios} />
      <BloqueHistoria titulo="Antecedentes gineco-obstétricos" datos={historia.gineco_obstetricos} />

      {/* Exploración física basal */}
      {tieneExplorBasal && (
        <div className="mb-2">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-700/70 mb-1.5">
            Exploración física basal
          </p>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(historia.exploracion_fisica_basal ?? {})
              .filter(([, c]) => c?.estado || c?.detalle)
              .map(([sistema, celda]) => (
                <span
                  key={sistema}
                  className="inline-flex items-center gap-1 text-[11px] rounded-full px-2.5 py-1"
                  style={{ background: 'rgba(201,162,39,0.10)', color: ORO_OSCURO }}
                >
                  {SISTEMA_LABEL[sistema] ?? sistema}
                  {celda?.estado ? `: ${celda.estado === 'con_alteraciones' ? 'Con alteraciones' : 'Sin alteraciones'}` : ''}
                  {celda?.detalle ? ` (${celda.detalle})` : ''}
                </span>
              ))}
          </div>
        </div>
      )}
    </Hoja>
  )
}

/** Bloque de texto libre (con saltos de línea preservados). */
function TextoLibre({ titulo, texto }: { titulo: string; texto: string }) {
  return (
    <div className="mb-4">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-700/70 mb-1">{titulo}</p>
      <p className="text-sm text-gray-700 whitespace-pre-wrap">{texto}</p>
    </div>
  )
}

// ── Capítulo (evolución) ─────────────────────────────────────────────────────

/** Tarjeta de una métrica de signos (PA, Temp, FC, SpO₂, Peso). */
function MetricaCard({
  label, value, unidad,
}: { label: string; value: string | number | null | undefined; unidad?: string }) {
  const hay = value != null && value !== ''
  if (!hay) return null
  return (
    <div
      className="rounded-xl px-3 py-2 text-center"
      style={{ background: 'rgba(14,124,123,0.07)', border: '1px solid rgba(14,124,123,0.2)' }}
    >
      <p className="text-[10px] uppercase tracking-wide" style={{ color: '#0E7C7B' }}>{label}</p>
      <p className="text-base font-bold text-gray-800 leading-tight">
        {value}{unidad && <span className="text-[10px] font-normal text-gray-400"> {unidad}</span>}
      </p>
    </div>
  )
}

/** Bloque de signos de enfermería como tarjetas de métricas. */
function SignosEnfermeria({ signos }: { signos: VitalSignsRecord }) {
  const pa = signos.systolic != null && signos.diastolic != null
    ? `${signos.systolic}/${signos.diastolic}`
    : null
  return (
    <div className="mb-4">
      <p className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide mb-2" style={{ color: '#0E7C7B' }}>
        <Activity className="w-3.5 h-3.5" /> Enfermería · signos · {formatFechaHora(signos.measured_at)}
      </p>
      <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(88px, 1fr))' }}>
        <MetricaCard label="PA" value={pa} unidad="mmHg" />
        <MetricaCard label="Temp" value={signos.temperature_c} unidad="°C" />
        <MetricaCard label="FC" value={signos.heart_rate} unidad="lpm" />
        <MetricaCard label="SpO₂" value={signos.oxygen_saturation} unidad="%" />
        <MetricaCard label="Peso" value={signos.weight_kg} unidad="kg" />
        <MetricaCard label="IMC" value={signos.imc} />
        <MetricaCard label="FR" value={signos.resp_rate} unidad="rpm" />
        <MetricaCard label="Glucosa" value={signos.glucose} unidad="mg/dL" />
      </div>
    </div>
  )
}

/** Bloque SOAP con su etiqueta de color. No renderiza si no hay contenido. */
function SoapBloque({
  letra, texto, extra,
}: {
  letra: keyof typeof SOAP
  texto?: string
  extra?: React.ReactNode
}) {
  const { label, color } = SOAP[letra]
  const hayTexto = !!texto && texto.trim() !== ''
  if (!hayTexto && !extra) return null
  return (
    <div className="flex gap-3">
      <span
        className="shrink-0 w-7 h-7 rounded-lg flex items-center justify-center text-sm font-bold text-white"
        style={{ background: color }}
        title={label}
      >
        {letra}
      </span>
      <div className="flex-1 min-w-0 pt-0.5">
        <p className="text-[11px] font-semibold uppercase tracking-wide mb-1" style={{ color }}>{label}</p>
        {hayTexto && <p className="text-sm text-gray-700 whitespace-pre-wrap">{texto}</p>}
        {extra}
      </div>
    </div>
  )
}

function CapituloPage({
  capitulo, numero, total, patientId, verEstadoCuenta,
}: {
  capitulo: BookCapitulo
  numero: number
  total: number
  patientId: string
  /** Si el rol puede ver costos: muestra el bloque "Estado de cuenta de la visita". */
  verEstadoCuenta: boolean
}) {
  const [ampliada, setAmpliada] = useState<EvolutionImage | null>(null)
  const { role } = useRole()
  const puedeResumen = role === 'owner' || role === 'admin' || role === 'doctor'
  const [resumenAbierto, setResumenAbierto] = useState(false)

  const planTexto = [
    capitulo.plan.tratamiento && `Tratamiento: ${capitulo.plan.tratamiento}`,
    capitulo.plan.recomendaciones && `Recomendaciones: ${capitulo.plan.recomendaciones}`,
    capitulo.plan.indicaciones_enfermeria && `Indicaciones para enfermería: ${capitulo.plan.indicaciones_enfermeria}`,
  ].filter(Boolean).join('\n')

  const hayAnalisis = !!capitulo.analisis.texto.trim() || capitulo.analisis.diagnosticos.length > 0

  return (
    <Hoja>
      {/* Encabezado del capítulo */}
      <div className="flex items-start justify-between gap-3 pb-4 mb-4 border-b border-amber-900/10">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-widest text-amber-700/70">
            Capítulo {numero} de {total}
          </p>
          <h2 className="inline-flex items-center gap-2 text-lg font-bold text-gray-900">
            <Stethoscope className="w-5 h-5" style={{ color: ORO }} />
            {formatFechaHora(capitulo.fecha)}
          </h2>
          <p className="text-sm text-gray-500">{capitulo.doctor.full_name}</p>
        </div>
        {puedeResumen && (
          <button
            type="button"
            onClick={() => setResumenAbierto(true)}
            className="inline-flex items-center gap-1.5 shrink-0 px-3 py-2 rounded-xl text-xs font-semibold text-white transition-all hover:brightness-110"
            style={{ background: ORO, boxShadow: '0 3px 10px rgba(201,162,39,0.35)' }}
            title="Genera el resumen que se entrega al paciente"
          >
            <FileHeart className="w-4 h-4" /> Resumen clínico
          </button>
        )}
      </div>

      {resumenAbierto && (
        <ResumenClinicoModal
          evolutionId={capitulo.id}
          patientId={patientId}
          onClose={() => setResumenAbierto(false)}
        />
      )}

      {/* Signos de enfermería */}
      {capitulo.signos && <SignosEnfermeria signos={capitulo.signos} />}

      {/* SOAP */}
      <div className="space-y-4">
        <SoapBloque letra="S" texto={capitulo.subjetivo} />
        <SoapBloque letra="O" texto={capitulo.objetivo} />
        <SoapBloque
          letra="A"
          texto={hayAnalisis ? capitulo.analisis.texto : undefined}
          extra={capitulo.analisis.diagnosticos.length > 0 ? (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {capitulo.analisis.diagnosticos.map(d => (
                <span
                  key={d.id}
                  className="inline-flex items-center gap-1 text-[11px] rounded-full px-2.5 py-1"
                  style={{ background: `${SOAP.A.color}1A`, color: SOAP.A.color }}
                >
                  <ClipboardCheck className="w-3 h-3" />
                  {d.cie_code ? `${d.cie_code} · ` : ''}{d.description}
                  <span className="opacity-70">({d.kind_display})</span>
                </span>
              ))}
            </div>
          ) : undefined}
        />
        <SoapBloque letra="P" texto={planTexto} />
      </div>

      {/* Exploración por aparatos */}
      {capitulo.exploracion.length > 0 && (
        <div className="mt-5 pt-4 border-t border-amber-900/10">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-700/70 mb-2">
            Exploración por aparatos
          </p>
          <div className="flex flex-wrap gap-1.5">
            {capitulo.exploracion.map((e, i) => (
              <span
                key={`${e.sistema}-${i}`}
                className="inline-flex items-center gap-1 text-[11px] rounded-full px-2.5 py-1"
                style={{ background: 'rgba(201,162,39,0.10)', color: ORO_OSCURO }}
              >
                {SISTEMA_LABEL[e.sistema] ?? e.sistema} · {e.estado}
                {e.detalle ? ` (${e.detalle})` : ''}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Imágenes */}
      {capitulo.imagenes.length > 0 && (
        <div className="mt-5 pt-4 border-t border-amber-900/10">
          <p className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-amber-700/70 mb-2">
            <ImageIcon className="w-3.5 h-3.5" /> Imágenes · {capitulo.imagenes.length}
          </p>
          <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(84px, 1fr))' }}>
            {capitulo.imagenes.map(img => (
              <button
                key={img.id}
                type="button"
                onClick={() => setAmpliada(img)}
                className="block w-full overflow-hidden rounded-xl transition-all hover:brightness-95"
                style={{ aspectRatio: '1 / 1', border: '1px solid rgba(201,162,39,0.25)' }}
                title={img.caption || 'Ver imagen'}
              >
                <img
                  src={img.image_url}
                  alt={img.caption || 'Imagen del capítulo'}
                  loading="lazy"
                  className="w-full h-full object-cover"
                />
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Recetas */}
      {capitulo.recetas.length > 0 && (
        <div className="mt-5 pt-4 border-t border-amber-900/10">
          <p className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-amber-700/70 mb-2">
            <Pill className="w-3.5 h-3.5" /> Recetas · {capitulo.recetas.length}
          </p>
          <div className="space-y-2">
            {capitulo.recetas.map(r => <RecetaResumenCard key={r.id} receta={r} />)}
          </div>
        </div>
      )}

      {/* Addenda */}
      {capitulo.addenda.length > 0 && (
        <div className="mt-5 pt-4 border-t border-amber-900/10 space-y-2">
          {capitulo.addenda.map(a => (
            <div key={a.id} className="rounded-lg px-3 py-2" style={{ background: 'rgba(201,162,39,0.08)' }}>
              <p className="inline-flex items-center gap-1.5 text-[11px] text-gray-400">
                <MessageSquare className="w-3 h-3" /> Addendum · {formatFechaHora(a.created_at)}
              </p>
              <p className="text-sm text-gray-700 whitespace-pre-wrap">{a.body}</p>
            </div>
          ))}
        </div>
      )}

      {/* Estado de cuenta de la visita (solo si el rol ve costos) */}
      {verEstadoCuenta && (
        <EstadoCuentaVisita patientId={patientId} fechaCapitulo={capitulo.fecha} />
      )}

      {/* Firma / pie */}
      <div className="mt-6 pt-4 border-t border-amber-900/10">
        <p className="text-sm font-semibold text-gray-800">{capitulo.doctor.full_name}</p>
        {capitulo.doctor.cedulas_validadas.length > 0 && (
          <p className="inline-flex items-center gap-1.5 text-xs text-gray-500 mt-0.5">
            <BadgeCheck className="w-3.5 h-3.5" style={{ color: '#0E7C7B' }} />
            Céd. {capitulo.doctor.cedulas_validadas.join(' · ')}
          </p>
        )}
      </div>

      {ampliada && <Lightbox imagen={ampliada} onClose={() => setAmpliada(null)} />}
    </Hoja>
  )
}

/** Resumen de una receta del capítulo, con botón para abrir su PDF. */
function RecetaResumenCard({ receta }: { receta: BookCapitulo['recetas'][number] }) {
  const abrirPdf = useOpenPrescriptionPdfWithFormat()
  const anulada = receta.status === 'cancelled'

  return (
    <div
      className="rounded-xl px-3 py-2.5"
      style={{ background: 'rgba(255,255,255,0.7)', border: '1px solid rgba(201,162,39,0.2)' }}
    >
      <div className="flex items-center justify-between gap-2 mb-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-gray-800">Folio {receta.folio}</span>
          {anulada && (
            <span className="text-[10px] font-semibold uppercase rounded-full px-2 py-0.5"
              style={{ background: 'rgba(192,57,43,0.12)', color: '#C0392B' }}>
              Anulada
            </span>
          )}
          <span className="text-[11px] text-gray-400">{formatFechaCorta(receta.issued_at)}</span>
        </div>
        <button
          type="button"
          onClick={() => abrirPdf.mutate({ prescriptionId: receta.id })}
          disabled={abrirPdf.isPending}
          className="inline-flex items-center gap-1.5 text-xs font-semibold text-amber-700 hover:text-amber-800 disabled:opacity-60"
        >
          {abrirPdf.isPending
            ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Abriendo…</>
            : <><Printer className="w-3.5 h-3.5" /> Ver PDF</>}
        </button>
      </div>
      {receta.items_resumen.length > 0 && (
        <ul className="text-sm text-gray-600 list-disc list-inside space-y-0.5">
          {receta.items_resumen.map((it, i) => <li key={i}>{it}</li>)}
        </ul>
      )}
    </div>
  )
}

/** Modal simple que muestra la imagen en grande (mismo patrón que EvolucionTab). */
function Lightbox({ imagen, onClose }: { imagen: EvolutionImage; onClose: () => void }) {
  return (
    <div
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(20,14,4,0.78)', backdropFilter: 'blur(4px)' }}
      role="dialog"
      aria-modal="true"
    >
      <div className="relative max-w-3xl max-h-full" onClick={e => e.stopPropagation()}>
        <button
          type="button"
          onClick={onClose}
          aria-label="Cerrar"
          className="absolute -top-3 -right-3 rounded-full p-1.5 text-gray-700 bg-white shadow-lg hover:text-gray-900"
        >
          <X className="w-4 h-4" />
        </button>
        <img
          src={imagen.image_url}
          alt={imagen.caption || 'Imagen del capítulo'}
          className="max-w-full max-h-[80vh] rounded-xl object-contain"
          style={{ boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}
        />
        {imagen.caption && <p className="mt-2 text-center text-sm text-white/90">{imagen.caption}</p>}
      </div>
    </div>
  )
}
