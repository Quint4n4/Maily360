/**
 * http — cliente HTTP central. TODA llamada a la API pasa por aquí.
 *
 * Responsabilidades (no repetir esta lógica en otro lado):
 *   - Base URL desde VITE_API_URL (en dev: ruta relativa /api/v1 vía proxy Vite).
 *   - credentials: 'include' → las cookies (refresh httpOnly, csrftoken) viajan solas.
 *   - Authorization: Bearer <access> tomado del tokenStore (memoria).
 *   - X-CSRFToken en métodos mutantes (double-submit que exige el backend).
 *   - Refresh automático: ante un 401, intenta /auth/refresh/ UNA vez y reintenta
 *     la petición original. Si el refresh falla, limpia el token y propaga el 401.
 *   - Normaliza errores en ApiError (status + cuerpo) para que la UI los maneje igual.
 *
 * Regla de oro: el frontend NUNCA decide permisos. Si el backend responde 403,
 * es la autoridad — la UI solo refleja ese resultado.
 */

import { getCsrfToken } from './csrf'
import { clearAccessToken, getAccessToken, setAccessToken } from './tokenStore'
import type { ApiErrorBody, RefreshResponse } from '../types/api'

const BASE_URL: string = (import.meta.env.VITE_API_URL ?? '/api/v1').replace(/\/$/, '')

/** Ruta del refresh, relativa a BASE_URL. Se excluye del retry para evitar bucles. */
const REFRESH_PATH = '/auth/refresh/'

const MUTATING_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

/** Error normalizado de la API. La UI puede leer `status` y `body.detail`. */
export class ApiError extends Error {
  readonly status: number
  readonly body: ApiErrorBody | null

  constructor(status: number, body: ApiErrorBody | null, message?: string) {
    super(message ?? deriveMessage(status, body))
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }

  /** true si el error es de red (sin respuesta del servidor). */
  get isNetwork(): boolean {
    return this.status === 0
  }
}

function deriveMessage(status: number, body: ApiErrorBody | null): string {
  if (status === 0) return 'No se pudo conectar con el servidor.'
  if (body?.detail) return body.detail
  return `Error ${status}`
}

export interface RequestOptions {
  method?: string
  /** Cuerpo a serializar como JSON. */
  body?: unknown
  /** Headers extra. */
  headers?: Record<string, string>
  /** Para cancelar la petición. */
  signal?: AbortSignal
  /** Uso interno: no intentar refresh+retry ante 401 (evita recursión). */
  skipAuthRefresh?: boolean
}

/** Promesa de refresh compartida: si varias peticiones dan 401 a la vez, refrescamos UNA sola vez. */
let refreshInFlight: Promise<boolean> | null = null

function ensureRefresh(): Promise<boolean> {
  if (refreshInFlight === null) {
    refreshInFlight = runRefresh().finally(() => {
      refreshInFlight = null
    })
  }
  return refreshInFlight
}

/**
 * Intenta renovar el access token usando la cookie httpOnly de refresh.
 * Nunca lanza: devuelve true si renovó, false si no hay sesión válida.
 */
async function runRefresh(): Promise<boolean> {
  try {
    const data = await request<RefreshResponse>(REFRESH_PATH, {
      method: 'POST',
      skipAuthRefresh: true,
    })
    if (data?.access) {
      setAccessToken(data.access)
      return true
    }
    clearAccessToken()
    return false
  } catch {
    clearAccessToken()
    return false
  }
}

async function doFetch(path: string, options: RequestOptions): Promise<Response> {
  const method = (options.method ?? 'GET').toUpperCase()
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...options.headers,
  }

  const accessToken = getAccessToken()
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`

  let body: BodyInit | undefined
  if (options.body instanceof FormData) {
    // multipart: NO fijamos Content-Type; el navegador pone el boundary correcto.
    body = options.body
  } else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }

  if (MUTATING_METHODS.has(method)) {
    const csrf = getCsrfToken()
    if (csrf) headers['X-CSRFToken'] = csrf
  }

  return fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    body,
    credentials: 'include',
    signal: options.signal,
  })
}

async function parseBody(response: Response): Promise<unknown> {
  // 204/205 o sin contenido → nada que parsear.
  if (response.status === 204 || response.status === 205) return undefined
  const text = await response.text()
  if (!text) return undefined
  const contentType = response.headers.get('content-type') ?? ''
  if (contentType.includes('application/json')) {
    try {
      return JSON.parse(text)
    } catch {
      return text
    }
  }
  return text
}

/**
 * Hace la petición (vía doFetch) y, ante un 401, intenta refrescar el access
 * token UNA vez y reintenta. Devuelve la Response cruda (sin parsear el cuerpo),
 * para que tanto `request` (JSON) como `requestBlob` (binario) la compartan.
 * Traduce errores de red a ApiError(0); propaga AbortError tal cual.
 */
async function fetchWithRefresh(path: string, options: RequestOptions): Promise<Response> {
  let response: Response
  try {
    response = await doFetch(path, options)
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError(0, null)
  }

  // Refresh automático ante 401 (una sola vez, salvo en el propio refresh).
  if (response.status === 401 && !options.skipAuthRefresh && path !== REFRESH_PATH) {
    const refreshed = await ensureRefresh()
    if (refreshed) {
      try {
        response = await doFetch(path, { ...options, skipAuthRefresh: true })
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') throw err
        throw new ApiError(0, null)
      }
    }
  }

  return response
}

/**
 * Realiza una petición a la API y devuelve el cuerpo tipado.
 * Lanza ApiError si la respuesta no es OK (incluido 401 tras refresh fallido).
 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await fetchWithRefresh(path, options)

  const parsed = await parseBody(response)

  if (!response.ok) {
    const errorBody = (parsed && typeof parsed === 'object' ? parsed : null) as ApiErrorBody | null
    throw new ApiError(response.status, errorBody)
  }

  return parsed as T
}

/**
 * Descarga un recurso binario protegido (ej. el PDF de una receta) como Blob.
 *
 * Por qué existe: el PDF requiere `Authorization: Bearer <access>`, que vive solo
 * en memoria (tokenStore). Un `<a href>` directo NO lleva ese header, así que el
 * servidor respondería 401. Aquí pasamos por el mismo flujo central (Bearer +
 * refresh automático) y devolvemos el Blob para abrirlo/descargarlo con un
 * object URL temporal.
 *
 * Ante error, intenta leer el cuerpo (puede ser JSON con `detail` o texto plano)
 * para construir un ApiError legible, igual que `request`.
 */
export async function requestBlob(path: string, options: RequestOptions = {}): Promise<Blob> {
  const response = await fetchWithRefresh(path, options)

  if (!response.ok) {
    // El error puede venir como JSON ({detail}) o como texto plano; reusamos parseBody.
    const parsed = await parseBody(response)
    const errorBody = (parsed && typeof parsed === 'object' ? parsed : null) as ApiErrorBody | null
    throw new ApiError(response.status, errorBody)
  }

  return response.blob()
}

/**
 * Parámetros de query string para `http.get`. Los valores undefined/null/'' se omiten.
 *
 * Se acepta cualquier objeto cuyos valores sean primitivos serializables (string,
 * number, boolean, null, undefined). Es estructural a propósito para que interfaces
 * concretas (DateRangeParams, etc.) se puedan pasar sin un index signature explícito.
 */
export type QueryValue = string | number | boolean | null | undefined
export type QueryParams = Record<string, QueryValue>

function withQuery(path: string, params?: Record<string, unknown>): string {
  if (!params) return path
  const qs = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') {
      qs.set(key, String(value))
    }
  }
  const suffix = qs.toString()
  if (!suffix) return path
  return path.includes('?') ? `${path}&${suffix}` : `${path}?${suffix}`
}

/**
 * Cliente HTTP de conveniencia (verbos REST) construido sobre `request`.
 *
 * Comparte exactamente el mismo pipeline central (Bearer + CSRF + refresh
 * automático ante 401). `get` serializa el segundo argumento como query string;
 * `post`/`patch`/`put` lo envían como cuerpo JSON.
 */
export const http = {
  get<T>(path: string, params?: Record<string, QueryValue> | object): Promise<T> {
    return request<T>(withQuery(path, params as Record<string, unknown> | undefined), {
      method: 'GET',
    })
  },
  post<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, { method: 'POST', body })
  },
  patch<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, { method: 'PATCH', body })
  },
  put<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, { method: 'PUT', body })
  },
  delete<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, { method: 'DELETE', body })
  },
}
