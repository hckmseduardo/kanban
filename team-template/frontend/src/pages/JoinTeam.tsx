import { useState, useEffect } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { teamApi } from '../services/api'

const PORTAL_URL = import.meta.env.VITE_PORTAL_URL || 'https://kanban.amazing-ai.tools'

export default function JoinTeam() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()

  // Get tokens from URL - portal appends 'token' param after login
  const urlToken = searchParams.get('token')

  // Check if this is a callback from portal login (we stored invitation token before redirect)
  const storedInvitationToken = localStorage.getItem('pending_invitation_token')

  // If we have a stored invitation token, this is a callback - urlToken is the portal auth token
  const isAuthCallback = !!storedInvitationToken && !!urlToken
  const invitationToken = isAuthCallback ? storedInvitationToken : urlToken
  const portalToken = isAuthCallback ? urlToken : null

  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false)

  // Fetch invitation details
  const { data: invitation, isLoading: loadingInvitation } = useQuery({
    queryKey: ['invitation', invitationToken],
    queryFn: async () => {
      if (!invitationToken) return null
      const response = await teamApi.getInvitation(invitationToken)
      return response.data
    },
    enabled: !!invitationToken && !portalToken,
    retry: false,
  })

  // Accept invitation mutation
  const acceptMutation = useMutation({
    mutationFn: (data: { token: string; userId: string; userEmail: string; userName: string }) =>
      teamApi.acceptInvitation(data.token, data.userId, data.userName, data.userEmail),
    onSuccess: (response) => {
      setSuccess(true)
      const member = response.data.member
      if (member) {
        localStorage.setItem('user_id', member.id)
        localStorage.setItem('user_name', member.name)
        localStorage.setItem('user_email', member.email)
      }
      setTimeout(() => {
        navigate('/')
      }, 2000)
    },
    onError: (err: any) => {
      setError(err.response?.data?.detail || 'Failed to accept invitation.')
      setIsProcessing(false)
    }
  })

  // Handle SSO callback - user returned from portal login
  useEffect(() => {
    const processSSO = async () => {
      if (!portalToken || !invitationToken) return

      setIsProcessing(true)
      try {
        // Exchange portal token for user info
        const response = await teamApi.exchangeSSOToken(portalToken)
        const user = response.data.user

        // Clear the stored invitation token
        localStorage.removeItem('pending_invitation_token')

        // Accept the invitation with the authenticated user
        acceptMutation.mutate({
          token: invitationToken,
          userId: user.id,
          userEmail: user.email,
          userName: user.display_name || user.email.split('@')[0]
        })
      } catch (err: any) {
        localStorage.removeItem('pending_invitation_token')
        setError('Failed to authenticate. Please try again.')
        setIsProcessing(false)
      }
    }

    processSSO()
  }, [portalToken, invitationToken])

  // Handle login redirect
  const handleLogin = () => {
    // Store the invitation token before redirecting to portal
    if (invitationToken) {
      localStorage.setItem('pending_invitation_token', invitationToken)
    }
    const callbackUrl = window.location.href.split('?')[0]
    // Redirect to portal login - it will append token= to the callback URL
    window.location.href = `${PORTAL_URL}/api/auth/login?redirect_url=${encodeURIComponent(callbackUrl)}`
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
            Your account has been linked successfully. Redirecting you to the dashboard...
          </p>
          <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600 mx-auto"></div>
        </div>
      </div>
    )
  }

  if (isProcessing || (portalToken && invitationToken)) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex items-center justify-center p-4">
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-8 max-w-md w-full text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <h1 className="text-xl font-bold text-gray-900 dark:text-white mb-2">Joining Team...</h1>
          <p className="text-gray-600 dark:text-gray-400">
            Please wait while we set up your account.
          </p>
        </div>
      </div>
    )
  }

  if (loadingInvitation) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex items-center justify-center p-4">
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-8 max-w-md w-full text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-gray-600 dark:text-gray-400">Loading invitation...</p>
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
          {invitation && (
            <p className="text-gray-600 dark:text-gray-400 mt-2">
              You've been invited to join as <span className="font-medium text-blue-600">{invitation.role}</span>
            </p>
          )}
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

        {!invitationToken ? (
          <div className="text-center">
            <div className="mb-4 p-4 bg-yellow-50 dark:bg-yellow-900/30 border border-yellow-200 dark:border-yellow-800 rounded-lg">
              <p className="text-yellow-700 dark:text-yellow-300 text-sm">
                No invitation token found. Please use the link from your invitation email.
              </p>
            </div>
            <a
              href={PORTAL_URL}
              className="text-blue-600 hover:text-blue-700 dark:text-blue-400 font-medium"
            >
              Go to Portal
            </a>
          </div>
        ) : invitation ? (
          <div className="space-y-4">
            {/* Invitation details */}
            <div className="p-4 bg-gray-50 dark:bg-gray-700 rounded-lg">
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">Invited email:</span>
                  <span className="text-gray-900 dark:text-white font-medium">{invitation.email}</span>
                </div>
                {invitation.invited_by_name && (
                  <div className="flex justify-between">
                    <span className="text-gray-500 dark:text-gray-400">Invited by:</span>
                    <span className="text-gray-900 dark:text-white">{invitation.invited_by_name}</span>
                  </div>
                )}
                {invitation.message && (
                  <div className="pt-2 border-t dark:border-gray-600">
                    <p className="text-gray-600 dark:text-gray-300 italic">"{invitation.message}"</p>
                  </div>
                )}
              </div>
            </div>

            {/* Login button */}
            <button
              onClick={handleLogin}
              className="w-full py-3 px-4 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg transition-colors flex items-center justify-center gap-2"
            >
              <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
                <path d="M3 3h8v8H3V3zm0 10h8v8H3v-8zm10 0h8v8h-8v-8zm0-10h8v8h-8V3z"/>
              </svg>
              Login with Microsoft
            </button>

            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-gray-300 dark:border-gray-600"></div>
              </div>
              <div className="relative flex justify-center text-sm">
                <span className="px-2 bg-white dark:bg-gray-800 text-gray-500">or</span>
              </div>
            </div>

            <p className="text-center text-sm text-gray-600 dark:text-gray-400">
              Don't have an account?{' '}
              <a
                href={`${PORTAL_URL}/login`}
                className="text-blue-600 hover:text-blue-700 dark:text-blue-400 font-medium"
              >
                Sign up on the portal
              </a>
            </p>
          </div>
        ) : (
          <div className="text-center">
            <div className="mb-4 p-4 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-lg">
              <p className="text-red-700 dark:text-red-300 text-sm">
                This invitation link is invalid or has expired.
              </p>
            </div>
            <p className="text-gray-600 dark:text-gray-400 text-sm">
              Please contact the team administrator for a new invitation.
            </p>
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
