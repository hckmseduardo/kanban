import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { webhooksApi } from '../services/api'

export default function Settings() {
  const queryClient = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)
  const [newWebhook, setNewWebhook] = useState({
    name: '',
    url: '',
    events: ['card.created', 'card.moved', 'card.updated'],
    secret: ''
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

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
        <p className="text-gray-500 mt-1">Configure webhooks for AI agent integrations</p>
      </div>

      <div className="bg-white rounded-lg shadow">
        <div className="px-6 py-4 border-b flex justify-between items-center">
          <h2 className="text-lg font-medium">Webhooks</h2>
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 text-sm"
          >
            Add Webhook
          </button>
        </div>

        {showCreate && (
          <div className="px-6 py-4 border-b bg-gray-50">
            <div className="space-y-4 max-w-lg">
              <input
                type="text"
                placeholder="Webhook name"
                value={newWebhook.name}
                onChange={e => setNewWebhook({ ...newWebhook, name: e.target.value })}
                className="w-full px-3 py-2 border rounded-lg"
              />
              <input
                type="url"
                placeholder="Webhook URL"
                value={newWebhook.url}
                onChange={e => setNewWebhook({ ...newWebhook, url: e.target.value })}
                className="w-full px-3 py-2 border rounded-lg"
              />
              <input
                type="text"
                placeholder="Secret (optional)"
                value={newWebhook.secret}
                onChange={e => setNewWebhook({ ...newWebhook, secret: e.target.value })}
                className="w-full px-3 py-2 border rounded-lg"
              />
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Events</label>
                <div className="flex flex-wrap gap-2">
                  {eventOptions.map(event => (
                    <button
                      key={event}
                      onClick={() => toggleEvent(event)}
                      className={`px-3 py-1 rounded-full text-sm ${
                        newWebhook.events.includes(event)
                          ? 'bg-primary-100 text-primary-700'
                          : 'bg-gray-100 text-gray-600'
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
                  className="px-4 py-2 text-gray-600 hover:text-gray-800"
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
          <div className="px-6 py-12 text-center text-gray-500">
            No webhooks configured. Add a webhook to integrate with AI agents.
          </div>
        ) : (
          <ul className="divide-y">
            {webhooks?.map((webhook: any) => (
              <li key={webhook.id} className="px-6 py-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="font-medium">{webhook.name}</h3>
                    <p className="text-sm text-gray-500">{webhook.url}</p>
                    <div className="flex gap-1 mt-2">
                      {webhook.events?.map((event: string) => (
                        <span key={event} className="px-2 py-0.5 bg-gray-100 text-gray-600 text-xs rounded">
                          {event}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="flex items-center space-x-2">
                    <button
                      onClick={() => testWebhook.mutate(webhook.id)}
                      className="text-sm text-primary-600 hover:text-primary-700"
                    >
                      Test
                    </button>
                    <button
                      onClick={() => deleteWebhook.mutate(webhook.id)}
                      className="text-sm text-red-600 hover:text-red-700"
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
