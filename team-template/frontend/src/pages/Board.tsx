import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { DndContext, DragEndEvent, DragOverlay, DragStartEvent, closestCorners } from '@dnd-kit/core'
import { SortableContext, horizontalListSortingStrategy } from '@dnd-kit/sortable'
import { boardsApi, columnsApi, cardsApi } from '../services/api'
import Column from '../components/Column'
import Card from '../components/Card'

export default function Board() {
  const { boardId } = useParams<{ boardId: string }>()
  const queryClient = useQueryClient()
  const [activeCard, setActiveCard] = useState<any>(null)
  const [showAddColumn, setShowAddColumn] = useState(false)
  const [newColumnName, setNewColumnName] = useState('')

  const { data: board, isLoading } = useQuery({
    queryKey: ['board', boardId],
    queryFn: () => boardsApi.get(boardId!).then(res => res.data),
    enabled: !!boardId
  })

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

      <DndContext
        collisionDetection={closestCorners}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
        <div className="flex space-x-4 overflow-x-auto pb-4">
          <SortableContext
            items={board.columns?.map((col: any) => col.id) || []}
            strategy={horizontalListSortingStrategy}
          >
            {board.columns?.map((column: any) => (
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
