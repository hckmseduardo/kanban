import { useEffect, useCallback, useState } from 'react'

export interface KeyboardShortcut {
  key: string
  description: string
  modifiers?: ('ctrl' | 'alt' | 'shift' | 'meta')[]
  action: () => void
  when?: () => boolean
}

// Check if the current element is an input that should consume keyboard events
function isInputElement(element: EventTarget | null): boolean {
  if (!element || !(element instanceof HTMLElement)) return false
  const tagName = element.tagName.toLowerCase()
  return (
    tagName === 'input' ||
    tagName === 'textarea' ||
    tagName === 'select' ||
    element.isContentEditable
  )
}

export function useKeyboardShortcuts(shortcuts: KeyboardShortcut[]) {
  const handleKeyDown = useCallback((event: KeyboardEvent) => {
    // Don't trigger shortcuts when typing in inputs (except for Escape)
    if (isInputElement(event.target) && event.key !== 'Escape') {
      return
    }

    for (const shortcut of shortcuts) {
      const { key, modifiers = [], action, when } = shortcut

      // Check if the key matches
      if (event.key.toLowerCase() !== key.toLowerCase()) continue

      // Check modifiers
      const ctrlRequired = modifiers.includes('ctrl')
      const altRequired = modifiers.includes('alt')
      const shiftRequired = modifiers.includes('shift')
      const metaRequired = modifiers.includes('meta')

      if (ctrlRequired !== (event.ctrlKey || event.metaKey)) continue
      if (altRequired !== event.altKey) continue
      if (shiftRequired !== event.shiftKey) continue
      if (metaRequired !== event.metaKey && !ctrlRequired) continue

      // Check condition
      if (when && !when()) continue

      // Execute action
      event.preventDefault()
      action()
      return
    }
  }, [shortcuts])

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [handleKeyDown])
}

// Hook to manage help modal visibility
export function useKeyboardShortcutsHelp() {
  const [showHelp, setShowHelp] = useState(false)

  const openHelp = useCallback(() => setShowHelp(true), [])
  const closeHelp = useCallback(() => setShowHelp(false), [])
  const toggleHelp = useCallback(() => setShowHelp(prev => !prev), [])

  return { showHelp, openHelp, closeHelp, toggleHelp }
}

// Format shortcut key for display
export function formatShortcutKey(key: string, modifiers: string[] = []): string {
  const isMac = typeof navigator !== 'undefined' && navigator.platform.toLowerCase().includes('mac')

  const modMap: Record<string, string> = isMac
    ? { ctrl: '⌘', alt: '⌥', shift: '⇧', meta: '⌘' }
    : { ctrl: 'Ctrl', alt: 'Alt', shift: 'Shift', meta: 'Win' }

  const parts = modifiers.map(m => modMap[m] || m)

  // Format special keys
  const keyDisplay = {
    'escape': 'Esc',
    'enter': '↵',
    'arrowup': '↑',
    'arrowdown': '↓',
    'arrowleft': '←',
    'arrowright': '→',
    ' ': 'Space',
    '?': '?',
    '/': '/',
  }[key.toLowerCase()] || key.toUpperCase()

  parts.push(keyDisplay)

  return isMac ? parts.join('') : parts.join('+')
}
