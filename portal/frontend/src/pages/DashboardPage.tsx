import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { usersApi, teamsApi, authApi, setNavigatingAway } from '../services/api'
import { useAuthStore } from '../stores/authStore'

export default function DashboardPage() {
  const { user } = useAuthStore()
  const queryClient = useQueryClient()
  const [deleteConfirm, setDeleteConfirm] = useState<{ slug: string; name: string } | null>(null)
  const [deleteInput, setDeleteInput] = useState('')

  const { data: teams, isLoading } = useQuery({
    queryKey: ['user-teams'],
    queryFn: () => usersApi.teams().then(res => res.data),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  })

  const deleteMutation = useMutation({
    mutationFn: (slug: string) => teamsApi.delete(slug),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['user-teams'] })
      setDeleteConfirm(null)
      setDeleteInput('')
    }
  })

  const handleOpenTeam = async (team: any) => {
    if (!user) return

    setNavigatingAway()

    try {
      const response = await authApi.getCrossDomainToken(team.slug, user.id)
      const { token } = response.data
      const teamUrl = `${team.subdomain}?sso_token=${token}`
      window.location.href = teamUrl
    } catch (error) {
      console.error('SSO failed, redirecting without token:', error)
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
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Your Teams</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">Click on a team to open its workspace, or create a new one to get started</p>
      </div>

      {/* Teams Grid */}
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {teams?.map((team: any) => (
          <div
            key={team.id}
            onClick={() => team.status === 'active' && handleOpenTeam(team)}
            className={`bg-white dark:bg-dark-800 overflow-hidden shadow dark:shadow-dark-700/30 rounded-xl transition-all duration-200 flex flex-col ${
              team.status === 'active'
                ? 'cursor-pointer hover:shadow-lg dark:hover:shadow-dark-700/50 hover:-translate-y-1 hover:ring-2 hover:ring-primary-400 dark:hover:ring-primary-500'
                : 'opacity-75'
            }`}
          >
            {/* Colored top border based on status */}
            <div className={`h-1.5 ${
              team.status === 'active' ? 'bg-gradient-to-r from-primary-500 to-primary-600' :
              team.status === 'provisioning' ? 'bg-gradient-to-r from-yellow-400 to-yellow-500' :
              team.status === 'pending_deletion' ? 'bg-gradient-to-r from-red-400 to-red-500' :
              'bg-gray-300 dark:bg-dark-600'
            }`} />
            <div className="p-5 flex-1 flex flex-col">
              <div className="flex items-start gap-3">
                {/* Team Avatar/Badge */}
                <div className="flex-shrink-0">
                  {team.badge ? (
                    team.badge.startsWith('http') ? (
                      <img
                        src={team.badge}
                        alt={team.name}
                        className="h-14 w-14 rounded-xl object-cover"
                      />
                    ) : (
                      <div className={`h-14 w-14 rounded-xl flex items-center justify-center text-2xl ${
                        team.status === 'active' ? 'bg-gradient-to-br from-primary-100 to-primary-200 dark:from-primary-900/50 dark:to-primary-800/50' : 'bg-gray-200 dark:bg-dark-700'
                      }`}>
                        {team.badge}
                      </div>
                    )
                  ) : (
                    <div className={`h-14 w-14 rounded-xl flex items-center justify-center transition-transform duration-200 ${
                      team.status === 'active' ? 'bg-gradient-to-br from-primary-400 to-primary-600' : 'bg-gray-300 dark:bg-dark-600'
                    }`}>
                      <span className="text-white text-xl font-bold">
                        {team.name.charAt(0).toUpperCase()}
                      </span>
                    </div>
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100 truncate">{team.name}</h3>
                  <p className="text-sm text-gray-400 dark:text-gray-500 font-mono">{team.slug}</p>
                </div>
              </div>
              {team.description && (
                <p className="mt-3 text-sm text-gray-500 dark:text-gray-400 line-clamp-2">{team.description}</p>
              )}
              <div className="mt-4 flex items-center justify-between flex-1 items-end">
                <span className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-medium ${
                  team.status === 'active' ? 'bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-400 ring-1 ring-green-200 dark:ring-green-800' :
                  team.status === 'provisioning' ? 'bg-yellow-50 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400 ring-1 ring-yellow-200 dark:ring-yellow-800' :
                  team.status === 'pending_deletion' ? 'bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400 ring-1 ring-red-200 dark:ring-red-800' :
                  'bg-gray-50 dark:bg-dark-700 text-gray-600 dark:text-gray-400 ring-1 ring-gray-200 dark:ring-dark-600'
                }`}>
                  {team.status === 'pending_deletion' ? 'Deleting...' :
                   team.status === 'provisioning' ? 'Setting up...' :
                   team.status === 'active' ? 'Active' : team.status}
                </span>
                <div className="flex items-center gap-2">
                  {team.owner_id === user?.id && team.status !== 'pending_deletion' && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        setDeleteConfirm({ slug: team.slug, name: team.name })
                      }}
                      className="text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/30 p-1.5 rounded-lg transition-all"
                      title="Delete team"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  )}
                  {team.status === 'active' && (
                    <span className="text-primary-600 dark:text-primary-400 text-sm font-medium flex items-center gap-1">
                      Open
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                      </svg>
                    </span>
                  )}
                </div>
              </div>
            </div>
          </div>
        ))}

        {/* Create New Team Card */}
        <Link
          to="/teams/new"
          className="bg-white dark:bg-dark-800 overflow-hidden shadow dark:shadow-dark-700/30 rounded-xl transition-all duration-200 border-2 border-dashed border-gray-200 dark:border-dark-600 hover:border-primary-400 dark:hover:border-primary-500 hover:shadow-lg hover:-translate-y-1 group"
        >
          <div className="h-1.5 bg-gray-100 dark:bg-dark-700 group-hover:bg-gradient-to-r group-hover:from-primary-400 group-hover:to-primary-600 transition-all duration-200" />
          <div className="p-5 h-full flex flex-col items-center justify-center min-h-[180px]">
            <div className="h-14 w-14 bg-gray-100 dark:bg-dark-700 group-hover:bg-gradient-to-br group-hover:from-primary-400 group-hover:to-primary-600 rounded-xl flex items-center justify-center transition-all duration-200">
              <svg className="w-7 h-7 text-gray-400 dark:text-gray-500 group-hover:text-white transition-colors duration-200" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
            </div>
            <h3 className="mt-4 text-lg font-semibold text-gray-900 dark:text-gray-100 group-hover:text-primary-600 dark:group-hover:text-primary-400 transition-colors">
              Create New Team
            </h3>
            <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">Start a new project workspace</p>
          </div>
        </Link>
      </div>

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
                <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">Delete Team</h2>
                <p className="text-sm text-gray-500 dark:text-gray-400">This action cannot be undone</p>
              </div>
            </div>

            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 mb-4">
              <p className="text-sm text-red-800 dark:text-red-300">
                You are about to delete <strong>{deleteConfirm.name}</strong>. This will:
              </p>
              <ul className="mt-2 text-sm text-red-700 dark:text-red-400 list-disc list-inside space-y-1">
                <li>Stop and remove all containers</li>
                <li>Archive all boards and data</li>
                <li>Remove all team members</li>
              </ul>
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
