import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { boardsApi } from '../services/api'

type Visibility = 'private' | 'team' | 'public'

const visibilityOptions: { value: Visibility; label: string; icon: string; description: string }[] = [
  { value: 'private', label: 'Private', icon: '🔒', description: 'Only you can view' },
  { value: 'team', label: 'Team', icon: '👥', description: 'All team members' },
  { value: 'public', label: 'Public', icon: '🌐', description: 'Anyone with link' }
]

export default function BoardList() {
  const queryClient = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)
  const [newBoard, setNewBoard] = useState({ name: '', description: '', visibility: 'team' as Visibility })

  const { data: boards, isLoading } = useQuery({
    queryKey: ['boards'],
    queryFn: () => boardsApi.list().then(res => res.data)
  })

  const createBoard = useMutation({
    mutationFn: (data: { name: string; description?: string }) => boardsApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['boards'] })
      setShowCreate(false)
      setNewBoard({ name: '', description: '', visibility: 'team' })
    }
  })

  const deleteBoard = useMutation({
    mutationFn: (id: string) => boardsApi.delete(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['boards'] })
  })

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold text-gray-900">Boards</h1>
        <button
          onClick={() => setShowCreate(true)}
          className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700"
        >
          New Board
        </button>
      </div>

      {showCreate && (
        <div className="bg-white p-4 rounded-lg shadow">
          <h2 className="text-lg font-medium mb-4">Create Board</h2>
          <div className="space-y-4">
            <input
              type="text"
              placeholder="Board name"
              value={newBoard.name}
              onChange={e => setNewBoard({ ...newBoard, name: e.target.value })}
              className="w-full px-3 py-2 border rounded-lg"
            />
            <textarea
              placeholder="Description (optional)"
              value={newBoard.description}
              onChange={e => setNewBoard({ ...newBoard, description: e.target.value })}
              className="w-full px-3 py-2 border rounded-lg"
              rows={2}
            />
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Visibility</label>
              <div className="grid grid-cols-3 gap-2">
                {visibilityOptions.map(option => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => setNewBoard({ ...newBoard, visibility: option.value })}
                    className={`p-3 rounded-lg border text-center transition-colors ${
                      newBoard.visibility === option.value
                        ? 'border-primary-500 bg-primary-50 text-primary-700'
                        : 'border-gray-200 hover:border-gray-300'
                    }`}
                  >
                    <div className="text-xl mb-1">{option.icon}</div>
                    <div className="text-sm font-medium">{option.label}</div>
                    <div className="text-xs text-gray-500">{option.description}</div>
                  </button>
                ))}
              </div>
            </div>
            <div className="flex space-x-2">
              <button
                onClick={() => createBoard.mutate(newBoard)}
                disabled={!newBoard.name || createBoard.isPending}
                className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50"
              >
                Create
              </button>
              <button
                onClick={() => {
                  setShowCreate(false)
                  setNewBoard({ name: '', description: '', visibility: 'team' })
                }}
                className="px-4 py-2 text-gray-600 hover:text-gray-800"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {boards?.map((board: any) => {
          const visibility = visibilityOptions.find(v => v.value === board.visibility) || visibilityOptions[1]
          return (
            <div key={board.id} className="bg-white p-4 rounded-lg shadow hover:shadow-md transition-shadow">
              <Link to={`/board/${board.id}`} className="block">
                <div className="flex items-start justify-between">
                  <h3 className="text-lg font-medium text-gray-900">{board.name}</h3>
                  <span className="text-sm" title={visibility.description}>{visibility.icon}</span>
                </div>
                {board.description && (
                  <p className="text-sm text-gray-500 mt-1">{board.description}</p>
                )}
              </Link>
              <div className="mt-4 flex justify-between items-center">
                <span className="text-xs text-gray-400">
                  {visibility.label}
                </span>
                <button
                  onClick={() => deleteBoard.mutate(board.id)}
                  className="text-sm text-red-600 hover:text-red-700"
                >
                  Delete
                </button>
              </div>
            </div>
          )
        })}

        {boards?.length === 0 && !showCreate && (
          <div className="col-span-full text-center py-12 text-gray-500">
            No boards yet. Create your first board to get started.
          </div>
        )}
      </div>
    </div>
  )
}
