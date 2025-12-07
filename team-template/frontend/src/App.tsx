import { Routes, Route } from 'react-router-dom'
import BoardList from './pages/BoardList'
import Board from './pages/Board'
import Settings from './pages/Settings'
import Reports from './pages/Reports'
import Calendar from './pages/Calendar'
import Swimlanes from './pages/Swimlanes'
import Analytics from './pages/Analytics'
import Gantt from './pages/Gantt'
import Layout from './components/Layout'
import { useSSO } from './hooks/useSSO'

export default function App() {
  const { isAuthenticating } = useSSO()

  // Show loading while SSO token is being exchanged
  if (isAuthenticating) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-100">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">Authenticating...</p>
        </div>
      </div>
    )
  }

  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<BoardList />} />
        <Route path="board/:boardId" element={<Board />} />
        <Route path="board/:boardId/reports" element={<Reports />} />
        <Route path="board/:boardId/calendar" element={<Calendar />} />
        <Route path="board/:boardId/swimlanes" element={<Swimlanes />} />
        <Route path="board/:boardId/analytics" element={<Analytics />} />
        <Route path="board/:boardId/gantt" element={<Gantt />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  )
}
