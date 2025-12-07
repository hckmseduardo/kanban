import { useState, useEffect, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { searchApi } from '../services/api'

interface SearchModalProps {
  isOpen: boolean
  onClose: () => void
}

interface SearchResult {
  id: string
  title: string
  description: string
  board_id: string
  board_name: string
  column_name: string
  priority?: string
  due_date?: string
  is_overdue: boolean
  labels: string[]
}

export default function SearchModal({ isOpen, onClose }: SearchModalProps) {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [filters, setFilters] = useState({
    priority: '',
    is_overdue: undefined as boolean | undefined,
    has_due_date: undefined as boolean | undefined,
    include_archived: false
  })
  const [showFilters, setShowFilters] = useState(false)

  const { data: results, isLoading } = useQuery({
    queryKey: ['search', query, filters],
    queryFn: () => searchApi.search({
      q: query,
      priority: filters.priority || undefined,
      is_overdue: filters.is_overdue,
      has_due_date: filters.has_due_date,
      include_archived: filters.include_archived,
      limit: 20
    }).then(res => res.data),
    enabled: isOpen && query.length >= 2
  })

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      onClose()
    }
  }, [onClose])

  useEffect(() => {
    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown)
      return () => document.removeEventListener('keydown', handleKeyDown)
    }
  }, [isOpen, handleKeyDown])

  const handleResultClick = (result: SearchResult) => {
    navigate(`/boards/${result.board_id}?card=${result.id}`)
    onClose()
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-start justify-center pt-20 z-50">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-2xl max-h-[70vh] flex flex-col">
        {/* Search input */}
        <div className="p-4 border-b dark:border-gray-700">
          <div className="flex items-center gap-2">
            <svg className="w-5 h-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search cards..."
              className="flex-1 bg-transparent border-none outline-none text-lg dark:text-white"
              autoFocus
            />
            <button
              onClick={() => setShowFilters(!showFilters)}
              className={`p-1 rounded ${showFilters ? 'bg-blue-100 text-blue-600' : 'text-gray-400 hover:text-gray-600'}`}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
              </svg>
            </button>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {/* Filters */}
          {showFilters && (
            <div className="mt-3 flex flex-wrap gap-2">
              <select
                value={filters.priority}
                onChange={(e) => setFilters({ ...filters, priority: e.target.value })}
                className="px-2 py-1 text-sm border rounded dark:bg-gray-700 dark:border-gray-600 dark:text-white"
              >
                <option value="">Any Priority</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>

              <label className="flex items-center gap-1 text-sm">
                <input
                  type="checkbox"
                  checked={filters.is_overdue === true}
                  onChange={(e) => setFilters({ ...filters, is_overdue: e.target.checked ? true : undefined })}
                />
                <span className="dark:text-white">Overdue only</span>
              </label>

              <label className="flex items-center gap-1 text-sm">
                <input
                  type="checkbox"
                  checked={filters.has_due_date === true}
                  onChange={(e) => setFilters({ ...filters, has_due_date: e.target.checked ? true : undefined })}
                />
                <span className="dark:text-white">Has due date</span>
              </label>

              <label className="flex items-center gap-1 text-sm">
                <input
                  type="checkbox"
                  checked={filters.include_archived}
                  onChange={(e) => setFilters({ ...filters, include_archived: e.target.checked })}
                />
                <span className="dark:text-white">Include archived</span>
              </label>
            </div>
          )}
        </div>

        {/* Results */}
        <div className="flex-1 overflow-y-auto p-2">
          {query.length < 2 ? (
            <p className="text-center text-gray-500 py-8">Type at least 2 characters to search</p>
          ) : isLoading ? (
            <p className="text-center text-gray-500 py-8">Searching...</p>
          ) : results?.results?.length === 0 ? (
            <p className="text-center text-gray-500 py-8">No cards found</p>
          ) : (
            <div className="space-y-1">
              {results?.results?.map((result: SearchResult) => (
                <button
                  key={result.id}
                  onClick={() => handleResultClick(result)}
                  className="w-full text-left p-3 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <h4 className="font-medium dark:text-white">{result.title}</h4>
                      <p className="text-sm text-gray-500">
                        {result.board_name} → {result.column_name}
                      </p>
                      {result.description && (
                        <p className="text-sm text-gray-400 mt-1 line-clamp-1">{result.description}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-2 ml-2">
                      {result.priority && (
                        <span className={`text-xs px-2 py-0.5 rounded ${
                          result.priority === 'high' ? 'bg-red-100 text-red-700' :
                          result.priority === 'medium' ? 'bg-yellow-100 text-yellow-700' :
                          'bg-green-100 text-green-700'
                        }`}>
                          {result.priority}
                        </span>
                      )}
                      {result.is_overdue && (
                        <span className="text-xs px-2 py-0.5 rounded bg-red-100 text-red-700">overdue</span>
                      )}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        {results?.total > 0 && (
          <div className="p-2 border-t dark:border-gray-700 text-sm text-gray-500 text-center">
            Showing {results.results.length} of {results.total} results
          </div>
        )}
      </div>
    </div>
  )
}
