import { useEffect, useState } from 'react'
import { useAuthStore } from '../stores/authStore'
import { Navigate, useSearchParams } from 'react-router-dom'

export default function LoginPage() {
  const { isAuthenticated, login } = useAuthStore()
  const [searchParams, setSearchParams] = useSearchParams()
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  // Handle error query parameters (e.g., from team redirect on 403)
  useEffect(() => {
    const error = searchParams.get('error')
    const team = searchParams.get('team')

    if (error === 'not_a_member' && team) {
      setErrorMessage(`You don't have access to team "${team}". Please request an invitation or sign in with a different account.`)
      // Clean up URL
      searchParams.delete('error')
      searchParams.delete('team')
      setSearchParams(searchParams)
    }
  }, [searchParams, setSearchParams])

  if (isAuthenticated) {
    return <Navigate to="/" replace />
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-md w-full space-y-8">
        <div>
          <h1 className="text-center text-4xl font-bold text-primary-600">Kanban</h1>
          <h2 className="mt-6 text-center text-3xl font-extrabold text-gray-900">
            Sign in to your account
          </h2>
          <p className="mt-2 text-center text-sm text-gray-600">
            Use your Microsoft, Google, or Facebook account
          </p>
        </div>

        {errorMessage && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">
            {errorMessage}
          </div>
        )}

        <div className="mt-8 space-y-4">
          <button
            onClick={login}
            className="group relative w-full flex justify-center py-3 px-4 border border-transparent text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500"
          >
            <span className="flex items-center">
              <svg className="h-5 w-5 mr-2" viewBox="0 0 21 21" fill="currentColor">
                <path d="M0 0h10v10H0zM11 0h10v10H11zM0 11h10v10H0zM11 11h10v10H11z" />
              </svg>
              Sign in with Microsoft
            </span>
          </button>
        </div>

        <p className="mt-4 text-center text-xs text-gray-500">
          By signing in, you agree to our Terms of Service and Privacy Policy
        </p>
      </div>
    </div>
  )
}
