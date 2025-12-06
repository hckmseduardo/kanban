import { useQuery } from '@tanstack/react-query'
import { utilsApi } from '../services/api'

interface LinkPreviewProps {
  url: string
  compact?: boolean
}

interface PreviewData {
  url: string
  title?: string
  description?: string
  image?: string
  site_name?: string
  favicon?: string
}

export default function LinkPreview({ url, compact = false }: LinkPreviewProps) {
  const { data: preview, isLoading, error } = useQuery<PreviewData>({
    queryKey: ['linkPreview', url],
    queryFn: () => utilsApi.getLinkPreview(url).then(res => res.data),
    staleTime: 1000 * 60 * 60, // Cache for 1 hour
    retry: 1
  })

  if (isLoading) {
    return (
      <div className="animate-pulse bg-gray-100 rounded-lg p-3 mt-2">
        <div className="h-4 bg-gray-200 rounded w-3/4 mb-2"></div>
        <div className="h-3 bg-gray-200 rounded w-1/2"></div>
      </div>
    )
  }

  if (error || !preview) {
    // Fallback to simple link
    return (
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="text-primary-600 hover:text-primary-700 text-sm underline mt-2 block truncate"
      >
        {url}
      </a>
    )
  }

  if (compact) {
    return (
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="flex items-center space-x-2 bg-gray-50 rounded p-2 mt-2 hover:bg-gray-100 transition-colors"
        onClick={(e) => e.stopPropagation()}
      >
        {preview.favicon && (
          <img
            src={preview.favicon}
            alt=""
            className="w-4 h-4 flex-shrink-0"
            onError={(e) => { e.currentTarget.style.display = 'none' }}
          />
        )}
        <span className="text-xs text-gray-600 truncate">
          {preview.title || preview.site_name || url}
        </span>
      </a>
    )
  }

  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="block mt-2 border rounded-lg overflow-hidden hover:border-primary-300 transition-colors"
      onClick={(e) => e.stopPropagation()}
    >
      {preview.image && (
        <div className="relative h-32 bg-gray-100">
          <img
            src={preview.image}
            alt={preview.title || ''}
            className="w-full h-full object-cover"
            onError={(e) => { e.currentTarget.parentElement!.style.display = 'none' }}
          />
        </div>
      )}
      <div className="p-3 bg-white">
        <div className="flex items-center space-x-2 mb-1">
          {preview.favicon && (
            <img
              src={preview.favicon}
              alt=""
              className="w-4 h-4"
              onError={(e) => { e.currentTarget.style.display = 'none' }}
            />
          )}
          <span className="text-xs text-gray-500">{preview.site_name || new URL(url).hostname}</span>
        </div>
        {preview.title && (
          <h4 className="text-sm font-medium text-gray-900 line-clamp-1">{preview.title}</h4>
        )}
        {preview.description && (
          <p className="text-xs text-gray-500 mt-1 line-clamp-2">{preview.description}</p>
        )}
      </div>
    </a>
  )
}

// Helper to extract first URL from text
export function extractFirstUrl(text: string): string | null {
  const urlPattern = /https?:\/\/[^\s<>"{}|\\^`\[\]]+/
  const match = text.match(urlPattern)
  return match ? match[0] : null
}
