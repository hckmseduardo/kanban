import { useQuery } from '@tanstack/react-query'
import { useState, useMemo } from 'react'
import { useParams, Link } from 'react-router-dom'
import { boardsApi } from '../services/api'

interface CardType {
  id: string
  title: string
  due_date: string
  priority?: string
  labels?: string[]
  column_name?: string
}

// Helper to get days in month
function getDaysInMonth(year: number, month: number): number {
  return new Date(year, month + 1, 0).getDate()
}

// Helper to get first day of month (0 = Sunday)
function getFirstDayOfMonth(year: number, month: number): number {
  return new Date(year, month, 1).getDay()
}

const monthNames = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'
]

const priorityColors: Record<string, string> = {
  high: 'bg-red-100 border-red-300 text-red-700',
  medium: 'bg-yellow-100 border-yellow-300 text-yellow-700',
  low: 'bg-green-100 border-green-300 text-green-700'
}

export default function Calendar() {
  const { boardId } = useParams<{ boardId: string }>()
  const today = new Date()
  const [currentYear, setCurrentYear] = useState(today.getFullYear())
  const [currentMonth, setCurrentMonth] = useState(today.getMonth())
  const [selectedCard, setSelectedCard] = useState<CardType | null>(null)

  const { data: board, isLoading } = useQuery({
    queryKey: ['board', boardId],
    queryFn: () => boardsApi.get(boardId!).then((res: { data: any }) => res.data),
    enabled: !!boardId
  })

  // Extract all cards with due dates
  const cardsWithDueDates = useMemo(() => {
    if (!board?.columns) return []

    const cards: CardType[] = []
    for (const column of board.columns) {
      for (const card of column.cards || []) {
        if (card.due_date && !card.archived) {
          cards.push({
            ...card,
            column_name: column.name
          })
        }
      }
    }
    return cards
  }, [board])

  // Group cards by date
  const cardsByDate = useMemo(() => {
    const map: Record<string, CardType[]> = {}
    for (const card of cardsWithDueDates) {
      const date = card.due_date
      if (!map[date]) map[date] = []
      map[date].push(card)
    }
    return map
  }, [cardsWithDueDates])

  const goToPreviousMonth = () => {
    if (currentMonth === 0) {
      setCurrentMonth(11)
      setCurrentYear(currentYear - 1)
    } else {
      setCurrentMonth(currentMonth - 1)
    }
  }

  const goToNextMonth = () => {
    if (currentMonth === 11) {
      setCurrentMonth(0)
      setCurrentYear(currentYear + 1)
    } else {
      setCurrentMonth(currentMonth + 1)
    }
  }

  const goToToday = () => {
    setCurrentYear(today.getFullYear())
    setCurrentMonth(today.getMonth())
  }

  const daysInMonth = getDaysInMonth(currentYear, currentMonth)
  const firstDayOfMonth = getFirstDayOfMonth(currentYear, currentMonth)

  // Build calendar grid
  const calendarDays: (number | null)[] = []
  for (let i = 0; i < firstDayOfMonth; i++) {
    calendarDays.push(null)
  }
  for (let day = 1; day <= daysInMonth; day++) {
    calendarDays.push(day)
  }

  const isToday = (day: number) => {
    return (
      day === today.getDate() &&
      currentMonth === today.getMonth() &&
      currentYear === today.getFullYear()
    )
  }

  const getDateString = (day: number) => {
    const month = String(currentMonth + 1).padStart(2, '0')
    const dayStr = String(day).padStart(2, '0')
    return `${currentYear}-${month}-${dayStr}`
  }

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-4">
          <Link to={`/board/${boardId}`} className="text-gray-500 hover:text-gray-700">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </Link>
          <h1 className="text-2xl font-bold text-gray-900">{board?.name} - Calendar</h1>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={goToToday}
            className="px-3 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
          >
            Today
          </button>
        </div>
      </div>

      {/* Calendar Navigation */}
      <div className="flex items-center justify-between bg-white p-4 rounded-lg shadow">
        <button
          onClick={goToPreviousMonth}
          className="p-2 hover:bg-gray-100 rounded-full"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
        </button>
        <h2 className="text-xl font-semibold">
          {monthNames[currentMonth]} {currentYear}
        </h2>
        <button
          onClick={goToNextMonth}
          className="p-2 hover:bg-gray-100 rounded-full"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        </button>
      </div>

      {/* Calendar Grid */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        {/* Day headers */}
        <div className="grid grid-cols-7 border-b bg-gray-50">
          {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map(day => (
            <div key={day} className="py-3 text-center text-sm font-medium text-gray-700">
              {day}
            </div>
          ))}
        </div>

        {/* Calendar days */}
        <div className="grid grid-cols-7">
          {calendarDays.map((day, index) => {
            const dateString = day ? getDateString(day) : ''
            const dayCards = day ? (cardsByDate[dateString] || []) : []

            return (
              <div
                key={index}
                className={`min-h-[120px] border-b border-r p-2 ${
                  day ? 'bg-white' : 'bg-gray-50'
                } ${isToday(day || 0) ? 'bg-primary-50' : ''}`}
              >
                {day && (
                  <>
                    <div className={`text-sm font-medium mb-1 ${
                      isToday(day) ? 'text-primary-600' : 'text-gray-700'
                    }`}>
                      {isToday(day) ? (
                        <span className="inline-flex items-center justify-center w-6 h-6 bg-primary-600 text-white rounded-full">
                          {day}
                        </span>
                      ) : day}
                    </div>
                    <div className="space-y-1 overflow-y-auto max-h-[80px]">
                      {dayCards.map(card => (
                        <button
                          key={card.id}
                          onClick={() => setSelectedCard(card)}
                          className={`w-full text-left px-2 py-1 text-xs rounded border truncate ${
                            card.priority ? priorityColors[card.priority] : 'bg-gray-100 border-gray-200 text-gray-700'
                          }`}
                        >
                          {card.title}
                        </button>
                      ))}
                      {dayCards.length > 3 && (
                        <div className="text-xs text-gray-500 px-2">
                          +{dayCards.length - 3} more
                        </div>
                      )}
                    </div>
                  </>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* Card Preview Modal */}
      {selectedCard && (
        <div
          className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50"
          onClick={() => setSelectedCard(null)}
        >
          <div
            className="bg-white rounded-lg w-full max-w-md p-4 shadow-xl"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-start justify-between mb-3">
              <h3 className="text-lg font-medium">{selectedCard.title}</h3>
              <button
                onClick={() => setSelectedCard(null)}
                className="text-gray-400 hover:text-gray-600"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <span className="text-sm text-gray-500">Due:</span>
                <span className="text-sm font-medium">
                  {new Date(selectedCard.due_date).toLocaleDateString()}
                </span>
              </div>

              {selectedCard.column_name && (
                <div className="flex items-center gap-2">
                  <span className="text-sm text-gray-500">Column:</span>
                  <span className="text-sm font-medium">{selectedCard.column_name}</span>
                </div>
              )}

              {selectedCard.priority && (
                <div className="flex items-center gap-2">
                  <span className="text-sm text-gray-500">Priority:</span>
                  <span className={`px-2 py-0.5 text-xs rounded ${priorityColors[selectedCard.priority]}`}>
                    {selectedCard.priority}
                  </span>
                </div>
              )}

              {selectedCard.labels && selectedCard.labels.length > 0 && (
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm text-gray-500">Labels:</span>
                  {selectedCard.labels.map(label => (
                    <span key={label} className="px-2 py-0.5 text-xs bg-gray-100 rounded">
                      {label}
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div className="mt-4 pt-4 border-t">
              <Link
                to={`/board/${boardId}`}
                className="text-sm text-primary-600 hover:text-primary-700"
              >
                View in Board
              </Link>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
