import { useEffect, useRef, useState, useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'

interface WebSocketMessage {
  type: string
  user_id?: string
  user_name?: string
  data?: unknown
  timestamp?: string
  x?: number
  y?: number
  card_id?: string
  field?: string
}

interface OnlineUser {
  user_id: string
  user_name: string
}

interface UseWebSocketOptions {
  boardId: string
  userId: string
  userName: string
  onMessage?: (message: WebSocketMessage) => void
}

export function useWebSocket({ boardId, userId, userName, onMessage }: UseWebSocketOptions) {
  const [isConnected, setIsConnected] = useState(false)
  const [onlineUsers, setOnlineUsers] = useState<OnlineUser[]>([])
  const [userCursors, setUserCursors] = useState<Record<string, { x: number; y: number; name: string }>>({})
  const [userFocus, setUserFocus] = useState<Record<string, { card_id: string; name: string }>>({})
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const queryClient = useQueryClient()
  const handleMessageRef = useRef<(message: WebSocketMessage) => void>(() => {})

  // Message handler - updates ref to avoid stale closure
  const handleMessage = useCallback((message: WebSocketMessage) => {
    switch (message.type) {
      case 'pong':
        // Keep-alive response
        break

      case 'users_online':
        setOnlineUsers((message as unknown as { users: OnlineUser[] }).users || [])
        break

      case 'user_joined':
        setOnlineUsers(prev => {
          if (prev.some(u => u.user_id === message.user_id)) return prev
          return [...prev, { user_id: message.user_id!, user_name: message.user_name! }]
        })
        break

      case 'user_left':
        setOnlineUsers(prev => prev.filter(u => u.user_id !== message.user_id))
        setUserCursors(prev => {
          const next = { ...prev }
          delete next[message.user_id!]
          return next
        })
        setUserFocus(prev => {
          const next = { ...prev }
          delete next[message.user_id!]
          return next
        })
        break

      case 'cursor_move':
        if (message.user_id && message.x !== undefined && message.y !== undefined) {
          setUserCursors(prev => ({
            ...prev,
            [message.user_id!]: { x: message.x!, y: message.y!, name: message.user_name || 'Unknown' }
          }))
        }
        break

      case 'card_focus':
        if (message.user_id && message.card_id) {
          setUserFocus(prev => ({
            ...prev,
            [message.user_id!]: { card_id: message.card_id!, name: message.user_name || 'Unknown' }
          }))
        }
        break

      case 'card_blur':
        if (message.user_id) {
          setUserFocus(prev => {
            const next = { ...prev }
            delete next[message.user_id!]
            return next
          })
        }
        break

      // Board/card change events - invalidate queries to refresh data
      case 'card_created':
      case 'card_updated':
      case 'card_moved':
      case 'card_deleted':
      case 'column_created':
      case 'column_updated':
      case 'column_deleted':
        queryClient.invalidateQueries({ queryKey: ['board', boardId] })
        break

      case 'comment_added':
        if (message.data && typeof message.data === 'object' && 'card_id' in message.data) {
          queryClient.invalidateQueries({ queryKey: ['comments', (message.data as { card_id: string }).card_id] })
        }
        break

      case 'label_changed':
      case 'assignee_changed':
        queryClient.invalidateQueries({ queryKey: ['board', boardId] })
        break
    }
  }, [boardId, queryClient])

  // Keep ref updated with latest handleMessage
  handleMessageRef.current = handleMessage

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    // Construct WebSocket URL
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const wsUrl = `${protocol}//${host}/api/ws/${boardId}?user_id=${userId}&user_name=${encodeURIComponent(userName)}`

    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      setIsConnected(true)
      console.log('[WS] Connected to board:', boardId)

      // Start ping interval to keep connection alive
      pingIntervalRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }))
        }
      }, 30000)
    }

    ws.onclose = () => {
      setIsConnected(false)
      console.log('[WS] Disconnected')

      // Clear ping interval
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current)
      }

      // Attempt to reconnect after 3 seconds
      reconnectTimeoutRef.current = setTimeout(() => {
        connect()
      }, 3000)
    }

    ws.onerror = (error) => {
      console.error('[WS] Error:', error)
    }

    ws.onmessage = (event) => {
      try {
        const message: WebSocketMessage = JSON.parse(event.data)
        // Use ref to get latest handler, avoiding stale closure
        handleMessageRef.current(message)
        onMessage?.(message)
      } catch (e) {
        console.error('[WS] Failed to parse message:', e)
      }
    }
  }, [boardId, userId, userName, onMessage])

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
    }
    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current)
    }
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }, [])

  const send = useCallback((message: WebSocketMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message))
    }
  }, [])

  // Send cursor position
  const sendCursorMove = useCallback((x: number, y: number, cardId?: string) => {
    send({ type: 'cursor_move', x, y, card_id: cardId })
  }, [send])

  // Send card focus event
  const sendCardFocus = useCallback((cardId: string) => {
    send({ type: 'card_focus', card_id: cardId })
  }, [send])

  // Send card blur event
  const sendCardBlur = useCallback((cardId: string) => {
    send({ type: 'card_blur', card_id: cardId })
  }, [send])

  // Send typing event
  const sendTyping = useCallback((cardId: string, field: string) => {
    send({ type: 'typing', card_id: cardId, field })
  }, [send])

  // Broadcast board/card changes
  const broadcastChange = useCallback((type: string, data: unknown) => {
    send({ type, data })
  }, [send])

  useEffect(() => {
    connect()
    return () => disconnect()
  }, [connect, disconnect])

  return {
    isConnected,
    onlineUsers,
    userCursors,
    userFocus,
    send,
    sendCursorMove,
    sendCardFocus,
    sendCardBlur,
    sendTyping,
    broadcastChange
  }
}
