/**
 * sucursalStore — único lugar que toca el storage de la SUCURSAL ACTIVA.
 *
 * Por qué existe: la sucursal activa la necesitan DOS capas que no comparten
 * React state — el cliente http central (para mandar `X-Sucursal-Id`) y el
 * SucursalContext (UI). Centralizar la clave y el acceso aquí evita duplicar el
 * string `maily.sucursal` y mantiene ambas capas sincronizadas.
 *
 * Fase 3 (finanzas por sucursal) añade una tercera opción: "Todas las
 * sucursales" (consolidado). Se persiste con un CENTINELA (`__todas__`) en la
 * misma clave, lo que permite distinguir tres estados:
 *
 *   - `{ modo: 'sede', id }` → sede concreta: el http manda `X-Sucursal-Id`.
 *   - `{ modo: 'todas' }`    → consolidado: el http NO manda el header, y el
 *                              backend filtra a las sedes PERMITIDAS del usuario
 *                              (dueño → todas; admin de sede → solo la suya).
 *   - `null`                 → sin elección persistida (primer arranque).
 *
 * A diferencia del access token, la sucursal activa NO es un secreto: es solo un
 * identificador de sede que persiste la preferencia del usuario entre recargas.
 * Por eso vive en localStorage (defensivo: si no está disponible, no rompe).
 */

const STORAGE_KEY = 'maily.sucursal'

/** Valor persistido que representa "Todas las sucursales" (consolidado). */
const TODAS = '__todas__'

/** Elección de sede del usuario, tal como se persiste. */
export type SeleccionSucursal = { modo: 'sede'; id: string } | { modo: 'todas' } | null

/** Suscriptores notificados cuando la selección de sucursal cambia (re-sync http/UI). */
const listeners = new Set<(seleccion: SeleccionSucursal) => void>()

/** Lee el valor crudo del storage (defensivo: sin storage → null). */
function leerCrudo(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

/** Lee la selección persistida: sede concreta, "todas", o null si no hay. */
export function getSeleccionSucursal(): SeleccionSucursal {
  const raw = leerCrudo()
  if (raw === null) return null
  if (raw === TODAS) return { modo: 'todas' }
  return { modo: 'sede', id: raw }
}

/**
 * Id de la sucursal activa para el cliente http. Es null cuando la selección es
 * "todas" (o no hay elección) → en ese caso NO se manda `X-Sucursal-Id` y es el
 * backend quien consolida sobre las sedes permitidas del usuario.
 */
export function getActiveSucursalId(): string | null {
  const sel = getSeleccionSucursal()
  return sel !== null && sel.modo === 'sede' ? sel.id : null
}

/** true si la selección persistida es "Todas las sucursales" (consolidado). */
export function esTodasSucursales(): boolean {
  const sel = getSeleccionSucursal()
  return sel !== null && sel.modo === 'todas'
}

/** Persiste la selección (o la borra con null) y notifica a los suscriptores. */
export function setSeleccionSucursal(seleccion: SeleccionSucursal): void {
  try {
    if (seleccion === null) window.localStorage.removeItem(STORAGE_KEY)
    else if (seleccion.modo === 'todas') window.localStorage.setItem(STORAGE_KEY, TODAS)
    else window.localStorage.setItem(STORAGE_KEY, seleccion.id)
  } catch {
    // Sin storage disponible: seguimos notificando para que la UI reaccione.
  }
  for (const listener of listeners) listener(seleccion)
}

/**
 * Persiste una SEDE concreta (o borra la elección con null). Azúcar sobre
 * setSeleccionSucursal para los llamadores que solo manejan ids.
 */
export function setActiveSucursalId(id: string | null): void {
  setSeleccionSucursal(id === null ? null : { modo: 'sede', id })
}

/** Suscríbete a los cambios de selección. Devuelve la función para cancelar. */
export function onActiveSucursalChange(
  listener: (seleccion: SeleccionSucursal) => void,
): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}
