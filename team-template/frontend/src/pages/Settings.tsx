import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { webhooksApi, teamApi } from '../services/api'

// Predefined badge options - emojis for quick selection
const BADGE_OPTIONS = [
  { emoji: '🚀', label: 'Rocket' },
  { emoji: '💼', label: 'Business' },
  { emoji: '🎯', label: 'Target' },
  { emoji: '⚡', label: 'Lightning' },
  { emoji: '🔥', label: 'Fire' },
  { emoji: '💡', label: 'Idea' },
  { emoji: '🎨', label: 'Creative' },
  { emoji: '🛠️', label: 'Tools' },
  { emoji: '📊', label: 'Analytics' },
  { emoji: '🌟', label: 'Star' },
  { emoji: '🏆', label: 'Trophy' },
  { emoji: '🎮', label: 'Gaming' },
  { emoji: '📱', label: 'Mobile' },
  { emoji: '💻', label: 'Code' },
  { emoji: '🌐', label: 'Web' },
  { emoji: '🔒', label: 'Security' },
]

export default function Settings() {
  const queryClient = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)
  const [customBadgeUrl, setCustomBadgeUrl] = useState('')
  const [teamName, setTeamName] = useState('')
  const [teamDescription, setTeamDescription] = useState('')
  const [isEditingTeamInfo, setIsEditingTeamInfo] = useState(false)
  const [newWebhook, setNewWebhook] = useState({
    name: '',
    url: '',
    events: ['card.created', 'card.moved', 'card.updated'],
    secret: ''
  })

  const { data: teamSettings } = useQuery({
    queryKey: ['team-settings'],
    queryFn: () => teamApi.getSettings().then(res => res.data)
  })

  const updateTeamSettings = useMutation({
    mutationFn: (data: { name?: string; description?: string; badge?: string }) => teamApi.updateSettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['team-settings'] })
      setIsEditingTeamInfo(false)
    }
  })

  const { data: webhooks, isLoading } = useQuery({
    queryKey: ['webhooks'],
    queryFn: () => webhooksApi.list().then(res => res.data)
  })

  const createWebhook = useMutation({
    mutationFn: (data: any) => webhooksApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['webhooks'] })
      setShowCreate(false)
      setNewWebhook({ name: '', url: '', events: ['card.created', 'card.moved', 'card.updated'], secret: '' })
    }
  })

  const deleteWebhook = useMutation({
    mutationFn: (id: string) => webhooksApi.delete(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['webhooks'] })
  })

  const testWebhook = useMutation({
    mutationFn: (id: string) => webhooksApi.test(id)
  })

  const eventOptions = [
    'card.created',
    'card.updated',
    'card.moved',
    'card.deleted'
  ]

  const toggleEvent = (event: string) => {
    if (newWebhook.events.includes(event)) {
      setNewWebhook({ ...newWebhook, events: newWebhook.events.filter(e => e !== event) })
    } else {
      setNewWebhook({ ...newWebhook, events: [...newWebhook.events, event] })
    }
  }

  const handleBadgeSelect = (badge: string) => {
    updateTeamSettings.mutate({ badge })
  }

  const handleCustomBadgeSubmit = () => {
    if (customBadgeUrl.trim()) {
      updateTeamSettings.mutate({ badge: customBadgeUrl.trim() })
      setCustomBadgeUrl('')
    }
  }

  const handleClearBadge = () => {
    updateTeamSettings.mutate({ badge: '' })
  }

  const handleEditTeamInfo = () => {
    setTeamName(teamSettings?.name || '')
    setTeamDescription(teamSettings?.description || '')
    setIsEditingTeamInfo(true)
  }

  const handleSaveTeamInfo = () => {
    updateTeamSettings.mutate({
      name: teamName,
      description: teamDescription
    })
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Settings</h1>
        <p className="text-gray-500 dark:text-gray-400 mt-1">Configure your team and integrations</p>
      </div>

      {/* Team Settings Section */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow dark:shadow-gray-900/30">
        <div className="px-6 py-4 border-b dark:border-gray-700 flex justify-between items-center">
          <div>
            <h2 className="text-lg font-medium text-gray-900 dark:text-gray-100">Team Profile</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">Customize how your team appears in the portal</p>
          </div>
          {!isEditingTeamInfo && (
            <button
              onClick={handleEditTeamInfo}
              className="text-sm text-primary-600 dark:text-primary-400 hover:text-primary-700 dark:hover:text-primary-300"
            >
              Edit
            </button>
          )}
        </div>
        <div className="p-6">
          {/* Team Name & Description */}
          <div className="mb-6 pb-6 border-b dark:border-gray-700">
            {isEditingTeamInfo ? (
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Team Name</label>
                  <input
                    type="text"
                    value={teamName}
                    onChange={e => setTeamName(e.target.value)}
                    className="w-full max-w-md px-3 py-2 border dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Description</label>
                  <textarea
                    value={teamDescription}
                    onChange={e => setTeamDescription(e.target.value)}
                    rows={3}
                    className="w-full max-w-lg px-3 py-2 border dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    placeholder="A short description of your team..."
                  />
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={handleSaveTeamInfo}
                    disabled={updateTeamSettings.isPending}
                    className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50"
                  >
                    {updateTeamSettings.isPending ? 'Saving...' : 'Save'}
                  </button>
                  <button
                    onClick={() => setIsEditingTeamInfo(false)}
                    className="px-4 py-2 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div>
                <div className="flex items-start gap-4">
                  {/* Badge Preview */}
                  {teamSettings?.badge ? (
                    teamSettings.badge.startsWith('http') ? (
                      <img
                        src={teamSettings.badge}
                        alt="Team badge"
                        className="h-16 w-16 rounded-xl object-cover ring-2 ring-primary-200 dark:ring-primary-700"
                      />
                    ) : (
                      <div className="h-16 w-16 rounded-xl bg-gradient-to-br from-primary-100 to-primary-200 dark:from-primary-900/50 dark:to-primary-800/50 flex items-center justify-center text-3xl ring-2 ring-primary-200 dark:ring-primary-700">
                        {teamSettings.badge}
                      </div>
                    )
                  ) : (
                    <div className="h-16 w-16 rounded-xl bg-gradient-to-br from-primary-400 to-primary-600 flex items-center justify-center text-white text-xl font-bold">
                      {teamSettings?.name?.charAt(0).toUpperCase() || 'T'}
                    </div>
                  )}
                  <div>
                    <h3 className="text-xl font-semibold text-gray-900 dark:text-gray-100">{teamSettings?.name || 'Team'}</h3>
                    <p className="text-gray-500 dark:text-gray-400 mt-1">{teamSettings?.description || 'No description set'}</p>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Badge Selection */}
          <div className="mb-6">
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Team Badge</label>
            <div className="flex items-center gap-4 mb-4">
              {teamSettings?.badge && (
                <button
                  onClick={handleClearBadge}
                  className="text-sm text-red-600 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300"
                >
                  Remove badge
                </button>
              )}
            </div>
          </div>

          {/* Predefined Badges */}
          <div className="mb-6">
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Quick Select</label>
            <div className="grid grid-cols-8 gap-2">
              {BADGE_OPTIONS.map(({ emoji, label }) => (
                <button
                  key={emoji}
                  onClick={() => handleBadgeSelect(emoji)}
                  className={`h-12 w-12 rounded-lg flex items-center justify-center text-2xl transition-all hover:scale-110 ${
                    teamSettings?.badge === emoji
                      ? 'bg-primary-100 dark:bg-primary-900/50 ring-2 ring-primary-500'
                      : 'bg-gray-50 dark:bg-gray-700 hover:bg-gray-100 dark:hover:bg-gray-600'
                  }`}
                  title={label}
                >
                  {emoji}
                </button>
              ))}
            </div>
          </div>

          {/* Custom Badge URL */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Custom Image URL</label>
            <div className="flex gap-2">
              <input
                type="url"
                placeholder="https://example.com/badge.png"
                value={customBadgeUrl}
                onChange={e => setCustomBadgeUrl(e.target.value)}
                className="flex-1 px-3 py-2 border dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              />
              <button
                onClick={handleCustomBadgeSubmit}
                disabled={!customBadgeUrl.trim()}
                className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Apply
              </button>
            </div>
            <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">Enter a URL to an image (PNG, JPG, SVG). Recommended size: 128x128 pixels.</p>
          </div>
        </div>
      </div>

      {/* Webhooks Section */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow dark:shadow-gray-900/30">
        <div className="px-6 py-4 border-b dark:border-gray-700 flex justify-between items-center">
          <h2 className="text-lg font-medium text-gray-900 dark:text-gray-100">Webhooks</h2>
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 text-sm"
          >
            Add Webhook
          </button>
        </div>

        {showCreate && (
          <div className="px-6 py-4 border-b dark:border-gray-700 bg-gray-50 dark:bg-gray-700/50">
            <div className="space-y-4 max-w-lg">
              <input
                type="text"
                placeholder="Webhook name"
                value={newWebhook.name}
                onChange={e => setNewWebhook({ ...newWebhook, name: e.target.value })}
                className="w-full px-3 py-2 border dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 rounded-lg"
              />
              <input
                type="url"
                placeholder="Webhook URL"
                value={newWebhook.url}
                onChange={e => setNewWebhook({ ...newWebhook, url: e.target.value })}
                className="w-full px-3 py-2 border dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 rounded-lg"
              />
              <input
                type="text"
                placeholder="Secret (optional)"
                value={newWebhook.secret}
                onChange={e => setNewWebhook({ ...newWebhook, secret: e.target.value })}
                className="w-full px-3 py-2 border dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 rounded-lg"
              />
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Events</label>
                <div className="flex flex-wrap gap-2">
                  {eventOptions.map(event => (
                    <button
                      key={event}
                      onClick={() => toggleEvent(event)}
                      className={`px-3 py-1 rounded-full text-sm ${
                        newWebhook.events.includes(event)
                          ? 'bg-primary-100 dark:bg-primary-900/50 text-primary-700 dark:text-primary-300'
                          : 'bg-gray-100 dark:bg-gray-600 text-gray-600 dark:text-gray-300'
                      }`}
                    >
                      {event}
                    </button>
                  ))}
                </div>
              </div>
              <div className="flex space-x-2">
                <button
                  onClick={() => createWebhook.mutate(newWebhook)}
                  disabled={!newWebhook.name || !newWebhook.url}
                  className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50"
                >
                  Create
                </button>
                <button
                  onClick={() => setShowCreate(false)}
                  className="px-4 py-2 text-gray-600 dark:text-gray-300 hover:text-gray-800 dark:hover:text-gray-100"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        )}

        {isLoading ? (
          <div className="px-6 py-12 text-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600 mx-auto"></div>
          </div>
        ) : webhooks?.length === 0 ? (
          <div className="px-6 py-12 text-center text-gray-500 dark:text-gray-400">
            No webhooks configured. Add a webhook to integrate with AI agents.
          </div>
        ) : (
          <ul className="divide-y dark:divide-gray-700">
            {webhooks?.map((webhook: any) => (
              <li key={webhook.id} className="px-6 py-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="font-medium text-gray-900 dark:text-gray-100">{webhook.name}</h3>
                    <p className="text-sm text-gray-500 dark:text-gray-400">{webhook.url}</p>
                    <div className="flex gap-1 mt-2">
                      {webhook.events?.map((event: string) => (
                        <span key={event} className="px-2 py-0.5 bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 text-xs rounded">
                          {event}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="flex items-center space-x-2">
                    <button
                      onClick={() => testWebhook.mutate(webhook.id)}
                      className="text-sm text-primary-600 dark:text-primary-400 hover:text-primary-700 dark:hover:text-primary-300"
                    >
                      Test
                    </button>
                    <button
                      onClick={() => deleteWebhook.mutate(webhook.id)}
                      className="text-sm text-red-600 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
