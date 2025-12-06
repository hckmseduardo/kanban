import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { teamsApi, authApi, setNavigatingAway } from '../services/api'
import { useAuthStore } from '../stores/authStore'

export default function TeamsPage() {
  const { user } = useAuthStore()

  const { data: teams, isLoading } = useQuery({
    queryKey: ['teams'],
    queryFn: () => teamsApi.list().then(res => res.data),
    staleTime: 5 * 60 * 1000, // 5 minutes - prevent unnecessary refetches
    refetchOnWindowFocus: false, // Don't refetch when window regains focus
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
                  <div className="h-12 w-12 bg-primary-100 rounded-full flex items-center justify-center">
                    <span className="text-primary-600 text-lg font-semibold">
                      {team.name.charAt(0).toUpperCase()}
                    </span>
                  </div>
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
                  'bg-gray-100 text-gray-800'
                }`}>
                  {team.status}
                </span>
                {team.status === 'active' && (
                  <button
                    onClick={() => handleOpenTeam(team)}
                    className="text-primary-600 hover:text-primary-700 text-sm font-medium"
                  >
                    Open Board →
                  </button>
                )}
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
    </div>
  )
}
