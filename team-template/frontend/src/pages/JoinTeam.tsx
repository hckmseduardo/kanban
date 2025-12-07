import { useState, useEffect } from 'react'
import { useSearchParams, useNavigate, Link } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { teamApi } from '../services/api'

export default function JoinTeam() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const token = searchParams.get('token')

  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)

  const acceptMutation = useMutation({
    mutationFn: (data: { token: string; userName: string }) =>
      teamApi.acceptInvitation(data.token, undefined, data.userName),
    onSuccess: (response) => {
      setSuccess(true)
      // Store the new member info if needed
      const member = response.data.member
      if (member) {
        localStorage.setItem('user_id', member.id)
        localStorage.setItem('user_name', member.name)
        localStorage.setItem('user_email', member.email)
      }
      // Redirect to home after 2 seconds
      setTimeout(() => {
        navigate('/')
      }, 2000)
    },
    onError: (err: any) => {
      setError(err.response?.data?.detail || 'Failed to accept invitation. The link may be invalid or expired.')
    }
  })

  useEffect(() => {
    if (!token) {
      setError('No invitation token provided. Please use the link from your invitation email.')
    }
  }, [token])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!token) return

    if (!name.trim()) {
      setError('Please enter your name')
      return
    }

    setError('')
    acceptMutation.mutate({ token, userName: name.trim() })
  }

  if (success) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex items-center justify-center p-4">
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-8 max-w-md w-full text-center">
          <div className="w-16 h-16 bg-green-100 dark:bg-green-900 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">Welcome to the Team!</h1>
          <p className="text-gray-600 dark:text-gray-400 mb-4">
            Your account has been created successfully. Redirecting you to the dashboard...
          </p>
          <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600 mx-auto"></div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-8 max-w-md w-full">
        <div className="text-center mb-6">
          <div className="w-16 h-16 bg-blue-100 dark:bg-blue-900 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-blue-600 dark:text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Join the Team</h1>
          <p className="text-gray-600 dark:text-gray-400 mt-2">
            You've been invited to join this team's Kanban workspace
          </p>
        </div>

        {error && (
          <div className="mb-4 p-4 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-lg">
            <div className="flex items-start gap-3">
              <svg className="w-5 h-5 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <p className="text-red-700 dark:text-red-300 text-sm">{error}</p>
            </div>
          </div>
        )}

        {token ? (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="name" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Your Name
              </label>
              <input
                type="text"
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent dark:bg-gray-700 dark:text-white"
                placeholder="Enter your full name"
                autoFocus
                required
              />
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                This is how you'll appear to other team members
              </p>
            </div>

            <button
              type="submit"
              disabled={acceptMutation.isPending}
              className="w-full py-3 px-4 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              {acceptMutation.isPending ? (
                <>
                  <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
                  Creating your account...
                </>
              ) : (
                <>
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 16l-4-4m0 0l4-4m-4 4h14m-5 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h7a3 3 0 013 3v1" />
                  </svg>
                  Join Team
                </>
              )}
            </button>
          </form>
        ) : (
          <div className="text-center">
            <p className="text-gray-600 dark:text-gray-400 mb-4">
              If you received an invitation email, please click the link in that email to join.
            </p>
            <Link
              to="/"
              className="text-blue-600 hover:text-blue-700 dark:text-blue-400 font-medium"
            >
              Go to Homepage
            </Link>
          </div>
        )}

        <div className="mt-6 pt-6 border-t dark:border-gray-700 text-center">
          <p className="text-xs text-gray-500 dark:text-gray-400">
            By joining, you agree to collaborate respectfully with your team members.
          </p>
        </div>
      </div>
    </div>
  )
}
