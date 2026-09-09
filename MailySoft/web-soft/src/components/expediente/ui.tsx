/**
 * Primitivas visuales y constantes compartidas por las pestañas del expediente.
 *
 * Usa los tokens del sistema (ver `tailwind.config.js`). Regla que aplica aquí:
 * el icono de una sección identifica una CATEGORÍA ("Datos generales", "Signos"),
 * así que va en un tono neutro. El color queda reservado para ESTADOS.
 */

import type { ReactNode } from 'react'
import { AlertCircle, Loader2 } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type {
  AllergySeverity,
  DiagnosisKind,
  ExploracionBasalEstado,
  ExploracionEvolucionEstado,
  ViviendaChoice,
} from '../../types/expediente'
import type { MedicationFormValue } from '../../types/recetas'
import type { BloodType, Education, MaritalStatus } from '../../types/paciente'
import type { AppointmentStatus } from '../../types/agenda'

export const SECCION_LABEL = 'text-xs font-semibold uppercase tracking-wide text-suave mb-3'

/** Card de sección glass reutilizable. */
export function Card({
  title,
  icon: Icon,
  children,
  className = '',
  action,
}: {
  title: string
  icon: LucideIcon
  children: ReactNode
  className?: string
  action?: ReactNode
}) {
  return (
    <div className={`rounded-2xl p-5 bg-superficie border border-borde shadow-card ${className}`}>
      <div className="flex items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <Icon className="w-4 h-4 text-borde-fuerte" />
          <h4 className="text-xs font-semibold uppercase tracking-wide text-suave">{title}</h4>
        </div>
        {action}
      </div>
      {children}
    </div>
  )
}

/** Una fila etiqueta–valor. */
export function Linea({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-borde last:border-0">
      <span className="text-xs text-suave">{label}</span>
      <span className="text-sm text-cuerpo font-medium text-right truncate ml-2">{value || '—'}</span>
    </div>
  )
}

/** Spinner de carga centrado. */
export function Cargando({ texto = 'Cargando…' }: { texto?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-accion text-sm">
      <Loader2 className="w-5 h-5 animate-spin" /> {texto}
    </div>
  )
}

/** Estado vacío de una lista. */
export function Vacio({ texto }: { texto: string }) {
  return <p className="text-sm text-suave italic py-8 text-center">{texto}</p>
}

/** Alerta de errores (lista de mensajes). */
export function ErroresAlerta({ errores }: { errores: string[] }) {
  if (errores.length === 0) return null
  return (
    <div className="flex items-start gap-2.5 rounded-xl px-4 py-3 bg-peligro-tinte border border-peligro-borde">
      <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-peligro" />
      <ul className="text-xs text-peligro space-y-0.5 list-disc list-inside">
        {errores.map((e, i) => (
          <li key={i}>{e}</li>
        ))}
      </ul>
    </div>
  )
}

// ── Citas (compartido por la ficha y la sección de citas) ───────────────────

/** Estados en los que una cita ya no cuenta como "próxima". */
export const ESTADOS_CITA_INACTIVOS = new Set<AppointmentStatus>(['attended', 'cancelled', 'no_show'])

/**
 * Estilo del chip de estado de una cita.
 *
 * Los cuatro estados usan la escala semántica y NADA más: atendida/confirmada
 * comparten el verde de éxito, cancelada/no asistió el rojo de peligro, y
 * pendiente el ámbar de aviso. Antes cada uno traía su propio hex suelto y
 * "cancelada" salía en #C0392B, que sobre su propio tinte daba 3.8:1.
 *
 * El color es el TERCER canal: quien pinte este chip debe acompañarlo del
 * texto del estado (y a ser posible un icono), porque ~8% de los hombres no
 * distingue bien rojo de verde.
 */
export function estadoCitaChip(s: AppointmentStatus): { bg: string; color: string } {
  if (s === 'attended') return { bg: 'var(--exito-tinte)', color: 'var(--exito)' }
  if (s === 'confirmed' || s === 'arrived' || s === 'in_progress') return { bg: 'var(--exito-tinte)', color: 'var(--exito)' }
  if (s === 'cancelled' || s === 'no_show') return { bg: 'var(--peligro-tinte)', color: 'var(--peligro)' }
  return { bg: 'var(--aviso-tinte)', color: 'var(--aviso)' }
}

// ── Constantes de choices/labels (reflejan los choices del backend) ──────────

export const SEVERITY_OPTIONS: { value: AllergySeverity; label: string }[] = [
  { value: '', label: 'Sin especificar' },
  { value: 'leve', label: 'Leve' },
  { value: 'moderada', label: 'Moderada' },
  { value: 'severa', label: 'Severa' },
]

export const VIVIENDA_OPTIONS: { value: ViviendaChoice | ''; label: string }[] = [
  { value: '', label: 'Sin especificar' },
  { value: 'propia', label: 'Propia' },
  { value: 'rentada', label: 'Rentada' },
  { value: 'prestada', label: 'Prestada' },
  { value: 'otro', label: 'Otro' },
]

export const MARITAL_OPTIONS: { value: MaritalStatus; label: string }[] = [
  { value: '', label: 'Sin especificar' },
  { value: 'soltero', label: 'Soltero/a' },
  { value: 'casado', label: 'Casado/a' },
  { value: 'union_libre', label: 'Unión libre' },
  { value: 'divorciado', label: 'Divorciado/a' },
  { value: 'viudo', label: 'Viudo/a' },
  { value: 'otro', label: 'Otro' },
]

export const EDUCATION_OPTIONS: { value: Education; label: string }[] = [
  { value: '', label: 'Sin especificar' },
  { value: 'ninguna', label: 'Ninguna' },
  { value: 'primaria', label: 'Primaria' },
  { value: 'secundaria', label: 'Secundaria' },
  { value: 'preparatoria', label: 'Preparatoria / Bachillerato' },
  { value: 'licenciatura', label: 'Licenciatura' },
  { value: 'posgrado', label: 'Posgrado' },
]

export const BLOOD_OPTIONS: { value: BloodType; label: string }[] = [
  { value: '', label: 'Sin especificar' },
  { value: 'A+', label: 'A+' },
  { value: 'A-', label: 'A-' },
  { value: 'B+', label: 'B+' },
  { value: 'B-', label: 'B-' },
  { value: 'AB+', label: 'AB+' },
  { value: 'AB-', label: 'AB-' },
  { value: 'O+', label: 'O+' },
  { value: 'O-', label: 'O-' },
  { value: 'desconocido', label: 'Desconocido' },
]

export const DIAGNOSIS_KIND_OPTIONS: { value: DiagnosisKind; label: string }[] = [
  { value: 'presuntivo', label: 'Presuntivo' },
  { value: 'definitivo', label: 'Definitivo' },
]

/** Formas farmacéuticas (reflejan models.MedicationForm.choices del backend). */
export const MEDICATION_FORM_OPTIONS: { value: MedicationFormValue; label: string }[] = [
  { value: 'tableta', label: 'Tableta' },
  { value: 'capsula', label: 'Cápsula' },
  { value: 'jarabe', label: 'Jarabe' },
  { value: 'suspension', label: 'Suspensión' },
  { value: 'solucion', label: 'Solución' },
  { value: 'solucion_inyectable', label: 'Solución inyectable' },
  { value: 'crema', label: 'Crema' },
  { value: 'unguento', label: 'Ungüento' },
  { value: 'gel', label: 'Gel' },
  { value: 'gotas', label: 'Gotas' },
  { value: 'ovulo', label: 'Óvulo' },
  { value: 'supositorio', label: 'Supositorio' },
  { value: 'parche', label: 'Parche' },
  { value: 'aerosol', label: 'Aerosol' },
  { value: 'polvo', label: 'Polvo' },
  { value: 'otro', label: 'Otro' },
]

/** Etiqueta legible de una forma farmacéutica (snapshot puede llegar como string libre). */
export function formaLabel(form: string): string {
  return MEDICATION_FORM_OPTIONS.find(o => o.value === form)?.label ?? form
}

/** Estados de la exploración basal (HC). */
export const EXPLORACION_BASAL_OPTIONS: { value: ExploracionBasalEstado; label: string }[] = [
  { value: 'sin_alteraciones', label: 'Sin alteraciones' },
  { value: 'con_alteraciones', label: 'Con alteraciones' },
]

/** Estados del semáforo de la exploración de la nota de evolución. */
export const EXPLORACION_EVOLUCION_OPTIONS: {
  value: ExploracionEvolucionEstado
  label: string
  color: string
}[] = [
  { value: 'no_evaluado', label: 'No evaluado', color: 'var(--tenue)' },
  { value: 'normal', label: 'Normal', color: 'var(--exito)' },
  { value: 'observacion', label: 'En observación', color: 'var(--aviso)' },
  { value: 'alterado', label: 'Alterado', color: 'var(--peligro)' },
]

/** Etiquetas legibles de los sistemas/aparatos. */
export const SISTEMA_LABEL: Record<string, string> = {
  cerebro: 'Cerebro',
  sistema_nervioso: 'Sistema nervioso',
  ocular: 'Ocular',
  endocrino: 'Endocrino',
  corazon: 'Corazón',
  circulatorio: 'Circulatorio',
  respiratorio: 'Respiratorio',
  hepatico: 'Hepático',
  pancreas: 'Páncreas',
  renal: 'Renal',
  gastrointestinal: 'Gastrointestinal',
  osteoarticular: 'Osteoarticular',
  tendomuscular: 'Tendomuscular',
  reproductor: 'Reproductor',
  inmunologico: 'Inmunológico',
  extremidades: 'Extremidades',
  piel_tegumentos: 'Piel y tegumentos',
  otros: 'Otros',
}

/**
 * Imagen (icono anatómico) por aparato/sistema, para dar identidad visual a la
 * exploración (similar al expediente legacy). Los SVG son de Healthicons
 * (healthicons.org, licencia MIT) y viven en `web-soft/public/organos/`.
 */
export const SISTEMA_ICONO_SRC: Record<string, string> = {
  cerebro: '/organos/cerebro.svg',
  sistema_nervioso: '/organos/sistema_nervioso.svg',
  ocular: '/organos/ocular.svg',
  endocrino: '/organos/endocrino.svg',
  corazon: '/organos/corazon.svg',
  circulatorio: '/organos/circulatorio.svg',
  respiratorio: '/organos/respiratorio.svg',
  hepatico: '/organos/hepatico.svg',
  pancreas: '/organos/pancreas.svg',
  renal: '/organos/renal.svg',
  gastrointestinal: '/organos/gastrointestinal.svg',
  osteoarticular: '/organos/osteoarticular.svg',
  tendomuscular: '/organos/tendomuscular.svg',
  reproductor: '/organos/reproductor.svg',
  inmunologico: '/organos/inmunologico.svg',
  extremidades: '/organos/extremidades.svg',
  piel_tegumentos: '/organos/piel_tegumentos.svg',
  otros: '/organos/otros.svg',
}

/** Icono anatómico (imagen) de un aparato/sistema. */
export function SistemaIcono({ sistema, className }: { sistema: string; className?: string }) {
  const src = SISTEMA_ICONO_SRC[sistema]
  if (!src) return null
  return <img src={src} alt="" aria-hidden="true" className={className ?? 'h-5 w-5 shrink-0'} />
}

/** Nombre del sistema con su icono anatómico al inicio (para encabezados). */
export function SistemaLabelConIcono({ sistema }: { sistema: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <SistemaIcono sistema={sistema} />
      {SISTEMA_LABEL[sistema] ?? sistema}
    </span>
  )
}
