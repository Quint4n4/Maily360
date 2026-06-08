import { Plus, UserCog } from 'lucide-react'
import PlatformLayout from '../../platform/PlatformLayout'
import { usePlatformRole } from '../../platform/PlatformRoleContext'
import { puedeEditarPlat } from '../../platform/permisos'

interface UsuarioPlat {
  nombre: string
  email: string
  rol: 'Súper Admin' | 'Ventas' | 'Ingeniería'
  activo: boolean
}

const USUARIOS: UsuarioPlat[] = [
  { nombre: 'Emanuel Real',   email: 'emanuel@maily360.mx', rol: 'Súper Admin', activo: true },
  { nombre: 'Laura Campos',   email: 'laura@maily360.mx',   rol: 'Ventas',      activo: true },
  { nombre: 'Diego Fuentes',  email: 'diego@maily360.mx',   rol: 'Ingeniería',  activo: true },
  { nombre: 'Mariana Ruiz',   email: 'mariana@maily360.mx', rol: 'Ventas',      activo: false },
]

const ini = (n: string) => n.split(' ').slice(0, 2).map(w => w[0]).join('').toUpperCase()

export default function UsuariosPage() {
  const { role } = usePlatformRole()
  const editar = puedeEditarPlat(role, 'usuarios')

  return (
    <PlatformLayout active="usuarios">
      <div className="glass-card rounded-2xl px-6 py-5 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Equipo Maily</h1>
          <p className="text-sm text-gray-500">Usuarios internos de la plataforma</p>
        </div>
        {editar && (
          <button className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110"
            style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}>
            <Plus className="w-4 h-4" /> Invitar usuario
          </button>
        )}
      </div>

      <div className="glass-card rounded-2xl overflow-hidden">
        <div className="grid items-center px-6 py-3 text-xs font-semibold text-gray-500 border-b border-white/40"
          style={{ gridTemplateColumns: '2fr 2fr 1fr 1fr' }}>
          <span>Nombre</span><span>Correo</span><span>Rol</span><span>Estado</span>
        </div>
        {USUARIOS.map(u => (
          <div key={u.email} className="grid items-center px-6 py-3 border-b border-white/30"
            style={{ gridTemplateColumns: '2fr 2fr 1fr 1fr' }}>
            <span className="flex items-center gap-3 min-w-0">
              <span className="w-9 h-9 rounded-full flex items-center justify-center text-xs font-bold shrink-0"
                style={{ background: 'rgba(201,162,39,0.16)', color: '#B8860B' }}>{ini(u.nombre)}</span>
              <span className="text-sm font-medium text-gray-800 truncate">{u.nombre}</span>
            </span>
            <span className="text-sm text-gray-600 truncate">{u.email}</span>
            <span className="flex items-center gap-1.5 text-sm text-gray-600">
              <UserCog className="w-3.5 h-3.5 text-gray-400" /> {u.rol}
            </span>
            <span><span className={`badge ${u.activo ? 'badge-success' : 'badge-neutral'}`}>{u.activo ? 'Activo' : 'Inactivo'}</span></span>
          </div>
        ))}
      </div>
    </PlatformLayout>
  )
}
