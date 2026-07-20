import { useEffect, useRef, useState } from 'react'
import { Pencil, Trash2, Bell, Pin, Check, Megaphone, Eye, X, Building2, AlertTriangle } from 'lucide-react'
import { formatMedio, formatFechaHora } from '../../lib/fecha'
import type { Note } from '../../types/nota'

export interface NotaColor { bg: string; ink: string }

interface Props {
  note: Note
  color: NotaColor
  editable?: boolean
  onEdit?: () => void
  onDelete?: () => void
  onToggleDone?: () => void
}

/** Pie compartido por la tarjeta y el modal: recordatorio + sede + etiqueta global. */
function PieNota({ note, color }: { note: Note; color: NotaColor }) {
  const esGlobal = note.scope !== 'personal'
  // Multi-sede: los avisos muestran a qué sede van (o "Todas las sedes").
  const etiquetaSede = note.sucursal ? note.sucursal.name : 'Todas las sedes'
  return (
    <div className="flex items-end justify-between gap-2 mt-3 pt-2" style={{ borderTop: `1px solid ${color.ink}22` }}>
      {note.remind_at ? (
        <span className="inline-flex items-center gap-1.5 text-[11px] font-medium shrink-0" style={{ color: color.ink }}>
          <Bell className="w-3.5 h-3.5" /> {formatFechaHora(note.remind_at)}
        </span>
      ) : <span />}
      {esGlobal && (
        <div className="flex flex-wrap items-center justify-end gap-1">
          <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full" style={{ background: `${color.ink}18`, color: color.ink }}>
            <Building2 className="w-3 h-3" /> {etiquetaSede}
          </span>
          <span className="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full" style={{ background: `${color.ink}22`, color: color.ink }}>
            <Megaphone className="w-3 h-3" />
            {note.scope === 'all' ? 'Para todos' : `Rol: ${note.target_role}`}
          </span>
        </div>
      )}
    </div>
  )
}

export default function NotaCard({ note, color, editable = false, onEdit, onDelete, onToggleDone }: Props) {
  const hecha = note.is_task && note.done

  const bodyRef = useRef<HTMLParagraphElement>(null)
  const [truncado, setTruncado] = useState(false)
  const [abierto, setAbierto] = useState(false)

  // Detecta si el cuerpo se cortó (excede las 5 líneas del clamp) para mostrar "Ver".
  useEffect(() => {
    const el = bodyRef.current
    if (!el) return
    setTruncado(el.scrollHeight > el.clientHeight + 1)
  }, [note.body])

  // Cerrar el modal con Escape.
  useEffect(() => {
    if (!abierto) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setAbierto(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [abierto])

  const titulo = note.title || (note.is_task ? 'Tarea' : 'Nota')

  return (
    <>
      <div
        className="group relative rounded-2xl p-5 flex flex-col min-h-[180px] transition-transform hover:-translate-y-0.5"
        style={{
          background: color.bg,
          boxShadow: note.is_important ? '0 4px 20px rgba(190,40,40,0.22)' : '0 4px 16px rgba(60,42,12,0.08)',
          border: note.is_important ? '1.5px solid rgba(190,40,40,0.55)' : '1.5px solid transparent',
        }}
      >
        {/* aviso importante: banda destacada */}
        {note.is_important && (
          <span className="inline-flex items-center gap-1 self-start text-[10px] font-extrabold px-2 py-0.5 rounded-full mb-2 tracking-wide"
            style={{ background: 'rgba(190,40,40,0.14)', color: '#B02828' }}>
            <AlertTriangle className="w-3 h-3" /> IMPORTANTE
          </span>
        )}
        {/* fila superior: fecha + acciones */}
        <div className="flex items-start justify-between mb-2">
          <span className="text-[11px] font-medium" style={{ color: color.ink, opacity: 0.7 }}>
            {formatMedio(new Date(note.created_at))}
          </span>
          <div className="flex items-center gap-1">
            {note.pinned && <Pin className="w-3.5 h-3.5" style={{ color: color.ink }} fill="currentColor" />}
            {editable && (
              <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <button onClick={onEdit} title="Editar"
                  className="w-6 h-6 rounded-md flex items-center justify-center hover:bg-black/10 transition-colors" style={{ color: color.ink }}>
                  <Pencil className="w-3.5 h-3.5" />
                </button>
                <button onClick={onDelete} title="Eliminar"
                  className="w-6 h-6 rounded-md flex items-center justify-center hover:bg-black/10 transition-colors text-red-600">
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            )}
          </div>
        </div>

        {/* título (+ checkbox de tarea) */}
        <div className="flex items-start gap-2">
          {note.is_task && (
            <button onClick={editable ? onToggleDone : undefined} disabled={!editable}
              className="mt-0.5 w-5 h-5 rounded-md shrink-0 flex items-center justify-center transition-colors"
              style={{ border: `2px solid ${color.ink}`, background: hecha ? color.ink : 'transparent', cursor: editable ? 'pointer' : 'default' }}>
              {hecha && <Check className="w-3 h-3 text-white" />}
            </button>
          )}
          <h3 className={`text-base font-bold leading-snug ${hecha ? 'line-through opacity-60' : ''}`} style={{ color: '#2A241B' }}>
            {titulo}
          </h3>
        </div>

        {/* cuerpo (recortado a 5 líneas) */}
        {note.body && (
          <p ref={bodyRef} className="text-sm mt-2 whitespace-pre-wrap" style={{ color: '#5A5246', display: '-webkit-box', WebkitLineClamp: 5, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
            {note.body}
          </p>
        )}

        {/* botón "Ver" — solo si el texto se cortó */}
        {note.body && truncado && (
          <button onClick={() => setAbierto(true)} title="Ver nota completa"
            className="self-start inline-flex items-center gap-1 text-xs font-semibold mt-1.5 px-2 py-1 -ml-2 rounded-lg hover:bg-black/5 transition-colors"
            style={{ color: color.ink }}>
            <Eye className="w-3.5 h-3.5" /> Ver
          </button>
        )}

        <div className="flex-1" />

        <PieNota note={note} color={color} />
      </div>

      {/* modal: nota completa */}
      {abierto && (
        <div className="fixed inset-0 z-[110] flex items-center justify-center px-4"
          style={{ background: 'rgba(40,28,8,0.5)', backdropFilter: 'blur(6px)' }}
          onClick={() => setAbierto(false)}>
          <div className="relative w-full max-w-lg rounded-3xl overflow-hidden"
            style={{ background: color.bg, boxShadow: '0 24px 70px rgba(60,42,12,0.3)' }}
            onClick={e => e.stopPropagation()}>
            <div className="p-7">
              <div className="flex items-start justify-between gap-3 mb-2">
                <span className="text-[11px] font-medium" style={{ color: color.ink, opacity: 0.7 }}>
                  {formatMedio(new Date(note.created_at))}
                </span>
                <button onClick={() => setAbierto(false)} title="Cerrar"
                  className="w-7 h-7 rounded-lg flex items-center justify-center hover:bg-black/10 transition-colors shrink-0" style={{ color: color.ink }}>
                  <X className="w-4 h-4" />
                </button>
              </div>
              <h3 className="text-xl font-bold leading-snug mb-3" style={{ color: '#2A241B' }}>{titulo}</h3>
              {note.body && (
                <p className="text-[15px] leading-relaxed whitespace-pre-wrap max-h-[60vh] overflow-y-auto" style={{ color: '#3A352C' }}>
                  {note.body}
                </p>
              )}
              <PieNota note={note} color={color} />
            </div>
          </div>
        </div>
      )}
    </>
  )
}
