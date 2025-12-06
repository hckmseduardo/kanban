/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL: string
  readonly VITE_PORTAL_API_URL: string
  readonly VITE_DOMAIN: string
  readonly VITE_PORT: string
  readonly VITE_TEAM_SLUG: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
