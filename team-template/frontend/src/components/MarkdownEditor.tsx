import { useState, useCallback } from 'react'

interface MarkdownEditorProps {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  minHeight?: string
  preview?: boolean
}

// Simple markdown to HTML converter
function markdownToHtml(markdown: string): string {
  let html = markdown
    // Escape HTML
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    // Headers
    .replace(/^### (.*$)/gim, '<h3 class="text-lg font-semibold mt-3 mb-1">$1</h3>')
    .replace(/^## (.*$)/gim, '<h2 class="text-xl font-semibold mt-4 mb-2">$1</h2>')
    .replace(/^# (.*$)/gim, '<h1 class="text-2xl font-bold mt-4 mb-2">$1</h1>')
    // Bold
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/__(.+?)__/g, '<strong>$1</strong>')
    // Italic
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/_(.+?)_/g, '<em>$1</em>')
    // Strikethrough
    .replace(/~~(.+?)~~/g, '<del>$1</del>')
    // Inline code
    .replace(/`(.+?)`/g, '<code class="bg-gray-100 dark:bg-gray-700 px-1 rounded text-sm">$1</code>')
    // Links
    .replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2" class="text-blue-600 hover:underline" target="_blank">$1</a>')
    // Unordered lists
    .replace(/^\s*[-*+] (.+)$/gim, '<li class="ml-4">$1</li>')
    // Ordered lists
    .replace(/^\s*\d+\. (.+)$/gim, '<li class="ml-4 list-decimal">$1</li>')
    // Checkboxes
    .replace(/\[ \]/g, '<input type="checkbox" disabled class="mr-1">')
    .replace(/\[x\]/gi, '<input type="checkbox" checked disabled class="mr-1">')
    // Blockquotes
    .replace(/^> (.+)$/gim, '<blockquote class="border-l-4 border-gray-300 pl-4 italic text-gray-600">$1</blockquote>')
    // Horizontal rule
    .replace(/^---$/gim, '<hr class="my-4 border-gray-300">')
    // Line breaks
    .replace(/\n/g, '<br>')

  return html
}

export default function MarkdownEditor({
  value,
  onChange,
  placeholder = 'Write something...',
  minHeight = '150px',
  preview = true
}: MarkdownEditorProps) {
  const [isPreview, setIsPreview] = useState(false)

  const insertText = useCallback((before: string, after: string = '') => {
    const textarea = document.querySelector('textarea[data-md-editor]') as HTMLTextAreaElement
    if (!textarea) return

    const start = textarea.selectionStart
    const end = textarea.selectionEnd
    const selectedText = value.substring(start, end)
    const newText = value.substring(0, start) + before + selectedText + after + value.substring(end)

    onChange(newText)

    // Restore cursor position
    setTimeout(() => {
      textarea.focus()
      textarea.setSelectionRange(start + before.length, end + before.length)
    }, 0)
  }, [value, onChange])

  return (
    <div className="border rounded-lg dark:border-gray-600 overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center gap-1 p-2 bg-gray-50 dark:bg-gray-700 border-b dark:border-gray-600">
        <button
          type="button"
          onClick={() => insertText('**', '**')}
          className="p-1.5 hover:bg-gray-200 dark:hover:bg-gray-600 rounded"
          title="Bold"
        >
          <svg className="w-4 h-4 dark:text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 4h8a4 4 0 014 4 4 4 0 01-4 4H6z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 12h9a4 4 0 014 4 4 4 0 01-4 4H6z" />
          </svg>
        </button>
        <button
          type="button"
          onClick={() => insertText('*', '*')}
          className="p-1.5 hover:bg-gray-200 dark:hover:bg-gray-600 rounded"
          title="Italic"
        >
          <svg className="w-4 h-4 dark:text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 4h4m-2 0v16m-4 0h8" />
          </svg>
        </button>
        <button
          type="button"
          onClick={() => insertText('~~', '~~')}
          className="p-1.5 hover:bg-gray-200 dark:hover:bg-gray-600 rounded"
          title="Strikethrough"
        >
          <svg className="w-4 h-4 dark:text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v4m0 4v8M4 12h16" />
          </svg>
        </button>
        <div className="w-px h-4 bg-gray-300 dark:bg-gray-500 mx-1" />
        <button
          type="button"
          onClick={() => insertText('# ')}
          className="p-1.5 hover:bg-gray-200 dark:hover:bg-gray-600 rounded text-sm font-bold dark:text-white"
          title="Heading"
        >
          H
        </button>
        <button
          type="button"
          onClick={() => insertText('`', '`')}
          className="p-1.5 hover:bg-gray-200 dark:hover:bg-gray-600 rounded"
          title="Code"
        >
          <svg className="w-4 h-4 dark:text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
          </svg>
        </button>
        <button
          type="button"
          onClick={() => insertText('[', '](url)')}
          className="p-1.5 hover:bg-gray-200 dark:hover:bg-gray-600 rounded"
          title="Link"
        >
          <svg className="w-4 h-4 dark:text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
          </svg>
        </button>
        <div className="w-px h-4 bg-gray-300 dark:bg-gray-500 mx-1" />
        <button
          type="button"
          onClick={() => insertText('- ')}
          className="p-1.5 hover:bg-gray-200 dark:hover:bg-gray-600 rounded"
          title="Bullet List"
        >
          <svg className="w-4 h-4 dark:text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
        <button
          type="button"
          onClick={() => insertText('- [ ] ')}
          className="p-1.5 hover:bg-gray-200 dark:hover:bg-gray-600 rounded"
          title="Task"
        >
          <svg className="w-4 h-4 dark:text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
          </svg>
        </button>
        <button
          type="button"
          onClick={() => insertText('> ')}
          className="p-1.5 hover:bg-gray-200 dark:hover:bg-gray-600 rounded"
          title="Quote"
        >
          <svg className="w-4 h-4 dark:text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
          </svg>
        </button>

        <div className="flex-1" />

        {preview && (
          <button
            type="button"
            onClick={() => setIsPreview(!isPreview)}
            className={`px-2 py-1 text-sm rounded ${
              isPreview ? 'bg-blue-100 text-blue-600' : 'hover:bg-gray-200 dark:hover:bg-gray-600 dark:text-white'
            }`}
          >
            {isPreview ? 'Edit' : 'Preview'}
          </button>
        )}
      </div>

      {/* Editor/Preview */}
      {isPreview ? (
        <div
          className="p-3 prose dark:prose-invert max-w-none dark:text-white"
          style={{ minHeight }}
          dangerouslySetInnerHTML={{ __html: markdownToHtml(value) || '<p class="text-gray-400">Nothing to preview</p>' }}
        />
      ) : (
        <textarea
          data-md-editor
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="w-full p-3 border-none outline-none resize-y dark:bg-gray-800 dark:text-white"
          style={{ minHeight }}
        />
      )}
    </div>
  )
}
