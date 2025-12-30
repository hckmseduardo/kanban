import { useState, useEffect, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { teamsApi, apiTokensApi, ApiToken } from '../services/api'

export default function TeamDetailPage() {
  const { slug } = useParams<{ slug: string }>()
  const queryClient = useQueryClient()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [newTokenName, setNewTokenName] = useState('')
  const [newTokenExpiry, setNewTokenExpiry] = useState<string>('')
  const [createdToken, setCreatedToken] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [copiedUrl, setCopiedUrl] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState<ApiToken | null>(null)
  const [restartConfirm, setRestartConfirm] = useState<'restart' | 'rebuild' | null>(null)
  const [restartMessage, setRestartMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const previousStatusRef = useRef<string | undefined>(undefined)

  const { data: team, isLoading: teamLoading } = useQuery({
    queryKey: ['team', slug],
    queryFn: () => teamsApi.get(slug!).then(res => res.data),
    enabled: !!slug,
    // Poll every 3 seconds when team is restarting to show status updates
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'restarting' ? 3000 : false
    },
  })

  const { data: tokens, isLoading: tokensLoading } = useQuery({
    queryKey: ['api-tokens', slug],
    queryFn: () => apiTokensApi.list(slug!).then(res => res.data),
    enabled: !!slug,
  })

  const createMutation = useMutation({
    mutationFn: () => {
      const expiryDays = newTokenExpiry ? parseInt(newTokenExpiry) : undefined
      return apiTokensApi.create(slug!, {
        name: newTokenName,
        expires_in_days: expiryDays,
      })
    },
    onSuccess: (response) => {
      setCreatedToken(response.data.plaintext_token)
      setNewTokenName('')
      setNewTokenExpiry('')
      queryClient.invalidateQueries({ queryKey: ['api-tokens', slug] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (tokenId: string) => apiTokensApi.delete(slug!, tokenId),
    onSuccess: () => {
      setDeleteConfirm(null)
      queryClient.invalidateQueries({ queryKey: ['api-tokens', slug] })
    },
  })

  const restartMutation = useMutation({
    mutationFn: (rebuild: boolean) => teamsApi.restart(slug!, rebuild),
    onSuccess: (response) => {
      setRestartConfirm(null)
      setRestartMessage({
        type: 'success',
        text: `Team ${restartConfirm === 'rebuild' ? 'rebuild' : 'restart'} initiated. Task ID: ${response.data.task_id}`
      })
      queryClient.invalidateQueries({ queryKey: ['team', slug] })
      // Clear message after 10 seconds
      setTimeout(() => setRestartMessage(null), 10000)
    },
    onError: (error: Error & { response?: { data?: { detail?: string } } }) => {
      setRestartConfirm(null)
      setRestartMessage({
        type: 'error',
        text: error.response?.data?.detail || 'Failed to restart team containers'
      })
      setTimeout(() => setRestartMessage(null), 10000)
    },
  })

  // Detect when restart/rebuild completes
  useEffect(() => {
    const currentStatus = team?.status
    const previousStatus = previousStatusRef.current

    // If status changed from 'restarting' to 'active', show completion message
    if (previousStatus === 'restarting' && currentStatus === 'active') {
      setRestartMessage({
        type: 'success',
        text: 'Team containers are now running!'
      })
      setTimeout(() => setRestartMessage(null), 5000)
    }

    // Update previous status ref
    previousStatusRef.current = currentStatus
  }, [team?.status])

  const handleCopyToken = async () => {
    if (createdToken) {
      await navigator.clipboard.writeText(createdToken)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const handleCopyUrl = async () => {
    if (team?.subdomain) {
      const apiUrl = `${team.subdomain}/api`
      await navigator.clipboard.writeText(apiUrl)
      setCopiedUrl(true)
      setTimeout(() => setCopiedUrl(false), 2000)
    }
  }

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return 'Never'
    return new Date(dateStr).toLocaleString()
  }

  if (teamLoading) {
    return (
      <div className="flex justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
      </div>
    )
  }

  if (!team) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500">Team not found</p>
        <Link to="/" className="text-primary-600 hover:text-primary-700">
          Back to Dashboard
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link to="/" className="text-gray-500 hover:text-gray-700">
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
          </svg>
        </Link>
        <div className="flex items-center gap-3">
          {team.badge ? (
            team.badge.startsWith('http') ? (
              <img src={team.badge} alt={team.name} className="h-10 w-10 rounded-full object-cover" />
            ) : (
              <div className="h-10 w-10 bg-gradient-to-br from-primary-100 to-primary-200 rounded-full flex items-center justify-center text-xl">
                {team.badge}
              </div>
            )
          ) : (
            <div className="h-10 w-10 bg-primary-100 rounded-full flex items-center justify-center">
              <span className="text-primary-600 text-lg font-semibold">
                {team.name.charAt(0).toUpperCase()}
              </span>
            </div>
          )}
          <div>
            <h1 className="text-2xl font-bold text-gray-900">{team.name}</h1>
            <p className="text-sm text-gray-500">{team.slug}</p>
          </div>
        </div>
      </div>

      {/* API URL Section */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-6 py-4">
          <h2 className="text-lg font-medium text-gray-900 mb-2">Team API URL</h2>
          <p className="text-sm text-gray-500 mb-3">
            Use this URL with your API token to make authenticated requests
          </p>
          <div className="flex items-center gap-2">
            <div className="flex-1 relative">
              <input
                type="text"
                readOnly
                value={team?.subdomain ? `${team.subdomain}/api` : ''}
                className="w-full px-3 py-2 pr-20 border border-gray-300 rounded-lg bg-gray-50 font-mono text-sm"
              />
              <button
                onClick={handleCopyUrl}
                className="absolute right-2 top-1/2 -translate-y-1/2 px-3 py-1 text-sm bg-primary-600 text-white rounded hover:bg-primary-700 flex items-center gap-1"
              >
                {copiedUrl ? (
                  <>
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                    Copied!
                  </>
                ) : (
                  <>
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                    </svg>
                    Copy
                  </>
                )}
              </button>
            </div>
          </div>
          <p className="text-xs text-gray-400 mt-2">
            Example: <code className="bg-gray-100 px-1 py-0.5 rounded">curl -H "Authorization: Bearer YOUR_TOKEN" {team?.subdomain}/api/boards</code>
          </p>
        </div>
      </div>

      {/* Container Management Section */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-medium text-gray-900">Container Management</h2>
          <p className="text-sm text-gray-500">
            Restart or rebuild this team's containers
          </p>
        </div>
        <div className="px-6 py-4">
          {restartMessage && (
            <div className={`mb-4 p-3 rounded-lg ${
              restartMessage.type === 'success'
                ? 'bg-green-50 border border-green-200 text-green-800'
                : 'bg-red-50 border border-red-200 text-red-800'
            }`}>
              <div className="flex items-center">
                {restartMessage.type === 'success' ? (
                  <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                ) : (
                  <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                )}
                <span className="text-sm">{restartMessage.text}</span>
              </div>
            </div>
          )}

          <div className="flex flex-wrap gap-4">
            <div className="flex-1 min-w-[280px] p-4 border border-gray-200 rounded-lg">
              <div className="flex items-start">
                <div className="flex-shrink-0">
                  <svg className="w-8 h-8 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                  </svg>
                </div>
                <div className="ml-4 flex-1">
                  <h3 className="text-sm font-medium text-gray-900">Quick Restart</h3>
                  <p className="text-sm text-gray-500 mt-1">
                    Stops and starts the containers without rebuilding. Use this for minor issues or after configuration changes.
                  </p>
                  <button
                    onClick={() => setRestartConfirm('restart')}
                    disabled={restartMutation.isPending || team?.status === 'restarting'}
                    className="mt-3 inline-flex items-center px-4 py-2 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {restartMutation.isPending && restartConfirm === 'restart' ? (
                      <>
                        <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-600 mr-2"></div>
                        Restarting...
                      </>
                    ) : (
                      <>
                        <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                        </svg>
                        Restart Containers
                      </>
                    )}
                  </button>
                </div>
              </div>
            </div>

            <div className="flex-1 min-w-[280px] p-4 border border-orange-200 bg-orange-50 rounded-lg">
              <div className="flex items-start">
                <div className="flex-shrink-0">
                  <svg className="w-8 h-8 text-orange-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
                  </svg>
                </div>
                <div className="ml-4 flex-1">
                  <h3 className="text-sm font-medium text-gray-900">Full Rebuild</h3>
                  <p className="text-sm text-gray-500 mt-1">
                    Removes images and rebuilds from scratch with --no-cache. Use this to apply code updates or fix corrupted containers.
                  </p>
                  <button
                    onClick={() => setRestartConfirm('rebuild')}
                    disabled={restartMutation.isPending || team?.status === 'restarting'}
                    className="mt-3 inline-flex items-center px-4 py-2 border border-orange-300 rounded-md shadow-sm text-sm font-medium text-orange-700 bg-white hover:bg-orange-100 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {restartMutation.isPending && restartConfirm === 'rebuild' ? (
                      <>
                        <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-orange-600 mr-2"></div>
                        Rebuilding...
                      </>
                    ) : (
                      <>
                        <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
                        </svg>
                        Rebuild Containers
                      </>
                    )}
                  </button>
                </div>
              </div>
            </div>
          </div>

          {team?.status === 'restarting' && (
            <div className="mt-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
              <div className="flex items-center">
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-600 mr-2"></div>
                <span className="text-sm text-blue-800">Team is currently restarting...</span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* API Tokens Section */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
          <div>
            <h2 className="text-lg font-medium text-gray-900">API Tokens</h2>
            <p className="text-sm text-gray-500">
              Create tokens to allow external services to access this team's API
            </p>
          </div>
          <button
            onClick={() => setShowCreateModal(true)}
            className="inline-flex items-center px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-primary-600 hover:bg-primary-700"
          >
            <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            Create Token
          </button>
        </div>

        <div className="px-6 py-4">
          {tokensLoading ? (
            <div className="flex justify-center py-8">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary-600"></div>
            </div>
          ) : tokens?.length === 0 ? (
            <div className="text-center py-8 text-gray-500">
              <svg className="w-12 h-12 mx-auto text-gray-400 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
              </svg>
              <p>No API tokens yet</p>
              <p className="text-sm mt-1">Create a token to allow external services to access this team's API</p>
            </div>
          ) : (
            <table className="min-w-full divide-y divide-gray-200">
              <thead>
                <tr>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Name</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Scopes</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Created</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Expires</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Last Used</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                  <th className="px-3 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {tokens?.map((token: ApiToken) => (
                  <tr key={token.id}>
                    <td className="px-3 py-4 whitespace-nowrap">
                      <div className="text-sm font-medium text-gray-900">{token.name}</div>
                    </td>
                    <td className="px-3 py-4 whitespace-nowrap">
                      <div className="flex flex-wrap gap-1">
                        {token.scopes.map(scope => (
                          <span
                            key={scope}
                            className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-800"
                          >
                            {scope}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-3 py-4 whitespace-nowrap text-sm text-gray-500">
                      {formatDate(token.created_at)}
                    </td>
                    <td className="px-3 py-4 whitespace-nowrap text-sm text-gray-500">
                      {token.expires_at ? formatDate(token.expires_at) : 'Never'}
                    </td>
                    <td className="px-3 py-4 whitespace-nowrap text-sm text-gray-500">
                      {formatDate(token.last_used_at)}
                    </td>
                    <td className="px-3 py-4 whitespace-nowrap">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                        token.is_active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                      }`}>
                        {token.is_active ? 'Active' : 'Revoked'}
                      </span>
                    </td>
                    <td className="px-3 py-4 whitespace-nowrap text-right text-sm">
                      <button
                        onClick={() => setDeleteConfirm(token)}
                        className="text-red-600 hover:text-red-800"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Create Token Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-md p-6">
            <h2 className="text-lg font-bold text-gray-900 mb-4">Create API Token</h2>

            {createdToken ? (
              <div className="space-y-4">
                <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
                  <div className="flex items-start">
                    <svg className="w-5 h-5 text-yellow-600 mt-0.5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                    </svg>
                    <div>
                      <p className="text-sm font-medium text-yellow-800">
                        Copy this token now - it won't be shown again!
                      </p>
                    </div>
                  </div>
                </div>

                <div className="relative">
                  <input
                    type="text"
                    readOnly
                    value={createdToken}
                    className="w-full px-3 py-2 pr-20 border border-gray-300 rounded-lg bg-gray-50 font-mono text-sm"
                  />
                  <button
                    onClick={handleCopyToken}
                    className="absolute right-2 top-1/2 -translate-y-1/2 px-3 py-1 text-sm bg-primary-600 text-white rounded hover:bg-primary-700"
                  >
                    {copied ? 'Copied!' : 'Copy'}
                  </button>
                </div>

                <div className="flex justify-end">
                  <button
                    onClick={() => {
                      setShowCreateModal(false)
                      setCreatedToken(null)
                    }}
                    className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200"
                  >
                    Done
                  </button>
                </div>
              </div>
            ) : (
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  createMutation.mutate()
                }}
                className="space-y-4"
              >
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Token Name
                  </label>
                  <input
                    type="text"
                    value={newTokenName}
                    onChange={(e) => setNewTokenName(e.target.value)}
                    placeholder="e.g., Webhook Integration"
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    required
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Expiration (optional)
                  </label>
                  <select
                    value={newTokenExpiry}
                    onChange={(e) => setNewTokenExpiry(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  >
                    <option value="">Never expires</option>
                    <option value="7">7 days</option>
                    <option value="30">30 days</option>
                    <option value="90">90 days</option>
                    <option value="365">1 year</option>
                  </select>
                </div>

                <div className="bg-blue-50 border border-blue-200 rounded-lg p-3">
                  <p className="text-sm text-blue-800">
                    This token will have full access (read, write, webhook) to this team's API.
                  </p>
                </div>

                <div className="flex justify-end gap-3">
                  <button
                    type="button"
                    onClick={() => {
                      setShowCreateModal(false)
                      setNewTokenName('')
                      setNewTokenExpiry('')
                    }}
                    className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={!newTokenName || createMutation.isPending}
                    className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50"
                  >
                    {createMutation.isPending ? 'Creating...' : 'Create Token'}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {deleteConfirm && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-md p-6">
            <h2 className="text-lg font-bold text-gray-900 mb-4">Delete API Token</h2>
            <p className="text-gray-600 mb-4">
              Are you sure you want to delete the token <strong>{deleteConfirm.name}</strong>?
              Any services using this token will lose access immediately.
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setDeleteConfirm(null)}
                className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg"
              >
                Cancel
              </button>
              <button
                onClick={() => deleteMutation.mutate(deleteConfirm.id)}
                disabled={deleteMutation.isPending}
                className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
              >
                {deleteMutation.isPending ? 'Deleting...' : 'Delete Token'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Restart Confirmation Modal */}
      {restartConfirm && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-md p-6">
            <h2 className="text-lg font-bold text-gray-900 mb-4">
              {restartConfirm === 'rebuild' ? 'Rebuild Containers' : 'Restart Containers'}
            </h2>
            <div className="mb-4">
              {restartConfirm === 'rebuild' ? (
                <div className="space-y-2">
                  <p className="text-gray-600">
                    This will perform a full rebuild of the team containers:
                  </p>
                  <ul className="text-sm text-gray-500 list-disc list-inside space-y-1">
                    <li>Stop all running containers</li>
                    <li>Remove existing container images</li>
                    <li>Rebuild from scratch with --no-cache</li>
                    <li>Start the new containers</li>
                  </ul>
                  <div className="mt-3 p-2 bg-orange-50 border border-orange-200 rounded text-sm text-orange-800">
                    This operation may take several minutes. The team will be unavailable during this time.
                  </div>
                </div>
              ) : (
                <div className="space-y-2">
                  <p className="text-gray-600">
                    This will restart the team containers:
                  </p>
                  <ul className="text-sm text-gray-500 list-disc list-inside space-y-1">
                    <li>Stop all running containers</li>
                    <li>Start containers again</li>
                  </ul>
                  <div className="mt-3 p-2 bg-blue-50 border border-blue-200 rounded text-sm text-blue-800">
                    The team will be briefly unavailable during the restart.
                  </div>
                </div>
              )}
            </div>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setRestartConfirm(null)}
                className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg"
              >
                Cancel
              </button>
              <button
                onClick={() => restartMutation.mutate(restartConfirm === 'rebuild')}
                disabled={restartMutation.isPending}
                className={`px-4 py-2 text-white rounded-lg disabled:opacity-50 ${
                  restartConfirm === 'rebuild'
                    ? 'bg-orange-600 hover:bg-orange-700'
                    : 'bg-blue-600 hover:bg-blue-700'
                }`}
              >
                {restartMutation.isPending
                  ? (restartConfirm === 'rebuild' ? 'Rebuilding...' : 'Restarting...')
                  : (restartConfirm === 'rebuild' ? 'Rebuild' : 'Restart')
                }
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
