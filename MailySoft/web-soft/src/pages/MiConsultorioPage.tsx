import { useState } from 'react'
import { BadgeCheck, Building, Building2, Clock, DollarSign, FileText, FlaskConical, GraduationCap, LayoutTemplate, ListChecks, ScrollText, Tag, Users } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import Topbar from '../components/Topbar'
import { useRole } from '../auth/RoleContext'
import {
  puedeEditarPlantillas,
  puedeGestionarConsultorio,
} from '../auth/permisos'
import SeccionDatosClinica from '../components/consultorio/SeccionDatosClinica'
import SeccionPlantillas from '../components/consultorio/SeccionPlantillas'
import SeccionCategorias from '../components/consultorio/SeccionCategorias'
import SeccionServicios from '../components/consultorio/SeccionServicios'
import SeccionPerfilMedico from '../components/consultorio/SeccionPerfilMedico'
import SeccionFormatos from '../components/consultorio/SeccionFormatos'
import SeccionCredencialesValidar from '../components/consultorio/SeccionCredencialesValidar'
import SeccionHistoriaClinica from '../components/consultorio/SeccionHistoriaClinica'
import SeccionPlantillasDocumento from '../components/consultorio/SeccionPlantillasDocumento'
import SeccionAnalitos from '../components/consultorio/SeccionAnalitos'
import SeccionEquipo from '../components/consultorio/SeccionEquipo'
import SeccionSucursales from '../components/consultorio/SeccionSucursales'
import SeccionHorarioAgenda from '../components/consultorio/SeccionHorarioAgenda'

type SeccionKey =
  | 'datos' | 'sucursales' | 'horario-agenda' | 'formatos' | 'plantillas' | 'categorias' | 'servicios'
  | 'plantillas-documento' | 'analitos' | 'equipo'
  | 'historia-clinica' | 'validar-credenciales' | 'perfil'

interface SeccionDef {
  key: SeccionKey
  label: string
  icon: LucideIcon
}

const SECCIONES: SeccionDef[] = [
  { key: 'datos', label: 'Datos de la clínica', icon: Building2 },
  { key: 'sucursales', label: 'Sucursales', icon: Building },
  { key: 'horario-agenda', label: 'Horario de la agenda', icon: Clock },
  { key: 'formatos', label: 'Configuración de recetas', icon: LayoutTemplate },
  { key: 'plantillas', label: 'Plantillas', icon: FileText },
  { key: 'categorias', label: 'Categorías de pacientes', icon: Tag },
  { key: 'servicios', label: 'Servicios y precios', icon: DollarSign },
  { key: 'plantillas-documento', label: 'Plantillas de documento', icon: ScrollText },
  { key: 'analitos', label: 'Catálogo de analitos', icon: FlaskConical },
  { key: 'equipo', label: 'Equipo / departamentos', icon: Users },
  { key: 'historia-clinica', label: 'Preguntas de historia clínica', icon: ListChecks },
  { key: 'validar-credenciales', label: 'Credenciales por validar', icon: BadgeCheck },
  { key: 'perfil', label: 'Mi perfil médico', icon: GraduationCap },
]

/** Página "Mi Consultorio": configuración de la clínica por secciones. */
export default function MiConsultorioPage() {
  const { role } = useRole()
  const [seccion, setSeccion] = useState<SeccionKey>('datos')

  const gestionable = puedeGestionarConsultorio(role) // datos, recetas, categorías
  const editaPlantillas = puedeEditarPlantillas(role)
  // Multi-sede (2026-07-16): lo que el admin NO puede tocar tampoco le aparece
  // en el menú (el backend es la autoridad, responde 403). SUCURSALES y
  // SERVICIOS/PRECIOS son dominio EXCLUSIVO del dueño. "Mi perfil médico" es de
  // quien atiende (dueño o médico) — un administrador puro no tiene perfil médico.
  const esOwner = role === 'owner'
  const editaPerfil = role === 'owner' || role === 'doctor'

  const titulo = SECCIONES.find((s) => s.key === seccion)?.label ?? ''

  const renderSeccion = () => {
    switch (seccion) {
      case 'datos':
        return <SeccionDatosClinica editable={gestionable} />
      case 'sucursales':
        return <SeccionSucursales editable={esOwner} />
      case 'horario-agenda':
        return <SeccionHorarioAgenda editable={gestionable} />
      case 'formatos':
        return <SeccionFormatos editable={gestionable} />
      case 'plantillas':
        return <SeccionPlantillas editable={editaPlantillas} />
      case 'categorias':
        return <SeccionCategorias editable={gestionable} />
      case 'servicios':
        return <SeccionServicios editable={esOwner} />
      case 'plantillas-documento':
        return <SeccionPlantillasDocumento editable={gestionable} />
      case 'analitos':
        return <SeccionAnalitos editable={gestionable} />
      case 'equipo':
        return <SeccionEquipo editable={gestionable} />
      case 'historia-clinica':
        return <SeccionHistoriaClinica editable={gestionable} />
      case 'validar-credenciales':
        return <SeccionCredencialesValidar editable={gestionable} />
      case 'perfil':
        return editaPerfil ? <SeccionPerfilMedico /> : null
    }
  }

  // Solo el DUEÑO: sucursales y servicios/precios (ni siquiera aparecen al admin).
  const soloDueno: SeccionKey[] = ['sucursales', 'servicios']
  // Gestión reservada a owner/admin (el backend es la autoridad):
  // credenciales, historia clínica, plantillas de documento, analitos y equipo.
  const soloGestion: SeccionKey[] = [
    'horario-agenda', 'validar-credenciales', 'historia-clinica', 'plantillas-documento', 'analitos', 'equipo',
  ]
  const seccionesVisibles = SECCIONES.filter((s) => {
    if (s.key === 'perfil') return editaPerfil
    if (soloDueno.includes(s.key)) return esOwner
    if (soloGestion.includes(s.key)) return gestionable
    return true
  })

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
