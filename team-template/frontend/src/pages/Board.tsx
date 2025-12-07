import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, useMemo } from 'react'
import { useParams, Link } from 'react-router-dom'
import { DndContext, DragEndEvent, DragOverlay, DragStartEvent, closestCorners, PointerSensor, useSensor, useSensors } from '@dnd-kit/core'
import { SortableContext, horizontalListSortingStrategy } from '@dnd-kit/sortable'
import { boardsApi, columnsApi, cardsApi, labelsApi } from '../services/api'
import Column from '../components/Column'
import Card from '../components/Card'

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

  // Configure sensors to require distance before drag starts, allowing clicks to work
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8, // Require 8px movement before drag starts
      },
    })
  )

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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['board', boardId] })
      setShowAddColumn(false)
      setNewColumnName('')
    }
  })

  const moveCard = useMutation({
    mutationFn: ({ cardId, columnId, position }: { cardId: string; columnId: string; position: number }) =>
      cardsApi.move(cardId, columnId, position),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['board', boardId] })
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
        </div>
        <div className="flex items-center gap-2">
          <Link
            to={`/board/${boardId}/reports`}
            className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
            Reports
          </Link>
        </div>
      </div>

      {/* Search and Filters */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            placeholder="Search cards..."
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
    </div>
  )
}
