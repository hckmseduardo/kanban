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
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)

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
      className={`flex-shrink-0 w-52 bg-gray-100 rounded-lg flex flex-col h-full ${isOver ? 'ring-2 ring-primary-400' : ''}`}
    >
      <div className="px-2 py-2 font-medium flex items-center justify-between border-b border-gray-200 flex-shrink-0">
        {editing ? (
          <input
            type="text"
            value={columnName}
            onChange={e => setColumnName(e.target.value)}
            onBlur={() => updateColumn.mutate(columnName)}
            onKeyDown={e => e.key === 'Enter' && updateColumn.mutate(columnName)}
            className="px-1 py-0.5 text-sm border rounded w-full"
            autoFocus
          />
        ) : (
          <div className="flex items-center gap-1 min-w-0">
            <span
              onClick={() => setEditing(true)}
              className="cursor-pointer hover:text-primary-600 text-sm font-semibold truncate"
              title={column.name}
            >
              {column.name}
            </span>
            <span className="text-xs text-gray-500 flex-shrink-0">
              {column.cards?.length || 0}{column.wip_limit ? `/${column.wip_limit}` : ''}
            </span>
          </div>
        )}
        {showDeleteConfirm ? (
          <div className="flex items-center gap-1 flex-shrink-0 ml-1">
            <span className="text-[10px] text-red-600">Delete?</span>
            <button
              onClick={() => {
                deleteColumn.mutate()
                setShowDeleteConfirm(false)
              }}
              className="text-[10px] px-1 py-0.5 bg-red-500 text-white rounded hover:bg-red-600"
            >
              Yes
            </button>
            <button
              onClick={() => setShowDeleteConfirm(false)}
              className="text-[10px] px-1 py-0.5 bg-gray-300 text-gray-700 rounded hover:bg-gray-400"
            >
              No
            </button>
          </div>
        ) : (
          <button
            onClick={() => setShowDeleteConfirm(true)}
            className="text-gray-400 hover:text-red-500 flex-shrink-0 ml-1"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>

      <div className="flex-1 px-1.5 py-1.5 space-y-1.5 overflow-y-auto min-h-0">
        <SortableContext
          items={column.cards?.map(c => c.id) || []}
          strategy={verticalListSortingStrategy}
        >
          {column.cards?.map(card => (
            <Card key={card.id} card={card} boardId={boardId} />
          ))}
        </SortableContext>

        {showAddCard ? (
          <div className="bg-white rounded p-1.5 shadow-sm">
            <textarea
              placeholder="Card title"
              value={newCardTitle}
              onChange={e => setNewCardTitle(e.target.value)}
              className="w-full px-1.5 py-1 text-xs border rounded resize-none"
              rows={2}
              autoFocus
            />
            <div className="flex space-x-1 mt-1">
              <button
                onClick={() => addCard.mutate(newCardTitle)}
                disabled={!newCardTitle || addCard.isPending}
                className="px-2 py-0.5 bg-primary-600 text-white text-xs rounded hover:bg-primary-700 disabled:opacity-50"
              >
                Add
              </button>
              <button
                onClick={() => setShowAddCard(false)}
                className="px-2 py-0.5 text-gray-600 text-xs"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button
            onClick={() => setShowAddCard(true)}
            disabled={isWipLimitReached}
            className="w-full py-1 text-gray-500 hover:text-gray-700 text-xs disabled:opacity-50 disabled:cursor-not-allowed"
          >
            + Add card
          </button>
        )}
      </div>
    </div>
  )
}
