import { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { workspacesApi, sandboxesApi, appTemplatesApi, Workspace, Sandbox, WorkspaceMember, WorkspaceInvitation, WorkspaceHealth, AppTemplate, LinkAppFromTemplateRequest, LinkAppFromRepoRequest, setNavigatingAway, authApi } from '../services/api'
import { useAuthStore } from '../stores/authStore'
import { useTaskProgressStore } from '../stores/taskProgressStore'

export default function WorkspaceDetailPage() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { user } = useAuthStore()
  const { startTask, getTaskByWorkspaceSlug } = useTaskProgressStore()
  const tasks = useTaskProgressStore((state) => state.tasks)

  // Get active task for this workspace (re-renders when tasks change)
  const activeTask = slug ? getTaskByWorkspaceSlug(slug) : undefined

  const [showCreateSandbox, setShowCreateSandbox] = useState(false)
  const [sandboxName, setSandboxName] = useState('')
  const [sandboxSlug, setSandboxSlug] = useState('')
  const [sandboxBranch, setSandboxBranch] = useState('main')
  const [createError, setCreateError] = useState('')
  const [pullRequestError, setPullRequestError] = useState('')
  const [startWorkspaceError, setStartWorkspaceError] = useState('')

  const [deleteConfirm, setDeleteConfirm] = useState<{ slug: string; name: string; type: 'workspace' | 'sandbox' } | null>(null)
  const [deleteInput, setDeleteInput] = useState('')
  const [deleteRepoOnDelete, setDeleteRepoOnDelete] = useState(false)

  // Restart workspace state
  const [showRestartModal, setShowRestartModal] = useState(false)
  const [restartRebuild, setRestartRebuild] = useState(false)
  const [restartApp, setRestartApp] = useState(true)

  // Tab state
  const [activeTab, setActiveTab] = useState<'dashboard' | 'members' | 'settings'>('dashboard')

  // Settings state
  const [selectedLLMProvider, setSelectedLLMProvider] = useState<string>('')
  const [settingsSaved, setSettingsSaved] = useState(false)

  // Member management state
  const [showInviteMember, setShowInviteMember] = useState(false)
  const [newMemberEmail, setNewMemberEmail] = useState('')
  const [newMemberRole, setNewMemberRole] = useState<'owner' | 'admin' | 'member' | 'viewer'>('member')
  const [inviteError, setInviteError] = useState('')
  const [inviteSuccess, setInviteSuccess] = useState<WorkspaceInvitation | null>(null)
  const [removeMemberConfirm, setRemoveMemberConfirm] = useState<WorkspaceMember | null>(null)
  const [cancelInviteConfirm, setCancelInviteConfirm] = useState<WorkspaceInvitation | null>(null)
  const [editingMember, setEditingMember] = useState<string | null>(null)

  // Link App state
  const [showLinkAppModal, setShowLinkAppModal] = useState(false)
  const [linkAppMode, setLinkAppMode] = useState<'template' | 'repo'>('template')
  const [selectedTemplate, setSelectedTemplate] = useState('')
  const [existingRepoUrl, setExistingRepoUrl] = useState('')
  const [existingRepoPat, setExistingRepoPat] = useState('')
  const [linkAppError, setLinkAppError] = useState('')

  // Unlink App state
  const [showUnlinkAppModal, setShowUnlinkAppModal] = useState(false)
  const [deleteRepoOnUnlink, setDeleteRepoOnUnlink] = useState(false)
  const [unlinkConfirmInput, setUnlinkConfirmInput] = useState('')

  const { data: workspace, isLoading: workspaceLoading, refetch: refetchWorkspace } = useQuery({
    queryKey: ['workspace', slug],
    queryFn: () => workspacesApi.get(slug!).then(res => res.data),
    enabled: !!slug,
    // Poll while linking or unlinking app
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return (status === 'linking_app' || status === 'unlinking_app') ? 2000 : false
    },
  })

  const { data: sandboxesData, isLoading: sandboxesLoading } = useQuery({
    queryKey: ['sandboxes', slug],
    queryFn: () => sandboxesApi.list(slug!).then(res => res.data),
    enabled: !!slug && (!!workspace?.app_template_id || !!workspace?.github_repo_url),
  })
  const sandboxes = sandboxesData?.sandboxes || []

  // Get workspace members
  const { data: membersData, isLoading: membersLoading } = useQuery({
    queryKey: ['workspace-members', slug],
    queryFn: () => workspacesApi.getMembers(slug!).then(res => res.data),
    enabled: !!slug,
  })

  // Get pending invitations
  const { data: invitationsData } = useQuery({
    queryKey: ['workspace-invitations', slug],
    queryFn: () => workspacesApi.getInvitations(slug!, 'pending').then(res => res.data),
    enabled: !!slug,
  })

  // Get workspace status (for provisioning progress)
  const { data: workspaceStatus } = useQuery({
    queryKey: ['workspace-status', slug],
    queryFn: () => workspacesApi.getStatus(slug!).then(res => res.data),
    enabled: !!slug && workspace?.status === 'provisioning',
    refetchInterval: workspace?.status === 'provisioning' ? 3000 : false,
  })

  // Get workspace health (container running status)
  const { data: workspaceHealth, isLoading: healthLoading, refetch: refetchHealth } = useQuery({
    queryKey: ['workspace-health', slug],
    queryFn: () => workspacesApi.getHealth(slug!).then(res => res.data),
    enabled: !!slug && workspace?.status === 'active',
    staleTime: 30000, // Cache for 30 seconds
    retry: 1, // Only retry once on failure
  })

  // Start workspace mutation
  const startWorkspaceMutation = useMutation({
    mutationFn: () => workspacesApi.start(slug!),
    onMutate: () => {
      setStartWorkspaceError('')
    },
    onSuccess: (response) => {
      const taskId = response.data.task_id
      if (taskId && workspace?.id && workspace?.slug) {
        startTask(taskId, workspace.id, workspace.slug, 'start_workspace')
      }
      // Invalidate health to trigger re-check after start completes
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ['workspace-health', slug] })
      }, 5000) // Wait 5 seconds before re-checking health
    },
    onError: (err: any) => {
      setStartWorkspaceError(err.response?.data?.detail || 'Failed to start workspace')
    }
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

  const createPullRequestMutation = useMutation({
    mutationFn: (sandboxSlug: string) => sandboxesApi.createPullRequest(slug!, sandboxSlug),
    onMutate: () => {
      setPullRequestError('')
    },
    onSuccess: (response, sandboxSlug) => {
      const taskId = response.data.task_id
      const sandboxRecord = sandboxes.find((sandbox) => sandbox.slug === sandboxSlug)
      if (taskId && workspace?.id && workspace?.slug) {
        startTask(
          taskId,
          workspace.id,
          workspace.slug,
          'sandbox.pull_request',
          sandboxRecord?.id,
          sandboxSlug
        )
      }
    },
    onError: (err: any) => {
      setPullRequestError(err.response?.data?.detail || 'Failed to create pull request')
    }
  })

  const deleteWorkspaceMutation = useMutation({
    mutationFn: (options?: { delete_github_repo?: boolean }) =>
      workspacesApi.delete(slug!, options),
    onSuccess: () => {
      navigate('/workspaces')
    }
  })

  const restartWorkspaceMutation = useMutation({
    mutationFn: (options: { rebuild?: boolean; restart_app?: boolean }) =>
      workspacesApi.restart(slug!, options),
    onSuccess: (response) => {
      const taskId = response.data.task_id
      if (taskId && workspace?.id && workspace?.slug) {
        startTask(taskId, workspace.id, workspace.slug, 'restart_workspace')
      }
      setShowRestartModal(false)
      setRestartRebuild(false)
      setRestartApp(true)
      queryClient.invalidateQueries({ queryKey: ['workspace', slug] })
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ['workspace-health', slug] })
      }, 5000)
    }
  })

  // Member management mutations
  const inviteMemberMutation = useMutation({
    mutationFn: (data: { email: string; role: 'owner' | 'admin' | 'member' | 'viewer' }) =>
      workspacesApi.inviteMember(slug!, data),
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: ['workspace-invitations', slug] })
      setInviteSuccess(response.data)
      setNewMemberEmail('')
      setNewMemberRole('member')
      setInviteError('')
    },
    onError: (err: any) => {
      setInviteError(err.response?.data?.detail || 'Failed to create invitation')
    }
  })

  const cancelInviteMutation = useMutation({
    mutationFn: (invitationId: string) =>
      workspacesApi.cancelInvitation(slug!, invitationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace-invitations', slug] })
      setCancelInviteConfirm(null)
    }
  })

  const updateMemberMutation = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: 'owner' | 'admin' | 'member' | 'viewer' }) =>
      workspacesApi.updateMember(slug!, userId, { role }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace-members', slug] })
      setEditingMember(null)
    }
  })

  const removeMemberMutation = useMutation({
    mutationFn: (userId: string) => workspacesApi.removeMember(slug!, userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace-members', slug] })
      setRemoveMemberConfirm(null)
    }
  })

  // Fetch app templates when link app modal is open
  const { data: appTemplatesData } = useQuery({
    queryKey: ['app-templates'],
    queryFn: () => appTemplatesApi.list().then(res => res.data),
    enabled: showLinkAppModal,
  })
  const appTemplates = appTemplatesData?.templates?.filter(t => t.active) || []

  // Link App mutation
  const linkAppMutation = useMutation({
    mutationFn: (data: LinkAppFromTemplateRequest | LinkAppFromRepoRequest) =>
      workspacesApi.linkApp(slug!, data),
    onMutate: () => {
      setLinkAppError('')
    },
    onSuccess: (response) => {
      const taskId = response.data.task_id
      if (taskId && workspace?.id && workspace?.slug) {
        startTask(taskId, workspace.id, workspace.slug, 'link_app')
      }
      setShowLinkAppModal(false)
      setSelectedTemplate('')
      setExistingRepoUrl('')
      setLinkAppMode('template')
      queryClient.invalidateQueries({ queryKey: ['workspace', slug] })
    },
    onError: (err: any) => {
      setLinkAppError(err.response?.data?.detail || 'Failed to link app')
    }
  })

  // Unlink App mutation
  const unlinkAppMutation = useMutation({
    mutationFn: (data: { delete_github_repo?: boolean }) =>
      workspacesApi.unlinkApp(slug!, data),
    onSuccess: (response) => {
      const taskId = response.data.task_id
      if (taskId && workspace?.id && workspace?.slug) {
        startTask(taskId, workspace.id, workspace.slug, 'unlink_app')
      }
      setShowUnlinkAppModal(false)
      setDeleteRepoOnUnlink(false)
      setUnlinkConfirmInput('')
      queryClient.invalidateQueries({ queryKey: ['workspace', slug] })
    }
  })

  // Update workspace settings mutation
  const updateWorkspaceMutation = useMutation({
    mutationFn: (data: { default_llm_provider?: string }) =>
      workspacesApi.update(slug!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', slug] })
      setSettingsSaved(true)
      setTimeout(() => setSettingsSaved(false), 3000)
    }
  })

  // Initialize LLM provider from workspace data
  useEffect(() => {
    if (workspace?.default_llm_provider !== undefined) {
      setSelectedLLMProvider(workspace.default_llm_provider || '')
    }
  }, [workspace?.default_llm_provider])

  const handleLinkApp = () => {
    if (linkAppMode === 'template') {
      if (!selectedTemplate) {
        setLinkAppError('Please select an app template')
        return
      }
      linkAppMutation.mutate({ app_template_slug: selectedTemplate })
    } else {
      if (!existingRepoUrl.trim()) {
        setLinkAppError('Please enter a GitHub repository URL')
        return
      }
      const repoRequest: { github_repo_url: string; github_pat?: string } = {
        github_repo_url: existingRepoUrl.trim()
      }
      // Only include PAT if provided
      if (existingRepoPat.trim()) {
        repoRequest.github_pat = existingRepoPat.trim()
      }
      linkAppMutation.mutate(repoRequest)
    }
  }

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

  // State for kanban starting flow
  const [isStartingKanban, setIsStartingKanban] = useState(false)

  // Start kanban only mutation (uses dedicated kanban-only endpoint for faster startup)
  const startKanbanMutation = useMutation({
    mutationFn: () => workspacesApi.startKanban(slug!),
    onMutate: () => {
      setIsStartingKanban(true)
    },
    onSuccess: () => {
      // Poll health until kanban is running, then open
      const pollHealth = async (attempts = 0) => {
        if (attempts > 30) { // Max 30 attempts (about 30 seconds)
          setIsStartingKanban(false)
          return
        }

        try {
          const healthRes = await workspacesApi.getHealth(slug!)
          if (healthRes.data.kanban_running) {
            setIsStartingKanban(false)
            queryClient.invalidateQueries({ queryKey: ['workspace-health', slug] })
            // Now open the kanban
            handleOpenKanban()
          } else {
            setTimeout(() => pollHealth(attempts + 1), 1000)
          }
        } catch {
          setTimeout(() => pollHealth(attempts + 1), 1000)
        }
      }

      // Start polling after a short delay
      setTimeout(() => pollHealth(), 3000)
    },
    onError: () => {
      setIsStartingKanban(false)
    }
  })

  const handleOpenKanban = async () => {
    if (!workspace || !user) return

    setNavigatingAway()
    try {
      const response = await authApi.getCrossDomainToken(workspace.slug, user.id)
      const { token } = response.data
      window.location.href = `${workspace.kanban_subdomain}?sso_token=${token}`
    } catch {
      window.location.href = workspace.kanban_subdomain
    }
  }

  const handleKanbanClick = () => {
    if (!workspace || !user) return

    // Check if kanban is stopped
    const kanbanStopped = workspaceHealth && !workspaceHealth.kanban_running

    if (kanbanStopped) {
      // Start the kanban first
      startKanbanMutation.mutate()
    } else {
      // Kanban is running, open directly
      handleOpenKanban()
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

  const getRoleBadge = (role: string) => {
    const colors: Record<string, string> = {
      owner: 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400',
      admin: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400',
      member: 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400',
      viewer: 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300',
    }
    return colors[role] || 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300'
  }

  // Get current user's membership - ownership determined from members list (role='owner')
  const members = membersData?.members || []
  const pendingInvitations = invitationsData?.invitations || []
  const currentUserMembership = members.find(m => m.user_id === user?.id)
  const userRole = currentUserMembership?.role || null
  const canManageMembers = userRole === 'owner' || userRole === 'admin'
  const canCreateSandbox = userRole === 'owner' || userRole === 'admin'
  const getSandboxPrTask = (sandboxSlug: string) =>
    Object.values(tasks).find(
      (task) =>
        task.sandboxSlug === sandboxSlug &&
        task.action === 'sandbox.pull_request' &&
        (task.status === 'pending' || task.status === 'in_progress')
    )
  const workspaceStartTask = Object.values(tasks).find(
    (task) =>
      task.workspaceSlug === slug &&
      task.action === 'start_workspace' &&
      (task.status === 'pending' || task.status === 'in_progress')
  )
  const workspaceRestartTask = Object.values(tasks).find(
    (task) =>
      task.workspaceSlug === slug &&
      task.action === 'restart_workspace' &&
      (task.status === 'pending' || task.status === 'in_progress')
  )
  const workspaceActionTask = workspaceStartTask || workspaceRestartTask
  const isWorkspaceStarting = startWorkspaceMutation.isPending || !!workspaceActionTask

  // Track link/unlink app tasks
  const linkAppTask = Object.values(tasks).find(
    (task) =>
      task.workspaceSlug === slug &&
      task.action === 'link_app' &&
      (task.status === 'pending' || task.status === 'in_progress')
  )
  const unlinkAppTask = Object.values(tasks).find(
    (task) =>
      task.workspaceSlug === slug &&
      task.action === 'unlink_app' &&
      (task.status === 'pending' || task.status === 'in_progress')
  )
  const appOperationTask = linkAppTask || unlinkAppTask

  // Refetch workspace when app operation completes
  useEffect(() => {
    // Find any recently completed link/unlink tasks for this workspace
    const completedTask = Object.values(tasks).find(
      (task) =>
        task.workspaceSlug === slug &&
        (task.action === 'link_app' || task.action === 'unlink_app') &&
        (task.status === 'completed' || task.status === 'failed')
    )
    if (completedTask) {
      refetchWorkspace()
      queryClient.invalidateQueries({ queryKey: ['sandboxes', slug] })
    }
  }, [tasks, slug, refetchWorkspace, queryClient])

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

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
        <div>
          <div className="flex items-center gap-3 flex-wrap">
            <Link to="/workspaces" className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
            </Link>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">{workspace.name}</h1>
            <span className={`px-2 py-1 rounded-full text-xs font-medium ${getStatusBadge(workspace.status)}`}>
              {workspace.status}
            </span>
            {userRole && (
              <span className={`px-2 py-1 rounded-full text-xs font-medium ${getRoleBadge(userRole)}`}>
                {userRole}
              </span>
            )}
          </div>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400 font-mono">{workspace.slug}</p>
        </div>
        {(userRole === 'owner' || userRole === 'admin') && (
          <div className="flex items-center gap-2 flex-wrap">
            {/* Unlink App button - visible if workspace has an app (from template or linked repo) */}
            {(workspace.app_template_id || workspace.github_repo_url) && (
              <button
                onClick={() => setShowUnlinkAppModal(true)}
                className="px-3 py-2 text-amber-600 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-900/20 rounded-lg text-sm font-medium flex items-center gap-2"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                </svg>
                Unlink App
              </button>
            )}
            <button
              onClick={() => setShowRestartModal(true)}
              className="px-3 py-2 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-dark-700 rounded-lg text-sm font-medium flex items-center gap-2"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              Restart
            </button>
            {userRole === 'owner' && (
              <button
                onClick={() => setDeleteConfirm({ slug: workspace.slug, name: workspace.name, type: 'workspace' })}
                className="px-3 py-2 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg text-sm font-medium"
              >
                Delete
              </button>
            )}
          </div>
        )}
      </div>

      {/* App Operation Progress Banner */}
      {appOperationTask && (
        <div className="bg-primary-50 dark:bg-primary-900/20 border border-primary-200 dark:border-primary-800 rounded-xl p-4">
          <div className="flex items-center gap-4">
            <div className="flex-shrink-0">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600 dark:border-primary-400"></div>
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="text-sm font-medium text-primary-900 dark:text-primary-100">
                {appOperationTask.action === 'link_app' ? 'Linking App to Workspace' : 'Unlinking App from Workspace'}
              </h3>
              <p className="text-sm text-primary-700 dark:text-primary-300 mt-1">
                {appOperationTask.stepName || 'Initializing...'}
              </p>
              {/* Progress bar */}
              <div className="mt-2 w-full bg-primary-100 dark:bg-primary-800/50 rounded-full h-2">
                <div
                  className="bg-primary-600 dark:bg-primary-400 h-2 rounded-full transition-all duration-300"
                  style={{ width: `${appOperationTask.percentage || 0}%` }}
                ></div>
              </div>
              <p className="text-xs text-primary-600 dark:text-primary-400 mt-1">
                Step {appOperationTask.step || 0} of {appOperationTask.totalSteps || 1}
                {appOperationTask.percentage > 0 && ` (${Math.round(appOperationTask.percentage)}%)`}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Tab Navigation */}
      <div className="border-b border-gray-200 dark:border-dark-700">
        <nav className="-mb-px flex gap-6">
          <button
            onClick={() => setActiveTab('dashboard')}
            className={`py-3 px-1 border-b-2 font-medium text-sm transition-colors ${
              activeTab === 'dashboard'
                ? 'border-primary-500 text-primary-600 dark:text-primary-400'
                : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-300 dark:hover:border-gray-600'
            }`}
          >
            <div className="flex items-center gap-2">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
              </svg>
              Dashboard
            </div>
          </button>
          <button
            onClick={() => setActiveTab('members')}
            className={`py-3 px-1 border-b-2 font-medium text-sm transition-colors ${
              activeTab === 'members'
                ? 'border-primary-500 text-primary-600 dark:text-primary-400'
                : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-300 dark:hover:border-gray-600'
            }`}
          >
            <div className="flex items-center gap-2">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
              </svg>
              Members
              <span className="bg-gray-100 dark:bg-dark-700 text-gray-600 dark:text-gray-400 px-2 py-0.5 rounded-full text-xs">
                {members.length}
              </span>
            </div>
          </button>
          <button
            onClick={() => setActiveTab('settings')}
            className={`py-3 px-1 border-b-2 font-medium text-sm transition-colors ${
              activeTab === 'settings'
                ? 'border-primary-500 text-primary-600 dark:text-primary-400'
                : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-300 dark:hover:border-gray-600'
            }`}
          >
            <div className="flex items-center gap-2">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
              Settings
            </div>
          </button>
        </nav>
      </div>

      {/* Dashboard Tab Content */}
      {activeTab === 'dashboard' && (
        <>
          {/* Workspace Stopped Banner */}
          {workspace.status === 'active' && !healthLoading && workspaceHealth && !workspaceHealth.all_healthy && (
            <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl p-4">
              <div className="flex items-start gap-4">
                <div className="flex-shrink-0">
                  <svg className="w-6 h-6 text-amber-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                  </svg>
                </div>
                <div className="flex-1">
                  <h3 className="text-sm font-semibold text-amber-800 dark:text-amber-200">
                    Workspace Containers Stopped
                  </h3>
                  <p className="mt-1 text-sm text-amber-700 dark:text-amber-300">
                    {!workspaceHealth.kanban_running && 'Kanban containers are not running. '}
                    {workspaceHealth.app_running === false && 'App containers are not running. '}
                    {workspaceHealth.sandboxes.some(s => !s.running) && 'Some sandbox containers are not running. '}
                    Click "Start Workspace" to rebuild and start all components.
                  </p>
                  <div className="mt-3 flex items-center gap-3">
                    {(userRole === 'owner' || userRole === 'admin') && (
                      <button
                        onClick={() => startWorkspaceMutation.mutate()}
                        disabled={isWorkspaceStarting}
                        className="px-4 py-2 bg-amber-600 text-white rounded-lg hover:bg-amber-700 text-sm font-medium flex items-center gap-2 disabled:opacity-50"
                      >
                        {isWorkspaceStarting ? (
                          <>
                            <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                            </svg>
                            {workspaceActionTask?.action === 'restart_workspace' ? 'Restarting...' : 'Starting...'}
                          </>
                        ) : (
                          <>
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                            Start Workspace
                          </>
                        )}
                      </button>
                    )}
                    <button
                      onClick={() => refetchHealth()}
                      className="px-3 py-2 text-amber-700 dark:text-amber-300 hover:bg-amber-100 dark:hover:bg-amber-900/30 rounded-lg text-sm font-medium"
                    >
                      Check Again
                    </button>
                  </div>
                  {workspaceActionTask && (
                    <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">
                      {workspaceActionTask.action === 'restart_workspace' ? 'Restarting workspace:' : 'Starting workspace:'} {workspaceActionTask.stepName}
                    </p>
                  )}
                  {startWorkspaceError && (
                    <p className="mt-2 text-sm text-red-600 dark:text-red-400">{startWorkspaceError}</p>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Health Check Loading State */}
          {workspace.status === 'active' && healthLoading && (
            <div className="bg-gray-50 dark:bg-dark-700/50 border border-gray-200 dark:border-dark-600 rounded-xl p-4">
              <div className="flex items-center gap-3">
                <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-primary-600"></div>
                <span className="text-sm text-gray-600 dark:text-gray-400">Checking workspace status...</span>
              </div>
            </div>
          )}

          {/* Quick Links */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {/* Kanban Board */}
            {(() => {
              const kanbanStopped = workspace.status === 'active' && workspaceHealth && !workspaceHealth.kanban_running
              const isStarting = isStartingKanban || startKanbanMutation.isPending || isWorkspaceStarting

              return (
                <button
                  onClick={handleKanbanClick}
                  disabled={isStarting}
                  className={`bg-white dark:bg-dark-800 rounded-xl shadow dark:shadow-dark-700/30 p-4 hover:shadow-lg transition-all flex items-center gap-4 ${
                    isStarting ? 'opacity-75 cursor-wait' : ''
                  }`}
                >
                  <div className={`h-12 w-12 rounded-lg flex items-center justify-center ${
                    isStarting
                      ? 'bg-blue-100 dark:bg-blue-900/30'
                      : kanbanStopped
                        ? 'bg-amber-100 dark:bg-amber-900/30'
                        : 'bg-indigo-100 dark:bg-indigo-900/30'
                  }`}>
                    {isStarting ? (
                      <svg className="w-6 h-6 text-blue-600 dark:text-blue-400 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                      </svg>
                    ) : kanbanStopped ? (
                      <svg className="w-6 h-6 text-amber-600 dark:text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 10a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z" />
                      </svg>
                    ) : (
                      <svg className="w-6 h-6 text-indigo-600 dark:text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                      </svg>
                    )}
                  </div>
                  <div className="text-left flex-1">
                    <div className="flex items-center gap-2">
                      <h3 className="font-semibold text-gray-900 dark:text-gray-100">Kanban Board</h3>
                      {kanbanStopped && !isStarting && (
                        <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400">
                          Stopped
                        </span>
                      )}
                      {isStarting && (
                        <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400">
                          Starting...
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      {isStarting
                        ? 'Starting kanban containers...'
                        : kanbanStopped
                          ? 'Click to start and open'
                          : workspace.kanban_subdomain.replace('https://', '')}
                    </p>
                  </div>
                  {isStarting ? (
                    <div className="w-5 h-5" /> /* Spacer */
                  ) : kanbanStopped ? (
                    <svg className="w-5 h-5 text-amber-500 ml-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                  ) : (
                    <svg className="w-5 h-5 text-gray-400 ml-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                    </svg>
                  )}
                </button>
              )
            })()}

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

        {/* Link App (for kanban-only workspaces - no template or linked repo) */}
        {!workspace.app_template_id && !workspace.github_repo_url && canManageMembers && (
          <button
            onClick={() => setShowLinkAppModal(true)}
            className="bg-white dark:bg-dark-800 rounded-xl shadow dark:shadow-dark-700/30 p-4 hover:shadow-lg transition-all flex items-center gap-4 border-2 border-dashed border-gray-200 dark:border-dark-600"
          >
            <div className="h-12 w-12 rounded-lg bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center">
              <svg className="w-6 h-6 text-emerald-600 dark:text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
            </div>
            <div className="text-left">
              <h3 className="font-semibold text-gray-900 dark:text-gray-100">Link App</h3>
              <p className="text-sm text-gray-500 dark:text-gray-400">Add an application to this workspace</p>
            </div>
          </button>
        )}
      </div>

      {/* Sandboxes Section (only for app workspaces - from template or linked repo) */}
      {(workspace.app_template_id || workspace.github_repo_url) && (
        <div className="bg-white dark:bg-dark-800 rounded-xl shadow dark:shadow-dark-700/30 overflow-hidden">
          <div className="p-4 border-b border-gray-200 dark:border-dark-700 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Sandboxes</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400">Development environments with database clones</p>
              <p className="text-xs text-amber-600 dark:text-amber-400 mt-1">
                Deploying a sandbox rebuilds the live app and may cause brief downtime.
              </p>
            </div>
            {canCreateSandbox && (
              <button
                onClick={() => setShowCreateSandbox(true)}
                className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 text-sm font-medium flex items-center gap-2 self-start sm:self-auto"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                New Sandbox
              </button>
            )}
          </div>

          {pullRequestError && (
            <div className="mx-4 mt-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 px-4 py-3 rounded-lg">
              {pullRequestError}
            </div>
          )}

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
              {sandboxes.map((sandbox: Sandbox) => {
                const sandboxTask = getSandboxPrTask(sandbox.slug)
                const canDeploySandbox = userRole === 'owner' || userRole === 'admin' || sandbox.owner_id === user?.id
                const isDeploying = !!sandboxTask

                return (
                  <div key={sandbox.id} className="p-4 hover:bg-gray-50 dark:hover:bg-dark-700/50">
                    {/* Mobile Layout */}
                    <div className="sm:hidden space-y-3">
                      <div className="flex items-start gap-3">
                        <div className={`h-10 w-10 flex-shrink-0 rounded-lg flex items-center justify-center ${
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
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <h3 className="font-medium text-gray-900 dark:text-gray-100 truncate">{sandbox.name}</h3>
                            <span className={`px-2 py-0.5 rounded-full text-xs font-medium flex-shrink-0 ${getStatusBadge(sandbox.status)}`}>
                              {sandbox.status}
                            </span>
                          </div>
                          <p className="text-xs text-gray-500 dark:text-gray-400 font-mono truncate mt-0.5">{sandbox.full_slug}</p>
                          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">Branch: {sandbox.git_branch}</p>
                        </div>
                      </div>
                      {sandboxTask && (
                        <div className="flex items-center gap-2 text-xs text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20 px-3 py-2 rounded-lg">
                          <svg className="w-3 h-3 animate-spin flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                          </svg>
                          <span>{sandboxTask.stepName}</span>
                        </div>
                      )}
                      <div className="flex items-center gap-2">
                        {canDeploySandbox && (
                          <button
                            onClick={() => createPullRequestMutation.mutate(sandbox.slug)}
                            disabled={sandbox.status !== 'active' || isDeploying || createPullRequestMutation.isPending}
                            className="flex-1 px-3 py-2 rounded-lg text-xs font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50"
                            title="Create and merge a PR to update main"
                          >
                            {isDeploying ? 'Deploying...' : 'Deploy to Main'}
                          </button>
                        )}
                        {sandbox.status === 'active' && (
                          <a
                            href={sandbox.subdomain}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex-1 px-3 py-2 rounded-lg text-xs font-medium text-center bg-primary-100 dark:bg-primary-900/30 text-primary-600 dark:text-primary-400 hover:bg-primary-200 dark:hover:bg-primary-900/50"
                          >
                            Open App
                          </a>
                        )}
                        <button
                          onClick={() => setDeleteConfirm({ slug: sandbox.slug, name: sandbox.name, type: 'sandbox' })}
                          className="p-2 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                        </button>
                      </div>
                    </div>

                    {/* Desktop Layout */}
                    <div className="hidden sm:flex sm:items-center sm:justify-between gap-3">
                      <div className="flex items-center gap-4 min-w-0">
                        <div className={`h-10 w-10 flex-shrink-0 rounded-lg flex items-center justify-center ${
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
                        <div className="min-w-0">
                          <h3 className="font-medium text-gray-900 dark:text-gray-100">{sandbox.name}</h3>
                          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-gray-500 dark:text-gray-400">
                            <span className="font-mono truncate">{sandbox.full_slug}</span>
                            <span>·</span>
                            <span>Branch: {sandbox.git_branch}</span>
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-3 flex-shrink-0">
                        {sandboxTask && (
                          <div className="flex items-center gap-2 text-xs text-blue-600 dark:text-blue-400">
                            <svg className="w-3 h-3 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                            </svg>
                            <span>{sandboxTask.stepName}</span>
                          </div>
                        )}
                        <span className={`px-2 py-1 rounded-full text-xs font-medium ${getStatusBadge(sandbox.status)}`}>
                          {sandbox.status}
                        </span>
                        {canDeploySandbox && (
                          <button
                            onClick={() => createPullRequestMutation.mutate(sandbox.slug)}
                            disabled={sandbox.status !== 'active' || isDeploying || createPullRequestMutation.isPending}
                            className="px-3 py-1.5 rounded-lg text-xs font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50"
                            title="Create and merge a PR to update main"
                          >
                            {isDeploying ? 'Deploying...' : 'Deploy to Main'}
                          </button>
                        )}
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
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}
        </>
      )}

      {/* Members Tab Content */}
      {activeTab === 'members' && (
        <>
        {/* Pending Invitations Section */}
        {pendingInvitations.length > 0 && (
          <div className="bg-white dark:bg-dark-800 rounded-xl shadow dark:shadow-dark-700/30 overflow-hidden mb-4">
            <div className="p-4 border-b border-gray-200 dark:border-dark-700">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Pending Invitations</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Users who have been invited but haven't accepted yet
              </p>
            </div>
            <div className="divide-y divide-gray-200 dark:divide-dark-700">
              {pendingInvitations.map((invitation: WorkspaceInvitation) => (
                <div key={invitation.id} className="p-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 hover:bg-gray-50 dark:hover:bg-dark-700/50">
                  <div className="flex items-center gap-4 min-w-0">
                    <div className="h-10 w-10 flex-shrink-0 rounded-full bg-yellow-100 dark:bg-yellow-900/30 flex items-center justify-center text-yellow-600 dark:text-yellow-400 font-medium">
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                      </svg>
                    </div>
                    <div className="min-w-0">
                      <h3 className="font-medium text-gray-900 dark:text-gray-100 truncate">{invitation.email}</h3>
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-gray-500 dark:text-gray-400">
                        <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${getRoleBadge(invitation.role)}`}>
                          {invitation.role}
                        </span>
                        <span className="hidden sm:inline">·</span>
                        <span>Expires {new Date(invitation.expires_at).toLocaleDateString()}</span>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 ml-14 sm:ml-0">
                    <button
                      onClick={() => {
                        navigator.clipboard.writeText(invitation.invite_url)
                      }}
                      className="text-primary-600 dark:text-primary-400 hover:text-primary-700 dark:hover:text-primary-300 text-sm font-medium flex items-center gap-1"
                      title="Copy invitation link"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3" />
                      </svg>
                      Copy Link
                    </button>
                    {canManageMembers && (
                      <button
                        onClick={() => setCancelInviteConfirm(invitation)}
                        className="text-gray-400 hover:text-red-500 p-1"
                        title="Cancel invitation"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="bg-white dark:bg-dark-800 rounded-xl shadow dark:shadow-dark-700/30 overflow-hidden">
          <div className="p-4 border-b border-gray-200 dark:border-dark-700 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Members</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Team members with access to this workspace
              </p>
            </div>
            {canManageMembers && (
              <button
                onClick={() => setShowInviteMember(true)}
                className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 text-sm font-medium flex items-center gap-2 self-start sm:self-auto"
              >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z" />
              </svg>
              Invite Member
            </button>
          )}
        </div>

        {membersLoading ? (
          <div className="p-8 flex justify-center">
            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary-600"></div>
          </div>
        ) : members.length === 0 ? (
          <div className="p-8 text-center">
            <svg className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
            </svg>
            <p className="mt-2 text-gray-500 dark:text-gray-400">No members yet</p>
          </div>
        ) : (
          <div className="divide-y divide-gray-200 dark:divide-dark-700">
            {members.map((member: WorkspaceMember) => (
              <div key={member.user_id} className="p-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 hover:bg-gray-50 dark:hover:bg-dark-700/50">
                <div className="flex items-center gap-4 min-w-0">
                  <div className="h-10 w-10 flex-shrink-0 rounded-full bg-gray-200 dark:bg-gray-700 flex items-center justify-center text-gray-600 dark:text-gray-300 font-medium">
                    {(member.name || member.email).charAt(0).toUpperCase()}
                  </div>
                  <div className="min-w-0">
                    <h3 className="font-medium text-gray-900 dark:text-gray-100 truncate">
                      {member.name || member.email}
                      {member.user_id === user?.id && (
                        <span className="ml-2 text-xs text-gray-400">(you)</span>
                      )}
                    </h3>
                    <p className="text-sm text-gray-500 dark:text-gray-400 truncate">{member.email}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3 ml-14 sm:ml-0 flex-wrap sm:flex-nowrap">
                  {editingMember === member.user_id ? (
                    <select
                      value={member.role}
                      onChange={(e) => {
                        updateMemberMutation.mutate({
                          userId: member.user_id,
                          role: e.target.value as 'owner' | 'admin' | 'member' | 'viewer'
                        })
                      }}
                      className="px-2 py-1 border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-gray-100 rounded-lg text-sm focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                      disabled={updateMemberMutation.isPending}
                    >
                      {userRole === 'owner' && <option value="owner">Owner</option>}
                      <option value="admin">Admin</option>
                      <option value="member">Member</option>
                      <option value="viewer">Viewer</option>
                    </select>
                  ) : (
                    <span className={`px-2 py-1 rounded-full text-xs font-medium ${getRoleBadge(member.role)}`}>
                      {member.role}
                    </span>
                  )}

                  {/* Actions - owners can edit other owners, admins can only edit non-owners */}
                  {((userRole === 'owner' && member.user_id !== user?.id) || (member.role !== 'owner' && canManageMembers)) && (
                    <div className="flex items-center gap-1">
                      {/* Edit role button */}
                      {editingMember === member.user_id ? (
                        <button
                          onClick={() => setEditingMember(null)}
                          className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 p-1"
                          title="Cancel"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        </button>
                      ) : (
                        <button
                          onClick={() => setEditingMember(member.user_id)}
                          className="text-gray-400 hover:text-primary-600 dark:hover:text-primary-400 p-1"
                          title="Edit role"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                          </svg>
                        </button>
                      )}

                      {/* Remove button */}
                      <button
                        onClick={() => setRemoveMemberConfirm(member)}
                        className="text-gray-400 hover:text-red-500 p-1"
                        title="Remove member"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
        </div>
        </>
      )}

      {/* Settings Tab Content */}
      {activeTab === 'settings' && (
        <div className="bg-white dark:bg-dark-800 rounded-xl shadow dark:shadow-dark-700/30 overflow-hidden">
          <div className="p-4 border-b border-gray-200 dark:border-dark-700">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Workspace Settings</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Configure default settings for this workspace
            </p>
          </div>
          <div className="p-6 space-y-6">
            {/* LLM Provider Setting */}
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Default LLM Provider
              </label>
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-3">
                Select the default AI provider for agents in this workspace. This can be overridden at the column level.
              </p>
              <select
                value={selectedLLMProvider}
                onChange={(e) => setSelectedLLMProvider(e.target.value)}
                className="w-full max-w-md px-3 py-2 border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-gray-100 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              >
                <option value="">System Default (Claude CLI)</option>
                <option value="claude-cli">Claude CLI</option>
                <option value="codex-cli">Codex CLI (OpenAI)</option>
                <option value="abacus-cli">Abacus CLI</option>
              </select>
            </div>

            {/* Save Button */}
            <div className="flex items-center gap-4">
              <button
                onClick={() => updateWorkspaceMutation.mutate({ default_llm_provider: selectedLLMProvider || '' })}
                disabled={updateWorkspaceMutation.isPending || selectedLLMProvider === (workspace?.default_llm_provider || '')}
                className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {updateWorkspaceMutation.isPending ? (
                  <>
                    <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    Saving...
                  </>
                ) : 'Save Settings'}
              </button>
              {settingsSaved && (
                <span className="text-sm text-green-600 dark:text-green-400 flex items-center gap-1">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                  Settings saved
                </span>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Invite Member Modal */}
      {showInviteMember && (
        <div className="fixed inset-0 bg-black/50 dark:bg-black/70 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-dark-800 rounded-xl shadow-xl dark:shadow-dark-900/50 w-full max-w-md p-6">
            {inviteSuccess ? (
              <>
                <div className="text-center mb-4">
                  <div className="w-12 h-12 rounded-full bg-green-100 dark:bg-green-900/30 flex items-center justify-center mx-auto mb-3">
                    <svg className="w-6 h-6 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  </div>
                  <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">Invitation Sent!</h2>
                  <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                    Share this link with <strong>{inviteSuccess.email}</strong>
                  </p>
                </div>

                <div className="bg-gray-50 dark:bg-dark-700 rounded-lg p-3 mb-4">
                  <div className="flex items-center gap-2">
                    <input
                      type="text"
                      readOnly
                      value={inviteSuccess.invite_url}
                      className="flex-1 bg-transparent text-sm text-gray-700 dark:text-gray-300 outline-none overflow-hidden text-ellipsis"
                    />
                    <button
                      onClick={() => {
                        navigator.clipboard.writeText(inviteSuccess.invite_url)
                      }}
                      className="px-3 py-1 bg-primary-600 text-white text-sm rounded hover:bg-primary-700"
                    >
                      Copy
                    </button>
                  </div>
                </div>

                <div className="text-sm text-gray-500 dark:text-gray-400 mb-4">
                  <p>The invitation will expire on {new Date(inviteSuccess.expires_at).toLocaleDateString()}</p>
                </div>

                <div className="flex justify-end">
                  <button
                    type="button"
                    onClick={() => {
                      setShowInviteMember(false)
                      setInviteSuccess(null)
                    }}
                    className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700"
                  >
                    Done
                  </button>
                </div>
              </>
            ) : (
              <>
                <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100 mb-4">Invite Member</h2>

                <form
                  onSubmit={(e) => {
                    e.preventDefault()
                    if (!newMemberEmail.trim()) {
                      setInviteError('Email is required')
                      return
                    }
                    inviteMemberMutation.mutate({ email: newMemberEmail, role: newMemberRole })
                  }}
                  className="space-y-4"
                >
                  {inviteError && (
                    <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 px-3 py-2 rounded-lg text-sm">
                      {inviteError}
                    </div>
                  )}

                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                      Email Address
                    </label>
                    <input
                      type="email"
                      value={newMemberEmail}
                      onChange={(e) => setNewMemberEmail(e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-gray-100 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                      placeholder="user@example.com"
                      autoFocus
                    />
                    <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                      They'll receive a link to join this workspace
                    </p>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                      Role
                    </label>
                    <select
                      value={newMemberRole}
                      onChange={(e) => setNewMemberRole(e.target.value as 'owner' | 'admin' | 'member' | 'viewer')}
                      className="w-full px-3 py-2 border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-gray-100 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    >
                      {userRole === 'owner' && <option value="owner">Owner - Full control over workspace</option>}
                      <option value="admin">Admin - Can manage members and sandboxes</option>
                      <option value="member">Member - Can view and create sandboxes</option>
                      <option value="viewer">Viewer - Read-only access</option>
                    </select>
                  </div>

                  <div className="flex justify-end gap-3 pt-4">
                    <button
                      type="button"
                      onClick={() => {
                        setShowInviteMember(false)
                        setNewMemberEmail('')
                        setNewMemberRole('member')
                        setInviteError('')
                      }}
                      className="px-4 py-2 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-dark-700 rounded-lg"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={inviteMemberMutation.isPending}
                      className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50"
                    >
                      {inviteMemberMutation.isPending ? 'Sending...' : 'Send Invitation'}
                    </button>
                  </div>
                </form>
              </>
            )}
          </div>
        </div>
      )}

      {/* Cancel Invitation Confirmation Modal */}
      {cancelInviteConfirm && (
        <div className="fixed inset-0 bg-black/50 dark:bg-black/70 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-dark-800 rounded-lg shadow-xl dark:shadow-dark-900/50 w-full max-w-md p-6">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
                <svg className="w-6 h-6 text-red-600 dark:text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              </div>
              <div>
                <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">Cancel Invitation</h2>
                <p className="text-sm text-gray-500 dark:text-gray-400">The link will no longer work</p>
              </div>
            </div>

            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 mb-4">
              <p className="text-sm text-red-800 dark:text-red-300">
                Are you sure you want to cancel the invitation for <strong>{cancelInviteConfirm.email}</strong>?
              </p>
            </div>

            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setCancelInviteConfirm(null)}
                className="px-4 py-2 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-dark-700 rounded-lg"
              >
                Keep Invitation
              </button>
              <button
                type="button"
                onClick={() => cancelInviteMutation.mutate(cancelInviteConfirm.id)}
                disabled={cancelInviteMutation.isPending}
                className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
              >
                {cancelInviteMutation.isPending ? 'Cancelling...' : 'Cancel Invitation'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Remove Member Confirmation Modal */}
      {removeMemberConfirm && (
        <div className="fixed inset-0 bg-black/50 dark:bg-black/70 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-dark-800 rounded-lg shadow-xl dark:shadow-dark-900/50 w-full max-w-md p-6">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
                <svg className="w-6 h-6 text-red-600 dark:text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              </div>
              <div>
                <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">Remove Member</h2>
                <p className="text-sm text-gray-500 dark:text-gray-400">This will revoke their access</p>
              </div>
            </div>

            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 mb-4">
              <p className="text-sm text-red-800 dark:text-red-300">
                Are you sure you want to remove <strong>{removeMemberConfirm.name || removeMemberConfirm.email}</strong> from this workspace?
              </p>
            </div>

            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setRemoveMemberConfirm(null)}
                className="px-4 py-2 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-dark-700 rounded-lg"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => removeMemberMutation.mutate(removeMemberConfirm.user_id)}
                disabled={removeMemberMutation.isPending}
                className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
              >
                {removeMemberMutation.isPending ? 'Removing...' : 'Remove'}
              </button>
            </div>
          </div>
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

      {/* Restart Workspace Modal */}
      {showRestartModal && (
        <div className="fixed inset-0 bg-black/50 dark:bg-black/70 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-dark-800 rounded-xl shadow-xl dark:shadow-dark-900/50 w-full max-w-md p-6">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
                <svg className="w-6 h-6 text-blue-600 dark:text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
              </div>
              <div>
                <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">Restart Workspace</h2>
                <p className="text-sm text-gray-500 dark:text-gray-400">Restart workspace containers</p>
              </div>
            </div>

            <div className="space-y-4 mb-6">
              <div className="flex items-start gap-3">
                <input
                  type="checkbox"
                  id="rebuild"
                  checked={restartRebuild}
                  onChange={(e) => setRestartRebuild(e.target.checked)}
                  className="mt-1 h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
                />
                <label htmlFor="rebuild" className="text-sm">
                  <span className="font-medium text-gray-900 dark:text-gray-100">Rebuild containers</span>
                  <p className="text-gray-500 dark:text-gray-400">
                    Rebuild images from scratch (slower, but ensures latest code)
                  </p>
                </label>
              </div>

              {workspace?.app_subdomain && (
                <div className="flex items-start gap-3">
                  <input
                    type="checkbox"
                    id="restart_app"
                    checked={restartApp}
                    onChange={(e) => setRestartApp(e.target.checked)}
                    className="mt-1 h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
                  />
                  <label htmlFor="restart_app" className="text-sm">
                    <span className="font-medium text-gray-900 dark:text-gray-100">Include app containers</span>
                    <p className="text-gray-500 dark:text-gray-400">
                      Also restart/rebuild the application containers
                    </p>
                  </label>
                </div>
              )}
            </div>

            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={() => {
                  setShowRestartModal(false)
                  setRestartRebuild(false)
                  setRestartApp(true)
                }}
                className="px-4 py-2 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-dark-700 rounded-lg"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => restartWorkspaceMutation.mutate({
                  rebuild: restartRebuild,
                  restart_app: restartApp
                })}
                disabled={restartWorkspaceMutation.isPending}
                className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50"
              >
                {restartWorkspaceMutation.isPending ? 'Restarting...' : 'Restart'}
              </button>
            </div>
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

            {/* GitHub repo deletion option - only show for workspaces with repos */}
            {deleteConfirm.type === 'workspace' && workspace?.github_repo_url && (
              <div className="mb-4">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={deleteRepoOnDelete}
                    onChange={(e) => setDeleteRepoOnDelete(e.target.checked)}
                    className="w-4 h-4 text-red-600 border-gray-300 rounded focus:ring-red-500"
                  />
                  <span className="text-sm text-gray-700 dark:text-gray-300">Also delete GitHub repository</span>
                </label>
                {deleteRepoOnDelete && (
                  <p className="mt-1 ml-6 text-xs text-red-600 dark:text-red-400">
                    Warning: This will permanently delete the repository!
                  </p>
                )}
              </div>
            )}

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
                  setDeleteRepoOnDelete(false)
                }}
                className="px-4 py-2 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-dark-700 rounded-lg"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  if (deleteConfirm.type === 'workspace') {
                    deleteWorkspaceMutation.mutate({ delete_github_repo: deleteRepoOnDelete })
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

      {/* Link App Modal */}
      {showLinkAppModal && (
        <div className="fixed inset-0 bg-black/50 dark:bg-black/70 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-dark-800 rounded-xl shadow-xl dark:shadow-dark-900/50 w-full max-w-lg p-6">
            <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100 mb-4">Link App to Workspace</h2>

            {/* Mode Selection */}
            <div className="flex gap-4 mb-6">
              <button
                type="button"
                onClick={() => setLinkAppMode('template')}
                className={`flex-1 p-4 rounded-lg border-2 transition-colors ${
                  linkAppMode === 'template'
                    ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/20'
                    : 'border-gray-200 dark:border-dark-600 hover:border-gray-300 dark:hover:border-dark-500'
                }`}
              >
                <div className="flex items-center gap-3">
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center ${
                    linkAppMode === 'template'
                      ? 'bg-primary-100 dark:bg-primary-900/30'
                      : 'bg-gray-100 dark:bg-gray-700'
                  }`}>
                    <svg className={`w-4 h-4 ${
                      linkAppMode === 'template' ? 'text-primary-600 dark:text-primary-400' : 'text-gray-500 dark:text-gray-400'
                    }`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" />
                    </svg>
                  </div>
                  <div className="text-left">
                    <h3 className={`font-medium ${
                      linkAppMode === 'template' ? 'text-primary-700 dark:text-primary-300' : 'text-gray-900 dark:text-gray-100'
                    }`}>From Template</h3>
                    <p className="text-sm text-gray-500 dark:text-gray-400">Create new repo from template</p>
                  </div>
                </div>
              </button>
              <button
                type="button"
                onClick={() => setLinkAppMode('repo')}
                className={`flex-1 p-4 rounded-lg border-2 transition-colors ${
                  linkAppMode === 'repo'
                    ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/20'
                    : 'border-gray-200 dark:border-dark-600 hover:border-gray-300 dark:hover:border-dark-500'
                }`}
              >
                <div className="flex items-center gap-3">
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center ${
                    linkAppMode === 'repo'
                      ? 'bg-primary-100 dark:bg-primary-900/30'
                      : 'bg-gray-100 dark:bg-gray-700'
                  }`}>
                    <svg className={`w-4 h-4 ${
                      linkAppMode === 'repo' ? 'text-primary-600 dark:text-primary-400' : 'text-gray-500 dark:text-gray-400'
                    }`} fill="currentColor" viewBox="0 0 24 24">
                      <path fillRule="evenodd" clipRule="evenodd" d="M12 2C6.477 2 2 6.477 2 12c0 4.42 2.87 8.17 6.84 9.5.5.08.66-.23.66-.5v-1.69c-2.77.6-3.36-1.34-3.36-1.34-.46-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.87 1.52 2.34 1.07 2.91.83.09-.65.35-1.09.63-1.34-2.22-.25-4.55-1.11-4.55-4.92 0-1.11.38-2 1.03-2.71-.1-.25-.45-1.29.1-2.64 0 0 .84-.27 2.75 1.02.79-.22 1.65-.33 2.5-.33.85 0 1.71.11 2.5.33 1.91-1.29 2.75-1.02 2.75-1.02.55 1.35.2 2.39.1 2.64.65.71 1.03 1.6 1.03 2.71 0 3.82-2.34 4.66-4.57 4.91.36.31.69.92.69 1.85V21c0 .27.16.59.67.5C19.14 20.16 22 16.42 22 12A10 10 0 0012 2z" />
                    </svg>
                  </div>
                  <div className="text-left">
                    <h3 className={`font-medium ${
                      linkAppMode === 'repo' ? 'text-primary-700 dark:text-primary-300' : 'text-gray-900 dark:text-gray-100'
                    }`}>Existing Repository</h3>
                    <p className="text-sm text-gray-500 dark:text-gray-400">Use existing GitHub repo</p>
                  </div>
                </div>
              </button>
            </div>

            {linkAppMode === 'template' ? (
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    App Template
                  </label>
                  <select
                    value={selectedTemplate}
                    onChange={(e) => setSelectedTemplate(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-gray-100 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  >
                    <option value="">Select a template...</option>
                    {appTemplates.map((t: AppTemplate) => (
                      <option key={t.slug} value={t.slug}>{t.name}</option>
                    ))}
                  </select>
                  {appTemplates.length === 0 && (
                    <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">No app templates available</p>
                  )}
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    GitHub Repository URL
                  </label>
                  <input
                    type="url"
                    value={existingRepoUrl}
                    onChange={(e) => setExistingRepoUrl(e.target.value)}
                    placeholder="https://github.com/org/repo"
                    className="w-full px-3 py-2 border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-gray-100 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  />
                  <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                    Enter the full URL to an existing GitHub repository
                  </p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    GitHub Personal Access Token (optional)
                  </label>
                  <input
                    type="password"
                    value={existingRepoPat}
                    onChange={(e) => setExistingRepoPat(e.target.value)}
                    placeholder="ghp_xxxxxxxxxxxx"
                    className="w-full px-3 py-2 border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-gray-100 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  />
                  <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                    If not provided, the default PAT from the keyvault will be used
                  </p>
                </div>
              </div>
            )}

            {linkAppError && (
              <div className="mt-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 px-3 py-2 rounded-lg text-sm">
                {linkAppError}
              </div>
            )}

            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => {
                  setShowLinkAppModal(false)
                  setSelectedTemplate('')
                  setExistingRepoUrl('')
                  setExistingRepoPat('')
                  setLinkAppError('')
                  setLinkAppMode('template')
                }}
                className="px-4 py-2 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-dark-700 rounded-lg"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleLinkApp}
                disabled={linkAppMutation.isPending}
                className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50"
              >
                {linkAppMutation.isPending ? 'Linking...' : 'Link App'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Unlink App Modal */}
      {showUnlinkAppModal && (
        <div className="fixed inset-0 bg-black/50 dark:bg-black/70 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-dark-800 rounded-xl shadow-xl dark:shadow-dark-900/50 w-full max-w-md p-6">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center">
                <svg className="w-6 h-6 text-amber-600 dark:text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              </div>
              <div>
                <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">Unlink App</h2>
                <p className="text-sm text-gray-500 dark:text-gray-400">Remove app from workspace</p>
              </div>
            </div>

            <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg p-4 mb-4">
              <p className="text-sm text-amber-800 dark:text-amber-300">
                This will remove the app and all sandboxes from this workspace.
                The kanban board will remain active.
              </p>
            </div>

            <div className="mb-4">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={deleteRepoOnUnlink}
                  onChange={(e) => setDeleteRepoOnUnlink(e.target.checked)}
                  className="h-4 w-4 text-amber-600 focus:ring-amber-500 border-gray-300 rounded"
                />
                <span className="text-sm text-gray-700 dark:text-gray-300">Also delete GitHub repository</span>
              </label>
              {deleteRepoOnUnlink && (
                <p className="mt-1 ml-6 text-xs text-red-600 dark:text-red-400">
                  Warning: This will permanently delete the repository!
                </p>
              )}
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Type <strong>unlink</strong> to confirm
              </label>
              <input
                type="text"
                value={unlinkConfirmInput}
                onChange={(e) => setUnlinkConfirmInput(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-gray-100 rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-transparent"
                placeholder="unlink"
              />
            </div>

            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={() => {
                  setShowUnlinkAppModal(false)
                  setDeleteRepoOnUnlink(false)
                  setUnlinkConfirmInput('')
                }}
                className="px-4 py-2 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-dark-700 rounded-lg"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => unlinkAppMutation.mutate({ delete_github_repo: deleteRepoOnUnlink })}
                disabled={unlinkConfirmInput !== 'unlink' || unlinkAppMutation.isPending}
                className="px-4 py-2 bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {unlinkAppMutation.isPending ? 'Unlinking...' : 'Unlink App'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
