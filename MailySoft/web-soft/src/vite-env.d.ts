/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** URL base de la API (en dev: '/api/v1' vía proxy de Vite). */
  readonly VITE_API_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
