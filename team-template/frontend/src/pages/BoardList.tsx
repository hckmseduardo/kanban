import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, useRef } from 'react'
import { Link } from 'react-router-dom'
import { boardsApi, templatesApi, exportApi } from '../services/api'
import KeyboardShortcutsHelp from '../components/KeyboardShortcutsHelp'
import { useKeyboardShortcuts, useKeyboardShortcutsHelp } from '../hooks/useKeyboardShortcuts'

type Visibility = 'private' | 'team' | 'public'

const visibilityOptions: { value: Visibility; label: string; icon: string; description: string }[] = [
  { value: 'private', label: 'Private', icon: '🔒', description: 'Only you can view' },
  { value: 'team', label: 'Team', icon: '👥', description: 'All team members' },
  { value: 'public', label: 'Public', icon: '🌐', description: 'Anyone with link' }
]

interface Template {
  id: string
  name: string
  description: string
  builtin: boolean
  columns: any[]
  labels: any[]
}

export default function BoardList() {
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [createMode, setCreateMode] = useState<'blank' | 'template'>('blank')
  const [selectedTemplate, setSelectedTemplate] = useState<string>('')
  const [newBoard, setNewBoard] = useState({ name: '', description: '', visibility: 'team' as Visibility })
  const [deleteConfirm, setDeleteConfirm] = useState<{ id: string; name: string } | null>(null)
  const { showHelp, openHelp, closeHelp } = useKeyboardShortcutsHelp()

  // Keyboard shortcuts
  useKeyboardShortcuts([
    {
      key: '?',
      description: 'Show keyboard shortcuts',
      action: openHelp
    },
    {
      key: 'Escape',
      description: 'Close modal',
      action: () => {
        if (showHelp) closeHelp()
        else if (showCreate) {
          setShowCreate(false)
          setNewBoard({ name: '', description: '', visibility: 'team' })
          setSelectedTemplate('')
          setCreateMode('blank')
        }
      }
    },
    {
      key: 'c',
      description: 'Create new board',
      action: () => setShowCreate(true)
    }
  ])

  const { data: boards, isLoading } = useQuery({
    queryKey: ['boards'],
    queryFn: () => boardsApi.list().then(res => res.data)
  })

  const { data: templates } = useQuery({
    queryKey: ['templates'],
    queryFn: () => templatesApi.list().then(res => res.data),
    enabled: showCreate
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

  const createFromTemplate = useMutation({
    mutationFn: ({ templateId, name, description }: { templateId: string; name: string; description?: string }) =>
      templatesApi.apply(templateId, name, description),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['boards'] })
      setShowCreate(false)
      setNewBoard({ name: '', description: '', visibility: 'team' })
      setSelectedTemplate('')
      setCreateMode('blank')
    }
  })

  const importBoard = useMutation({
    mutationFn: (data: any) => exportApi.importBoard(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['boards'] })
    }
  })

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    try {
      const text = await file.text()
      const data = JSON.parse(text)
      importBoard.mutate(data)
    } catch (error) {
      console.error('Failed to parse import file:', error)
    }

    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const handleCreate = () => {
    if (createMode === 'template' && selectedTemplate) {
      createFromTemplate.mutate({
        templateId: selectedTemplate,
        name: newBoard.name,
        description: newBoard.description
      })
    } else {
      createBoard.mutate(newBoard)
    }
  }

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
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Boards</h1>
        <div className="flex items-center gap-2">
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleImport}
            accept=".json"
            className="hidden"
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={importBoard.isPending}
            className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
            </svg>
            {importBoard.isPending ? 'Importing...' : 'Import'}
          </button>
          <button
            onClick={openHelp}
            className="flex items-center justify-center w-9 h-9 text-sm font-medium text-gray-500 dark:text-gray-400 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700"
            title="Keyboard shortcuts (?)"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </button>
        </div>
      </div>

      {/* Create Board Modal */}
      {showCreate && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-lg p-6 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-bold text-gray-900 dark:text-white">Create Board</h2>
              <button
                onClick={() => {
                  setShowCreate(false)
                  setNewBoard({ name: '', description: '', visibility: 'team' })
                  setSelectedTemplate('')
                  setCreateMode('blank')
                }}
                className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="space-y-4">
              {/* Mode Selection */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Start from</label>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => { setCreateMode('blank'); setSelectedTemplate(''); }}
                    className={`p-3 rounded-lg border text-center transition-colors ${
                      createMode === 'blank'
                        ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-300'
                        : 'border-gray-200 dark:border-gray-600 hover:border-gray-300 dark:hover:border-gray-500'
                    }`}
                  >
                    <div className="text-lg mb-1">📋</div>
                    <div className="text-sm font-medium dark:text-gray-200">Blank Board</div>
                  </button>
                  <button
                    type="button"
                    onClick={() => setCreateMode('template')}
                    className={`p-3 rounded-lg border text-center transition-colors ${
                      createMode === 'template'
                        ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-300'
                        : 'border-gray-200 dark:border-gray-600 hover:border-gray-300 dark:hover:border-gray-500'
                    }`}
                  >
                    <div className="text-lg mb-1">📝</div>
                    <div className="text-sm font-medium dark:text-gray-200">From Template</div>
                  </button>
                </div>
              </div>

              {/* Template Selection */}
              {createMode === 'template' && templates && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Choose Template</label>
                  <div className="grid gap-2 max-h-48 overflow-y-auto">
                    {templates.builtin?.map((template: Template) => (
                      <button
                        key={template.id}
                        type="button"
                        onClick={() => setSelectedTemplate(template.id)}
                        className={`p-3 rounded-lg border text-left transition-colors ${
                          selectedTemplate === template.id
                            ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/30'
                            : 'border-gray-200 dark:border-gray-600 hover:border-gray-300 dark:hover:border-gray-500'
                        }`}
                      >
                        <div className="font-medium text-sm dark:text-gray-200">{template.name}</div>
                        <div className="text-xs text-gray-500 dark:text-gray-400">{template.description}</div>
                      </button>
                    ))}
                    {templates.custom?.map((template: Template) => (
                      <button
                        key={template.id}
                        type="button"
                        onClick={() => setSelectedTemplate(template.id)}
                        className={`p-3 rounded-lg border text-left transition-colors ${
                          selectedTemplate === template.id
                            ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/30'
                            : 'border-gray-200 dark:border-gray-600 hover:border-gray-300 dark:hover:border-gray-500'
                        }`}
                      >
                        <div className="font-medium text-sm dark:text-gray-200">{template.name} <span className="text-xs text-gray-400">(custom)</span></div>
                        <div className="text-xs text-gray-500 dark:text-gray-400">{template.description}</div>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <input
                type="text"
                placeholder="Board name"
                value={newBoard.name}
                onChange={e => setNewBoard({ ...newBoard, name: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400"
                autoFocus
              />
              <textarea
                placeholder="Description (optional)"
                value={newBoard.description}
                onChange={e => setNewBoard({ ...newBoard, description: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400"
                rows={2}
              />
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Visibility</label>
                <div className="grid grid-cols-3 gap-2">
                  {visibilityOptions.map(option => (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setNewBoard({ ...newBoard, visibility: option.value })}
                      className={`p-3 rounded-lg border text-center transition-colors ${
                        newBoard.visibility === option.value
                          ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-300'
                          : 'border-gray-200 dark:border-gray-600 hover:border-gray-300 dark:hover:border-gray-500'
                      }`}
                    >
                      <div className="text-xl mb-1">{option.icon}</div>
                      <div className="text-sm font-medium dark:text-gray-200">{option.label}</div>
                      <div className="text-xs text-gray-500 dark:text-gray-400">{option.description}</div>
                    </button>
                  ))}
                </div>
              </div>
              <div className="flex justify-end gap-3 pt-2">
                <button
                  onClick={() => {
                    setShowCreate(false)
                    setNewBoard({ name: '', description: '', visibility: 'team' })
                    setSelectedTemplate('')
                    setCreateMode('blank')
                  }}
                  className="px-4 py-2 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  onClick={handleCreate}
                  disabled={!newBoard.name || createBoard.isPending || createFromTemplate.isPending || (createMode === 'template' && !selectedTemplate)}
                  className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50"
                >
                  {createBoard.isPending || createFromTemplate.isPending ? 'Creating...' : 'Create Board'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {boards?.map((board: any) => {
          const visibility = visibilityOptions.find(v => v.value === board.visibility) || visibilityOptions[1]
          return (
            <div key={board.id} className="bg-white dark:bg-gray-800 p-4 rounded-lg shadow hover:shadow-md transition-shadow min-h-[140px] flex flex-col">
              <Link to={`/board/${board.id}`} className="block flex-1">
                <div className="flex items-start justify-between">
                  <h3 className="text-lg font-medium text-gray-900 dark:text-white">{board.name}</h3>
                  <span className="text-sm" title={visibility.description}>{visibility.icon}</span>
                </div>
                {board.description && (
                  <p className="text-sm text-gray-500 dark:text-gray-400 mt-1 line-clamp-2">{board.description}</p>
                )}
              </Link>
              <div className="mt-4 flex justify-between items-center">
                <span className="text-xs text-gray-400 dark:text-gray-500">
                  {visibility.label}
                </span>
                <button
                  onClick={() => setDeleteConfirm({ id: board.id, name: board.name })}
                  className="text-sm text-red-600 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300"
                >
                  Delete
                </button>
              </div>
            </div>
          )
        })}

        {/* Create Board Card */}
        <button
          onClick={() => setShowCreate(true)}
          className="bg-white dark:bg-gray-800 p-4 rounded-lg shadow hover:shadow-md transition-all border-2 border-dashed border-gray-300 dark:border-gray-600 hover:border-primary-400 dark:hover:border-primary-500 hover:bg-primary-50 dark:hover:bg-primary-900/20 min-h-[140px] flex flex-col items-center justify-center gap-2 group"
        >
          <div className="w-12 h-12 rounded-full bg-gray-100 dark:bg-gray-700 group-hover:bg-primary-100 dark:group-hover:bg-primary-900/50 flex items-center justify-center transition-colors">
            <svg className="w-6 h-6 text-gray-400 dark:text-gray-500 group-hover:text-primary-600 dark:group-hover:text-primary-400 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
          </div>
          <span className="text-gray-500 dark:text-gray-400 group-hover:text-primary-600 dark:group-hover:text-primary-400 font-medium transition-colors">Create Board</span>
          <span className="text-xs text-gray-400 dark:text-gray-500 group-hover:text-primary-500 dark:group-hover:text-primary-400 transition-colors">Press 'c' for shortcut</span>
        </button>
      </div>

      {/* Keyboard Shortcuts Help Modal */}
      <KeyboardShortcutsHelp isOpen={showHelp} onClose={closeHelp} />

      {/* Delete Confirmation Modal */}
      {deleteConfirm && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-md p-6">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
                <svg className="w-6 h-6 text-red-600 dark:text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </div>
              <div>
                <h2 className="text-lg font-bold text-gray-900 dark:text-white">Delete Board</h2>
                <p className="text-sm text-gray-500 dark:text-gray-400">This action cannot be undone</p>
              </div>
            </div>

            <p className="text-gray-700 dark:text-gray-300 mb-6">
              Are you sure you want to delete <strong>"{deleteConfirm.name}"</strong>? All cards and columns will be permanently removed.
            </p>

            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setDeleteConfirm(null)}
                className="px-4 py-2 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  deleteBoard.mutate(deleteConfirm.id)
                  setDeleteConfirm(null)
                }}
                disabled={deleteBoard.isPending}
                className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
              >
                {deleteBoard.isPending ? 'Deleting...' : 'Delete Board'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
