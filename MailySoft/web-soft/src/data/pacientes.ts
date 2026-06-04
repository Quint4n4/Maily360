export type Sexo = 'F' | 'M' | 'O'

export interface Paciente {
  id: string
  expediente: string
  firstName: string
  paternal: string
  maternal: string
  fechaNac: string        // ISO yyyy-mm-dd
  sexo: Sexo
  telefono: string
  email: string
  curp: string
  ultimaCita: string | null  // "12 may 2026"
  activo: boolean
  notas: string
}

export const SEXO_LABEL: Record<Sexo, string> = {
  F: 'Femenino',
  M: 'Masculino',
  O: 'Otro',
}

export const fullName = (p: Paciente) =>
  `${p.firstName} ${p.paternal} ${p.maternal}`.trim()

export const initials = (p: Paciente) =>
  `${p.firstName[0] ?? ''}${p.paternal[0] ?? ''}`.toUpperCase()

export const edad = (fechaNac: string) => {
  const [y, m, d] = fechaNac.split('-').map(Number)
  const hoy = new Date(2026, 5, 4)            // demo: 4 jun 2026
  let e = hoy.getFullYear() - y
  if (hoy.getMonth() + 1 < m || (hoy.getMonth() + 1 === m && hoy.getDate() < d)) e--
  return e
}

/* ─── Pacientes demo ─────────────────────────────────────────────────────── */
export const PACIENTES: Paciente[] = [
  { id: '1', expediente: 'EXP-0001', firstName: 'María',   paternal: 'González', maternal: 'Pérez',   fechaNac: '1990-03-12', sexo: 'F', telefono: '55 1234 5678', email: 'maria.gonzalez@correo.mx',  curp: 'GOPM900312MDFNRR04', ultimaCita: '28 may 2026', activo: true,  notas: 'Alérgica a penicilina.' },
  { id: '2', expediente: 'EXP-0002', firstName: 'Roberto', paternal: 'Sánchez',  maternal: 'Luna',    fechaNac: '1985-07-25', sexo: 'M', telefono: '55 2345 6789', email: 'roberto.sanchez@correo.mx', curp: 'SALR850725HDFNNB09', ultimaCita: '20 may 2026', activo: true,  notas: '' },
  { id: '3', expediente: 'EXP-0003', firstName: 'Lucía',   paternal: 'Ramírez',  maternal: 'Soto',    fechaNac: '1998-11-02', sexo: 'F', telefono: '55 3456 7890', email: 'lucia.ramirez@correo.mx',   curp: 'RASL981102MDFMTC01', ultimaCita: '02 jun 2026', activo: true,  notas: 'Primera vez.' },
  { id: '4', expediente: 'EXP-0004', firstName: 'Jorge',   paternal: 'Mendoza',  maternal: 'Ríos',    fechaNac: '1979-01-18', sexo: 'M', telefono: '55 4567 8901', email: 'jorge.mendoza@correo.mx',   curp: 'MERJ790118HDFNSR07', ultimaCita: '15 abr 2026', activo: true,  notas: 'Seguimiento de tratamiento.' },
  { id: '5', expediente: 'EXP-0005', firstName: 'Alondra', paternal: 'Reyes',    maternal: 'Benítez', fechaNac: '2001-06-30', sexo: 'F', telefono: '55 5678 9012', email: 'alondra.reyes@correo.mx',   curp: 'REBA010630MDFYNL03', ultimaCita: null,          activo: true,  notas: '' },
  { id: '6', expediente: 'EXP-0006', firstName: 'Carlos',  paternal: 'Hernández',maternal: 'Vega',    fechaNac: '1972-09-09', sexo: 'M', telefono: '55 6789 0123', email: 'carlos.hernandez@correo.mx',curp: 'HEVC720909HDFRGR05', ultimaCita: '10 mar 2026', activo: false, notas: 'Inactivo desde marzo.' },
  { id: '7', expediente: 'EXP-0007', firstName: 'Daniela', paternal: 'Torres',   maternal: 'Macías',  fechaNac: '1995-12-21', sexo: 'F', telefono: '55 7890 1234', email: 'daniela.torres@correo.mx',  curp: 'TOMD951221MDFRCN02', ultimaCita: '30 may 2026', activo: true,  notas: '' },
  { id: '8', expediente: 'EXP-0008', firstName: 'Andrés',  paternal: 'Flores',   maternal: 'Díaz',    fechaNac: '1988-04-04', sexo: 'M', telefono: '55 8901 2345', email: 'andres.flores@correo.mx',   curp: 'FODA880404HDFLRN08', ultimaCita: '18 may 2026', activo: true,  notas: '' },
]

/* Historial de citas demo por paciente (para el expediente) */
export const HISTORIAL: Record<string, { fecha: string; doctor: string; motivo: string; estado: 'Atendida' | 'Cancelada' | 'No asistió' }[]> = {
  '1': [
    { fecha: '28 may 2026', doctor: 'Dra. Martínez', motivo: 'Valoración',  estado: 'Atendida' },
    { fecha: '02 abr 2026', doctor: 'Dra. Martínez', motivo: 'Seguimiento', estado: 'Atendida' },
    { fecha: '15 feb 2026', doctor: 'Dr. Herrera',   motivo: 'Primera vez', estado: 'Cancelada' },
  ],
  '3': [
    { fecha: '02 jun 2026', doctor: 'Dra. Martínez', motivo: 'Primera vez', estado: 'Atendida' },
  ],
}
