export type EstadoClinica = 'active' | 'trial' | 'suspended'

export interface Clinica {
  id: string
  nombre: string
  ciudad: string
  plan: 'Básico' | 'Pro' | 'Premium'
  estado: EstadoClinica
  usuarios: number
  pacientes: number
  ingresoMensual: number   // MXN
  desde: string
}

export const ESTADO_CLINICA: Record<EstadoClinica, { label: string; badge: string }> = {
  active:    { label: 'Activa',     badge: 'badge-success' },
  trial:     { label: 'En prueba',  badge: 'badge-warning' },
  suspended: { label: 'Suspendida', badge: 'badge-danger' },
}

export const CLINICAS: Clinica[] = [
  { id: '1', nombre: 'Clínica Regenera',        ciudad: 'CDMX',         plan: 'Premium', estado: 'active',    usuarios: 12, pacientes: 2400, ingresoMensual: 8900, desde: 'Ene 2025' },
  { id: '2', nombre: 'Bienestar Médico',        ciudad: 'Guadalajara',  plan: 'Pro',     estado: 'active',    usuarios: 7,  pacientes: 980,  ingresoMensual: 4500, desde: 'Mar 2025' },
  { id: '3', nombre: 'Clínica Dental Martínez', ciudad: 'Monterrey',    plan: 'Pro',     estado: 'active',    usuarios: 5,  pacientes: 1320, ingresoMensual: 4500, desde: 'Nov 2024' },
  { id: '4', nombre: 'Vida Estética',           ciudad: 'Puebla',       plan: 'Básico',  estado: 'trial',     usuarios: 3,  pacientes: 120,  ingresoMensual: 0,    desde: 'May 2026' },
  { id: '5', nombre: 'Ortopedia Integral',      ciudad: 'Querétaro',    plan: 'Pro',     estado: 'trial',     usuarios: 4,  pacientes: 60,   ingresoMensual: 0,    desde: 'May 2026' },
  { id: '6', nombre: 'Centro Médico del Valle', ciudad: 'CDMX',         plan: 'Básico',  estado: 'suspended', usuarios: 2,  pacientes: 540,  ingresoMensual: 0,    desde: 'Ago 2024' },
]

export const mxn = (n: number) =>
  n.toLocaleString('es-MX', { style: 'currency', currency: 'MXN', minimumFractionDigits: 0 })
