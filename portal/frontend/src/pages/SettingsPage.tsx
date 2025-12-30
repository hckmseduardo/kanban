import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { portalApiTokensApi, PortalApiToken } from '../services/api'

const AVAILABLE_SCOPES = [
  { value: 'teams:read', label: 'Teams - Read', description: 'List and view teams' },
  { value: 'teams:write', label: 'Teams - Write', description: 'Create and delete teams' },
  { value: 'members:read', label: 'Members - Read', description: 'List team members' },
  { value: 'members:write', label: 'Members - Write', description: 'Add/remove team members' },
  { value: 'boards:read', label: 'Boards - Read', description: 'List team boards' },
  { value: 'boards:write', label: 'Boards - Write', description: 'Create team boards' },
]

export default function SettingsPage() {
  const queryClient = useQueryClient()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [newTokenName, setNewTokenName] = useState('')
  const [selectedScopes, setSelectedScopes] = useState<string[]>([
    'teams:read', 'teams:write', 'members:read', 'members:write', 'boards:read', 'boards:write'
  ])
  const [createdToken, setCreatedToken] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [copiedApiUrl, setCopiedApiUrl] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState<PortalApiToken | null>(null)

  const { data: tokens, isLoading } = useQuery({
    queryKey: ['portal-api-tokens'],
    queryFn: () => portalApiTokensApi.list().then(res => res.data),
    staleTime: 30 * 1000,
  })

  const createMutation = useMutation({
    mutationFn: (data: { name: string; scopes: string[] }) =>
      portalApiTokensApi.create(data),
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: ['portal-api-tokens'] })
      setCreatedToken(response.data.token)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (tokenId: string) => portalApiTokensApi.delete(tokenId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['portal-api-tokens'] })
      setDeleteConfirm(null)
    },
  })

  const handleCreate = () => {
    if (!newTokenName.trim()) return
    createMutation.mutate({
      name: newTokenName,
      scopes: selectedScopes,
    })
  }

  const handleCopyToken = async () => {
    if (createdToken) {
      await navigator.clipboard.writeText(createdToken)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const handleCopyApiUrl = async () => {
    const url = `${window.location.origin}/api`
    await navigator.clipboard.writeText(url)
    setCopiedApiUrl(true)
    setTimeout(() => setCopiedApiUrl(false), 2000)
  }

  const toggleScope = (scope: string) => {
    setSelectedScopes(prev =>
      prev.includes(scope)
        ? prev.filter(s => s !== scope)
        : [...prev, scope]
    )
  }

  const apiUrl = `${window.location.origin}/api`

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Settings</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          Manage your Portal API tokens for programmatic access
        </p>
      </div>

      {/* Portal API URL Section */}
      <div className="bg-white dark:bg-dark-800 shadow dark:shadow-dark-700/30 rounded-lg p-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">Portal API URL</h2>
        <div className="flex items-center gap-3">
          <code className="flex-1 px-4 py-2 bg-gray-100 dark:bg-dark-700 rounded-lg font-mono text-sm text-gray-800 dark:text-gray-200">
            {apiUrl}
          </code>
          <button
            onClick={handleCopyApiUrl}
            className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors flex items-center gap-2"
          >
            {copiedApiUrl ? (
              <>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                Copied!
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3" />
                </svg>
                Copy
              </>
            )}
          </button>
        </div>
        <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">
          Use this URL with your Portal API token to manage teams, members, and boards programmatically.
        </p>
        <div className="mt-4 p-3 bg-gray-50 dark:bg-dark-700 rounded-lg">
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">Example request:</p>
          <code className="text-xs font-mono text-gray-700 dark:text-gray-300 break-all">
            curl -H "Authorization: Bearer pk_your_token" {apiUrl}/teams
          </code>
        </div>
      </div>

      {/* Portal API Tokens Section */}
      <div className="bg-white dark:bg-dark-800 shadow dark:shadow-dark-700/30 rounded-lg p-6">
        <div className="flex justify-between items-center mb-6">
          <div>
            <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Portal API Tokens</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Tokens for programmatic access to the Portal API
            </p>
          </div>
          <button
            onClick={() => {
              setShowCreateModal(true)
              setNewTokenName('')
              setSelectedScopes(['teams:read', 'teams:write', 'members:read', 'members:write', 'boards:read', 'boards:write'])
              setCreatedToken(null)
            }}
            className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors"
          >
            Create Token
          </button>
        </div>

        {isLoading ? (
          <div className="flex justify-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
          </div>
        ) : tokens?.length === 0 ? (
          <div className="text-center py-8 text-gray-500 dark:text-gray-400">
            <svg className="w-12 h-12 mx-auto mb-3 text-gray-300 dark:text-dark-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
            </svg>
            <p>No Portal API tokens yet</p>
            <p className="text-sm mt-1">Create a token to access the Portal API programmatically</p>
          </div>
        ) : (
          <div className="space-y-3">
            {tokens?.map((token: PortalApiToken) => (
              <div
                key={token.id}
                className="flex items-center justify-between p-4 border border-gray-200 dark:border-dark-600 rounded-lg"
              >
                <div>
                  <p className="font-medium text-gray-900 dark:text-gray-100">{token.name}</p>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {token.scopes.map(scope => (
                      <span
                        key={scope}
                        className="px-2 py-0.5 text-xs bg-gray-100 dark:bg-dark-700 text-gray-600 dark:text-gray-400 rounded"
                      >
                        {scope}
                      </span>
                    ))}
                  </div>
                  <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
                    Created {new Date(token.created_at).toLocaleDateString()}
                    {token.last_used_at && ` • Last used ${new Date(token.last_used_at).toLocaleDateString()}`}
                  </p>
                </div>
                <button
                  onClick={() => setDeleteConfirm(token)}
                  className="text-red-500 hover:text-red-700 p-2"
                  title="Delete token"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* API Documentation */}
      <div className="bg-white dark:bg-dark-800 shadow dark:shadow-dark-700/30 rounded-lg p-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">API Documentation</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
          Available endpoints with Portal API tokens (pk_*):
        </p>
        <div className="space-y-3">
          <div className="p-3 bg-gray-50 dark:bg-dark-700 rounded-lg">
            <code className="text-sm font-mono text-green-600 dark:text-green-400">GET</code>
            <code className="text-sm font-mono text-gray-700 dark:text-gray-300 ml-2">/teams</code>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">List your teams</p>
          </div>
          <div className="p-3 bg-gray-50 dark:bg-dark-700 rounded-lg">
            <code className="text-sm font-mono text-blue-600 dark:text-blue-400">POST</code>
            <code className="text-sm font-mono text-gray-700 dark:text-gray-300 ml-2">/teams</code>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Create a new team (requires teams:write scope)</p>
          </div>
          <div className="p-3 bg-gray-50 dark:bg-dark-700 rounded-lg">
            <code className="text-sm font-mono text-green-600 dark:text-green-400">GET</code>
            <code className="text-sm font-mono text-gray-700 dark:text-gray-300 ml-2">/teams/:slug</code>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Get team details</p>
          </div>
          <div className="p-3 bg-gray-50 dark:bg-dark-700 rounded-lg">
            <code className="text-sm font-mono text-orange-600 dark:text-orange-400">PUT</code>
            <code className="text-sm font-mono text-gray-700 dark:text-gray-300 ml-2">/teams/:slug</code>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Update team (requires teams:write scope)</p>
          </div>
          <div className="p-3 bg-gray-50 dark:bg-dark-700 rounded-lg">
            <code className="text-sm font-mono text-red-600 dark:text-red-400">DELETE</code>
            <code className="text-sm font-mono text-gray-700 dark:text-gray-300 ml-2">/teams/:slug</code>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Delete team (owner only, requires teams:write scope)</p>
          </div>
          <div className="p-3 bg-gray-50 dark:bg-dark-700 rounded-lg">
            <code className="text-sm font-mono text-green-600 dark:text-green-400">GET</code>
            <code className="text-sm font-mono text-gray-700 dark:text-gray-300 ml-2">/teams/:slug/members</code>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">List team members</p>
          </div>
          <div className="p-3 bg-gray-50 dark:bg-dark-700 rounded-lg">
            <code className="text-sm font-mono text-blue-600 dark:text-blue-400">POST</code>
            <code className="text-sm font-mono text-gray-700 dark:text-gray-300 ml-2">/teams/:slug/members</code>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Add team member (requires members:write scope)</p>
          </div>
        </div>
        <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">
          View full documentation at{' '}
          <a href={`${apiUrl}/docs`} target="_blank" rel="noopener noreferrer" className="text-primary-600 hover:text-primary-700">
            {apiUrl}/docs
          </a>
        </p>
      </div>

      {/* Create Token Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/50 dark:bg-black/70 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-dark-800 rounded-lg shadow-xl dark:shadow-dark-900/50 w-full max-w-md p-6">
            {createdToken ? (
              <>
                <div className="flex items-center gap-3 mb-4">
                  <div className="w-10 h-10 rounded-full bg-green-100 dark:bg-green-900/30 flex items-center justify-center">
                    <svg className="w-6 h-6 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  </div>
                  <div>
                    <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">Token Created</h2>
                    <p className="text-sm text-gray-500 dark:text-gray-400">Copy it now - you won't see it again!</p>
                  </div>
                </div>

                <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-3 mb-4">
                  <p className="text-sm text-yellow-800 dark:text-yellow-300 font-medium">
                    ⚠️ This token will only be shown once. Make sure to copy it now.
                  </p>
                </div>

                <div className="mb-4">
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Your API Token</label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      readOnly
                      value={createdToken}
                      className="flex-1 px-3 py-2 border border-gray-300 dark:border-dark-600 bg-gray-50 dark:bg-dark-700 text-gray-900 dark:text-gray-100 rounded-lg font-mono text-sm"
                    />
                    <button
                      onClick={handleCopyToken}
                      className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700"
                    >
                      {copied ? 'Copied!' : 'Copy'}
                    </button>
                  </div>
                </div>

                <div className="flex justify-end">
                  <button
                    onClick={() => {
                      setShowCreateModal(false)
                      setCreatedToken(null)
                    }}
                    className="px-4 py-2 bg-gray-100 dark:bg-dark-700 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-dark-600"
                  >
                    Done
                  </button>
                </div>
              </>
            ) : (
              <>
                <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100 mb-4">Create Portal API Token</h2>

                <div className="mb-4">
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Token Name</label>
                  <input
                    type="text"
                    value={newTokenName}
                    onChange={(e) => setNewTokenName(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-gray-100 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    placeholder="e.g., CI/CD Pipeline"
                    autoFocus
                  />
                </div>

                <div className="mb-4">
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Scopes</label>
                  <div className="space-y-2 max-h-48 overflow-y-auto">
                    {AVAILABLE_SCOPES.map(scope => (
                      <label key={scope.value} className="flex items-start gap-3 p-2 hover:bg-gray-50 dark:hover:bg-dark-700 rounded cursor-pointer">
                        <input
                          type="checkbox"
                          checked={selectedScopes.includes(scope.value)}
                          onChange={() => toggleScope(scope.value)}
                          className="mt-1"
                        />
                        <div>
                          <p className="text-sm font-medium text-gray-900 dark:text-gray-100">{scope.label}</p>
                          <p className="text-xs text-gray-500 dark:text-gray-400">{scope.description}</p>
                        </div>
                      </label>
                    ))}
                  </div>
                </div>

                <div className="flex justify-end gap-3">
                  <button
                    onClick={() => setShowCreateModal(false)}
                    className="px-4 py-2 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-dark-700 rounded-lg"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleCreate}
                    disabled={!newTokenName.trim() || selectedScopes.length === 0 || createMutation.isPending}
                    className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {createMutation.isPending ? 'Creating...' : 'Create Token'}
                  </button>
                </div>
              </>
            )}
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
                <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">Delete Token</h2>
                <p className="text-sm text-gray-500 dark:text-gray-400">This cannot be undone</p>
              </div>
            </div>

            <p className="text-gray-600 dark:text-gray-300 mb-4">
              Are you sure you want to delete <strong>{deleteConfirm.name}</strong>? Any applications using this token will lose access.
            </p>

            <div className="flex justify-end gap-3">
              <button
                onClick={() => setDeleteConfirm(null)}
                className="px-4 py-2 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-dark-700 rounded-lg"
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
    </div>
  )
}
