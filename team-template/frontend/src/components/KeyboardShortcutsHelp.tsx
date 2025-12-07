import { useEffect } from 'react'
import { formatShortcutKey } from '../hooks/useKeyboardShortcuts'

interface ShortcutCategory {
  title: string
  shortcuts: {
    key: string
    modifiers?: string[]
    description: string
  }[]
}

interface KeyboardShortcutsHelpProps {
  isOpen: boolean
  onClose: () => void
  shortcuts?: ShortcutCategory[]
}

const defaultShortcuts: ShortcutCategory[] = [
  {
    title: 'General',
    shortcuts: [
      { key: '?', description: 'Show keyboard shortcuts' },
      { key: 'Escape', description: 'Close modal / Cancel action' },
      { key: '/', description: 'Focus search' },
    ]
  },
  {
    title: 'Board Navigation',
    shortcuts: [
      { key: 'n', description: 'Create new card (in first column)' },
      { key: 'f', description: 'Toggle filters panel' },
      { key: 'a', description: 'Toggle archived cards' },
      { key: 'r', description: 'Toggle activity panel' },
      { key: 'e', description: 'Export board' },
    ]
  },
  {
    title: 'Board List',
    shortcuts: [
      { key: 'c', description: 'Create new board' },
    ]
  }
]

export default function KeyboardShortcutsHelp({
  isOpen,
  onClose,
  shortcuts = defaultShortcuts
}: KeyboardShortcutsHelpProps) {
  // Close on Escape key
  useEffect(() => {
    if (!isOpen) return

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose])

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg w-full max-w-lg max-h-[80vh] overflow-hidden flex flex-col shadow-xl"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b">
          <h2 className="text-lg font-semibold text-gray-900">Keyboard Shortcuts</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-6">
          {shortcuts.map((category) => (
            <div key={category.title}>
              <h3 className="text-sm font-medium text-gray-500 uppercase tracking-wider mb-3">
                {category.title}
              </h3>
              <div className="space-y-2">
                {category.shortcuts.map((shortcut) => (
                  <div
                    key={shortcut.key + shortcut.description}
                    className="flex items-center justify-between py-2 px-3 rounded-lg hover:bg-gray-50"
                  >
                    <span className="text-sm text-gray-700">{shortcut.description}</span>
                    <kbd className="inline-flex items-center px-2.5 py-1 rounded bg-gray-100 font-mono text-sm text-gray-700 border border-gray-200 shadow-sm">
                      {formatShortcutKey(shortcut.key, shortcut.modifiers)}
                    </kbd>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="p-4 border-t bg-gray-50">
          <p className="text-xs text-gray-500 text-center">
            Press <kbd className="px-1.5 py-0.5 bg-gray-200 rounded text-gray-700 font-mono">?</kbd> anytime to show this help
          </p>
        </div>
      </div>
    </div>
  )
}
