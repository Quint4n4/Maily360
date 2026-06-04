import { useState } from 'react'
import { ChevronLeft, ChevronRight, Eye, Cake, FileText, CircleDollarSign, UserX } from 'lucide-react'
import Topbar from '../components/Topbar'
import CrearEventoModal from '../components/agenda/CrearEventoModal'
import DetalleCitaModal, { CitaDetalle, EstadoCita } from '../components/agenda/DetalleCitaModal'

/* ─── Datos demo ────────────────────────────────────────────────────────── */
const CONSULTORIOS = [
  { name: 'Consultorio 1', color: '#C9A227' },
  { name: 'Consultorio 2', color: '#3A6EA5' },
  { name: 'Consultorio 3', color: '#2E7D5B' },
]

interface Cita {
  consultorio: number
  h: number; m: number
  dur: number
  paciente: string
  motivo: string
  estado: 'confirmada' | 'pendiente'
  notas?: string
}

const CITAS: Cita[] = [
  { consultorio: 0, h: 9,  m: 0,  dur: 60, paciente: 'María González',  motivo: 'Valoración',   estado: 'confirmada', notas: 'Alérgica a penicilina.' },
  { consultorio: 1, h: 10, m: 0,  dur: 30, paciente: 'Roberto Sánchez', motivo: 'Subsecuente',  estado: 'pendiente'  },
  { consultorio: 0, h: 11, m: 30, dur: 60, paciente: 'Lucía Ramírez',   motivo: 'Primera vez',  estado: 'confirmada' },
  { consultorio: 2, h: 13, m: 0,  dur: 30, paciente: 'Jorge Mendoza',   motivo: 'Urgente',      estado: 'pendiente'  },
]

const SLOTS = Array.from({ length: 18 }, (_, i) => {
  const h = 9 + Math.floor(i / 2)
  const m = i % 2 === 0 ? 0 : 30
  return { h, m, label: `${h}:${m === 0 ? '00' : '30'}` }
})

const ROW_H = 60
const slotIndex = (h: number, m: number) => (h - 9) * 2 + (m === 30 ? 1 : 0)
const pad = (n: number) => (n < 10 ? `0${n}` : `${n}`)
const rangoHorario = (h: number, m: number, dur: number) => {
  const total = h * 60 + m + dur
  return `${h}:${pad(m)} – ${Math.floor(total / 60)}:${pad(total % 60)}`
}

const DIAS_SEMANA = ['L', 'M', 'M', 'J', 'V', 'S', 'D']
const monthGrid = (() => {
  const first = new Date(2026, 5, 1)
  const lead  = (first.getDay() + 6) % 7
  const total = 30
  const cells: (number | null)[] = []
  for (let i = 0; i < lead; i++) cells.push(null)
  for (let d = 1; d <= total; d++) cells.push(d)
  while (cells.length % 7 !== 0) cells.push(null)
  return cells
})()

const QUICK_LINKS = [
  { icon: Cake,             label: 'Cumpleaños',           color: '#C9A227' },
  { icon: FileText,         label: 'Hoja diaria',          color: '#9A7B1E' },
  { icon: CircleDollarSign, label: 'Cuentas por cobrar',   color: '#C0392B' },
  { icon: UserX,            label: 'Contactos cancelados', color: '#C0392B' },
]

/* ─── Componente ─────────────────────────────────────────────────────────── */
export default function AgendaPage() {
  const [selectedDay] = useState(4)
  const [modalOpen, setModalOpen] = useState(false)
  const [slotSel, setSlotSel] = useState<{ hora: string; consultorio: string }>({ hora: '09:00', consultorio: 'Consultorio 1' })
  const [citaSel, setCitaSel] = useState<CitaDetalle | null>(null)

  const abrirCrear = (label: string, consultorioName: string) => {
    setSlotSel({ hora: label.length === 4 ? `0${label}` : label, consultorio: consultorioName })
    setModalOpen(true)
  }

  const abrirCita = (cita: Cita) => {
    const c = CONSULTORIOS[cita.consultorio]
    const estadoInicial: EstadoCita = cita.estado === 'confirmada' ? 'confirmada' : 'agendada'
    setCitaSel({
      paciente: cita.paciente,
      doctor: 'Dra. Martínez',
      consultorioName: c.name,
      consultorioColor: c.color,
      horario: rangoHorario(cita.h, cita.m, cita.dur),
      fecha: 'Jueves 4 de Junio, 2026',
      motivo: cita.motivo,
      especialidad: 'Medicina regenerativa',
      notas: cita.notas ?? '',
      estadoInicial,
    })
  }

  return (
    <div className="min-h-screen relative">

      {/* Fondo */}
      <div className="fixed inset-0 -z-10" style={{ background: 'linear-gradient(135deg, #b89a52 0%, #d8c690 45%, #f1e8cf 100%)' }} />
      <div className="fixed inset-0 -z-10 bg-cover bg-center" style={{ backgroundImage: "url('/fondo-agenda.jpg')" }} />
      <div className="fixed inset-0 -z-10" style={{ background: 'rgba(255,255,255,0.20)' }} />

      <Topbar active="agenda" />

      <div className="flex gap-5 p-5 max-w-[1500px] mx-auto">

        {/* ════════ Panel izquierdo ════════ */}
        <aside className="w-80 shrink-0 space-y-4">

          {/* Calendario */}
          <div className="glass-card rounded-2xl p-5">
            <div className="flex items-center justify-between mb-4">
              <button className="p-1 rounded-lg hover:bg-white/40 text-gray-500"><ChevronLeft className="w-5 h-5" /></button>
              <span className="text-sm font-semibold text-gray-800">4 de Junio de 2026</span>
              <div className="flex items-center gap-1">
                <button className="p-1 rounded-lg hover:bg-white/40 text-gray-500"><ChevronRight className="w-5 h-5" /></button>
                <button className="p-1 rounded-lg hover:bg-white/40" style={{ color: '#C9A227' }}><Eye className="w-5 h-5" /></button>
              </div>
            </div>

            <div className="grid grid-cols-7 gap-1 mb-1">
              {DIAS_SEMANA.map((d, i) => (
                <div key={i} className="text-center text-xs font-semibold text-gray-500 py-1">{d}</div>
              ))}
            </div>

            <div className="grid grid-cols-7 gap-1">
              {monthGrid.map((d, i) => (
                <div key={i} className="aspect-square flex items-center justify-center">
                  {d && (
                    <button
                      className="w-8 h-8 rounded-full text-sm flex items-center justify-center transition-colors hover:bg-white/50"
                      style={d === selectedDay
                        ? { background: '#C9A227', color: '#fff', fontWeight: 600 }
                        : { color: '#374151' }}
                    >
                      {d}
                    </button>
                  )}
                </div>
              ))}
            </div>

            <div className="flex items-center justify-between mt-4 pt-4 border-t border-white/40 text-sm">
              <button className="text-gray-600 hover:text-gray-800">Mes ant.</button>
              <button className="font-semibold" style={{ color: '#C9A227' }}>Hoy</button>
              <button className="text-gray-600 hover:text-gray-800">Mes sig.</button>
            </div>
          </div>

          {/* Accesos rápidos */}
          <div className="glass-card rounded-2xl overflow-hidden">
            {QUICK_LINKS.map(({ icon: Icon, label, color }, i) => (
              <button
                key={label}
                className="w-full flex items-center gap-3 px-5 py-3.5 hover:bg-white/40 transition-colors text-left"
                style={{ borderTop: i > 0 ? '1px solid rgba(255,255,255,0.45)' : 'none' }}
              >
                <Icon className="w-5 h-5 shrink-0" style={{ color }} />
                <span className="text-sm font-medium" style={{ color }}>{label}</span>
              </button>
            ))}
          </div>
        </aside>

        {/* ════════ Panel derecho — rejilla ════════ */}
        <main className="glass-card flex-1 rounded-2xl overflow-hidden">

          {/* Encabezado de columnas */}
          <div className="grid border-b border-white/50" style={{ gridTemplateColumns: '70px repeat(3, 1fr)' }}>
            <div className="py-3 text-center text-xs font-bold text-gray-500">Hr.</div>
            {CONSULTORIOS.map(c => (
              <div key={c.name} className="py-3 text-center text-sm font-semibold border-l border-white/50" style={{ color: '#374151' }}>
                <span className="inline-flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full" style={{ background: c.color }} />
                  {c.name}
                </span>
              </div>
            ))}
          </div>

          {/* Cuerpo */}
          <div className="relative grid" style={{ gridTemplateColumns: '70px repeat(3, 1fr)', gridAutoRows: `${ROW_H}px` }}>
            {SLOTS.map((s, r) => (
              <div key={`row-${r}`} className="contents">
                <div className="flex items-start justify-center pt-1 text-xs text-gray-500 border-b border-white/40"
                  style={{ gridColumn: 1, gridRow: r + 1 }}>
                  {s.label}
                </div>
                {CONSULTORIOS.map((c, ci) => (
                  <button
                    key={`cell-${r}-${ci}`}
                    onClick={() => abrirCrear(s.label, c.name)}
                    className="border-b border-l border-white/40 hover:bg-white/40 transition-colors"
                    style={{ gridColumn: ci + 2, gridRow: r + 1 }}
                  />
                ))}
              </div>
            ))}

            {/* Citas */}
            {CITAS.map((cita, idx) => {
              const start = slotIndex(cita.h, cita.m)
              const span  = Math.max(1, Math.round(cita.dur / 30))
              const c     = CONSULTORIOS[cita.consultorio]
              const confirmada = cita.estado === 'confirmada'
              return (
                <div
                  key={idx}
                  onClick={() => abrirCita(cita)}
                  className="relative m-1 rounded-3xl px-3 py-1.5 overflow-hidden cursor-pointer transition-transform hover:scale-[1.01] flex flex-col items-center justify-center text-center leading-tight"
                  style={{
                    gridColumn: cita.consultorio + 2,
                    gridRow: `${start + 1} / span ${span}`,
                    background: 'rgba(255,255,255,0.82)',
                    backdropFilter: 'blur(6px)',
                    boxShadow: '0 2px 10px rgba(60,42,12,0.12)',
                    zIndex: 5,
                  }}
                >
                  <span className="absolute top-2.5 right-3 w-2.5 h-2.5 rounded-full"
                    style={{ background: c.color, boxShadow: `0 0 0 3px ${c.color}22` }} />
                  <p className="text-xs font-semibold text-gray-800 leading-tight truncate w-full px-3">{cita.paciente}</p>
                  <p className="text-[11px] text-gray-500 truncate w-full">{cita.motivo}</p>
                  {span >= 2 && (
                    <span
                      className="inline-block mt-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium"
                      style={confirmada
                        ? { background: '#E7F6EE', color: '#2E7D5B' }
                        : { background: '#FBF1D9', color: '#9A7B1E' }}
                    >
                      {confirmada ? 'Confirmada' : 'Pendiente'}
                    </span>
                  )}
                </div>
              )
            })}
          </div>
        </main>
      </div>

      <CrearEventoModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        fecha="04/06/2026"
        horaInicio={slotSel.hora}
        consultorio={slotSel.consultorio}
      />

      <DetalleCitaModal cita={citaSel} onClose={() => setCitaSel(null)} />
    </div>
  )
}
