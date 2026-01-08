import { useEffect, useState } from 'react'
import { useSearchParams, useNavigate, Link } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { invitationsApi } from '../services/api'
import { useAuthStore } from '../stores/authStore'

export default function AcceptInvitePage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { isAuthenticated, isLoading: authLoading, user } = useAuthStore()
  const token = searchParams.get('token')

  const [acceptError, setAcceptError] = useState('')
  const [acceptSuccess, setAcceptSuccess] = useState<{ workspace_slug: string; already_member: boolean } | null>(null)

  // Fetch invitation info (public endpoint)
  const { data: inviteInfo, isLoading: infoLoading, error: infoError } = useQuery({
    queryKey: ['invitation-info', token],
    queryFn: () => invitationsApi.getInfo(token!).then(res => res.data),
    enabled: !!token,
    retry: false,
  })

  // Accept invitation mutation
  const acceptMutation = useMutation({
    mutationFn: () => invitationsApi.accept(token!),
    onSuccess: (response) => {
      setAcceptSuccess({
        workspace_slug: response.data.workspace_slug,
        already_member: response.data.already_member
      })
    },
    onError: (err: any) => {
      setAcceptError(err.response?.data?.detail || 'Failed to accept invitation')
    }
  })

  // Auto-accept when authenticated and email matches
  useEffect(() => {
    if (
      isAuthenticated &&
      inviteInfo &&
      inviteInfo.status === 'pending' &&
      user?.email?.toLowerCase() === inviteInfo.email.toLowerCase() &&
      !acceptMutation.isPending &&
      !acceptSuccess &&
      !acceptError
    ) {
      acceptMutation.mutate()
    }
  }, [isAuthenticated, inviteInfo, user, acceptMutation, acceptSuccess, acceptError])

  if (!token) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-dark-900 flex items-center justify-center p-4">
        <div className="bg-white dark:bg-dark-800 rounded-xl shadow-lg dark:shadow-dark-900/50 p-8 max-w-md w-full text-center">
          <div className="w-16 h-16 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-red-600 dark:text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100 mb-2">Invalid Link</h1>
          <p className="text-gray-500 dark:text-gray-400 mb-6">
            This invitation link is invalid or malformed.
          </p>
          <Link
            to="/"
            className="inline-block px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700"
          >
            Go to Dashboard
          </Link>
        </div>
      </div>
    )
  }

  if (infoLoading || authLoading) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-dark-900 flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600"></div>
      </div>
    )
  }

  if (infoError || !inviteInfo) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-dark-900 flex items-center justify-center p-4">
        <div className="bg-white dark:bg-dark-800 rounded-xl shadow-lg dark:shadow-dark-900/50 p-8 max-w-md w-full text-center">
          <div className="w-16 h-16 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-red-600 dark:text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </div>
          <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100 mb-2">Invitation Not Found</h1>
          <p className="text-gray-500 dark:text-gray-400 mb-6">
            This invitation link may have expired or been cancelled.
          </p>
          <Link
            to="/"
            className="inline-block px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700"
          >
            Go to Dashboard
          </Link>
        </div>
      </div>
    )
  }

  // Invitation is expired or already used
  if (inviteInfo.status !== 'pending') {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-dark-900 flex items-center justify-center p-4">
        <div className="bg-white dark:bg-dark-800 rounded-xl shadow-lg dark:shadow-dark-900/50 p-8 max-w-md w-full text-center">
          <div className="w-16 h-16 rounded-full bg-yellow-100 dark:bg-yellow-900/30 flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-yellow-600 dark:text-yellow-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100 mb-2">
            Invitation {inviteInfo.status === 'expired' ? 'Expired' : inviteInfo.status === 'accepted' ? 'Already Used' : 'Unavailable'}
          </h1>
          <p className="text-gray-500 dark:text-gray-400 mb-6">
            {inviteInfo.status === 'expired'
              ? 'This invitation has expired. Please ask for a new invitation.'
              : inviteInfo.status === 'accepted'
              ? 'This invitation has already been accepted.'
              : 'This invitation is no longer available.'}
          </p>
          <Link
            to="/"
            className="inline-block px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700"
          >
            Go to Dashboard
          </Link>
        </div>
      </div>
    )
  }

  // Show success state
  if (acceptSuccess) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-dark-900 flex items-center justify-center p-4">
        <div className="bg-white dark:bg-dark-800 rounded-xl shadow-lg dark:shadow-dark-900/50 p-8 max-w-md w-full text-center">
          <div className="w-16 h-16 rounded-full bg-green-100 dark:bg-green-900/30 flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100 mb-2">
            {acceptSuccess.already_member ? 'Already a Member' : 'Welcome to the Team!'}
          </h1>
          <p className="text-gray-500 dark:text-gray-400 mb-6">
            {acceptSuccess.already_member
              ? `You are already a member of ${inviteInfo.workspace_name}.`
              : `You have successfully joined ${inviteInfo.workspace_name}.`}
          </p>
          <button
            onClick={() => navigate(`/workspaces/${acceptSuccess.workspace_slug}`)}
            className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700"
          >
            Go to Workspace
          </button>
        </div>
      </div>
    )
  }

  // Show error state
  if (acceptError) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-dark-900 flex items-center justify-center p-4">
        <div className="bg-white dark:bg-dark-800 rounded-xl shadow-lg dark:shadow-dark-900/50 p-8 max-w-md w-full text-center">
          <div className="w-16 h-16 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-red-600 dark:text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </div>
          <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100 mb-2">Failed to Accept</h1>
          <p className="text-gray-500 dark:text-gray-400 mb-6">{acceptError}</p>
          <Link
            to="/"
            className="inline-block px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700"
          >
            Go to Dashboard
          </Link>
        </div>
      </div>
    )
  }

  // Not authenticated - show invitation info and login prompt
  if (!isAuthenticated) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-dark-900 flex items-center justify-center p-4">
        <div className="bg-white dark:bg-dark-800 rounded-xl shadow-lg dark:shadow-dark-900/50 p-8 max-w-md w-full">
          <div className="text-center mb-6">
            <div className="w-16 h-16 rounded-full bg-primary-100 dark:bg-primary-900/30 flex items-center justify-center mx-auto mb-4">
              <svg className="w-8 h-8 text-primary-600 dark:text-primary-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z" />
              </svg>
            </div>
            <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100 mb-2">You're Invited!</h1>
            <p className="text-gray-500 dark:text-gray-400">
              <strong>{inviteInfo.invited_by}</strong> has invited you to join
            </p>
          </div>

          <div className="bg-gray-50 dark:bg-dark-700 rounded-lg p-4 mb-6">
            <h2 className="font-semibold text-gray-900 dark:text-gray-100 text-lg">{inviteInfo.workspace_name}</h2>
            <div className="flex items-center gap-2 mt-2 text-sm text-gray-500 dark:text-gray-400">
              <span>Role:</span>
              <span className="px-2 py-0.5 rounded-full bg-primary-100 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 text-xs font-medium capitalize">
                {inviteInfo.role}
              </span>
            </div>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">
              Invitation for: <strong>{inviteInfo.email}</strong>
            </p>
          </div>

          <a
            href={`/login?returnTo=${encodeURIComponent(window.location.pathname + window.location.search)}`}
            className="block w-full px-4 py-3 bg-primary-600 text-white text-center rounded-lg hover:bg-primary-700 font-medium"
          >
            Sign in to Accept
          </a>

          <p className="text-center text-sm text-gray-500 dark:text-gray-400 mt-4">
            Expires on {new Date(inviteInfo.expires_at).toLocaleDateString()}
          </p>
        </div>
      </div>
    )
  }

  // Authenticated but email doesn't match
  if (user?.email?.toLowerCase() !== inviteInfo.email.toLowerCase()) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-dark-900 flex items-center justify-center p-4">
        <div className="bg-white dark:bg-dark-800 rounded-xl shadow-lg dark:shadow-dark-900/50 p-8 max-w-md w-full text-center">
          <div className="w-16 h-16 rounded-full bg-yellow-100 dark:bg-yellow-900/30 flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-yellow-600 dark:text-yellow-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100 mb-2">Wrong Account</h1>
          <p className="text-gray-500 dark:text-gray-400 mb-4">
            This invitation was sent to <strong>{inviteInfo.email}</strong>, but you are signed in as <strong>{user?.email}</strong>.
          </p>
          <p className="text-gray-500 dark:text-gray-400 mb-6">
            Please sign in with the correct account to accept this invitation.
          </p>
          <div className="flex flex-col gap-3">
            <a
              href={`/login?switch_account=true&returnTo=${encodeURIComponent(window.location.pathname + window.location.search)}`}
              className="px-4 py-2 bg-primary-600 text-white text-center rounded-lg hover:bg-primary-700"
            >
              Sign in with Different Account
            </a>
            <Link
              to="/"
              className="px-4 py-2 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-dark-700 rounded-lg text-center"
            >
              Go to Dashboard
            </Link>
          </div>
        </div>
      </div>
    )
  }

  // Accepting invitation (loading state)
  return (
    <div className="min-h-screen bg-gray-50 dark:bg-dark-900 flex items-center justify-center">
      <div className="text-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600 mx-auto mb-4"></div>
        <p className="text-gray-500 dark:text-gray-400">Accepting invitation...</p>
      </div>
    </div>
  )
}
