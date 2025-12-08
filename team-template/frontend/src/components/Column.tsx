import { useState } from 'react'
import { useDroppable } from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { columnsApi, cardsApi } from '../services/api'
import Card from './Card'

interface ColumnProps {
  column: {
    id: string
    name: string
    wip_limit?: number
    cards?: any[]
  }
  boardId: string
  onBroadcastChange?: (type: string, data: unknown) => void
}

export default function Column({ column, boardId, onBroadcastChange }: ColumnProps) {
  const queryClient = useQueryClient()
  const [showAddCard, setShowAddCard] = useState(false)
  const [newCardTitle, setNewCardTitle] = useState('')
  const [editing, setEditing] = useState(false)
  const [columnName, setColumnName] = useState(column.name)

  const { setNodeRef, isOver } = useDroppable({
    id: column.id
  })

  const updateColumn = useMutation({
    mutationFn: (name: string) => columnsApi.update(column.id, { name }),
    onSuccess: (_, name) => {
      queryClient.invalidateQueries({ queryKey: ['board', boardId] })
      onBroadcastChange?.('column_updated', { columnId: column.id, name })
      setEditing(false)
    }
  })

  const deleteColumn = useMutation({
    mutationFn: () => columnsApi.delete(column.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['board', boardId] })
      onBroadcastChange?.('column_deleted', { columnId: column.id })
    }
  })

  const addCard = useMutation({
    mutationFn: (title: string) => cardsApi.create({
      column_id: column.id,
      title,
      position: column.cards?.length || 0
    }),
    onSuccess: (response, title) => {
      queryClient.invalidateQueries({ queryKey: ['board', boardId] })
      onBroadcastChange?.('card_created', { columnId: column.id, title, cardId: response?.data?.id })
      setShowAddCard(false)
      setNewCardTitle('')
    }
  })

  const isWipLimitReached = !!(column.wip_limit && (column.cards?.length || 0) >= column.wip_limit)

  return (
    <div
      ref={setNodeRef}
      className={`flex-shrink-0 w-72 bg-gray-100 rounded-lg ${isOver ? 'ring-2 ring-primary-400' : ''}`}
    >
      <div className="p-3 font-medium flex items-center justify-between">
        {editing ? (
          <input
            type="text"
            value={columnName}
            onChange={e => setColumnName(e.target.value)}
            onBlur={() => updateColumn.mutate(columnName)}
            onKeyDown={e => e.key === 'Enter' && updateColumn.mutate(columnName)}
            className="px-2 py-1 border rounded w-full"
            autoFocus
          />
        ) : (
          <div className="flex items-center space-x-2">
            <span
              onClick={() => setEditing(true)}
              className="cursor-pointer hover:text-primary-600"
            >
              {column.name}
            </span>
            <span className="text-sm text-gray-500">
              ({column.cards?.length || 0}{column.wip_limit ? `/${column.wip_limit}` : ''})
            </span>
          </div>
        )}
        <button
          onClick={() => deleteColumn.mutate()}
          className="text-gray-400 hover:text-red-500"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div className="px-3 pb-3 space-y-2 min-h-[100px]">
        <SortableContext
          items={column.cards?.map(c => c.id) || []}
          strategy={verticalListSortingStrategy}
        >
          {column.cards?.map(card => (
            <Card key={card.id} card={card} boardId={boardId} />
          ))}
        </SortableContext>

        {showAddCard ? (
          <div className="bg-white rounded-lg p-2 shadow-sm">
            <textarea
              placeholder="Card title"
              value={newCardTitle}
              onChange={e => setNewCardTitle(e.target.value)}
              className="w-full px-2 py-1 border rounded resize-none"
              rows={2}
              autoFocus
            />
            <div className="flex space-x-2 mt-2">
              <button
                onClick={() => addCard.mutate(newCardTitle)}
                disabled={!newCardTitle || addCard.isPending}
                className="px-3 py-1 bg-primary-600 text-white text-sm rounded hover:bg-primary-700 disabled:opacity-50"
              >
                Add
              </button>
              <button
                onClick={() => setShowAddCard(false)}
                className="px-3 py-1 text-gray-600 text-sm"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button
            onClick={() => setShowAddCard(true)}
            disabled={isWipLimitReached}
            className="w-full py-2 text-gray-500 hover:text-gray-700 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
          >
            + Add card
          </button>
        )}
      </div>
    </div>
  )
}
