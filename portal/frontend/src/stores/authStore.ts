import { create } from 'zustand'
import { api } from '../services/api'

interface User {
  id: string
  email: string
  display_name: string
  avatar_url?: string
}

interface AuthState {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (returnTo?: string) => void
  logout: () => void
  checkAuth: () => Promise<void>
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,

  login: (returnTo?: string) => {
    // Redirect to Entra ID login
    const apiUrl = import.meta.env.VITE_API_URL || 'https://api.localhost:4443'
    let loginUrl = `${apiUrl}/auth/login`
    if (returnTo) {
      loginUrl += `?returnTo=${encodeURIComponent(returnTo)}`
    }
    console.log('[AuthStore] login - redirecting to:', loginUrl)
    window.location.href = loginUrl
  },

  logout: async () => {
    console.log('[AuthStore] logout called')
    localStorage.removeItem('token')
    set({ user: null, isAuthenticated: false })
  },

  checkAuth: async () => {
    const token = localStorage.getItem('token')
    console.log('[AuthStore] checkAuth - token:', token ? 'present (' + token.slice(0, 20) + '...)' : 'MISSING')

    if (!token) {
      console.log('[AuthStore] No token - setting unauthenticated')
      set({ user: null, isAuthenticated: false, isLoading: false })
      return
    }

    try {
      console.log('[AuthStore] Fetching /users/me...')
      const response = await api.get('/users/me')
      console.log('[AuthStore] User fetched:', response.data)
      set({
        user: response.data,
        isAuthenticated: true,
        isLoading: false
      })
    } catch (error) {
      console.error('[AuthStore] checkAuth failed:', error)
      localStorage.removeItem('token')
      set({ user: null, isAuthenticated: false, isLoading: false })
    }
  }
}))
