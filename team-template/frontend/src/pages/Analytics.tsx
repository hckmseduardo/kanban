import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { analyticsApi, boardsApi } from '../services/api'

export default function Analytics() {
  const { boardId } = useParams<{ boardId: string }>()

  const { data: board } = useQuery({
    queryKey: ['board', boardId],
    queryFn: () => boardsApi.get(boardId!).then(res => res.data),
    enabled: !!boardId
  })

  const { data: overview, isLoading: overviewLoading } = useQuery({
    queryKey: ['analytics-overview', boardId],
    queryFn: () => analyticsApi.overview(boardId!).then(res => res.data),
    enabled: !!boardId
  })

  const { data: velocity } = useQuery({
    queryKey: ['analytics-velocity', boardId],
    queryFn: () => analyticsApi.velocity(boardId!, 8).then(res => res.data),
    enabled: !!boardId
  })

  const { data: labelDist } = useQuery({
    queryKey: ['analytics-labels', boardId],
    queryFn: () => analyticsApi.labelDistribution(boardId!).then(res => res.data),
    enabled: !!boardId
  })

  const { data: workload } = useQuery({
    queryKey: ['analytics-workload', boardId],
    queryFn: () => analyticsApi.assigneeWorkload(boardId!).then(res => res.data),
    enabled: !!boardId
  })

  const { data: wipAging } = useQuery({
    queryKey: ['analytics-wip', boardId],
    queryFn: () => analyticsApi.wipAging(boardId!).then(res => res.data),
    enabled: !!boardId
  })

  if (overviewLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    )
  }

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="flex items-center gap-2 text-sm text-gray-500 mb-1">
            <Link to="/" className="hover:text-blue-600">Boards</Link>
            <span>/</span>
            <Link to={`/boards/${boardId}`} className="hover:text-blue-600">{board?.name}</Link>
            <span>/</span>
            <span>Analytics</span>
          </div>
          <h1 className="text-2xl font-bold dark:text-white">Board Analytics</h1>
        </div>
        <Link
          to={`/boards/${boardId}`}
          className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg dark:text-gray-300 dark:hover:bg-gray-700"
        >
          Back to Board
        </Link>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <div className="bg-white dark:bg-gray-800 rounded-lg p-4 shadow">
          <h3 className="text-sm text-gray-500 dark:text-gray-400">Active Cards</h3>
          <p className="text-3xl font-bold dark:text-white">{overview?.summary?.active_cards || 0}</p>
        </div>
        <div className="bg-white dark:bg-gray-800 rounded-lg p-4 shadow">
          <h3 className="text-sm text-gray-500 dark:text-gray-400">Completed</h3>
          <p className="text-3xl font-bold text-green-600">{overview?.summary?.completed_cards || 0}</p>
        </div>
        <div className="bg-white dark:bg-gray-800 rounded-lg p-4 shadow">
          <h3 className="text-sm text-gray-500 dark:text-gray-400">Overdue</h3>
          <p className="text-3xl font-bold text-red-600">{overview?.summary?.overdue_cards || 0}</p>
        </div>
        <div className="bg-white dark:bg-gray-800 rounded-lg p-4 shadow">
          <h3 className="text-sm text-gray-500 dark:text-gray-400">Blocked</h3>
          <p className="text-3xl font-bold text-orange-600">{overview?.summary?.blocked_cards || 0}</p>
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        {/* Velocity Chart */}
        <div className="bg-white dark:bg-gray-800 rounded-lg p-4 shadow">
          <h3 className="text-lg font-semibold mb-4 dark:text-white">Weekly Velocity</h3>
          {velocity?.velocity_data && (
            <>
              <div className="flex items-end gap-1 h-40">
                {velocity.velocity_data.map((week: { week_starting: string; cards_completed: number }, i: number) => (
                  <div key={i} className="flex-1 flex flex-col items-center">
                    <div
                      className="w-full bg-blue-500 rounded-t"
                      style={{
                        height: `${Math.max(4, (week.cards_completed / (velocity.statistics?.max || 1)) * 100)}%`
                      }}
                    />
                    <span className="text-xs text-gray-400 mt-1 rotate-45 origin-left">
                      W{i + 1}
                    </span>
                  </div>
                ))}
              </div>
              <div className="mt-4 flex justify-around text-sm">
                <div className="text-center">
                  <p className="text-gray-500">Average</p>
                  <p className="font-semibold dark:text-white">{velocity.statistics?.average}</p>
                </div>
                <div className="text-center">
                  <p className="text-gray-500">Max</p>
                  <p className="font-semibold dark:text-white">{velocity.statistics?.max}</p>
                </div>
                <div className="text-center">
                  <p className="text-gray-500">Min</p>
                  <p className="font-semibold dark:text-white">{velocity.statistics?.min}</p>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Column Distribution */}
        <div className="bg-white dark:bg-gray-800 rounded-lg p-4 shadow">
          <h3 className="text-lg font-semibold mb-4 dark:text-white">Cards by Column</h3>
          <div className="space-y-3">
            {overview?.columns?.map((col: { id: string; name: string; card_count: number; wip_limit?: number }) => {
              const maxCards = Math.max(...(overview.columns?.map((c: { card_count: number }) => c.card_count) || [1]))
              const percentage = (col.card_count / maxCards) * 100
              const isOverLimit = col.wip_limit && col.card_count > col.wip_limit

              return (
                <div key={col.id}>
                  <div className="flex justify-between text-sm mb-1">
                    <span className="dark:text-white">{col.name}</span>
                    <span className={isOverLimit ? 'text-red-600 font-semibold' : 'text-gray-500'}>
                      {col.card_count}
                      {col.wip_limit && <span className="text-gray-400">/{col.wip_limit}</span>}
                    </span>
                  </div>
                  <div className="h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${isOverLimit ? 'bg-red-500' : 'bg-blue-500'}`}
                      style={{ width: `${percentage}%` }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* Label Distribution */}
        <div className="bg-white dark:bg-gray-800 rounded-lg p-4 shadow">
          <h3 className="text-lg font-semibold mb-4 dark:text-white">Label Distribution</h3>
          {labelDist?.distribution?.length ? (
            <div className="space-y-2">
              {labelDist.distribution.slice(0, 8).map((label: { label_id: string; name: string; color?: string; count: number; percentage: number }) => (
                <div key={label.label_id} className="flex items-center gap-2">
                  <div
                    className="w-3 h-3 rounded-full"
                    style={{ backgroundColor: label.color || '#6B7280' }}
                  />
                  <span className="flex-1 dark:text-white">{label.name}</span>
                  <span className="text-sm text-gray-500">{label.count}</span>
                  <span className="text-xs text-gray-400">({label.percentage}%)</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-gray-500 text-center py-4">No labels used</p>
          )}
        </div>

        {/* Assignee Workload */}
        <div className="bg-white dark:bg-gray-800 rounded-lg p-4 shadow">
          <h3 className="text-lg font-semibold mb-4 dark:text-white">Workload by Assignee</h3>
          {workload?.workload?.length ? (
            <div className="space-y-3">
              {workload.workload.map((assignee: { assignee_id: string | null; name: string; total_cards: number; overdue_cards: number; blocked_cards: number }) => (
                <div key={assignee.assignee_id || 'unassigned'} className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-gray-200 dark:bg-gray-700 flex items-center justify-center text-sm font-medium">
                    {assignee.name?.charAt(0) || '?'}
                  </div>
                  <div className="flex-1">
                    <div className="flex justify-between">
                      <span className="dark:text-white">{assignee.name}</span>
                      <span className="text-sm font-medium dark:text-white">{assignee.total_cards} cards</span>
                    </div>
                    <div className="flex gap-2 text-xs">
                      {assignee.overdue_cards > 0 && (
                        <span className="text-red-600">{assignee.overdue_cards} overdue</span>
                      )}
                      {assignee.blocked_cards > 0 && (
                        <span className="text-orange-600">{assignee.blocked_cards} blocked</span>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-gray-500 text-center py-4">No assignees</p>
          )}
        </div>

        {/* WIP Aging */}
        <div className="bg-white dark:bg-gray-800 rounded-lg p-4 shadow md:col-span-2">
          <h3 className="text-lg font-semibold mb-4 dark:text-white">Work In Progress Aging</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b dark:border-gray-700">
                  <th className="text-left py-2 dark:text-white">Column</th>
                  <th className="text-center py-2 dark:text-white">Cards</th>
                  <th className="text-center py-2 dark:text-white">Avg Age</th>
                  <th className="text-center py-2 dark:text-white">Max Age</th>
                  <th className="text-left py-2 dark:text-white">Oldest Cards</th>
                </tr>
              </thead>
              <tbody>
                {wipAging?.columns?.map((col: { column_id: string; column_name: string; card_count: number; avg_age: number; max_age: number; cards: Array<{ id: string; title: string; age_days: number }> }) => (
                  <tr key={col.column_id} className="border-b dark:border-gray-700">
                    <td className="py-2 dark:text-white">{col.column_name}</td>
                    <td className="text-center py-2 dark:text-white">{col.card_count}</td>
                    <td className="text-center py-2 dark:text-white">{col.avg_age} days</td>
                    <td className="text-center py-2">
                      <span className={col.max_age > 14 ? 'text-red-600 font-semibold' : 'dark:text-white'}>
                        {col.max_age} days
                      </span>
                    </td>
                    <td className="py-2 text-gray-500">
                      {col.cards?.slice(0, 2).map((c: { title: string }) => c.title).join(', ')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
