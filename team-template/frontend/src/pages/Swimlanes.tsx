import { useQuery } from '@tanstack/react-query'
import { useState, useMemo } from 'react'
import { useParams, Link } from 'react-router-dom'
import { boardsApi, labelsApi, membersApi } from '../services/api'

interface CardType {
  id: string
  title: string
  description?: string
  labels?: string[]
  priority?: string
  due_date?: string
  assignee_id?: string
  column_id: string
  archived?: boolean
}

interface ColumnType {
  id: string
  name: string
  cards?: CardType[]
}

interface LabelType {
  id: string
  name: string
  color: string
  bg: string
  text: string
}

interface MemberType {
  id: string
  name: string
  email: string
}

type GroupBy = 'assignee' | 'priority' | 'label' | 'none'

export default function Swimlanes() {
  const { boardId } = useParams<{ boardId: string }>()
  const [groupBy, setGroupBy] = useState<GroupBy>('priority')

  const { data: board, isLoading } = useQuery({
    queryKey: ['board', boardId],
    queryFn: () => boardsApi.get(boardId!).then((res: { data: any }) => res.data),
    enabled: !!boardId
  })

  const { data: boardLabels = [] } = useQuery<LabelType[]>({
    queryKey: ['labels', boardId],
    queryFn: () => labelsApi.list(boardId!).then((res: { data: LabelType[] }) => res.data),
    enabled: !!boardId
  })

  const { data: members = [] } = useQuery<MemberType[]>({
    queryKey: ['members'],
    queryFn: () => membersApi.list().then((res: { data: MemberType[] }) => res.data),
    enabled: !!boardId
  })

  // Extract all cards from all columns
  const allCards = useMemo(() => {
    if (!board?.columns) return []
    const cards: (CardType & { column_name: string })[] = []
    for (const column of board.columns as ColumnType[]) {
      for (const card of column.cards || []) {
        if (!card.archived) {
          cards.push({ ...card, column_name: column.name })
        }
      }
    }
    return cards
  }, [board])

  // Group cards based on groupBy selection
  const groupedCards = useMemo(() => {
    const groups: Record<string, (CardType & { column_name: string })[]> = {}

    if (groupBy === 'none') {
      groups['All Cards'] = allCards
      return groups
    }

    if (groupBy === 'priority') {
      groups['High'] = []
      groups['Medium'] = []
      groups['Low'] = []
      groups['No Priority'] = []

      for (const card of allCards) {
        if (card.priority === 'high') groups['High'].push(card)
        else if (card.priority === 'medium') groups['Medium'].push(card)
        else if (card.priority === 'low') groups['Low'].push(card)
        else groups['No Priority'].push(card)
      }
    }

    if (groupBy === 'assignee') {
      groups['Unassigned'] = []
      for (const member of members) {
        groups[member.name] = []
      }

      for (const card of allCards) {
        if (!card.assignee_id) {
          groups['Unassigned'].push(card)
        } else {
          const member = members.find(m => m.id === card.assignee_id)
          if (member) {
            groups[member.name].push(card)
          } else {
            groups['Unassigned'].push(card)
          }
        }
      }
    }

    if (groupBy === 'label') {
      groups['No Label'] = []
      for (const label of boardLabels) {
        groups[label.name] = []
      }

      for (const card of allCards) {
        if (!card.labels || card.labels.length === 0) {
          groups['No Label'].push(card)
        } else {
          // Card appears in each label's swimlane
          for (const labelName of card.labels) {
            if (groups[labelName]) {
              groups[labelName].push(card)
            }
          }
        }
      }
    }

    // Remove empty groups (except for specific ones we want to show)
    const result: Record<string, (CardType & { column_name: string })[]> = {}
    for (const [key, cards] of Object.entries(groups)) {
      if (cards.length > 0 || key === 'Unassigned' || key === 'No Priority' || key === 'No Label') {
        result[key] = cards
      }
    }

    return result
  }, [allCards, groupBy, members, boardLabels])

  const priorityColors: Record<string, string> = {
    high: 'bg-red-100 border-l-red-500',
    medium: 'bg-yellow-100 border-l-yellow-500',
    low: 'bg-green-100 border-l-green-500'
  }

  const getLabelStyle = (labelName: string) => {
    const label = boardLabels.find(l => l.name === labelName)
    if (label) {
      return { backgroundColor: label.bg, color: label.text }
    }
    return { backgroundColor: '#E5E7EB', color: '#374151' }
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
          <h1 className="text-2xl font-bold text-gray-900">{board?.name} - Swimlanes</h1>
        </div>
        <div className="flex items-center gap-3">
          <label className="text-sm font-medium text-gray-700">Group by:</label>
          <select
            value={groupBy}
            onChange={(e) => setGroupBy(e.target.value as GroupBy)}
            className="px-3 py-2 border rounded-lg text-sm bg-white"
          >
            <option value="priority">Priority</option>
            <option value="assignee">Assignee</option>
            <option value="label">Label</option>
            <option value="none">No Grouping</option>
          </select>
        </div>
      </div>

      {/* Swimlanes */}
      <div className="space-y-6">
        {Object.entries(groupedCards).map(([groupName, cards]) => (
          <div key={groupName} className="bg-white rounded-lg shadow overflow-hidden">
            {/* Swimlane Header */}
            <div className={`px-4 py-3 border-b flex items-center justify-between ${
              groupBy === 'priority' && groupName === 'High' ? 'bg-red-50' :
              groupBy === 'priority' && groupName === 'Medium' ? 'bg-yellow-50' :
              groupBy === 'priority' && groupName === 'Low' ? 'bg-green-50' :
              'bg-gray-50'
            }`}>
              <div className="flex items-center gap-2">
                <h3 className="font-semibold text-gray-800">{groupName}</h3>
                <span className="px-2 py-0.5 text-xs bg-gray-200 rounded-full text-gray-600">
                  {cards.length}
                </span>
              </div>
            </div>

            {/* Cards Grid */}
            <div className="p-4">
              {cards.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                  {cards.map(card => (
                    <div
                      key={card.id}
                      className={`p-3 rounded-lg border-l-4 shadow-sm ${
                        card.priority ? priorityColors[card.priority] : 'bg-gray-50 border-l-gray-300'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <h4 className="text-sm font-medium text-gray-900">{card.title}</h4>
                      </div>

                      {card.description && (
                        <p className="text-xs text-gray-500 mt-1 line-clamp-2">{card.description}</p>
                      )}

                      <div className="mt-2 flex flex-wrap gap-1">
                        <span className="px-2 py-0.5 text-xs bg-gray-200 rounded text-gray-600">
                          {card.column_name}
                        </span>
                        {card.labels?.map(label => (
                          <span
                            key={label}
                            className="px-2 py-0.5 text-xs rounded"
                            style={getLabelStyle(label)}
                          >
                            {label}
                          </span>
                        ))}
                      </div>

                      {card.due_date && (
                        <div className="mt-2 text-xs text-gray-500">
                          Due: {new Date(card.due_date).toLocaleDateString()}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-gray-400 italic py-4 text-center">No cards in this group</p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
