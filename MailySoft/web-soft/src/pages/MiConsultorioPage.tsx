import { useState } from 'react'
import { Building2, FileText, GraduationCap, Printer, ScrollText, Tag } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import Topbar from '../components/Topbar'
import { useRole } from '../auth/RoleContext'
import {
  puedeEditarPlantillas,
  puedeGestionarConsultorio,
  puedeGestionarPerfilMedico,
} from '../auth/permisos'
import SeccionDatosClinica from '../components/consultorio/SeccionDatosClinica'
import SeccionMembrete from '../components/consultorio/SeccionMembrete'
import SeccionRecetas from '../components/consultorio/SeccionRecetas'
import SeccionPlantillas from '../components/consultorio/SeccionPlantillas'
import SeccionCategorias from '../components/consultorio/SeccionCategorias'
import SeccionPerfilMedico from '../components/consultorio/SeccionPerfilMedico'

type SeccionKey = 'datos' | 'membrete' | 'recetas' | 'plantillas' | 'categorias' | 'perfil'

interface SeccionDef {
  key: SeccionKey
  label: string
  icon: LucideIcon
}

const SECCIONES: SeccionDef[] = [
  { key: 'datos', label: 'Datos de la clínica', icon: Building2 },
  { key: 'membrete', label: 'Membrete', icon: Printer },
  { key: 'recetas', label: 'Recetas', icon: ScrollText },
  { key: 'plantillas', label: 'Plantillas', icon: FileText },
  { key: 'categorias', label: 'Categorías de pacientes', icon: Tag },
  { key: 'perfil', label: 'Mi perfil médico', icon: GraduationCap },
]

/** Página "Mi Consultorio": configuración de la clínica por secciones. */
export default function MiConsultorioPage() {
  const { role } = useRole()
  const [seccion, setSeccion] = useState<SeccionKey>('datos')

  const gestionable = puedeGestionarConsultorio(role) // datos, membrete, recetas, categorías
  const editaPlantillas = puedeEditarPlantillas(role)
  const editaPerfil = puedeGestionarPerfilMedico(role)

  const titulo = SECCIONES.find((s) => s.key === seccion)?.label ?? ''

  const renderSeccion = () => {
    switch (seccion) {
      case 'datos':
        return <SeccionDatosClinica editable={gestionable} />
      case 'membrete':
        return <SeccionMembrete editable={gestionable} />
      case 'recetas':
        return <SeccionRecetas editable={gestionable} />
      case 'plantillas':
        return <SeccionPlantillas editable={editaPlantillas} />
      case 'categorias':
        return <SeccionCategorias editable={gestionable} />
      case 'perfil':
        return editaPerfil ? <SeccionPerfilMedico /> : null
    }
  }

  // El perfil médico solo aparece para owner/admin/doctor.
  const seccionesVisibles = SECCIONES.filter((s) => s.key !== 'perfil' || editaPerfil)

  return (
    <div className="min-h-screen relative">
      {/* Fondo */}
      <div className="fixed inset-0 -z-10" style={{ background: 'linear-gradient(135deg, #b89a52 0%, #d8c690 45%, #f1e8cf 100%)' }} />
      <div className="fixed inset-0 -z-10 bg-cover bg-center" style={{ backgroundImage: "url('/fondo-agenda.jpg')" }} />
      <div className="fixed inset-0 -z-10" style={{ background: 'rgba(255,255,255,0.20)' }} />

      <Topbar />

      <div className="p-5 max-w-[1300px] mx-auto">
        <div className="mb-5">
          <h1 className="text-2xl font-bold" style={{ color: '#2A241B' }}>Mi Consultorio</h1>
          <p className="text-sm" style={{ color: '#6B6459' }}>Configura los datos, documentos y perfil de tu clínica.</p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-[260px_1fr] gap-5">
          {/* Navegación lateral */}
          <nav className="glass-card rounded-2xl p-2 h-fit lg:sticky lg:top-20">
            {seccionesVisibles.map(({ key, label, icon: Icon }) => {
              const activo = key === seccion
              return (
                <button
                  key={key}
                  onClick={() => setSeccion(key)}
                  className="w-full flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm font-medium transition-colors mb-0.5"
                  style={{
                    background: activo ? 'rgba(201,162,39,0.16)' : 'transparent',
                    color: activo ? '#B8860B' : '#6B6459',
                  }}
                >
                  <Icon className="w-4 h-4 shrink-0" />
                  <span className="text-left">{label}</span>
                </button>
              )
            })}
          </nav>

          {/* Contenido de la sección */}
          <section className="glass-card rounded-2xl p-6">
            <h2 className="text-lg font-semibold text-gray-800 mb-5">{titulo}</h2>
            {renderSeccion()}
          </section>
        </div>
      </div>
    </div>
  )
}
