export interface Doctor {
  id: string
  nombre: string
  email: string
  especialidad: string
  cedula: string
  duracion: number     // minutos (duración default de cita)
  bio: string
  activo: boolean
}

export interface Consultorio {
  id: string
  name: string
  location: string
  color: string
  activo: boolean
}

export interface Horario {
  dia: string          // "Lunes"
  inicio: string       // "09:00"
  fin: string          // "14:00"
  consultorio: string  // "Consultorio 1"
}

export const initialesDoctor = (nombre: string) =>
  nombre.replace(/^(Dr|Dra)\.?\s*/i, '').split(' ').slice(0, 2).map(w => w[0]).join('').toUpperCase()

/* ─── Doctores demo ──────────────────────────────────────────────────────── */
export const DOCTORES: Doctor[] = [
  { id: '1', nombre: 'Dra. Laura Martínez', email: 'laura.martinez@maily360.mx', especialidad: 'Medicina regenerativa', cedula: '7654321', duracion: 60, bio: 'Especialista en terapias regenerativas con 12 años de experiencia.', activo: true },
  { id: '2', nombre: 'Dr. Carlos Herrera',  email: 'carlos.herrera@maily360.mx', especialidad: 'Ortopedia regenerativa', cedula: '8765432', duracion: 45, bio: 'Enfoque en regeneración articular y terapia con PRP.', activo: true },
  { id: '3', nombre: 'Dra. Sofía Ramírez',  email: 'sofia.ramirez@maily360.mx',  especialidad: 'Dermatología',          cedula: '9876543', duracion: 30, bio: '', activo: false },
]

/* ─── Consultorios demo ──────────────────────────────────────────────────── */
export const CONSULTORIOS_DATA: Consultorio[] = [
  { id: '1', name: 'Consultorio 1', location: 'Planta baja, ala norte', color: '#C9A227', activo: true },
  { id: '2', name: 'Consultorio 2', location: 'Primer piso',            color: '#3A6EA5', activo: true },
  { id: '3', name: 'Consultorio 3', location: 'Primer piso, ala sur',   color: '#2E7D5B', activo: true },
]

/* ─── Horarios por doctor (DoctorSchedule) ───────────────────────────────── */
export const HORARIOS: Record<string, Horario[]> = {
  '1': [
    { dia: 'Lunes',     inicio: '09:00', fin: '14:00', consultorio: 'Consultorio 1' },
    { dia: 'Miércoles', inicio: '09:00', fin: '14:00', consultorio: 'Consultorio 1' },
    { dia: 'Viernes',   inicio: '10:00', fin: '15:00', consultorio: 'Consultorio 2' },
  ],
  '2': [
    { dia: 'Martes', inicio: '08:00', fin: '13:00', consultorio: 'Consultorio 3' },
    { dia: 'Jueves', inicio: '08:00', fin: '13:00', consultorio: 'Consultorio 3' },
  ],
  '3': [],
}
