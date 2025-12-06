import { useEffect, useRef, useCallback, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useAuthStore } from '../stores/authStore'

interface TaskUpdate {
  type: 'task_progress' | 'task_completed' | 'task_failed' | 'subscribed'
  task_id?: string
  progress?: {
    current_step: number
    total_steps: number
    step_name: string
    percentage: number
    message?: string
  }
  result?: Record<string, unknown>
  error?: string
  channel?: string
}

interface UseTaskWebSocketOptions {
  onTaskUpdate?: (update: TaskUpdate) => void
  onTaskCompleted?: (taskId: string, result?: Record<string, unknown>) => void
  onTaskFailed?: (taskId: string, error?: string) => void
}

export function useTaskWebSocket(options: UseTaskWebSocketOptions = {}) {
  const { user } = useAuthStore()
  const queryClient = useQueryClient()
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const [connectionError, setConnectionError] = useState<string | null>(null)

  const connect = useCallback(() => {
    if (!user?.id) return

    // Build WebSocket URL
    const apiUrl = import.meta.env.VITE_API_URL || 'https://api.localhost:4443'
    const wsProtocol = apiUrl.startsWith('https') ? 'wss' : 'ws'
    const wsHost = apiUrl.replace(/^https?:\/\//, '')
    const wsUrl = `${wsProtocol}://${wsHost}/tasks/ws`

    console.log('[WebSocket] Connecting to:', wsUrl)

    try {
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        console.log('[WebSocket] Connected, sending user_id')
        setIsConnected(true)
        setConnectionError(null)
        // Send user ID to subscribe
        ws.send(JSON.stringify({ user_id: user.id }))
      }

      ws.onmessage = (event) => {
        try {
          const data: TaskUpdate = JSON.parse(event.data)
          console.log('[WebSocket] Message received:', data.type, data)

          if (data.type === 'subscribed') {
            console.log('[WebSocket] Subscribed to channel:', data.channel)
            return
          }

          // Invalidate tasks query to refresh the list
          queryClient.invalidateQueries({ queryKey: ['tasks'] })

          // Call callbacks
          options.onTaskUpdate?.(data)

          if (data.type === 'task_completed' && data.task_id) {
            options.onTaskCompleted?.(data.task_id, data.result)
          }

          if (data.type === 'task_failed' && data.task_id) {
            options.onTaskFailed?.(data.task_id, data.error)
          }
        } catch (err) {
          console.error('[WebSocket] Failed to parse message:', err)
        }
      }

      ws.onerror = (error) => {
        console.error('[WebSocket] Error:', error)
        setConnectionError('WebSocket connection error')
      }

      ws.onclose = (event) => {
        console.log('[WebSocket] Closed:', event.code, event.reason)
        setIsConnected(false)
        wsRef.current = null

        // Reconnect after 3 seconds if not intentionally closed
        if (event.code !== 1000) {
          reconnectTimeoutRef.current = setTimeout(() => {
            console.log('[WebSocket] Attempting to reconnect...')
            connect()
          }, 3000)
        }
      }
    } catch (err) {
      console.error('[WebSocket] Failed to create connection:', err)
      setConnectionError('Failed to establish WebSocket connection')
    }
  }, [user?.id, queryClient, options])

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
    if (wsRef.current) {
      wsRef.current.close(1000, 'Client disconnecting')
      wsRef.current = null
    }
    setIsConnected(false)
  }, [])

  useEffect(() => {
    connect()
    return () => disconnect()
  }, [connect, disconnect])

  return {
    isConnected,
    connectionError,
    reconnect: connect
  }
}
