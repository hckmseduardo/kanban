import { create } from 'zustand'

type Theme = 'light' | 'dark' | 'system'

interface ThemeState {
  theme: Theme
  setTheme: (theme: Theme) => void
  toggleTheme: () => void
}

const COOKIE_NAME = 'theme'
const COOKIE_MAX_AGE = 365 * 24 * 60 * 60 // 1 year in seconds

// Get the root domain for cookie sharing across subdomains
const getCookieDomain = (): string => {
  if (typeof window === 'undefined') return ''
  const hostname = window.location.hostname
  // For localhost, don't set domain (cookies work locally)
  if (hostname === 'localhost' || hostname === '127.0.0.1') return ''
  // Extract root domain (e.g., kanban.amazing-ai.tools from subdomain.kanban.amazing-ai.tools)
  const parts = hostname.split('.')
  if (parts.length >= 3) {
    // Return the last 3 parts as the domain (e.g., .kanban.amazing-ai.tools)
    return '.' + parts.slice(-3).join('.')
  }
  return '.' + hostname
}

// Read theme from cookie
const getThemeCookie = (): Theme | null => {
  if (typeof document === 'undefined') return null
  const match = document.cookie.match(new RegExp(`(^| )${COOKIE_NAME}=([^;]+)`))
  if (match) {
    const value = match[2] as Theme
    if (['light', 'dark', 'system'].includes(value)) {
      return value
    }
  }
  return null
}

// Write theme to cookie (shared across subdomains)
const setThemeCookie = (theme: Theme) => {
  if (typeof document === 'undefined') return
  const domain = getCookieDomain()
  const domainPart = domain ? `; domain=${domain}` : ''
  document.cookie = `${COOKIE_NAME}=${theme}; path=/; max-age=${COOKIE_MAX_AGE}${domainPart}; SameSite=Lax`
}

const getSystemTheme = (): 'light' | 'dark' => {
  if (typeof window !== 'undefined' && window.matchMedia) {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }
  return 'light'
}

const applyTheme = (theme: Theme) => {
  const root = document.documentElement
  const effectiveTheme = theme === 'system' ? getSystemTheme() : theme

  if (effectiveTheme === 'dark') {
    root.classList.add('dark')
  } else {
    root.classList.remove('dark')
  }

  setThemeCookie(theme)
}

// Initialize theme from cookie or system preference
const initTheme = (): Theme => {
  if (typeof window !== 'undefined') {
    const stored = getThemeCookie()
    if (stored) {
      applyTheme(stored)
      return stored
    }
    // Default to system
    applyTheme('system')
    return 'system'
  }
  return 'system'
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: initTheme(),

  setTheme: (theme: Theme) => {
    applyTheme(theme)
    set({ theme })
  },

  toggleTheme: () => {
    const current = get().theme
    const effectiveCurrent = current === 'system' ? getSystemTheme() : current
    const newTheme: Theme = effectiveCurrent === 'light' ? 'dark' : 'light'
    applyTheme(newTheme)
    set({ theme: newTheme })
  }
}))

// Listen for system theme changes
if (typeof window !== 'undefined' && window.matchMedia) {
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    const { theme } = useThemeStore.getState()
    if (theme === 'system') {
      applyTheme('system')
    }
  })
}
