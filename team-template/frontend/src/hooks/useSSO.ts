import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

export function useSSO() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [isAuthenticating, setIsAuthenticating] = useState(false)

  useEffect(() => {
    const ssoToken = searchParams.get('sso_token')

    if (ssoToken && !isAuthenticating) {
      setIsAuthenticating(true)

      // Exchange SSO token for JWT
      exchangeToken(ssoToken)
        .then((data) => {
          // Store the token
          localStorage.setItem('token', data.access_token)
          localStorage.setItem('user', JSON.stringify(data.user))

          // Remove sso_token from URL
          searchParams.delete('sso_token')
          setSearchParams(searchParams)

          // Reload to apply auth
          window.location.reload()
        })
        .catch((error) => {
          console.error('SSO token exchange failed:', error)
          // Remove invalid token from URL
          searchParams.delete('sso_token')
          setSearchParams(searchParams)
        })
        .finally(() => {
          setIsAuthenticating(false)
        })
    }
  }, [searchParams])

  return { isAuthenticating }
}

async function exchangeToken(ssoToken: string) {
  // Call portal API to exchange token
  const portalApiUrl = import.meta.env.VITE_PORTAL_API_URL || 'https://api.localhost:4443'
  const response = await fetch(`${portalApiUrl}/auth/exchange?token=${ssoToken}`, {
    method: 'POST',
  })

  if (!response.ok) {
    throw new Error('Token exchange failed')
  }

  return response.json()
}
