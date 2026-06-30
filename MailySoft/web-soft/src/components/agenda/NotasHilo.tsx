import { useState } from 'react'
import { Loader2, Send, Trash2, MessageSquare } from 'lucide-react'
import { useAgendaItemNotes, useAddAgendaItemNote, useDeleteAgendaItemNote } from '../../hooks/agenda'
import { useRole } from '../../auth/RoleContext'
import { useAuth } from '../../auth/AuthContext'
import { puedeEditar } from '../../auth/permisos'
import { formatFechaHora } from '../../lib/fecha'
import { errorMsg } from '../../lib/apiErrors'

interface Props {
  kind: 'cita' | 'evento'
  itemId: string
}

const iniciales = (nombre: string): string =>
  nombre.trim().split(/\s+/).slice(0, 2).map(w => w[0]).join('').toUpperCase() || '?'

/** Hilo de notas colaborativas (con autor) de una cita o evento. Todos lo ven;
 *  los roles con edición en agenda pueden agregar; borra el autor, Dueño o Admin. */
export default function NotasHilo({ kind, itemId }: Props) {
  const { role } = useRole()
  const { user } = useAuth()
  const puedeAgregar = puedeEditar(role, 'agenda')
  const esGestor = role === 'owner' || role === 'admin'
  const [texto, setTexto] = useState('')

  const { data: notas, isLoading } = useAgendaItemNotes(kind, itemId)
  const agregar = useAddAgendaItemNote()
  const borrar = useDeleteAgendaItemNote()
  const lista = notas ?? []

  const enviar = async () => {
    const body = texto.trim()
    if (!body || agregar.isPending) return
    // El error NO se traga: la UI lo muestra con agregar.isError (abajo). El catch
    // solo evita el unhandled-rejection de mutateAsync; el texto se conserva.
    try { await agregar.mutateAsync({ kind, id: itemId, body }); setTexto('') } catch { /* mostrado via agregar.isError */ }
  }

  return (
    <div>
      <h4 className="text-xs font-bold text-gray-500 uppercase tracking-wide flex items-center gap-1.5 mb-2">
        <MessageSquare className="w-3.5 h-3.5" style={{ color: '#C9A227' }} /> Notas del equipo
      </h4>

      {isLoading ? (
        <p className="text-xs text-gray-400 italic py-2">Cargando…</p>
      ) : lista.length === 0 ? (
        <p className="text-xs text-gray-400 italic py-2">Aún no hay notas. Agrega la primera.</p>
      ) : (
        <div className="space-y-2 max-h-44 overflow-y-auto pr-1">
          {lista.map(n => {
            const puedeBorrar = n.author.id === user?.id || esGestor
            return (
              <div key={n.id} className="group flex items-start gap-2.5 rounded-xl px-3 py-2 bg-white/60">
                {n.author.avatar ? (
                  <img src={n.author.avatar} alt={n.author.full_name}
                    className="w-7 h-7 rounded-full shrink-0 object-cover" style={{ border: '1px solid rgba(201,162,39,0.4)' }} />
                ) : (
                  <div className="w-7 h-7 rounded-full shrink-0 flex items-center justify-center text-[11px] font-bold text-white" style={{ background: '#C9A227' }}>
                    {iniciales(n.author.full_name)}
                  </div>
                )}
                <div className="min-w-0 flex-1">
                  <p className="text-[11px] text-gray-400">
                    <span className="font-semibold text-gray-600">{n.author.full_name}</span> · {formatFechaHora(n.created_at)}
                  </p>
                  <p className="text-sm text-gray-800 whitespace-pre-wrap break-words">{n.body}</p>
                </div>
                {puedeBorrar && (
                  <button onClick={() => borrar.mutate({ noteId: n.id })} title="Eliminar nota"
                    className="opacity-0 group-hover:opacity-100 transition-opacity text-red-500 hover:text-red-600 shrink-0 mt-0.5">
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            )
          })}
        </div>
      )}

      {puedeAgregar && (
        <div className="mt-3">
          <div className="flex items-center gap-2">
            <input
              value={texto}
              onChange={e => setTexto(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); enviar() } }}
              placeholder="Escribe una nota para el equipo…"
              maxLength={1000}
              className="flex-1 rounded-xl border border-white/60 bg-white/70 px-3.5 py-2 text-sm text-gray-800 outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-500/20"
            />
            <button onClick={enviar} disabled={!texto.trim() || agregar.isPending}
              className="w-10 h-10 rounded-xl flex items-center justify-center text-white transition-all hover:brightness-110 disabled:opacity-40 shrink-0"
              style={{ background: '#C9A227' }}>
              {agregar.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            </button>
          </div>
          {agregar.isError && (
            <p className="text-xs text-red-600 mt-1.5">{errorMsg(agregar.error)}</p>
          )}
        </div>
      )}
    </div>
  )
}
