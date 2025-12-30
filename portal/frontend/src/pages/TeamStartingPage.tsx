import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { teamsApi, authApi, setNavigatingAway } from '../services/api'
import { useAuthStore } from '../stores/authStore'
import { useTaskWebSocket } from '../hooks/useTaskWebSocket'

interface Progress {
  step: number
  total: number
  name: string
}

export default function TeamStartingPage() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const { user } = useAuthStore()
  const [progress, setProgress] = useState<Progress>({ step: 0, total: 4, name: 'Initializing...' })
  const [error, setError] = useState<string | null>(null)
  const [taskId, setTaskId] = useState<string | null>(null)

  // WebSocket for real-time progress updates
  useTaskWebSocket({
    onTaskUpdate: (update) => {
      if (update.task_id === taskId && update.type === 'task.progress') {
        setProgress({
          step: update.step || 0,
          total: update.total_steps || 4,
          name: update.step_name || 'Processing...'
        })
      }
    },
    onTaskCompleted: (completedTaskId, result) => {
      if (completedTaskId === taskId) {
        console.log('[TeamStartingPage] Task completed:', result)
        redirectToTeam()
      }
    },
    onTaskFailed: (failedTaskId, errorMsg) => {
      if (failedTaskId === taskId) {
        console.log('[TeamStartingPage] Task failed:', errorMsg)
        setError(errorMsg || 'Failed to start team')
      }
    }
  })

  // Start the team
  const startMutation = useMutation({
    mutationFn: () => teamsApi.start(slug!),
    onSuccess: (response) => {
      const data = response.data
      console.log('[TeamStartingPage] Start response:', data)

      if (data.status === 'active') {
        // Team already active, redirect immediately
        redirectToTeam()
      } else if (data.task_id) {
        setTaskId(data.task_id)
      } else if (data.status === 'starting') {
        // Already starting, poll for status
        setTaskId('polling')
      }
    },
    onError: (err: any) => {
      console.error('[TeamStartingPage] Start error:', err)
      setError(err.response?.data?.detail || 'Failed to start team')
    }
  })

  // Redirect to the team subdomain
  const redirectToTeam = async () => {
    if (!user || !slug) return

    setNavigatingAway()

    try {
      // Get team info
      const teamResponse = await teamsApi.get(slug)
      const team = teamResponse.data

      // Get SSO token
      const tokenResponse = await authApi.getCrossDomainToken(slug, user.id)
      const { token } = tokenResponse.data

      // Redirect to team
      const teamUrl = `${team.subdomain}?sso_token=${token}`
      console.log('[TeamStartingPage] Redirecting to:', teamUrl)
      window.location.href = teamUrl
    } catch (err) {
      console.error('[TeamStartingPage] Redirect failed:', err)
      setError('Team started but redirect failed. Please try again.')
    }
  }

  // Auto-start when page loads
  useEffect(() => {
    if (slug && !taskId && !startMutation.isPending && !error) {
      console.log('[TeamStartingPage] Auto-starting team:', slug)
      startMutation.mutate()
    }
  }, [slug])

  // Poll for status as backup (in case WebSocket misses the update)
  const { data: statusData } = useQuery({
    queryKey: ['team-status', slug],
    queryFn: () => teamsApi.getStatus(slug!),
    refetchInterval: taskId ? 3000 : false,
    enabled: !!taskId && taskId !== 'polling'
  })

  useEffect(() => {
    if (statusData?.data?.status === 'active') {
      console.log('[TeamStartingPage] Status poll: team is active')
      redirectToTeam()
    }
  }, [statusData])

  const progressPercentage = progress.total > 0
    ? Math.round((progress.step / progress.total) * 100)
    : 0

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="max-w-md w-full bg-white rounded-lg shadow-lg p-8">
        <div className="text-center">
          <div className="mb-6">
            <div className="w-16 h-16 bg-blue-100 rounded-full flex items-center justify-center mx-auto">
              {error ? (
                <svg className="w-8 h-8 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              ) : (
                <svg className="w-8 h-8 text-blue-600 animate-pulse" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
                </svg>
              )}
            </div>
          </div>

          <h1 className="text-xl font-semibold text-gray-900 mb-2">
            {error ? 'Startup Failed' : 'Starting Team'}
          </h1>

          <p className="text-gray-500 mb-6">
            {error ? error : progress.name}
          </p>

          {!error && (
            <>
              <div className="w-full bg-gray-200 rounded-full h-2 mb-4">
                <div
                  className="bg-blue-600 h-2 rounded-full transition-all duration-500"
                  style={{ width: `${progressPercentage}%` }}
                />
              </div>

              <p className="text-sm text-gray-400">
                Step {progress.step} of {progress.total}
              </p>
            </>
          )}

          {error && (
            <div className="mt-6 flex gap-3 justify-center">
              <button
                onClick={() => navigate('/teams')}
                className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg"
              >
                Back to Teams
              </button>
              <button
                onClick={() => {
                  setError(null)
                  setTaskId(null)
                  startMutation.mutate()
                }}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
              >
                Retry
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
