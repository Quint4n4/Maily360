import { useState, useEffect } from 'react'
import { Search, UserCog, Loader2, AlertCircle } from 'lucide-react'
import PlatformLayout from '../../platform/PlatformLayout'
import { usePlatformStaff } from '../../hooks/plataforma'

const ini = (n: string) => n.split(' ').slice(0, 2).map(w => w[0] ?? '').join('').toUpperCase() || '?'

export default function UsuariosPage() {
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 350)
    return () => clearTimeout(t)
  }, [query])

  const { data, isLoading, isError } = usePlatformStaff(debounced)
  const lista = data?.results ?? []
  const total = data?.count ?? 0

  return (
    <PlatformLayout active="usuarios">
      <div className="glass-card rounded-2xl px-6 py-5">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Equipo Maily</h1>
          <p className="text-sm text-gray-500">
            {isLoading ? 'Cargando…' : `${total} usuario${total === 1 ? '' : 's'} interno${total === 1 ? '' : 's'} de la plataforma`}
          </p>
        </div>
        <div className="relative mt-4 max-w-md">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
          <input value={query} onChange={e => setQuery(e.target.value)}
            placeholder="Buscar por nombre o correo" className="input pl-10" style={{ background: 'rgba(255,255,255,0.7)' }} />
        </div>
      </div>

      {isError && (
        <div className="glass-card rounded-2xl py-10 px-6 flex items-center justify-center gap-3">
          <AlertCircle className="w-5 h-5 text-red-500 shrink-0" />
          <p className="text-sm text-red-600">No se pudo cargar el equipo. ¿Tienes permiso de Súper Admin?</p>
        </div>
      )}

      {isLoading && !isError && (
        <div className="flex items-center justify-center gap-2 py-16 text-amber-700">
          <Loader2 className="w-5 h-5 animate-spin" /> Cargando equipo…
        </div>
      )}

      {!isLoading && !isError && (
        <div className="glass-card rounded-2xl overflow-hidden">
          <div className="grid items-center px-6 py-3 text-xs font-semibold text-gray-500 border-b border-white/40"
            style={{ gridTemplateColumns: '2fr 2fr 1fr 1fr' }}>
            <span>Nombre</span><span>Correo</span><span>Rol</span><span>Estado</span>
          </div>
          {lista.map(u => (
            <div key={u.id} className="grid items-center px-6 py-3 border-b border-white/30"
              style={{ gridTemplateColumns: '2fr 2fr 1fr 1fr' }}>
              <span className="flex items-center gap-3 min-w-0">
                <span className="w-9 h-9 rounded-full flex items-center justify-center text-xs font-bold shrink-0"
                  style={{ background: 'rgba(201,162,39,0.16)', color: '#B8860B' }}>{ini(u.full_name)}</span>
                <span className="text-sm font-medium text-gray-800 truncate">{u.full_name || '—'}</span>
              </span>
              <span className="text-sm text-gray-600 truncate">{u.email}</span>
              <span className="flex items-center gap-1.5 text-sm text-gray-600">
                <UserCog className="w-3.5 h-3.5 text-gray-400" /> {u.platform_role_display || '—'}
              </span>
              <span><span className={`badge ${u.is_active ? 'badge-success' : 'badge-neutral'}`}>{u.is_active ? 'Activo' : 'Inactivo'}</span></span>
            </div>
          ))}
          {lista.length === 0 && (
            <p className="px-6 py-12 text-center text-sm text-gray-400">No hay usuarios con ese criterio.</p>
          )}
        </div>
      )}
    </PlatformLayout>
  )
}
