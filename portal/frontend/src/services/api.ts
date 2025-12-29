import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || 'https://api.localhost:4443'

console.log('[API] Initializing with base URL:', API_URL)

// Flag to prevent redirect during navigation
let isNavigatingAway = false

export const setNavigatingAway = () => {
  isNavigatingAway = true
}

export const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Add auth token to requests
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  console.log('[API Request]', config.method?.toUpperCase(), config.url, '| Token:', token ? 'present' : 'MISSING')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Handle auth errors
api.interceptors.response.use(
  (response) => {
    console.log('[API Response]', response.status, response.config.url)
    return response
  },
  (error) => {
    console.error('[API Error]', error.response?.status, error.config?.url, error.message)
    if (error.response?.status === 401) {
      console.error('[API] 401 Unauthorized detected')
      // Don't redirect if we're already navigating away (e.g., to team subdomain)
      if (isNavigatingAway) {
        console.log('[API] Navigation in progress - skipping redirect to login')
        return Promise.reject(error)
      }
      console.error('[API] Redirecting to login')
      localStorage.removeItem('token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// API functions
export const teamsApi = {
  list: () => api.get('/teams'),
  get: (slug: string) => api.get(`/teams/${slug}`),
  create: (data: { name: string; slug: string; description?: string }) =>
    api.post('/teams', data),
  update: (slug: string, data: { name?: string; description?: string }) =>
    api.put(`/teams/${slug}`, data),
  delete: (slug: string) => api.delete(`/teams/${slug}`),
  getMembers: (slug: string) => api.get(`/teams/${slug}/members`),
}

export const tasksApi = {
  list: (status?: string) =>
    api.get('/tasks', { params: { status } }),
  get: (id: string) => api.get(`/tasks/${id}`),
  retry: (id: string) => api.post(`/tasks/${id}/retry`),
  cancel: (id: string) => api.post(`/tasks/${id}/cancel`),
  stats: () => api.get('/tasks/stats/summary'),
}

export const usersApi = {
  me: () => api.get('/users/me'),
  update: (data: { display_name?: string; avatar_url?: string }) =>
    api.put('/users/me', data),
  teams: () => api.get('/users/me/teams'),
}

export const authApi = {
  getCrossDomainToken: (teamSlug: string, userId: string) =>
    api.get('/auth/cross-domain-token', { params: { team_slug: teamSlug, user_id: userId } }),
}

export interface ApiToken {
  id: string
  team_id: string
  name: string
  scopes: string[]
  created_by: string
  created_at: string
  expires_at: string | null
  last_used_at: string | null
  is_active: boolean
}

export interface CreateApiTokenRequest {
  name: string
  scopes?: string[]
  expires_in_days?: number
}

export interface CreateApiTokenResponse {
  token: ApiToken
  plaintext_token: string
}

export const apiTokensApi = {
  list: (slug: string) =>
    api.get<ApiToken[]>(`/teams/${slug}/api-tokens`),
  create: (slug: string, data: CreateApiTokenRequest) =>
    api.post<CreateApiTokenResponse>(`/teams/${slug}/api-tokens`, data),
  delete: (slug: string, tokenId: string) =>
    api.delete(`/teams/${slug}/api-tokens/${tokenId}`),
}

// Portal API Tokens (for programmatic portal access)
export interface PortalApiToken {
  id: string
  name: string
  scopes: string[]
  created_by: string
  created_at: string
  expires_at: string | null
  last_used_at: string | null
  is_active: boolean
}

export interface CreatePortalApiTokenRequest {
  name: string
  scopes?: string[]
}

export interface CreatePortalApiTokenResponse extends PortalApiToken {
  token: string // Only returned on creation
}

export const portalApiTokensApi = {
  list: () =>
    api.get<PortalApiToken[]>('/api/tokens'),
  create: (data: CreatePortalApiTokenRequest) =>
    api.post<CreatePortalApiTokenResponse>('/api/tokens', data),
  delete: (tokenId: string) =>
    api.delete(`/api/tokens/${tokenId}`),
}
