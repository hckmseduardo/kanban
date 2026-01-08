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
      // Preserve current URL as returnTo so user returns here after login
      const currentPath = window.location.pathname + window.location.search
      const loginUrl = currentPath && currentPath !== '/' && currentPath !== '/login'
        ? `/login?returnTo=${encodeURIComponent(currentPath)}`
        : '/login'
      window.location.href = loginUrl
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
  restart: (slug: string, rebuild: boolean = false) =>
    api.post(`/teams/${slug}/restart`, { rebuild }),
  start: (slug: string) => api.post(`/teams/${slug}/start`),
  getStatus: (slug: string) => api.get(`/teams/${slug}/status`),
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
    api.get<PortalApiToken[]>('portal/tokens'),
  create: (data: CreatePortalApiTokenRequest) =>
    api.post<CreatePortalApiTokenResponse>('portal/tokens', data),
  delete: (tokenId: string) =>
    api.delete(`portal/tokens/${tokenId}`),
}

// Workspace Types
export interface AppTemplate {
  id: string
  slug: string
  name: string
  description: string
  github_template_owner: string
  github_template_repo: string
  active: boolean
  created_at: string
}

export interface Workspace {
  id: string
  slug: string
  name: string
  description: string | null
  user_role: 'owner' | 'admin' | 'member' | 'viewer' | null
  kanban_team_id: string | null
  kanban_subdomain: string
  app_template_id: string | null
  app_template_slug: string | null
  github_repo_url: string | null
  github_repo_name: string | null
  app_subdomain: string | null
  app_database_name: string | null
  status: 'provisioning' | 'active' | 'suspended' | 'deleted'
  created_at: string
  provisioned_at: string | null
}

export interface CreateWorkspaceRequest {
  name: string
  slug: string
  description?: string
  app_template_slug?: string
  github_org?: string
}

export interface Sandbox {
  id: string
  workspace_id: string
  slug: string
  full_slug: string
  name: string
  description: string | null
  owner_id: string
  git_branch: string
  source_branch: string
  subdomain: string
  database_name: string
  agent_container_name: string
  agent_webhook_url: string
  agent_webhook_secret: string | null
  status: 'provisioning' | 'active' | 'deleted'
  created_at: string
  provisioned_at: string | null
}

export interface CreateSandboxRequest {
  name: string
  slug: string
  description?: string
  source_branch?: string
}

// Workspace Member Types
export interface WorkspaceMember {
  user_id: string
  email: string
  name: string | null
  role: 'owner' | 'admin' | 'member' | 'viewer'
  joined_at: string | null
}

export interface InviteMemberRequest {
  email: string
  role: 'admin' | 'member' | 'viewer'
}

export interface UpdateWorkspaceMemberRequest {
  role: 'admin' | 'member' | 'viewer'
}

// Workspace Invitation Types
export interface WorkspaceInvitation {
  id: string
  workspace_id: string
  email: string
  role: 'admin' | 'member' | 'viewer'
  status: 'pending' | 'accepted' | 'cancelled' | 'expired'
  invite_url: string
  invited_by: string
  created_at: string
  expires_at: string
}

export interface InvitationInfo {
  workspace_name: string
  workspace_slug: string
  email: string
  role: string
  status: string
  invited_by: string
  expires_at: string
}

// Workspace Health Types
export interface SandboxHealthStatus {
  slug: string
  full_slug: string
  running: boolean
}

export interface WorkspaceHealth {
  workspace_id: string
  workspace_slug: string
  kanban_running: boolean
  app_running: boolean | null
  sandboxes: SandboxHealthStatus[]
  all_healthy: boolean
}

export interface WorkspaceHealthBatch {
  workspaces: Record<string, WorkspaceHealth>
}

// App Templates API
export const appTemplatesApi = {
  list: () => api.get<{ templates: AppTemplate[]; total: number }>('/app-templates'),
  get: (slug: string) => api.get<AppTemplate>(`/app-templates/${slug}`),
}

// Workspaces API
export const workspacesApi = {
  list: () => api.get<{ workspaces: Workspace[]; total: number }>('/workspaces'),
  get: (slug: string) => api.get<Workspace>(`/workspaces/${slug}`),
  create: (data: CreateWorkspaceRequest) =>
    api.post<{ message: string; workspace: Workspace; task_id: string }>('/workspaces', data),
  delete: (slug: string) =>
    api.delete<{ message: string; task_id: string }>(`/workspaces/${slug}`),
  restart: (slug: string, options?: { rebuild?: boolean; restart_app?: boolean }) =>
    api.post<{ message: string; task_id: string; rebuild: boolean; restart_app: boolean }>(
      `/workspaces/${slug}/restart`,
      options || {}
    ),
  start: (slug: string) =>
    api.post<{ message: string; task_id: string }>(`/workspaces/${slug}/start`),
  startKanban: (slug: string) =>
    api.post<{ message: string; task_id: string }>(`/workspaces/${slug}/start-kanban`),
  getStatus: (slug: string) => api.get(`/workspaces/${slug}/status`),
  getHealth: (slug: string) => api.get<WorkspaceHealth>(`/workspaces/${slug}/health`),
  getHealthBatch: () => api.get<WorkspaceHealthBatch>('/workspaces/health/batch'),
  // Member management
  getMembers: (slug: string) =>
    api.get<{ members: WorkspaceMember[]; total: number }>(`/workspaces/${slug}/members`),
  inviteMember: (slug: string, data: InviteMemberRequest) =>
    api.post<WorkspaceInvitation>(`/workspaces/${slug}/members`, data),
  updateMember: (slug: string, userId: string, data: UpdateWorkspaceMemberRequest) =>
    api.patch<WorkspaceMember>(`/workspaces/${slug}/members/${userId}`, data),
  removeMember: (slug: string, userId: string) =>
    api.delete<{ message: string }>(`/workspaces/${slug}/members/${userId}`),
  // Invitation management
  getInvitations: (slug: string, status?: string) =>
    api.get<{ invitations: WorkspaceInvitation[]; total: number }>(
      `/workspaces/${slug}/invitations`,
      { params: status ? { status } : undefined }
    ),
  cancelInvitation: (slug: string, invitationId: string) =>
    api.delete<{ message: string }>(`/workspaces/${slug}/invitations/${invitationId}`),
}

// Invitation acceptance API (public routes)
export const invitationsApi = {
  getInfo: (token: string) =>
    api.get<InvitationInfo>('/workspaces/invitations/info', { params: { token } }),
  accept: (token: string) =>
    api.post<{ message: string; workspace_slug: string; role?: string; already_member: boolean }>(
      '/workspaces/invitations/accept',
      null,
      { params: { token } }
    ),
}

// Sandboxes API
export const sandboxesApi = {
  list: (workspaceSlug: string) =>
    api.get<{ sandboxes: Sandbox[]; total: number }>(`/workspaces/${workspaceSlug}/sandboxes`),
  get: (workspaceSlug: string, sandboxSlug: string) =>
    api.get<Sandbox>(`/workspaces/${workspaceSlug}/sandboxes/${sandboxSlug}`),
  create: (workspaceSlug: string, data: CreateSandboxRequest) =>
    api.post<{ message: string; sandbox: Sandbox; task_id: string }>(
      `/workspaces/${workspaceSlug}/sandboxes`,
      data
    ),
  delete: (workspaceSlug: string, sandboxSlug: string) =>
    api.delete<{ message: string; task_id: string }>(
      `/workspaces/${workspaceSlug}/sandboxes/${sandboxSlug}`
    ),
  restartAgent: (workspaceSlug: string, sandboxSlug: string) =>
    api.post(`/workspaces/${workspaceSlug}/sandboxes/${sandboxSlug}/agent/restart`),
}
