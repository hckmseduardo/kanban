import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, useMemo, useRef, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { DndContext, DragEndEvent, DragOverlay, DragStartEvent, closestCorners, PointerSensor, useSensor, useSensors } from '@dnd-kit/core'
import { SortableContext, horizontalListSortingStrategy } from '@dnd-kit/sortable'
import { boardsApi, columnsApi, cardsApi, labelsApi, exportApi, activityApi } from '../services/api'
import Column from '../components/Column'
import Card from '../components/Card'
import KeyboardShortcutsHelp from '../components/KeyboardShortcutsHelp'
import OnlineUsers from '../components/OnlineUsers'
import { useKeyboardShortcuts, useKeyboardShortcutsHelp } from '../hooks/useKeyboardShortcuts'
import { useWebSocket } from '../hooks/useWebSocket'

// Helper to parse JWT token
function parseJwt(token: string): { sub?: string; email?: string } | null {
  try {
    const base64Url = token.split('.')[1]
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/')
    const jsonPayload = decodeURIComponent(atob(base64).split('').map(c =>
      '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)
    ).join(''))
    return JSON.parse(jsonPayload)
  } catch {
    return null
  }
}

interface CardType {
  id: string
  title: string
  description?: string
  labels?: string[]
  priority?: string
  due_date?: string
  assignee_id?: string
}

interface ColumnType {
  id: string
  name: string
  cards?: CardType[]
}

interface LabelType {
  id: string
  name: string
  color: string
  bg: string
  text: string
}

export default function Board() {
  const { boardId } = useParams<{ boardId: string }>()
  const queryClient = useQueryClient()
  const [activeCard, setActiveCard] = useState<CardType | null>(null)
  const [showAddColumn, setShowAddColumn] = useState(false)
  const [newColumnName, setNewColumnName] = useState('')
  const [showFilters, setShowFilters] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [filterLabel, setFilterLabel] = useState('')
  const [filterPriority, setFilterPriority] = useState('')
  const [filterDueDate, setFilterDueDate] = useState('')
  const [showArchived, setShowArchived] = useState(false)
  const [showActivity, setShowActivity] = useState(false)
  const [showQuickAdd, setShowQuickAdd] = useState(false)
  const [quickAddTitle, setQuickAddTitle] = useState('')
  const searchInputRef = useRef<HTMLInputElement>(null)
  const quickAddInputRef = useRef<HTMLInputElement>(null)
  const { showHelp, openHelp, closeHelp } = useKeyboardShortcutsHelp()

  // Configure sensors to require distance before drag starts, allowing clicks to work
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8, // Require 8px movement before drag starts
      },
    })
  )

  // Get user info from JWT token for WebSocket
  const token = localStorage.getItem('token')
  const tokenData = token ? parseJwt(token) : null
  const userId = tokenData?.sub || 'anonymous'
  const userName = tokenData?.email?.split('@')[0] || 'Anonymous'

  // WebSocket for real-time collaboration
  const { isConnected, onlineUsers, broadcastChange } = useWebSocket({
    boardId: boardId || '',
    userId,
    userName
  })

  const { data: board, isLoading } = useQuery({
    queryKey: ['board', boardId],
    queryFn: () => boardsApi.get(boardId!).then((res: { data: any }) => res.data),
    enabled: !!boardId
  })

  const { data: boardLabels = [] } = useQuery<LabelType[]>({
    queryKey: ['labels', boardId],
    queryFn: () => labelsApi.list(boardId!).then((res: { data: LabelType[] }) => res.data),
    enabled: !!boardId
  })

  const { data: archivedCards = [] } = useQuery<CardType[]>({
    queryKey: ['archivedCards', boardId],
    queryFn: async () => {
      // Get all cards from all columns and filter archived ones
      const boardData = await boardsApi.get(boardId!).then((res: { data: any }) => res.data)
      const archived: CardType[] = []
      for (const col of boardData.columns || []) {
        for (const card of col.cards || []) {
          if (card.archived) {
            archived.push({ ...card, columnName: col.name })
          }
        }
      }
      return archived
    },
    enabled: !!boardId && showArchived
  })

  const { data: boardActivity = { activities: [], total: 0 } } = useQuery({
    queryKey: ['boardActivity', boardId],
    queryFn: () => activityApi.getBoardActivity(boardId!, { limit: 50 }).then((res: { data: any }) => res.data),
    enabled: !!boardId && showActivity
  })

  // Export function
  const handleExport = async () => {
    try {
      const response = await exportApi.exportBoard(boardId!, false)
      const blob = new Blob([response.data], { type: 'application/json' })
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${board?.name || 'board'}.json`
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (error) {
      console.error('Export failed:', error)
    }
  }

  // Restore card mutation
  const restoreCard = useMutation({
    mutationFn: (cardId: string) => cardsApi.restore(cardId),
    onSuccess: (_, cardId) => {
      queryClient.invalidateQueries({ queryKey: ['board', boardId] })
      queryClient.invalidateQueries({ queryKey: ['archivedCards', boardId] })
      broadcastChange('card_updated', { cardId, restored: true })
    }
  })

  // Quick add card mutation
  const quickAddCard = useMutation({
    mutationFn: (title: string) => {
      const firstColumn = board?.columns?.[0]
      if (!firstColumn) throw new Error('No columns available')
      return cardsApi.create({
        column_id: firstColumn.id,
        title,
        position: 0
      })
    },
    onSuccess: (response, title) => {
      queryClient.invalidateQueries({ queryKey: ['board', boardId] })
      broadcastChange('card_created', { title, cardId: response?.data?.id })
      setShowQuickAdd(false)
      setQuickAddTitle('')
    }
  })

  // Keyboard shortcuts
  useKeyboardShortcuts([
    {
      key: '?',
      description: 'Show keyboard shortcuts',
      action: openHelp
    },
    {
      key: 'Escape',
      description: 'Close panels',
      action: () => {
        if (showHelp) closeHelp()
        else if (showQuickAdd) setShowQuickAdd(false)
        else if (showFilters) setShowFilters(false)
        else if (showArchived) setShowArchived(false)
        else if (showActivity) setShowActivity(false)
      }
    },
    {
      key: '/',
      description: 'Focus search',
      action: () => {
        searchInputRef.current?.focus()
      }
    },
    {
      key: 'n',
      description: 'New card',
      action: () => {
        if (board?.columns?.length) {
          setShowQuickAdd(true)
          setTimeout(() => quickAddInputRef.current?.focus(), 50)
        }
      }
    },
    {
      key: 'f',
      description: 'Toggle filters',
      action: () => setShowFilters(!showFilters)
    },
    {
      key: 'a',
      description: 'Toggle archived',
      action: () => setShowArchived(!showArchived)
    },
    {
      key: 'r',
      description: 'Toggle activity',
      action: () => setShowActivity(!showActivity)
    },
    {
      key: 'e',
      description: 'Export board',
      action: handleExport
    }
  ])

  // Focus quick add input when modal opens
  useEffect(() => {
    if (showQuickAdd && quickAddInputRef.current) {
      quickAddInputRef.current.focus()
    }
  }, [showQuickAdd])

  // Filter cards based on search and filters
  const filteredBoard = useMemo(() => {
    if (!board) return null

    const filterCard = (card: CardType): boolean => {
      // Search filter
      if (searchQuery) {
        const query = searchQuery.toLowerCase()
        const matchesTitle = card.title.toLowerCase().includes(query)
        const matchesDesc = card.description?.toLowerCase().includes(query)
        if (!matchesTitle && !matchesDesc) return false
      }

      // Label filter
      if (filterLabel && (!card.labels || !card.labels.includes(filterLabel))) {
        return false
      }

      // Priority filter
      if (filterPriority && card.priority !== filterPriority) {
        return false
      }

      // Due date filter
      if (filterDueDate && card.due_date) {
        const due = new Date(card.due_date)
        const today = new Date()
        today.setHours(0, 0, 0, 0)
        const diffDays = Math.ceil((due.getTime() - today.getTime()) / (1000 * 60 * 60 * 24))

        if (filterDueDate === 'overdue' && diffDays >= 0) return false
        if (filterDueDate === 'today' && diffDays !== 0) return false
        if (filterDueDate === 'week' && (diffDays < 0 || diffDays > 7)) return false
      } else if (filterDueDate && !card.due_date) {
        return false
      }

      return true
    }

    return {
      ...board,
      columns: board.columns?.map((col: ColumnType) => ({
        ...col,
        cards: col.cards?.filter(filterCard)
      }))
    }
  }, [board, searchQuery, filterLabel, filterPriority, filterDueDate])

  const hasActiveFilters = searchQuery || filterLabel || filterPriority || filterDueDate

  const clearFilters = () => {
    setSearchQuery('')
    setFilterLabel('')
    setFilterPriority('')
    setFilterDueDate('')
  }

  const addColumn = useMutation({
    mutationFn: (name: string) => columnsApi.create({
      board_id: boardId!,
      name,
      position: board?.columns?.length || 0
    }),
    onSuccess: (_, name) => {
      queryClient.invalidateQueries({ queryKey: ['board', boardId] })
      broadcastChange('column_created', { name })
      setShowAddColumn(false)
      setNewColumnName('')
    }
  })

  const moveCard = useMutation({
    mutationFn: ({ cardId, columnId, position }: { cardId: string; columnId: string; position: number }) =>
      cardsApi.move(cardId, columnId, position),
    onSuccess: (_, { cardId, columnId, position }) => {
      queryClient.invalidateQueries({ queryKey: ['board', boardId] })
      broadcastChange('card_moved', { cardId, columnId, position })
    }
  })

  const handleDragStart = (event: DragStartEvent) => {
    const { active } = event
    const card = board?.columns
      ?.flatMap((col: any) => col.cards)
      ?.find((c: any) => c.id === active.id)
    setActiveCard(card)
  }

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event
    setActiveCard(null)

    if (!over) return

    const cardId = active.id as string
    const overId = over.id as string

    // Find source and destination columns
    let destColumnId: string | null = null
    let position = 0

    for (const col of board?.columns || []) {
      if (col.id === overId) {
        destColumnId = col.id
        position = col.cards?.length || 0
        break
      }
      const cardIndex = col.cards?.findIndex((c: any) => c.id === overId)
      if (cardIndex !== undefined && cardIndex >= 0) {
        destColumnId = col.id
        position = cardIndex
        break
      }
    }

    if (destColumnId) {
      moveCard.mutate({ cardId, columnId: destColumnId, position })
    }
  }

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
      </div>
    )
  }

  if (!board) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500">Board not found</p>
        <Link to="/" className="text-primary-600 hover:text-primary-700 mt-2 inline-block">
          Back to boards
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-4">
          <Link to="/" className="text-gray-500 hover:text-gray-700">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </Link>
          <h1 className="text-2xl font-bold text-gray-900">{board.name}</h1>
          {/* Connection status indicator */}
          <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'}`} title={isConnected ? 'Connected' : 'Disconnected'} />
          {/* Online users */}
          <OnlineUsers users={onlineUsers} currentUserId={userId} />
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowActivity(!showActivity)}
            className={`flex items-center gap-2 px-3 py-2 text-sm font-medium border rounded-lg ${
              showActivity ? 'bg-primary-50 border-primary-300 text-primary-700' : 'text-gray-700 bg-white border-gray-300 hover:bg-gray-50'
            }`}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            Activity
          </button>
          <button
            onClick={() => setShowArchived(!showArchived)}
            className={`flex items-center gap-2 px-3 py-2 text-sm font-medium border rounded-lg ${
              showArchived ? 'bg-yellow-50 border-yellow-300 text-yellow-700' : 'text-gray-700 bg-white border-gray-300 hover:bg-gray-50'
            }`}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4" />
            </svg>
            Archived
          </button>
          <button
            onClick={handleExport}
            className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
            </svg>
            Export
          </button>
          <Link
            to={`/board/${boardId}/reports`}
            className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
            Reports
          </Link>
          <Link
            to={`/board/${boardId}/calendar`}
            className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
            Calendar
          </Link>
          <Link
            to={`/board/${boardId}/swimlanes`}
            className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
            Swimlanes
          </Link>
          <button
            onClick={openHelp}
            className="flex items-center justify-center w-9 h-9 text-sm font-medium text-gray-500 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
            title="Keyboard shortcuts (?)"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </button>
        </div>
      </div>

      {/* Search and Filters */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            ref={searchInputRef}
            type="text"
            placeholder="Search cards... (press / to focus)"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-4 py-2 text-sm border rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
          />
        </div>
        <button
          onClick={() => setShowFilters(!showFilters)}
          className={`flex items-center gap-2 px-3 py-2 text-sm border rounded-lg ${
            hasActiveFilters ? 'bg-primary-50 border-primary-300 text-primary-700' : 'bg-white text-gray-700 hover:bg-gray-50'
          }`}
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
          </svg>
          Filters
          {hasActiveFilters && (
            <span className="w-2 h-2 bg-primary-500 rounded-full"></span>
          )}
        </button>
        {hasActiveFilters && (
          <button
            onClick={clearFilters}
            className="text-sm text-gray-500 hover:text-gray-700"
          >
            Clear
          </button>
        )}
      </div>

      {/* Filter Panel */}
      {showFilters && (
        <div className="flex flex-wrap gap-4 p-4 bg-gray-50 rounded-lg border">
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Label</label>
            <select
              value={filterLabel}
              onChange={(e) => setFilterLabel(e.target.value)}
              className="px-3 py-1.5 text-sm border rounded-lg bg-white"
            >
              <option value="">All labels</option>
              {boardLabels.map((label: LabelType) => (
                <option key={label.id} value={label.name}>{label.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Priority</label>
            <select
              value={filterPriority}
              onChange={(e) => setFilterPriority(e.target.value)}
              className="px-3 py-1.5 text-sm border rounded-lg bg-white"
            >
              <option value="">All priorities</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Due Date</label>
            <select
              value={filterDueDate}
              onChange={(e) => setFilterDueDate(e.target.value)}
              className="px-3 py-1.5 text-sm border rounded-lg bg-white"
            >
              <option value="">Any time</option>
              <option value="overdue">Overdue</option>
              <option value="today">Due today</option>
              <option value="week">Due this week</option>
            </select>
          </div>
        </div>
      )}

      {/* Archived Cards Panel */}
      {showArchived && (
        <div className="p-4 bg-yellow-50 rounded-lg border border-yellow-200">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-medium text-yellow-800">Archived Cards ({archivedCards.length})</h3>
            <button
              onClick={() => setShowArchived(false)}
              className="text-yellow-600 hover:text-yellow-800"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          {archivedCards.length > 0 ? (
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {archivedCards.map((card: any) => (
                <div key={card.id} className="p-3 bg-white rounded-lg border shadow-sm">
                  <div className="flex items-start justify-between">
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-sm truncate">{card.title}</p>
                      {card.columnName && (
                        <p className="text-xs text-gray-500 mt-0.5">From: {card.columnName}</p>
                      )}
                    </div>
                    <button
                      onClick={() => restoreCard.mutate(card.id)}
                      className="ml-2 px-2 py-1 text-xs bg-green-100 text-green-700 rounded hover:bg-green-200"
                      disabled={restoreCard.isPending}
                    >
                      Restore
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-yellow-700 italic">No archived cards</p>
          )}
        </div>
      )}

      {/* Activity Panel */}
      {showActivity && (
        <div className="p-4 bg-gray-50 rounded-lg border">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-medium text-gray-800">Recent Activity ({boardActivity.total})</h3>
            <button
              onClick={() => setShowActivity(false)}
              className="text-gray-500 hover:text-gray-700"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          {boardActivity.activities && boardActivity.activities.length > 0 ? (
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {boardActivity.activities.map((activity: any) => (
                <div key={activity.id} className="flex items-center gap-3 p-2 bg-white rounded border text-sm">
                  <div className="w-6 h-6 bg-gray-100 rounded-full flex items-center justify-center flex-shrink-0">
                    {activity.action === 'created' && <span className="text-green-600 text-xs">+</span>}
                    {activity.action === 'moved' && <span className="text-blue-600 text-xs">→</span>}
                    {activity.action === 'archived' && <span className="text-yellow-600 text-xs">📦</span>}
                    {activity.action === 'deleted' && <span className="text-red-600 text-xs">×</span>}
                  </div>
                  <div className="flex-1 min-w-0">
                    <span className="font-medium">{activity.card_title}</span>
                    {activity.action === 'moved' && (
                      <span className="text-gray-500"> moved to {activity.to_column_name}</span>
                    )}
                    {activity.action === 'created' && <span className="text-gray-500"> created</span>}
                    {activity.action === 'archived' && <span className="text-gray-500"> archived</span>}
                  </div>
                  <span className="text-xs text-gray-400 flex-shrink-0">
                    {new Date(activity.timestamp).toLocaleDateString()}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-500 italic">No activity recorded</p>
          )}
        </div>
      )}

      <DndContext
        sensors={sensors}
        collisionDetection={closestCorners}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
        <div className="flex space-x-4 overflow-x-auto pb-4">
          <SortableContext
            items={filteredBoard?.columns?.map((col: ColumnType) => col.id) || []}
            strategy={horizontalListSortingStrategy}
          >
            {filteredBoard?.columns?.map((column: ColumnType) => (
              <Column
                key={column.id}
                column={column}
                boardId={boardId!}
                onBroadcastChange={broadcastChange}
              />
            ))}
          </SortableContext>

          <div className="flex-shrink-0 w-72">
            {showAddColumn ? (
              <div className="bg-gray-100 rounded-lg p-3">
                <input
                  type="text"
                  placeholder="Column name"
                  value={newColumnName}
                  onChange={e => setNewColumnName(e.target.value)}
                  className="w-full px-3 py-2 border rounded-lg mb-2"
                  autoFocus
                />
                <div className="flex space-x-2">
                  <button
                    onClick={() => addColumn.mutate(newColumnName)}
                    disabled={!newColumnName}
                    className="px-3 py-1 bg-primary-600 text-white rounded hover:bg-primary-700 disabled:opacity-50"
                  >
                    Add
                  </button>
                  <button
                    onClick={() => setShowAddColumn(false)}
                    className="px-3 py-1 text-gray-600 hover:text-gray-800"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button
                onClick={() => setShowAddColumn(true)}
                className="w-full h-12 border-2 border-dashed border-gray-300 rounded-lg text-gray-500 hover:border-gray-400 hover:text-gray-600"
              >
                + Add Column
              </button>
            )}
          </div>
        </div>

        <DragOverlay>
          {activeCard && <Card card={activeCard} isDragging />}
        </DragOverlay>
      </DndContext>

      {/* Quick Add Card Modal */}
      {showQuickAdd && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={() => setShowQuickAdd(false)}>
          <div className="bg-white rounded-lg w-full max-w-md p-4 shadow-xl" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-medium mb-3">Quick Add Card</h3>
            <p className="text-sm text-gray-500 mb-3">
              Adding to column: <span className="font-medium">{board?.columns?.[0]?.name || 'First column'}</span>
            </p>
            <input
              ref={quickAddInputRef}
              type="text"
              value={quickAddTitle}
              onChange={e => setQuickAddTitle(e.target.value)}
              placeholder="Card title..."
              className="w-full px-3 py-2 border rounded-lg mb-3"
              onKeyDown={e => {
                if (e.key === 'Enter' && quickAddTitle.trim()) {
                  quickAddCard.mutate(quickAddTitle.trim())
                } else if (e.key === 'Escape') {
                  setShowQuickAdd(false)
                }
              }}
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowQuickAdd(false)}
                className="px-4 py-2 text-gray-600 hover:text-gray-800"
              >
                Cancel
              </button>
              <button
                onClick={() => quickAddTitle.trim() && quickAddCard.mutate(quickAddTitle.trim())}
                disabled={!quickAddTitle.trim() || quickAddCard.isPending}
                className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50"
              >
                {quickAddCard.isPending ? 'Adding...' : 'Add Card'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Keyboard Shortcuts Help Modal */}
      <KeyboardShortcutsHelp isOpen={showHelp} onClose={closeHelp} />
    </div>
  )
}
