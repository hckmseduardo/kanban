import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'

interface MarkdownProps {
  content: string
  className?: string
  compact?: boolean
}

export default function Markdown({ content, className = '', compact = false }: MarkdownProps) {
  return (
    <ReactMarkdown
      className={`prose prose-sm max-w-none ${compact ? 'prose-compact' : ''} ${className}`}
      remarkPlugins={[remarkGfm]}
      components={{
        // Code blocks with syntax highlighting
        code(props) {
          const { className, children, ...rest } = props
          const match = /language-(\w+)/.exec(className || '')
          const language = match ? match[1] : ''
          const isInline = !language && !String(children).includes('\n')

          if (!isInline && language) {
            return (
              <SyntaxHighlighter
                style={oneDark}
                language={language}
                PreTag="div"
                className="rounded-md text-sm"
              >
                {String(children).replace(/\n$/, '')}
              </SyntaxHighlighter>
            )
          }

          // Inline code
          return (
            <code
              className="bg-gray-100 text-gray-800 px-1.5 py-0.5 rounded text-sm font-mono"
              {...rest}
            >
              {children}
            </code>
          )
        },

        // Links open in new tab
        a({ href, children, ...props }) {
          return (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary-600 hover:text-primary-700 underline"
              onClick={(e) => e.stopPropagation()}
              {...props}
            >
              {children}
            </a>
          )
        },

        // Tables with styling
        table({ children }) {
          return (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 border border-gray-200 rounded">
                {children}
              </table>
            </div>
          )
        },

        th({ children }) {
          return (
            <th className="px-3 py-2 bg-gray-50 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              {children}
            </th>
          )
        },

        td({ children }) {
          return (
            <td className="px-3 py-2 text-sm text-gray-900 border-t border-gray-200">
              {children}
            </td>
          )
        },

        // Checkboxes (GFM task lists)
        input({ type, checked, ...props }) {
          if (type === 'checkbox') {
            return (
              <input
                type="checkbox"
                checked={checked}
                disabled
                className="rounded border-gray-300 text-primary-600 mr-2"
                {...props}
              />
            )
          }
          return <input type={type} {...props} />
        },

        // Blockquotes
        blockquote({ children }) {
          return (
            <blockquote className="border-l-4 border-gray-300 pl-4 italic text-gray-600">
              {children}
            </blockquote>
          )
        },

        // Headings
        h1({ children }) {
          return <h1 className="text-xl font-bold text-gray-900 mt-4 mb-2">{children}</h1>
        },
        h2({ children }) {
          return <h2 className="text-lg font-semibold text-gray-900 mt-3 mb-2">{children}</h2>
        },
        h3({ children }) {
          return <h3 className="text-base font-medium text-gray-900 mt-2 mb-1">{children}</h3>
        },

        // Lists
        ul({ children }) {
          return <ul className="list-disc list-inside space-y-1 my-2">{children}</ul>
        },
        ol({ children }) {
          return <ol className="list-decimal list-inside space-y-1 my-2">{children}</ol>
        },

        // Paragraphs
        p({ children }) {
          return <p className="my-2 text-gray-700">{children}</p>
        },

        // Horizontal rules
        hr() {
          return <hr className="my-4 border-gray-200" />
        },

        // Images
        img({ src, alt }) {
          return (
            <img
              src={src}
              alt={alt || ''}
              className="max-w-full h-auto rounded my-2"
              loading="lazy"
            />
          )
        }
      }}
    >
      {content}
    </ReactMarkdown>
  )
}
