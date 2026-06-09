import { Pencil, Trash2, Bell, Pin, Check, Megaphone } from 'lucide-react'
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

export default function NotaCard({ note, color, editable = false, onEdit, onDelete, onToggleDone }: Props) {
  const esGlobal = note.scope !== 'personal'
  const hecha = note.is_task && note.done

  return (
    <div
      className="group relative rounded-2xl p-5 flex flex-col min-h-[180px] transition-transform hover:-translate-y-0.5"
      style={{ background: color.bg, boxShadow: '0 4px 16px rgba(60,42,12,0.08)' }}
    >
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
          {note.title || (note.is_task ? 'Tarea' : 'Nota')}
        </h3>
      </div>

      {/* cuerpo */}
      {note.body && (
        <p className="text-sm mt-2 flex-1 whitespace-pre-wrap" style={{ color: '#5A5246', display: '-webkit-box', WebkitLineClamp: 5, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
          {note.body}
        </p>
      )}
      <div className="flex-1" />

      {/* pie: recordatorio / global */}
      <div className="flex items-center justify-between gap-2 mt-3 pt-2" style={{ borderTop: `1px solid ${color.ink}22` }}>
        {note.remind_at ? (
          <span className="inline-flex items-center gap-1.5 text-[11px] font-medium" style={{ color: color.ink }}>
            <Bell className="w-3.5 h-3.5" /> {formatFechaHora(note.remind_at)}
          </span>
        ) : <span />}
        {esGlobal && (
          <span className="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full" style={{ background: `${color.ink}22`, color: color.ink }}>
            <Megaphone className="w-3 h-3" />
            {note.scope === 'all' ? 'Para todos' : `Rol: ${note.target_role}`}
          </span>
        )}
      </div>
    </div>
  )
}
