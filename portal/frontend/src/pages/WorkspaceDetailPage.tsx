import { useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { workspacesApi, sandboxesApi, teamsApi, Workspace, Sandbox, setNavigatingAway, authApi } from '../services/api'
import { useAuthStore } from '../stores/authStore'

export default function WorkspaceDetailPage() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { user } = useAuthStore()

  const [showCreateSandbox, setShowCreateSandbox] = useState(false)
  const [sandboxName, setSandboxName] = useState('')
  const [sandboxSlug, setSandboxSlug] = useState('')
  const [sandboxBranch, setSandboxBranch] = useState('main')
  const [createError, setCreateError] = useState('')
  const [isStartingTeam, setIsStartingTeam] = useState(false)

  const [deleteConfirm, setDeleteConfirm] = useState<{ slug: string; name: string; type: 'workspace' | 'sandbox' } | null>(null)
  const [deleteInput, setDeleteInput] = useState('')

  const { data: workspace, isLoading: workspaceLoading } = useQuery({
    queryKey: ['workspace', slug],
    queryFn: () => workspacesApi.get(slug!).then(res => res.data),
    enabled: !!slug,
  })

  const { data: sandboxesData, isLoading: sandboxesLoading } = useQuery({
    queryKey: ['sandboxes', slug],
    queryFn: () => sandboxesApi.list(slug!).then(res => res.data),
    enabled: !!slug && !!workspace?.app_template_id,
  })

  // Get team status to check if suspended
  const { data: teamStatus, refetch: refetchTeamStatus } = useQuery({
    queryKey: ['team-status', slug],
    queryFn: () => teamsApi.getStatus(slug!).then(res => res.data),
    enabled: !!slug && !!workspace?.kanban_team_id,
    refetchInterval: isStartingTeam ? 2000 : false, // Poll while starting
  })

  const createSandboxMutation = useMutation({
    mutationFn: (data: { name: string; slug: string; source_branch?: string }) =>
      sandboxesApi.create(slug!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sandboxes', slug] })
      setShowCreateSandbox(false)
      setSandboxName('')
      setSandboxSlug('')
      setSandboxBranch('main')
      setCreateError('')
    },
    onError: (err: any) => {
      setCreateError(err.response?.data?.detail || 'Failed to create sandbox')
    }
  })

  const deleteSandboxMutation = useMutation({
    mutationFn: (sandboxSlug: string) => sandboxesApi.delete(slug!, sandboxSlug),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sandboxes', slug] })
      setDeleteConfirm(null)
      setDeleteInput('')
    }
  })

  const deleteWorkspaceMutation = useMutation({
    mutationFn: () => workspacesApi.delete(slug!),
    onSuccess: () => {
      navigate('/workspaces')
    }
  })

  const handleSandboxNameChange = (value: string) => {
    setSandboxName(value)
    const generatedSlug = value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '')
    setSandboxSlug(generatedSlug)
  }

  const handleCreateSandbox = (e: React.FormEvent) => {
    e.preventDefault()
    setCreateError('')

    if (!sandboxName.trim()) {
      setCreateError('Sandbox name is required')
      return
    }

    if (!sandboxSlug.trim() || sandboxSlug.length < 2) {
      setCreateError('Sandbox slug must be at least 2 characters')
      return
    }

    createSandboxMutation.mutate({
      name: sandboxName.trim(),
      slug: sandboxSlug.trim(),
      source_branch: sandboxBranch || 'main'
    })
  }

  const handleOpenKanban = async () => {
    if (!workspace || !user) return

    // Check if team is suspended and needs to be started
    if (teamStatus?.status === 'suspended') {
      setIsStartingTeam(true)
      try {
        await teamsApi.start(workspace.slug)
        // Poll for team to be running
        const checkTeamReady = async (attempts = 0): Promise<boolean> => {
          if (attempts > 30) return false // Max 60 seconds
          const status = await teamsApi.getStatus(workspace.slug)
          if (status.data.status === 'running') return true
          await new Promise(resolve => setTimeout(resolve, 2000))
          return checkTeamReady(attempts + 1)
        }
        const isReady = await checkTeamReady()
        setIsStartingTeam(false)
        if (!isReady) {
          console.error('Team failed to start in time')
          return
        }
        refetchTeamStatus()
      } catch (err) {
        console.error('Failed to start team:', err)
        setIsStartingTeam(false)
        return
      }
    }

    setNavigatingAway()
    try {
      const response = await authApi.getCrossDomainToken(workspace.slug, user.id)
      const { token } = response.data
      window.location.href = `${workspace.kanban_subdomain}?sso_token=${token}`
    } catch {
      window.location.href = workspace.kanban_subdomain
    }
  }

  const getStatusBadge = (status: string) => {
    const colors: Record<string, string> = {
      active: 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400',
      provisioning: 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400',
      suspended: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400',
      deleted: 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400',
    }
    return colors[status] || 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300'
  }

  if (workspaceLoading) {
    return (
      <div className="flex justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
      </div>
    )
  }

  if (!workspace) {
    return (
      <div className="text-center py-12">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Workspace not found</h2>
        <Link to="/workspaces" className="mt-4 text-primary-600 hover:text-primary-500">
          Back to workspaces
        </Link>
      </div>
    )
  }

  const sandboxes = sandboxesData?.sandboxes || []

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3">
            <Link to="/workspaces" className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
            </Link>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">{workspace.name}</h1>
            <span className={`px-2 py-1 rounded-full text-xs font-medium ${getStatusBadge(workspace.status)}`}>
              {workspace.status}
            </span>
          </div>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400 font-mono">{workspace.slug}</p>
        </div>
        {workspace.owner_id === user?.id && (
          <button
            onClick={() => setDeleteConfirm({ slug: workspace.slug, name: workspace.name, type: 'workspace' })}
            className="px-3 py-2 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg text-sm font-medium"
          >
            Delete Workspace
          </button>
        )}
      </div>

      {/* Quick Links */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {/* Kanban Board */}
        <button
          onClick={handleOpenKanban}
          disabled={isStartingTeam}
          className="bg-white dark:bg-dark-800 rounded-xl shadow dark:shadow-dark-700/30 p-4 hover:shadow-lg transition-all flex items-center gap-4 disabled:opacity-75 disabled:cursor-wait"
        >
          <div className={`h-12 w-12 rounded-lg flex items-center justify-center ${
            teamStatus?.status === 'suspended'
              ? 'bg-yellow-100 dark:bg-yellow-900/30'
              : 'bg-indigo-100 dark:bg-indigo-900/30'
          }`}>
            {isStartingTeam ? (
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-indigo-600 dark:border-indigo-400"></div>
            ) : (
              <svg className={`w-6 h-6 ${
                teamStatus?.status === 'suspended'
                  ? 'text-yellow-600 dark:text-yellow-400'
                  : 'text-indigo-600 dark:text-indigo-400'
              }`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
            )}
          </div>
          <div className="text-left">
            <h3 className="font-semibold text-gray-900 dark:text-gray-100">Kanban Board</h3>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {isStartingTeam
                ? 'Starting team containers...'
                : teamStatus?.status === 'suspended'
                  ? 'Click to start (suspended)'
                  : workspace.kanban_subdomain.replace('https://', '')}
            </p>
          </div>
          <svg className="w-5 h-5 text-gray-400 ml-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
          </svg>
        </button>

        {/* App (if exists) */}
        {workspace.app_subdomain && (
          <a
            href={workspace.app_subdomain}
            target="_blank"
            rel="noopener noreferrer"
            className="bg-white dark:bg-dark-800 rounded-xl shadow dark:shadow-dark-700/30 p-4 hover:shadow-lg transition-all flex items-center gap-4"
          >
            <div className="h-12 w-12 rounded-lg bg-purple-100 dark:bg-purple-900/30 flex items-center justify-center">
              <svg className="w-6 h-6 text-purple-600 dark:text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
              </svg>
            </div>
            <div className="text-left">
              <h3 className="font-semibold text-gray-900 dark:text-gray-100">App</h3>
              <p className="text-sm text-gray-500 dark:text-gray-400">{workspace.app_subdomain.replace('https://', '')}</p>
            </div>
            <svg className="w-5 h-5 text-gray-400 ml-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
            </svg>
          </a>
        )}

        {/* GitHub Repo (if exists) */}
        {workspace.github_repo_url && (
          <a
            href={workspace.github_repo_url}
            target="_blank"
            rel="noopener noreferrer"
            className="bg-white dark:bg-dark-800 rounded-xl shadow dark:shadow-dark-700/30 p-4 hover:shadow-lg transition-all flex items-center gap-4"
          >
            <div className="h-12 w-12 rounded-lg bg-gray-100 dark:bg-gray-700 flex items-center justify-center">
              <svg className="w-6 h-6 text-gray-700 dark:text-gray-300" fill="currentColor" viewBox="0 0 24 24">
                <path fillRule="evenodd" clipRule="evenodd" d="M12 2C6.477 2 2 6.477 2 12c0 4.42 2.87 8.17 6.84 9.5.5.08.66-.23.66-.5v-1.69c-2.77.6-3.36-1.34-3.36-1.34-.46-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.87 1.52 2.34 1.07 2.91.83.09-.65.35-1.09.63-1.34-2.22-.25-4.55-1.11-4.55-4.92 0-1.11.38-2 1.03-2.71-.1-.25-.45-1.29.1-2.64 0 0 .84-.27 2.75 1.02.79-.22 1.65-.33 2.5-.33.85 0 1.71.11 2.5.33 1.91-1.29 2.75-1.02 2.75-1.02.55 1.35.2 2.39.1 2.64.65.71 1.03 1.6 1.03 2.71 0 3.82-2.34 4.66-4.57 4.91.36.31.69.92.69 1.85V21c0 .27.16.59.67.5C19.14 20.16 22 16.42 22 12A10 10 0 0012 2z" />
              </svg>
            </div>
            <div className="text-left">
              <h3 className="font-semibold text-gray-900 dark:text-gray-100">GitHub</h3>
              <p className="text-sm text-gray-500 dark:text-gray-400">{workspace.github_repo_name}</p>
            </div>
            <svg className="w-5 h-5 text-gray-400 ml-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
            </svg>
          </a>
        )}
      </div>

      {/* Sandboxes Section (only for app workspaces) */}
      {workspace.app_template_id && (
        <div className="bg-white dark:bg-dark-800 rounded-xl shadow dark:shadow-dark-700/30 overflow-hidden">
          <div className="p-4 border-b border-gray-200 dark:border-dark-700 flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Sandboxes</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400">Development environments with database clones</p>
            </div>
            <button
              onClick={() => setShowCreateSandbox(true)}
              className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 text-sm font-medium flex items-center gap-2"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              New Sandbox
            </button>
          </div>

          {sandboxesLoading ? (
            <div className="p-8 flex justify-center">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary-600"></div>
            </div>
          ) : sandboxes.length === 0 ? (
            <div className="p-8 text-center">
              <svg className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
              </svg>
              <p className="mt-2 text-gray-500 dark:text-gray-400">No sandboxes yet</p>
              <p className="text-sm text-gray-400 dark:text-gray-500">Create a sandbox to develop features with isolated data</p>
            </div>
          ) : (
            <div className="divide-y divide-gray-200 dark:divide-dark-700">
              {sandboxes.map((sandbox: Sandbox) => (
                <div key={sandbox.id} className="p-4 flex items-center justify-between hover:bg-gray-50 dark:hover:bg-dark-700/50">
                  <div className="flex items-center gap-4">
                    <div className={`h-10 w-10 rounded-lg flex items-center justify-center ${
                      sandbox.status === 'active'
                        ? 'bg-green-100 dark:bg-green-900/30'
                        : 'bg-yellow-100 dark:bg-yellow-900/30'
                    }`}>
                      <svg className={`w-5 h-5 ${
                        sandbox.status === 'active'
                          ? 'text-green-600 dark:text-green-400'
                          : 'text-yellow-600 dark:text-yellow-400'
                      }`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                      </svg>
                    </div>
                    <div>
                      <h3 className="font-medium text-gray-900 dark:text-gray-100">{sandbox.name}</h3>
                      <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
                        <span className="font-mono">{sandbox.full_slug}</span>
                        <span>·</span>
                        <span>Branch: {sandbox.git_branch}</span>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className={`px-2 py-1 rounded-full text-xs font-medium ${getStatusBadge(sandbox.status)}`}>
                      {sandbox.status}
                    </span>
                    {sandbox.status === 'active' && (
                      <a
                        href={sandbox.subdomain}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-primary-600 dark:text-primary-400 hover:text-primary-700 dark:hover:text-primary-300 text-sm font-medium"
                      >
                        Open
                      </a>
                    )}
                    <button
                      onClick={() => setDeleteConfirm({ slug: sandbox.slug, name: sandbox.name, type: 'sandbox' })}
                      className="text-gray-400 hover:text-red-500 p-1"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Create Sandbox Modal */}
      {showCreateSandbox && (
        <div className="fixed inset-0 bg-black/50 dark:bg-black/70 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-dark-800 rounded-xl shadow-xl dark:shadow-dark-900/50 w-full max-w-md p-6">
            <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100 mb-4">Create Sandbox</h2>

            <form onSubmit={handleCreateSandbox} className="space-y-4">
              {createError && (
                <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 px-3 py-2 rounded-lg text-sm">
                  {createError}
                </div>
              )}

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Sandbox Name
                </label>
                <input
                  type="text"
                  value={sandboxName}
                  onChange={(e) => handleSandboxNameChange(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-gray-100 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  placeholder="Feature Development"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Sandbox Slug
                </label>
                <div className="flex rounded-lg shadow-sm">
                  <span className="inline-flex items-center px-3 rounded-l-lg border border-r-0 border-gray-300 dark:border-dark-600 bg-gray-50 dark:bg-dark-700 text-gray-500 dark:text-gray-400 text-sm">
                    {workspace.slug}-
                  </span>
                  <input
                    type="text"
                    value={sandboxSlug}
                    onChange={(e) => setSandboxSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ''))}
                    className="flex-1 px-3 py-2 border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-gray-100 rounded-r-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    placeholder="feature-dev"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Source Branch
                </label>
                <input
                  type="text"
                  value={sandboxBranch}
                  onChange={(e) => setSandboxBranch(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-gray-100 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  placeholder="main"
                />
                <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                  Branch to clone code from (database will be cloned from production)
                </p>
              </div>

              <div className="flex justify-end gap-3 pt-4">
                <button
                  type="button"
                  onClick={() => {
                    setShowCreateSandbox(false)
                    setSandboxName('')
                    setSandboxSlug('')
                    setCreateError('')
                  }}
                  className="px-4 py-2 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-dark-700 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={createSandboxMutation.isPending}
                  className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50"
                >
                  {createSandboxMutation.isPending ? 'Creating...' : 'Create Sandbox'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {deleteConfirm && (
        <div className="fixed inset-0 bg-black/50 dark:bg-black/70 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-dark-800 rounded-lg shadow-xl dark:shadow-dark-900/50 w-full max-w-md p-6">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
                <svg className="w-6 h-6 text-red-600 dark:text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              </div>
              <div>
                <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">
                  Delete {deleteConfirm.type === 'workspace' ? 'Workspace' : 'Sandbox'}
                </h2>
                <p className="text-sm text-gray-500 dark:text-gray-400">This action cannot be undone</p>
              </div>
            </div>

            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 mb-4">
              <p className="text-sm text-red-800 dark:text-red-300">
                You are about to delete <strong>{deleteConfirm.name}</strong>.
              </p>
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Type <strong>{deleteConfirm.slug}</strong> to confirm
              </label>
              <input
                type="text"
                value={deleteInput}
                onChange={(e) => setDeleteInput(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-gray-100 rounded-lg focus:ring-2 focus:ring-red-500 focus:border-transparent"
                placeholder={deleteConfirm.slug}
                autoFocus
              />
            </div>

            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={() => {
                  setDeleteConfirm(null)
                  setDeleteInput('')
                }}
                className="px-4 py-2 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-dark-700 rounded-lg"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  if (deleteConfirm.type === 'workspace') {
                    deleteWorkspaceMutation.mutate()
                  } else {
                    deleteSandboxMutation.mutate(deleteConfirm.slug)
                  }
                }}
                disabled={deleteInput !== deleteConfirm.slug || deleteSandboxMutation.isPending || deleteWorkspaceMutation.isPending}
                className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {(deleteSandboxMutation.isPending || deleteWorkspaceMutation.isPending) ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
