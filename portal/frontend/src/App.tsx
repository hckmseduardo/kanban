import { Routes, Route, Navigate } from 'react-router-dom'
import { useEffect } from 'react'
import { useAuthStore } from './stores/authStore'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import CreateTeamPage from './pages/CreateTeamPage'
import TeamDetailPage from './pages/TeamDetailPage'
import TeamStartingPage from './pages/TeamStartingPage'
import TasksPage from './pages/TasksPage'
import SettingsPage from './pages/SettingsPage'
import WorkspacesPage from './pages/WorkspacesPage'
import CreateWorkspacePage from './pages/CreateWorkspacePage'
import WorkspaceDetailPage from './pages/WorkspaceDetailPage'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuthStore()

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600"></div>
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  return <>{children}</>
}

function App() {
  const { checkAuth } = useAuthStore()

  useEffect(() => {
    // Check for token in URL (from OAuth callback)
    const params = new URLSearchParams(window.location.search)
    const token = params.get('token')

    if (token) {
      localStorage.setItem('token', token)
      // Clean URL
      window.history.replaceState({}, '', window.location.pathname)
    }

    checkAuth()
  }, [checkAuth])

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      <Route
        path="/"
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route index element={<WorkspacesPage />} />
        <Route path="workspaces" element={<Navigate to="/" replace />} />
        <Route path="workspaces/new" element={<CreateWorkspacePage />} />
        <Route path="workspaces/:slug" element={<WorkspaceDetailPage />} />
        <Route path="tasks" element={<TasksPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
