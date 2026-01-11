import { create } from 'zustand'

export interface TaskProgress {
  taskId: string
  workspaceId?: string
  workspaceSlug?: string
  sandboxId?: string
  sandboxSlug?: string
  action: string
  step: number
  totalSteps: number
  stepName: string
  percentage: number
  status: 'pending' | 'in_progress' | 'completed' | 'failed'
  error?: string
  result?: Record<string, unknown>
  updatedAt: number
}

interface TaskProgressState {
  // Map of taskId -> TaskProgress
  tasks: Record<string, TaskProgress>

  // Start tracking a new task
  startTask: (
    taskId: string,
    workspaceId?: string,
    workspaceSlug?: string,
    action?: string,
    sandboxId?: string,
    sandboxSlug?: string
  ) => void

  // Update task progress from WebSocket
  updateProgress: (taskId: string, update: Partial<TaskProgress>) => void

  // Mark task as completed
  completeTask: (taskId: string, result?: Record<string, unknown>) => void

  // Mark task as failed
  failTask: (taskId: string, error?: string) => void

  // Remove a task from tracking
  removeTask: (taskId: string) => void

  // Get task by workspace slug
  getTaskByWorkspaceSlug: (slug: string) => TaskProgress | undefined

  // Get all active tasks (pending or in_progress)
  getActiveTasks: () => TaskProgress[]

  // Clean up old completed/failed tasks (older than 30 seconds)
  cleanupOldTasks: () => void
}

export const useTaskProgressStore = create<TaskProgressState>((set, get) => ({
  tasks: {},

  startTask: (taskId, workspaceId, workspaceSlug, action = 'unknown', sandboxId, sandboxSlug) => {
    set((state) => ({
      tasks: {
        ...state.tasks,
        [taskId]: {
          taskId,
          workspaceId,
          workspaceSlug,
          sandboxId,
          sandboxSlug,
          action,
          step: 0,
          totalSteps: 1,
          stepName: 'Starting...',
          percentage: 0,
          status: 'pending',
          updatedAt: Date.now(),
        },
      },
    }))
  },

  updateProgress: (taskId, update) => {
    set((state) => {
      const existing = state.tasks[taskId]
      if (!existing) {
        // Create a new task entry if it doesn't exist
        return {
          tasks: {
            ...state.tasks,
            [taskId]: {
              taskId,
              action: update.action || 'unknown',
              workspaceId: update.workspaceId,
              workspaceSlug: update.workspaceSlug,
              sandboxId: update.sandboxId,
              sandboxSlug: update.sandboxSlug,
              step: update.step || 0,
              totalSteps: update.totalSteps || 1,
              stepName: update.stepName || 'Processing...',
              percentage: update.percentage || 0,
              status: 'in_progress',
              updatedAt: Date.now(),
            },
          },
        }
      }
      return {
        tasks: {
          ...state.tasks,
          [taskId]: {
            ...existing,
            ...update,
            status: 'in_progress',
            updatedAt: Date.now(),
          },
        },
      }
    })
  },

  completeTask: (taskId, result) => {
    set((state) => {
      const existing = state.tasks[taskId]
      if (!existing) return state
      return {
        tasks: {
          ...state.tasks,
          [taskId]: {
            ...existing,
            status: 'completed',
            percentage: 100,
            stepName: 'Completed',
            result,
            updatedAt: Date.now(),
          },
        },
      }
    })
  },

  failTask: (taskId, error) => {
    set((state) => {
      const existing = state.tasks[taskId]
      if (!existing) return state
      return {
        tasks: {
          ...state.tasks,
          [taskId]: {
            ...existing,
            status: 'failed',
            error,
            stepName: 'Failed',
            updatedAt: Date.now(),
          },
        },
      }
    })
  },

  removeTask: (taskId) => {
    set((state) => {
      const { [taskId]: _, ...rest } = state.tasks
      return { tasks: rest }
    })
  },

  getTaskByWorkspaceSlug: (slug) => {
    const tasks = get().tasks
    return Object.values(tasks).find(
      (t) => t.workspaceSlug === slug && (t.status === 'pending' || t.status === 'in_progress')
    )
  },

  getActiveTasks: () => {
    const tasks = get().tasks
    return Object.values(tasks).filter(
      (t) => t.status === 'pending' || t.status === 'in_progress'
    )
  },

  cleanupOldTasks: () => {
    const now = Date.now()
    const threshold = 30 * 1000 // 30 seconds
    set((state) => {
      const filtered = Object.entries(state.tasks).filter(([_, task]) => {
        if (task.status === 'pending' || task.status === 'in_progress') return true
        return now - task.updatedAt < threshold
      })
      return { tasks: Object.fromEntries(filtered) }
    })
  },
}))
