import { useState, useMemo } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { boardsApi } from '../services/api'

interface CardType {
  id: string
  title: string
  due_date?: string
  created_at?: string
  priority?: string
  assignee_id?: string
  column_id: string
}

interface ColumnType {
  id: string
  name: string
  cards?: CardType[]
}

export default function Gantt() {
  const { boardId } = useParams<{ boardId: string }>()
  const [viewWeeks, setViewWeeks] = useState(4)

  const { data: board, isLoading } = useQuery({
    queryKey: ['board', boardId],
    queryFn: () => boardsApi.get(boardId!).then(res => res.data),
    enabled: !!boardId
  })

  // Get all cards with dates
  const cardsWithDates = useMemo(() => {
    if (!board?.columns) return []

    const cards: (CardType & { column_name: string })[] = []
    board.columns.forEach((col: ColumnType) => {
      col.cards?.forEach((card: CardType) => {
        if (card.due_date || card.created_at) {
          cards.push({ ...card, column_name: col.name })
        }
      })
    })

    return cards.sort((a, b) => {
      const dateA = a.due_date || a.created_at || ''
      const dateB = b.due_date || b.created_at || ''
      return dateA.localeCompare(dateB)
    })
  }, [board])

  // Generate date range
  const { startDate, days, weeks } = useMemo(() => {
    const today = new Date()
    today.setHours(0, 0, 0, 0)

    const start = new Date(today)
    start.setDate(start.getDate() - 7) // Start a week ago

    const end = new Date(today)
    end.setDate(end.getDate() + (viewWeeks * 7))

    const dayCount = Math.ceil((end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24))
    const daysArray = Array.from({ length: dayCount }, (_, i) => {
      const d = new Date(start)
      d.setDate(d.getDate() + i)
      return d
    })

    // Group by weeks
    const weeksArray: Date[][] = []
    let currentWeek: Date[] = []
    daysArray.forEach((day, i) => {
      currentWeek.push(day)
      if (day.getDay() === 0 || i === daysArray.length - 1) {
        weeksArray.push(currentWeek)
        currentWeek = []
      }
    })

    return { startDate: start, days: daysArray, weeks: weeksArray }
  }, [viewWeeks])

  const getCardPosition = (card: CardType & { column_name: string }) => {
    const created = card.created_at ? new Date(card.created_at) : null
    const due = card.due_date ? new Date(card.due_date) : null

    if (!created && !due) return null

    const barStart = created || due!
    const barEnd = due || created!

    const startOffset = Math.max(0, (barStart.getTime() - startDate.getTime()) / (1000 * 60 * 60 * 24))
    const endOffset = Math.min(days.length, (barEnd.getTime() - startDate.getTime()) / (1000 * 60 * 60 * 24))

    const width = Math.max(1, endOffset - startOffset)

    return {
      left: (startOffset / days.length) * 100,
      width: (width / days.length) * 100
    }
  }

  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const todayOffset = (today.getTime() - startDate.getTime()) / (1000 * 60 * 60 * 24)
  const todayPosition = (todayOffset / days.length) * 100

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    )
  }

  return (
    <div className="p-6 h-screen flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="flex items-center gap-2 text-sm text-gray-500 mb-1">
            <Link to="/" className="hover:text-blue-600">Boards</Link>
            <span>/</span>
            <Link to={`/boards/${boardId}`} className="hover:text-blue-600">{board?.name}</Link>
            <span>/</span>
            <span>Gantt</span>
          </div>
          <h1 className="text-2xl font-bold dark:text-white">Gantt Chart</h1>
        </div>
        <div className="flex items-center gap-4">
          <select
            value={viewWeeks}
            onChange={(e) => setViewWeeks(Number(e.target.value))}
            className="px-3 py-2 border rounded-lg dark:bg-gray-800 dark:border-gray-600 dark:text-white"
          >
            <option value={2}>2 Weeks</option>
            <option value={4}>4 Weeks</option>
            <option value={8}>8 Weeks</option>
            <option value={12}>12 Weeks</option>
          </select>
          <Link
            to={`/boards/${boardId}`}
            className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg dark:text-gray-300 dark:hover:bg-gray-700"
          >
            Back to Board
          </Link>
        </div>
      </div>

      {/* Gantt Chart */}
      <div className="flex-1 bg-white dark:bg-gray-800 rounded-lg shadow overflow-hidden flex flex-col">
        {/* Week headers */}
        <div className="flex border-b dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
          <div className="w-64 flex-shrink-0 px-4 py-2 font-semibold dark:text-white border-r dark:border-gray-700">
            Card
          </div>
          <div className="flex-1 flex">
            {weeks.map((week, i) => (
              <div
                key={i}
                className="flex-1 text-center py-2 text-sm font-medium dark:text-white border-r dark:border-gray-700 last:border-r-0"
              >
                {week[0]?.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                {week.length > 1 && ` - ${week[week.length - 1]?.toLocaleDateString('en-US', { day: 'numeric' })}`}
              </div>
            ))}
          </div>
        </div>

        {/* Day headers */}
        <div className="flex border-b dark:border-gray-700">
          <div className="w-64 flex-shrink-0 border-r dark:border-gray-700" />
          <div className="flex-1 flex relative">
            {days.map((day, i) => {
              const isToday = day.getTime() === today.getTime()
              const isWeekend = day.getDay() === 0 || day.getDay() === 6

              return (
                <div
                  key={i}
                  className={`flex-1 text-center text-xs py-1 border-r dark:border-gray-700 last:border-r-0 ${
                    isToday ? 'bg-blue-100 dark:bg-blue-900 font-bold' :
                    isWeekend ? 'bg-gray-100 dark:bg-gray-700' : ''
                  } dark:text-white`}
                >
                  {day.getDate()}
                </div>
              )
            })}
          </div>
        </div>

        {/* Cards */}
        <div className="flex-1 overflow-y-auto relative">
          {/* Today line */}
          {todayPosition >= 0 && todayPosition <= 100 && (
            <div
              className="absolute top-0 bottom-0 w-0.5 bg-red-500 z-10"
              style={{ left: `calc(256px + ${todayPosition}% * (100% - 256px) / 100)` }}
            />
          )}

          {cardsWithDates.length === 0 ? (
            <div className="flex items-center justify-center h-full text-gray-500">
              No cards with due dates
            </div>
          ) : (
            cardsWithDates.map((card) => {
              const position = getCardPosition(card)
              const isOverdue = card.due_date && new Date(card.due_date) < today

              return (
                <div key={card.id} className="flex border-b dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700">
                  <div className="w-64 flex-shrink-0 px-4 py-2 border-r dark:border-gray-700">
                    <div className="font-medium dark:text-white truncate">{card.title}</div>
                    <div className="text-xs text-gray-500">{card.column_name}</div>
                  </div>
                  <div className="flex-1 relative py-2 px-1">
                    {position && (
                      <div
                        className={`absolute h-6 rounded cursor-pointer transition-all hover:opacity-80 ${
                          isOverdue ? 'bg-red-500' :
                          card.priority === 'high' ? 'bg-orange-500' :
                          card.priority === 'medium' ? 'bg-yellow-500' :
                          'bg-blue-500'
                        }`}
                        style={{
                          left: `${position.left}%`,
                          width: `${Math.max(position.width, 2)}%`,
                          top: '50%',
                          transform: 'translateY(-50%)'
                        }}
                        title={`${card.title}${card.due_date ? ` - Due: ${card.due_date}` : ''}`}
                      >
                        <span className="absolute inset-0 flex items-center justify-center text-white text-xs font-medium truncate px-1">
                          {position.width > 5 ? card.title : ''}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              )
            })
          )}
        </div>
      </div>

      {/* Legend */}
      <div className="mt-4 flex items-center justify-center gap-6 text-sm">
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 rounded bg-blue-500" />
          <span className="dark:text-white">Normal</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 rounded bg-yellow-500" />
          <span className="dark:text-white">Medium Priority</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 rounded bg-orange-500" />
          <span className="dark:text-white">High Priority</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 rounded bg-red-500" />
          <span className="dark:text-white">Overdue</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-0.5 h-4 bg-red-500" />
          <span className="dark:text-white">Today</span>
        </div>
      </div>
    </div>
  )
}
