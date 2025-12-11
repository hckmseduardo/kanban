import { Outlet, Link } from 'react-router-dom'
import { useAuthStore } from '../stores/authStore'
import { useState, useRef, useEffect } from 'react'
import ThemeToggle from './ThemeToggle'

export default function Layout() {
  const { user, logout } = useAuthStore()
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

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
                        to="/tasks"
                        className="block px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-dark-700"
                        onClick={() => setIsUserMenuOpen(false)}
                      >
                        Task Manager
                      </Link>
                      <button
                        onClick={() => {
                          setIsUserMenuOpen(false)
                          logout()
                        }}
                        className="block w-full text-left px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-dark-700"
                      >
                        Logout
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
    </div>
  )
}
