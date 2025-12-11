import { create } from 'zustand'

type Theme = 'light' | 'dark' | 'system'

interface ThemeState {
  theme: Theme
  setTheme: (theme: Theme) => void
  toggleTheme: () => void
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

  localStorage.setItem('theme', theme)
}

// Initialize theme from localStorage or system preference
const initTheme = (): Theme => {
  if (typeof window !== 'undefined') {
    const stored = localStorage.getItem('theme') as Theme | null
    if (stored && ['light', 'dark', 'system'].includes(stored)) {
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
