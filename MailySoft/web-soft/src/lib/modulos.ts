/**
 * Catálogo de módulos vendibles — ESPEJO de apps/core/modules.py.
 *
 * El backend es la AUTORIDAD: valida las dependencias y responde 400 si un plan
 * queda incoherente. Esto existe para que la interfaz del super-admin ajuste la
 * selección EN VIVO (desmarcar "Servicios" desmarca Paquetes y Cotizaciones
 * explicando por qué), en vez de dejar guardar y luego mostrar un error.
 *
 * Si MODULE_REQUIRES cambia en el backend, hay que sincronizarlo aquí.
 */

/** Slug de un módulo. Coincide con Module.values del backend. */
export type ModuloId =
  | 'agenda' | 'recordatorios' | 'expediente' | 'recetas' | 'notas'
  | 'servicios' | 'paquetes' | 'cotizaciones' | 'cobranza' | 'cfdi'
  | 'calendarizacion' | 'personal'

/** Nombre legible de cada módulo (copia de Module.labels). */
export const MODULO_LABEL: Record<ModuloId, string> = {
  agenda: 'Agenda y citas',
  recordatorios: 'Recordatorios de cita',
  expediente: 'Expediente clínico',
  recetas: 'Recetas',
  notas: 'Notas y tareas',
  servicios: 'Servicios y precios',
  paquetes: 'Paquetes',
  cotizaciones: 'Cotizaciones',
  cobranza: 'Cobranza y estado de cuenta',
  cfdi: 'Facturación CFDI',
  calendarizacion: 'Calendarización de tratamientos',
  personal: 'Gestión de personal',
}

/** Dependencias duras: encender la llave exige encender los valores. (MODULE_REQUIRES) */
export const MODULO_REQUIERE: Partial<Record<ModuloId, ModuloId[]>> = {
  recordatorios: ['agenda'],
  paquetes: ['servicios'],
  cotizaciones: ['servicios'],
  cfdi: ['cobranza'],
  calendarizacion: ['expediente', 'servicios', 'cotizaciones'],
}

/** Qué módulo hace útil a cada rol. (ROLE_REQUIRES) */
export const ROL_REQUIERE: Record<string, ModuloId[]> = {
  owner: [],
  admin: [],
  readonly: [],
  doctor: ['expediente'],
  nurse: ['expediente'],
  reception: ['agenda'],
  finance: ['cobranza'],
}

/** Agrupación para la interfaz del super-admin. (MODULE_GROUPS) */
export const MODULO_GRUPOS: { titulo: string; modulos: ModuloId[] }[] = [
  { titulo: 'Clínico', modulos: ['agenda', 'recordatorios', 'expediente', 'recetas', 'notas'] },
  { titulo: 'Comercial', modulos: ['servicios', 'paquetes', 'cotizaciones', 'cobranza', 'cfdi'] },
  { titulo: 'Especiales', modulos: ['calendarizacion'] },
  { titulo: 'Operación', modulos: ['personal'] },
]

/** Todos los slugs del catálogo. */
export const TODOS_LOS_MODULOS: ModuloId[] = MODULO_GRUPOS.flatMap(g => g.modulos)

/**
 * Agrega en cascada las dependencias de los módulos dados.
 * Ej. {calendarizacion} → {calendarizacion, expediente, servicios, cotizaciones}.
 */
export function expandirDependencias(modulos: ModuloId[]): ModuloId[] {
  const resultado = new Set<ModuloId>(modulos)
  const pendientes = [...resultado]
  while (pendientes.length) {
    const actual = pendientes.pop()!
    for (const requerido of MODULO_REQUIERE[actual] ?? []) {
      if (!resultado.has(requerido)) {
        resultado.add(requerido)
        pendientes.push(requerido)
      }
    }
  }
  return [...resultado]
}

/**
 * Módulos que dejan de tener sentido al apagar `quitado`, en cascada.
 * Ej. apagar "servicios" arrastra paquetes, cotizaciones y calendarización.
 */
export function dependientesDe(quitado: ModuloId, activos: ModuloId[]): ModuloId[] {
  const restantes = new Set(activos)
  restantes.delete(quitado)
  let cambio = true
  while (cambio) {
    cambio = false
    for (const m of [...restantes]) {
      const requiere = MODULO_REQUIERE[m] ?? []
      if (requiere.some(r => !restantes.has(r))) {
        restantes.delete(m)
        cambio = true
      }
    }
  }
  return activos.filter(m => m !== quitado && !restantes.has(m))
}

/** Roles asignables con estos módulos. Se derivan, no se configuran. */
export function rolesDisponibles(modulos: ModuloId[]): string[] {
  const activos = new Set(modulos)
  return Object.entries(ROL_REQUIERE)
    .filter(([, requeridos]) => requeridos.every(r => activos.has(r)))
    .map(([rol]) => rol)
}
