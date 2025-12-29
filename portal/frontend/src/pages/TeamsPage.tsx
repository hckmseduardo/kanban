import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { teamsApi, authApi, setNavigatingAway } from '../services/api'
import { useAuthStore } from '../stores/authStore'
import { useTaskWebSocket } from '../hooks/useTaskWebSocket'

interface Toast {
  id: string
  type: 'success' | 'error' | 'info'
  message: string
}

export default function TeamsPage() {
  const { user } = useAuthStore()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [deleteConfirm, setDeleteConfirm] = useState<{ slug: string; name: string } | null>(null)
  const [deleteInput, setDeleteInput] = useState('')
  const [toasts, setToasts] = useState<Toast[]>([])

  // Show toast notification
  const showToast = (type: Toast['type'], message: string) => {
    const id = Date.now().toString()
    setToasts(prev => [...prev, { id, type, message }])
    // Auto-dismiss after 5 seconds
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id))
    }, 5000)
  }

  // Handle error query parameters (e.g., from team redirect on 403)
  useEffect(() => {
    const error = searchParams.get('error')
    const team = searchParams.get('team')

    if (error === 'not_a_member' && team) {
      showToast('error', `You don't have access to team "${team}". Please request an invitation.`)
      // Clean up URL
      searchParams.delete('error')
      searchParams.delete('team')
      setSearchParams(searchParams)
    }
  }, [searchParams, setSearchParams])

  // WebSocket for real-time task updates
  useTaskWebSocket({
    onTaskCompleted: (_taskId, result) => {
      const action = (result as any)?.action
      const teamSlug = (result as any)?.team_slug

      if (action === 'create_team') {
        showToast('success', `Team "${teamSlug}" created successfully!`)
      } else if (action === 'delete_team') {
        showToast('success', `Team "${teamSlug}" deleted successfully!`)
      }

      // Refresh teams list
      queryClient.invalidateQueries({ queryKey: ['teams'] })
    },
    onTaskFailed: (_taskId, error) => {
      showToast('error', `Task failed: ${error || 'Unknown error'}`)
      // Refresh to show current state
      queryClient.invalidateQueries({ queryKey: ['teams'] })
    }
  })

  const { data: teams, isLoading, refetch } = useQuery({
    queryKey: ['teams'],
    queryFn: () => teamsApi.list().then(res => res.data),
    staleTime: 30 * 1000, // 30 seconds - allow quicker updates after changes
    refetchOnWindowFocus: true, // Refetch when window regains focus
  })

  const deleteMutation = useMutation({
    mutationFn: (slug: string) => teamsApi.delete(slug),
    onMutate: async (slug: string) => {
      // Cancel outgoing refetches
      await queryClient.cancelQueries({ queryKey: ['teams'] })

      // Snapshot previous value
      const previousTeams = queryClient.getQueryData(['teams'])

      // Optimistically remove the team from the list
      queryClient.setQueryData(['teams'], (old: any[]) =>
        old?.filter((team: any) => team.slug !== slug) || []
      )

      // Close modal immediately
      setDeleteConfirm(null)
      setDeleteInput('')

      return { previousTeams }
    },
    onError: (_err, _slug, context) => {
      // Rollback on error
      if (context?.previousTeams) {
        queryClient.setQueryData(['teams'], context.previousTeams)
      }
    },
    onSettled: () => {
      // Refetch to ensure consistency
      queryClient.invalidateQueries({ queryKey: ['teams'] })
    }
  })

  const handleOpenTeam = async (team: any) => {
    console.log('[TeamsPage] handleOpenTeam called', { team, user })
    if (!user) {
      console.error('[TeamsPage] No user - returning early')
      return
    }

    // Mark that we're navigating away to prevent 401 handler from redirecting to login
    setNavigatingAway()

    try {
      // Get cross-domain token for SSO
      console.log('[TeamsPage] Requesting cross-domain token for:', team.slug, 'user:', user.id)
      const response = await authApi.getCrossDomainToken(team.slug, user.id)
      const { token } = response.data
      console.log('[TeamsPage] Got SSO token, redirecting to team')

      // Redirect to team with token
      const teamUrl = `${team.subdomain}?sso_token=${token}`
      console.log('[TeamsPage] Redirecting to:', teamUrl)
      window.location.href = teamUrl
    } catch (error) {
      console.error('[TeamsPage] SSO failed, redirecting without token:', error)
      window.location.href = team.subdomain
    }
  }

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold text-gray-900">Teams</h1>
        <Link
          to="/teams/new"
          className="inline-flex items-center px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-primary-600 hover:bg-primary-700"
        >
          Create Team
        </Link>
      </div>

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {teams?.map((team: any) => (
          <div key={team.id} className="bg-white overflow-hidden shadow rounded-lg">
            <div className="p-5">
              <div className="flex items-center">
                <div className="flex-shrink-0">
                  {team.badge ? (
                    team.badge.startsWith('http') ? (
                      <img
                        src={team.badge}
                        alt={team.name}
                        className="h-12 w-12 rounded-full object-cover ring-2 ring-primary-100"
                      />
                    ) : (
                      <div className="h-12 w-12 bg-gradient-to-br from-primary-100 to-primary-200 rounded-full flex items-center justify-center text-2xl ring-2 ring-primary-100">
                        {team.badge}
                      </div>
                    )
                  ) : (
                    <div className="h-12 w-12 bg-primary-100 rounded-full flex items-center justify-center">
                      <span className="text-primary-600 text-lg font-semibold">
                        {team.name.charAt(0).toUpperCase()}
                      </span>
                    </div>
                  )}
                </div>
                <div className="ml-4">
                  <h3 className="text-lg font-medium text-gray-900">{team.name}</h3>
                  <p className="text-sm text-gray-500">{team.slug}</p>
                </div>
              </div>
              {team.description && (
                <p className="mt-4 text-sm text-gray-600">{team.description}</p>
              )}
              <div className="mt-4 flex items-center justify-between">
                <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                  team.status === 'active' ? 'bg-green-100 text-green-800' :
                  team.status === 'provisioning' ? 'bg-yellow-100 text-yellow-800' :
                  team.status === 'pending_deletion' ? 'bg-red-100 text-red-800' :
                  'bg-gray-100 text-gray-800'
                }`}>
                  {team.status === 'pending_deletion' ? 'Deleting...' : team.status}
                </span>
                <div className="flex items-center gap-2">
                  {team.status === 'active' && (
                    <button
                      onClick={() => handleOpenTeam(team)}
                      className="text-primary-600 hover:text-primary-700 text-sm font-medium"
                    >
                      Open Board →
                    </button>
                  )}
                  {team.status !== 'pending_deletion' && (
                    <Link
                      to={`/teams/${team.slug}`}
                      className="text-gray-500 hover:text-gray-700 p-1"
                      title="Team settings & API tokens"
                    >
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                      </svg>
                    </Link>
                  )}
                  {team.owner_id === user?.id && team.status !== 'pending_deletion' && (
                    <button
                      onClick={() => setDeleteConfirm({ slug: team.slug, name: team.name })}
                      className="text-red-500 hover:text-red-700 p-1"
                      title="Delete team"
                    >
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  )}
                </div>
              </div>
            </div>
          </div>
        ))}

        {teams?.length === 0 && (
          <div className="col-span-full text-center py-12">
            <p className="text-gray-500">No teams yet</p>
            <Link
              to="/teams/new"
              className="mt-4 inline-flex items-center text-primary-600 hover:text-primary-700"
            >
              Create your first team
            </Link>
          </div>
        )}
      </div>

      {/* Toast Notifications */}
      <div className="fixed bottom-4 right-4 z-50 space-y-2">
        {toasts.map(toast => (
          <div
            key={toast.id}
            className={`px-4 py-3 rounded-lg shadow-lg flex items-center gap-3 animate-slide-in ${
              toast.type === 'success' ? 'bg-green-500 text-white' :
              toast.type === 'error' ? 'bg-red-500 text-white' :
              'bg-blue-500 text-white'
            }`}
          >
            {toast.type === 'success' && (
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            )}
            {toast.type === 'error' && (
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            )}
            <span>{toast.message}</span>
            <button
              onClick={() => setToasts(prev => prev.filter(t => t.id !== toast.id))}
              className="ml-2 hover:opacity-75"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        ))}
      </div>

      {/* Delete Confirmation Modal */}
      {deleteConfirm && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-md p-6">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center">
                <svg className="w-6 h-6 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              </div>
              <div>
                <h2 className="text-lg font-bold text-gray-900">Delete Team</h2>
                <p className="text-sm text-gray-500">This action cannot be undone</p>
              </div>
            </div>

            <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-4">
              <p className="text-sm text-red-800">
                You are about to delete <strong>{deleteConfirm.name}</strong>. This will:
              </p>
              <ul className="mt-2 text-sm text-red-700 list-disc list-inside space-y-1">
                <li>Stop and remove all containers</li>
                <li>Archive all boards and data</li>
                <li>Remove all team members</li>
              </ul>
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Type <strong>{deleteConfirm.slug}</strong> to confirm
              </label>
              <input
                type="text"
                value={deleteInput}
                onChange={(e) => setDeleteInput(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-red-500 focus:border-transparent"
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
                className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => deleteMutation.mutate(deleteConfirm.slug)}
                disabled={deleteInput !== deleteConfirm.slug || deleteMutation.isPending}
                className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {deleteMutation.isPending ? 'Deleting...' : 'Delete Team'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
