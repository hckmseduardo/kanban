import { useState, useEffect, useCallback } from 'react'

type Theme = 'light' | 'dark' | 'system'

const COOKIE_NAME = 'theme'
const COOKIE_MAX_AGE = 365 * 24 * 60 * 60 // 1 year in seconds

// Get the root domain for cookie sharing across subdomains
function getCookieDomain(): string {
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
function getThemeCookie(): Theme | null {
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
function setThemeCookie(theme: Theme) {
  if (typeof document === 'undefined') return
  const domain = getCookieDomain()
  const domainPart = domain ? `; domain=${domain}` : ''
  document.cookie = `${COOKIE_NAME}=${theme}; path=/; max-age=${COOKIE_MAX_AGE}${domainPart}; SameSite=Lax`
}

function getSystemTheme(): 'light' | 'dark' {
  if (typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches) {
    return 'dark'
  }
  return 'light'
}

function getInitialTheme(): Theme {
  if (typeof window === 'undefined') return 'system'
  const stored = getThemeCookie()
  return stored || 'system'
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(getInitialTheme)
  const [resolvedTheme, setResolvedTheme] = useState<'light' | 'dark'>('light')

  // Resolve theme based on system preference
  const resolveTheme = useCallback(() => {
    if (theme === 'system') {
      return getSystemTheme()
    }
    return theme
  }, [theme])

  // Apply theme to document
  useEffect(() => {
    const resolved = resolveTheme()
    setResolvedTheme(resolved)

    const root = document.documentElement
    if (resolved === 'dark') {
      root.classList.add('dark')
    } else {
      root.classList.remove('dark')
    }

    setThemeCookie(theme)
  }, [theme, resolveTheme])

  // Listen for system theme changes
  useEffect(() => {
    if (theme !== 'system') return

    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')

    const handleChange = () => {
      setResolvedTheme(getSystemTheme())
      const root = document.documentElement
      if (getSystemTheme() === 'dark') {
        root.classList.add('dark')
      } else {
        root.classList.remove('dark')
      }
    }

    mediaQuery.addEventListener('change', handleChange)
    return () => mediaQuery.removeEventListener('change', handleChange)
  }, [theme])

  const setTheme = useCallback((newTheme: Theme) => {
    setThemeState(newTheme)
  }, [])

  const toggleTheme = useCallback(() => {
    setThemeState(current => {
      if (current === 'light') return 'dark'
      if (current === 'dark') return 'system'
      return 'light'
    })
  }, [])

  return {
    theme,
    resolvedTheme,
    setTheme,
    toggleTheme,
    isDark: resolvedTheme === 'dark'
  }
}
