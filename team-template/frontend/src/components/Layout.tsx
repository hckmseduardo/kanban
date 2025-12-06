import { Outlet, Link, useLocation } from 'react-router-dom'

const TEAM_SLUG = import.meta.env.VITE_TEAM_SLUG || 'Team'

export default function Layout() {
  const location = useLocation()

  return (
    <div className="min-h-screen">
      <nav className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16">
            <div className="flex items-center space-x-8">
              <Link to="/" className="flex items-center space-x-2">
                <svg className="w-8 h-8 text-primary-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2" />
                </svg>
                <span className="text-xl font-bold text-gray-900">{TEAM_SLUG}</span>
              </Link>
              <div className="hidden sm:flex sm:space-x-4">
                <Link
                  to="/"
                  className={`px-3 py-2 text-sm font-medium ${location.pathname === '/' ? 'text-primary-600' : 'text-gray-500 hover:text-gray-700'}`}
                >
                  Boards
                </Link>
                <Link
                  to="/settings"
                  className={`px-3 py-2 text-sm font-medium ${location.pathname === '/settings' ? 'text-primary-600' : 'text-gray-500 hover:text-gray-700'}`}
                >
                  Settings
                </Link>
              </div>
            </div>
          </div>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Outlet />
      </main>
    </div>
  )
}
