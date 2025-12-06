import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { cardsApi } from '../services/api'

interface ChecklistItem {
  id: string
  text: string
  completed: boolean
}

interface ChecklistProps {
  cardId: string
  boardId?: string
  items: ChecklistItem[]
}

export default function Checklist({ cardId, boardId, items }: ChecklistProps) {
  const queryClient = useQueryClient()
  const [newItemText, setNewItemText] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editText, setEditText] = useState('')

  const invalidateBoard = () => {
    if (boardId) {
      queryClient.invalidateQueries({ queryKey: ['board', boardId] })
    }
  }

  const addItem = useMutation({
    mutationFn: (text: string) => cardsApi.addChecklistItem(cardId, text),
    onSuccess: () => {
      invalidateBoard()
      setNewItemText('')
    }
  })

  const toggleItem = useMutation({
    mutationFn: (itemId: string) => cardsApi.toggleChecklistItem(cardId, itemId),
    onSuccess: invalidateBoard
  })

  const updateItem = useMutation({
    mutationFn: ({ itemId, text }: { itemId: string; text: string }) =>
      cardsApi.updateChecklistItem(cardId, itemId, { text }),
    onSuccess: () => {
      invalidateBoard()
      setEditingId(null)
    }
  })

  const deleteItem = useMutation({
    mutationFn: (itemId: string) => cardsApi.deleteChecklistItem(cardId, itemId),
    onSuccess: invalidateBoard
  })

  const completedCount = items.filter(item => item.completed).length
  const totalCount = items.length
  const progress = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0

  const handleAddItem = (e: React.FormEvent) => {
    e.preventDefault()
    if (newItemText.trim()) {
      addItem.mutate(newItemText.trim())
    }
  }

  const startEdit = (item: ChecklistItem) => {
    setEditingId(item.id)
    setEditText(item.text)
  }

  const saveEdit = () => {
    if (editingId && editText.trim()) {
      updateItem.mutate({ itemId: editingId, text: editText.trim() })
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-gray-700">Checklist</h3>
        {totalCount > 0 && (
          <span className="text-xs text-gray-500">
            {completedCount}/{totalCount} ({progress}%)
          </span>
        )}
      </div>

      {/* Progress bar */}
      {totalCount > 0 && (
        <div className="w-full bg-gray-200 rounded-full h-1.5">
          <div
            className={`h-1.5 rounded-full transition-all duration-300 ${
              progress === 100 ? 'bg-green-500' : 'bg-primary-600'
            }`}
            style={{ width: `${progress}%` }}
          />
        </div>
      )}

      {/* Checklist items */}
      <ul className="space-y-2">
        {items.map(item => (
          <li key={item.id} className="flex items-start space-x-2 group">
            <input
              type="checkbox"
              checked={item.completed}
              onChange={() => toggleItem.mutate(item.id)}
              className="mt-1 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
            />

            {editingId === item.id ? (
              <div className="flex-1 flex space-x-2">
                <input
                  type="text"
                  value={editText}
                  onChange={(e) => setEditText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') saveEdit()
                    if (e.key === 'Escape') setEditingId(null)
                  }}
                  className="flex-1 px-2 py-1 text-sm border rounded"
                  autoFocus
                />
                <button
                  onClick={saveEdit}
                  className="px-2 py-1 text-xs bg-primary-600 text-white rounded hover:bg-primary-700"
                >
                  Save
                </button>
                <button
                  onClick={() => setEditingId(null)}
                  className="px-2 py-1 text-xs text-gray-600 hover:text-gray-800"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <>
                <span
                  className={`flex-1 text-sm cursor-pointer ${
                    item.completed ? 'line-through text-gray-400' : 'text-gray-700'
                  }`}
                  onClick={() => startEdit(item)}
                >
                  {item.text}
                </span>
                <button
                  onClick={() => deleteItem.mutate(item.id)}
                  className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 transition-opacity"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </>
            )}
          </li>
        ))}
      </ul>

      {/* Add new item */}
      <form onSubmit={handleAddItem} className="flex space-x-2">
        <input
          type="text"
          value={newItemText}
          onChange={(e) => setNewItemText(e.target.value)}
          placeholder="Add an item..."
          className="flex-1 px-2 py-1 text-sm border rounded focus:ring-1 focus:ring-primary-500 focus:border-primary-500"
        />
        <button
          type="submit"
          disabled={!newItemText.trim() || addItem.isPending}
          className="px-3 py-1 text-sm bg-gray-100 text-gray-700 rounded hover:bg-gray-200 disabled:opacity-50"
        >
          Add
        </button>
      </form>
    </div>
  )
}
