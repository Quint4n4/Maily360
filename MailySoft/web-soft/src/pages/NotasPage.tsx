import { useState } from 'react'
import { Plus, Loader2, StickyNote, Megaphone } from 'lucide-react'
import Topbar from '../components/Topbar'
import NotaCard, { NotaColor } from '../components/notas/NotaCard'
import NuevaNotaModal from '../components/notas/NuevaNotaModal'
import { useNotes, useDeleteNote, useToggleNoteDone } from '../hooks/notas'
import { useAuth } from '../auth/AuthContext'
import type { Note } from '../types/nota'

type Filtro = 'todas' | 'notas' | 'tareas'

const PALETA: NotaColor[] = [
  { bg: '#FEF3C7', ink: '#B7791F' }, // amarillo
  { bg: '#FCE4EC', ink: '#C2185B' }, // rosa
  { bg: '#E3F2FD', ink: '#1976D2' }, // azul
  { bg: '#E8F5E9', ink: '#2E7D5B' }, // verde
  { bg: '#F3E5F5', ink: '#7B1FA2' }, // morado
  { bg: '#FFF3E0', ink: '#E8924E' }, // naranja
]
const colorDe = (i: number): NotaColor => PALETA[i % PALETA.length]

const FILTROS: { key: Filtro; label: string }[] = [
  { key: 'todas', label: 'Todas' },
  { key: 'notas', label: 'Notas' },
  { key: 'tareas', label: 'Tareas' },
]

export default function NotasPage() {
  const { user } = useAuth()
  const [filtro, setFiltro] = useState<Filtro>('todas')
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<Note | null>(null)

  const filtros = filtro === 'tareas' ? { is_task: true } : filtro === 'notas' ? { is_task: false } : {}
  const { data, isLoading, isError } = useNotes(filtros)
  const borrar = useDeleteNote()
  const toggle = useToggleNoteDone()

  const notes = data?.results ?? []
  const personales = notes.filter(n => n.scope === 'personal')
  const globales = notes.filter(n => n.scope !== 'personal')

  const abrirNueva = () => { setEditing(null); setModalOpen(true) }
  const abrirEditar = (n: Note) => { setEditing(n); setModalOpen(true) }
  const esMia = (n: Note) => n.author.id === user?.id

  return (
    <div className="min-h-screen relative">
      <div className="fixed inset-0 -z-10" style={{ background: 'linear-gradient(135deg, #b89a52 0%, #d8c690 45%, #f1e8cf 100%)' }} />
      <div className="fixed inset-0 -z-10 bg-cover bg-center" style={{ backgroundImage: "url('/fondo-agenda.jpg')" }} />
      <div className="fixed inset-0 -z-10" style={{ background: 'rgba(255,255,255,0.20)' }} />

      <Topbar active="notas" />

      <div className="p-5 max-w-[1300px] mx-auto">
        {/* Encabezado */}
        <div className="glass-card rounded-2xl px-6 py-5 flex items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
              <StickyNote className="w-6 h-6" style={{ color: '#C9A227' }} /> Notas y Tareas
            </h1>
            <p className="text-sm text-gray-500 mt-0.5">Tus notas personales y los avisos de la clínica.</p>
          </div>
          <button onClick={abrirNueva}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 shrink-0"
            style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}>
            <Plus className="w-4 h-4" /> Nueva nota
          </button>
        </div>

        {/* Filtros */}
        <div className="flex gap-2 mt-5">
          {FILTROS.map(f => (
            <button key={f.key} onClick={() => setFiltro(f.key)}
              className="px-4 py-1.5 rounded-full text-sm font-semibold transition-all"
              style={filtro === f.key
                ? { background: '#C9A227', color: '#fff', boxShadow: '0 2px 8px rgba(201,162,39,0.35)' }
                : { background: 'rgba(255,255,255,0.6)', color: '#7A756C' }}>
              {f.label}
            </button>
          ))}
        </div>

        {isLoading && <div className="flex items-center justify-center gap-2 mt-20 text-amber-700"><Loader2 className="w-5 h-5 animate-spin" /> Cargando…</div>}
        {isError && <div className="glass-card rounded-2xl mt-6 py-10 text-center text-sm text-red-600">No se pudieron cargar las notas.</div>}

        {!isLoading && !isError && (
          <>
            {/* Mis notas / tareas */}
            <h2 className="text-sm font-bold text-gray-700 uppercase tracking-wide mt-6 mb-3">Mis notas y tareas</h2>
            <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))' }}>
              {personales.map((n, i) => (
                <NotaCard key={n.id} note={n} color={colorDe(i)} editable
                  onEdit={() => abrirEditar(n)} onDelete={() => borrar.mutate(n.id)} onToggleDone={() => toggle.mutate(n.id)} />
              ))}
              {/* Tarjeta "Nueva nota" */}
              <button onClick={abrirNueva}
                className="rounded-2xl min-h-[180px] flex flex-col items-center justify-center gap-2 text-gray-400 hover:text-amber-600 transition-colors"
                style={{ border: '2px dashed rgba(201,162,39,0.4)', background: 'rgba(255,255,255,0.35)' }}>
                <Plus className="w-7 h-7" />
                <span className="text-sm font-semibold">Nueva nota</span>
              </button>
            </div>

            {/* Recibidas (globales) */}
            {globales.length > 0 && (
              <>
                <h2 className="text-sm font-bold text-gray-700 uppercase tracking-wide mt-8 mb-3 flex items-center gap-2">
                  <Megaphone className="w-4 h-4" style={{ color: '#3A6EA5' }} /> Avisos de la clínica
                </h2>
                <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))' }}>
                  {globales.map((n, i) => (
                    <NotaCard key={n.id} note={n} color={colorDe(i + 2)} editable={esMia(n)}
                      onEdit={() => abrirEditar(n)} onDelete={() => borrar.mutate(n.id)} />
                  ))}
                </div>
              </>
            )}

            {personales.length === 0 && globales.length === 0 && (
              <div className="glass-card rounded-2xl mt-6 py-16 text-center">
                <StickyNote className="w-10 h-10 mx-auto mb-3" style={{ color: '#C9A227', opacity: 0.5 }} />
                <p className="text-sm text-gray-500">Aún no tienes notas. Crea la primera con “Nueva nota”.</p>
              </div>
            )}
          </>
        )}
      </div>

      <NuevaNotaModal open={modalOpen} onClose={() => setModalOpen(false)} editing={editing} />
    </div>
  )
}
