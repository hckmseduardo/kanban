import { Outlet, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '../stores/authStore'
import { useTaskProgressStore } from '../stores/taskProgressStore'
import { useState, useRef, useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import ThemeToggle from './ThemeToggle'
import LanguageSelector from './LanguageSelector'
import { useTaskWebSocket } from '../hooks/useTaskWebSocket'

interface Toast {
  id: string
  type: 'success' | 'error' | 'info'
  message: string
}

export default function Layout() {
  const { t } = useTranslation()
  const { user, logout } = useAuthStore()
  const { updateProgress, completeTask, failTask, cleanupOldTasks } = useTaskProgressStore()
  const queryClient = useQueryClient()
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false)
  const [toasts, setToasts] = useState<Toast[]>([])
  const menuRef = useRef<HTMLDivElement>(null)

  // Show toast notification
  const showToast = (type: Toast['type'], message: string) => {
    const id = Date.now().toString()
    setToasts(prev => [...prev, { id, type, message }])
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id))
    }, 5000)
  }

  // Cleanup old completed/failed tasks periodically
  useEffect(() => {
    const interval = setInterval(cleanupOldTasks, 10000)
    return () => clearInterval(interval)
  }, [cleanupOldTasks])

  // WebSocket for real-time task updates (app-level)
  useTaskWebSocket({
    onTaskUpdate: (update) => {
      // Handle progress updates
      if (update.type === 'task.progress' && update.task_id) {
        const payload = (update as any).payload || {}
        updateProgress(update.task_id, {
          workspaceId: payload.workspace_id,
          workspaceSlug: payload.workspace_slug,
          sandboxId: payload.sandbox_id,
          sandboxSlug: payload.sandbox_slug,
          action: payload.action,
          step: update.step || 0,
          totalSteps: update.total_steps || 1,
          stepName: update.step_name || 'Processing...',
          percentage: update.percentage || 0,
        })
        // Also refresh workspaces list on progress updates to show the workspace card
        if (payload.action === 'create_workspace') {
          queryClient.invalidateQueries({ queryKey: ['workspaces'] })
        }
      }
    },
    onTaskCompleted: (taskId, result) => {
      // Mark task as completed in store
      completeTask(taskId, result)

      const action = (result as any)?.action
      const teamSlug = (result as any)?.team_slug

      if (action === 'create_team') {
        showToast('success', `Team "${teamSlug}" created successfully!`)
      } else if (action === 'delete_team') {
        showToast('success', `Team "${teamSlug}" deleted successfully!`)
      }

      // Workspace/Sandbox actions
      const workspaceSlug = (result as any)?.workspace_slug
      const sandboxSlug = (result as any)?.sandbox_slug

      if (action === 'create_workspace') {
        showToast('success', `Workspace "${workspaceSlug}" created successfully!`)
        queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      } else if (action === 'delete_workspace') {
        showToast('success', `Workspace "${workspaceSlug}" deleted successfully!`)
        queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      } else if (action === 'create_sandbox') {
        showToast('success', `Sandbox "${sandboxSlug}" created successfully!`)
        queryClient.invalidateQueries({ queryKey: ['workspaces'] })
        queryClient.invalidateQueries({ queryKey: ['sandboxes'] })
      } else if (action === 'delete_sandbox') {
        showToast('success', `Sandbox "${sandboxSlug}" deleted successfully!`)
        queryClient.invalidateQueries({ queryKey: ['workspaces'] })
        queryClient.invalidateQueries({ queryKey: ['sandboxes'] })
      }

      // Refresh teams lists
      queryClient.invalidateQueries({ queryKey: ['user-teams'] })
      queryClient.invalidateQueries({ queryKey: ['teams'] })
    },
    onTaskFailed: (taskId, error) => {
      // Mark task as failed in store
      failTask(taskId, error)

      showToast('error', `Task failed: ${error || 'Unknown error'}`)
      queryClient.invalidateQueries({ queryKey: ['user-teams'] })
      queryClient.invalidateQueries({ queryKey: ['teams'] })
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
    }
  })

  // Close menu when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsUserMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-dark-900 transition-colors">
      {/* Header */}
      <header className="bg-white dark:bg-dark-800 shadow-sm dark:shadow-dark-700/20">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16">
            {/* Logo */}
            <div className="flex">
              <div className="flex-shrink-0 flex items-center">
                <Link to="/" className="text-xl font-bold text-primary-600 dark:text-primary-400">
                  Kanban
                </Link>
              </div>
            </div>

            {/* User Menu */}
            <div className="flex items-center gap-2">
              <LanguageSelector />
              <ThemeToggle />
              <div className="relative" ref={menuRef}>
                <button
                  onClick={() => setIsUserMenuOpen(!isUserMenuOpen)}
                  className="flex items-center space-x-2 text-sm text-gray-700 dark:text-gray-200 hover:text-gray-900 dark:hover:text-white focus:outline-none"
                >
                  <div className="h-8 w-8 bg-primary-100 dark:bg-primary-900/50 rounded-full flex items-center justify-center">
                    <span className="text-primary-600 dark:text-primary-400 font-medium">
                      {user?.display_name?.charAt(0).toUpperCase() || 'U'}
                    </span>
                  </div>
                  <span className="hidden sm:block">{user?.display_name}</span>
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </button>

                {/* Dropdown Menu */}
                {isUserMenuOpen && (
                  <div className="absolute right-0 mt-2 w-48 bg-white dark:bg-dark-800 rounded-md shadow-lg ring-1 ring-black ring-opacity-5 dark:ring-dark-600 z-50">
                    <div className="py-1">
                      <div className="px-4 py-2 border-b border-gray-100 dark:border-dark-700">
                        <p className="text-sm font-medium text-gray-900 dark:text-gray-100">{user?.display_name}</p>
                        <p className="text-xs text-gray-500 dark:text-gray-400 truncate">{user?.email}</p>
                      </div>
                      <Link
                        to="/"
                        className="block px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-dark-700"
                        onClick={() => setIsUserMenuOpen(false)}
                      >
                        {t('nav.workspaces', 'Workspaces')}
                      </Link>
                      <Link
                        to="/tasks"
                        className="block px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-dark-700"
                        onClick={() => setIsUserMenuOpen(false)}
                      >
                        {t('nav.taskManager')}
                      </Link>
                      <Link
                        to="/settings"
                        className="block px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-dark-700"
                        onClick={() => setIsUserMenuOpen(false)}
                      >
                        {t('nav.settings', 'Settings')}
                      </Link>
                      <button
                        onClick={() => {
                          setIsUserMenuOpen(false)
                          logout()
                        }}
                        className="block w-full text-left rtl:text-right px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-dark-700"
                      >
                        {t('nav.logout')}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto py-6 px-4 sm:px-6 lg:px-8">
        <Outlet />
      </main>

      {/* Toast Notifications (app-level) */}
      <div className="fixed bottom-4 right-4 z-50 space-y-2">
        {toasts.map(toast => (
          <div
            key={toast.id}
            className={`px-4 py-3 rounded-lg shadow-lg flex items-center gap-3 animate-slide-in ${
              toast.type === 'success' ? 'bg-green-500 text-white' :
              toast.type === 'error' ? 'bg-red-500 text-white' :
              'bg-blue-500 text-white'
            }`}
          >
            {toast.type === 'success' && (
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            )}
            {toast.type === 'error' && (
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            )}
            <span>{toast.message}</span>
            <button
              onClick={() => setToasts(prev => prev.filter(t => t.id !== toast.id))}
              className="ml-2 hover:opacity-75"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
