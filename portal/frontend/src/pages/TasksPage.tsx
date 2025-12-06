import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { tasksApi } from '../services/api'
import { formatDistanceToNow } from 'date-fns'
import { useTaskWebSocket } from '../hooks/useTaskWebSocket'

export default function TasksPage() {
  const queryClient = useQueryClient()
  const [notification, setNotification] = useState<{ type: 'success' | 'error', message: string } | null>(null)

  // WebSocket for real-time updates
  const { isConnected, connectionError } = useTaskWebSocket({
    onTaskCompleted: (taskId, result) => {
      setNotification({ type: 'success', message: `Task completed successfully!` })
      setTimeout(() => setNotification(null), 5000)
    },
    onTaskFailed: (taskId, error) => {
      setNotification({ type: 'error', message: `Task failed: ${error || 'Unknown error'}` })
      setTimeout(() => setNotification(null), 5000)
    }
  })

  const { data: tasks, isLoading } = useQuery({
    queryKey: ['tasks'],
    queryFn: () => tasksApi.list().then(res => res.data),
    // Only poll if WebSocket is not connected (fallback)
    refetchInterval: isConnected ? false : 5000
  })

  const retryTask = useMutation({
    mutationFn: (taskId: string) => tasksApi.retry(taskId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tasks'] })
  })

  const cancelTask = useMutation({
    mutationFn: (taskId: string) => tasksApi.cancel(taskId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tasks'] })
  })

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'pending': return '⏳'
      case 'in_progress': return '🔄'
      case 'completed': return '✓'
      case 'failed': return '✗'
      default: return '?'
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'pending': return 'bg-yellow-100 text-yellow-800'
      case 'in_progress': return 'bg-blue-100 text-blue-800'
      case 'completed': return 'bg-green-100 text-green-800'
      case 'failed': return 'bg-red-100 text-red-800'
      default: return 'bg-gray-100 text-gray-800'
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
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Task Manager</h1>
        <div className="flex items-center space-x-2">
          <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${
            isConnected
              ? 'bg-green-100 text-green-800'
              : connectionError
                ? 'bg-red-100 text-red-800'
                : 'bg-yellow-100 text-yellow-800'
          }`}>
            <span className={`w-2 h-2 rounded-full mr-1.5 ${
              isConnected ? 'bg-green-500' : connectionError ? 'bg-red-500' : 'bg-yellow-500'
            }`}></span>
            {isConnected ? 'Live updates' : connectionError ? 'Disconnected' : 'Connecting...'}
          </span>
        </div>
      </div>

      {/* Notification banner */}
      {notification && (
        <div className={`rounded-md p-4 ${
          notification.type === 'success'
            ? 'bg-green-50 border border-green-200'
            : 'bg-red-50 border border-red-200'
        }`}>
          <div className="flex">
            <div className="flex-shrink-0">
              {notification.type === 'success' ? (
                <svg className="h-5 w-5 text-green-400" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                </svg>
              ) : (
                <svg className="h-5 w-5 text-red-400" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                </svg>
              )}
            </div>
            <div className="ml-3">
              <p className={`text-sm font-medium ${
                notification.type === 'success' ? 'text-green-800' : 'text-red-800'
              }`}>
                {notification.message}
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="bg-white shadow rounded-lg overflow-hidden">
        <ul className="divide-y divide-gray-200">
          {tasks?.length === 0 && (
            <li className="px-6 py-12 text-center text-gray-500">
              No tasks yet
            </li>
          )}

          {tasks?.map((task: any) => (
            <li key={task.task_id} className="px-6 py-4">
              <div className="flex items-center justify-between">
                <div className="flex-1">
                  <div className="flex items-center space-x-3">
                    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getStatusColor(task.status)}`}>
                      {getStatusIcon(task.status)} {task.status}
                    </span>
                    <span className="text-sm font-medium text-gray-900">
                      {task.type.replace('.', ' ').replace(/\b\w/g, (l: string) => l.toUpperCase())}
                    </span>
                  </div>

                  {/* Progress bar for in-progress tasks */}
                  {task.status === 'in_progress' && (
                    <div className="mt-3">
                      <div className="flex items-center justify-between text-sm text-gray-600 mb-1">
                        <span>{task.progress.step_name}</span>
                        <span>{task.progress.percentage}%</span>
                      </div>
                      <div className="w-full bg-gray-200 rounded-full h-2">
                        <div
                          className="bg-primary-600 h-2 rounded-full transition-all duration-500"
                          style={{ width: `${task.progress.percentage}%` }}
                        ></div>
                      </div>
                      <p className="mt-1 text-xs text-gray-500">
                        Step {task.progress.current_step} of {task.progress.total_steps}
                      </p>
                    </div>
                  )}

                  {/* Error message for failed tasks */}
                  {task.status === 'failed' && task.error && (
                    <p className="mt-2 text-sm text-red-600">{task.error}</p>
                  )}

                  {/* Result for completed tasks */}
                  {task.status === 'completed' && task.result?.url && (
                    <p className="mt-2 text-sm text-green-600">
                      Ready: <a href={task.result.url} target="_blank" rel="noopener noreferrer" className="underline">{task.result.url}</a>
                    </p>
                  )}

                  <p className="mt-2 text-xs text-gray-400">
                    Created {formatDistanceToNow(new Date(task.created_at))} ago
                  </p>
                </div>

                <div className="ml-4 flex space-x-2">
                  {task.status === 'failed' && (
                    <button
                      onClick={() => retryTask.mutate(task.task_id)}
                      disabled={retryTask.isPending}
                      className="text-sm text-primary-600 hover:text-primary-700"
                    >
                      Retry
                    </button>
                  )}
                  {task.status === 'pending' && (
                    <button
                      onClick={() => cancelTask.mutate(task.task_id)}
                      disabled={cancelTask.isPending}
                      className="text-sm text-red-600 hover:text-red-700"
                    >
                      Cancel
                    </button>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
