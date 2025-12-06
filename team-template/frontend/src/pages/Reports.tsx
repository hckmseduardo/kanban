import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { format, subDays } from 'date-fns'
import { reportsApi, boardsApi } from '../services/api'
import { MetricCard } from '../components/reports/MetricCard'
import { CycleTimeChart } from '../components/reports/CycleTimeChart'
import { ThroughputChart } from '../components/reports/ThroughputChart'

type GroupBy = 'day' | 'week' | 'month'

export default function Reports() {
  const { boardId } = useParams<{ boardId: string }>()
  const [groupBy, setGroupBy] = useState<GroupBy>('day')
  const [dateRange, setDateRange] = useState(30)

  const fromDate = format(subDays(new Date(), dateRange), 'yyyy-MM-dd')
  const toDate = format(new Date(), 'yyyy-MM-dd')

  const { data: board } = useQuery({
    queryKey: ['board', boardId],
    queryFn: () => boardsApi.get(boardId!).then(res => res.data),
    enabled: !!boardId
  })

  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ['reports', 'summary', boardId],
    queryFn: () => reportsApi.getSummary(boardId!).then(res => res.data),
    enabled: !!boardId
  })

  const { data: cycleTime, isLoading: cycleTimeLoading } = useQuery({
    queryKey: ['reports', 'cycle-time', boardId, fromDate, toDate, groupBy],
    queryFn: () => reportsApi.getCycleTime(boardId!, { from_date: fromDate, to_date: toDate, group_by: groupBy }).then(res => res.data),
    enabled: !!boardId
  })

  const { data: leadTime, isLoading: leadTimeLoading } = useQuery({
    queryKey: ['reports', 'lead-time', boardId, fromDate, toDate, groupBy],
    queryFn: () => reportsApi.getLeadTime(boardId!, { from_date: fromDate, to_date: toDate, group_by: groupBy }).then(res => res.data),
    enabled: !!boardId
  })

  const { data: throughput, isLoading: throughputLoading } = useQuery({
    queryKey: ['reports', 'throughput', boardId, fromDate, toDate, groupBy],
    queryFn: () => reportsApi.getThroughput(boardId!, { from_date: fromDate, to_date: toDate, group_by: groupBy }).then(res => res.data),
    enabled: !!boardId
  })

  const formatHours = (hours: number) => {
    if (hours < 24) return `${hours.toFixed(1)}h`
    return `${(hours / 24).toFixed(1)}d`
  }

  const isLoading = summaryLoading || cycleTimeLoading || leadTimeLoading || throughputLoading

  return (
    <div className="min-h-screen bg-gray-100">
      {/* Header */}
      <header className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Link
                to={`/boards/${boardId}`}
                className="text-gray-500 hover:text-gray-700"
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
                </svg>
              </Link>
              <div>
                <h1 className="text-2xl font-bold text-gray-900">Reports</h1>
                {board && <p className="text-sm text-gray-500">{board.name}</p>}
              </div>
            </div>

            {/* Filters */}
            <div className="flex items-center gap-4">
              <select
                value={dateRange}
                onChange={(e) => setDateRange(Number(e.target.value))}
                className="border border-gray-300 rounded-md px-3 py-2 text-sm"
              >
                <option value={7}>Last 7 days</option>
                <option value={30}>Last 30 days</option>
                <option value={90}>Last 90 days</option>
              </select>

              <select
                value={groupBy}
                onChange={(e) => setGroupBy(e.target.value as GroupBy)}
                className="border border-gray-300 rounded-md px-3 py-2 text-sm"
              >
                <option value="day">By Day</option>
                <option value="week">By Week</option>
                <option value="month">By Month</option>
              </select>
            </div>
          </div>
        </div>
      </header>

      {/* Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {isLoading ? (
          <div className="flex items-center justify-center h-64">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
          </div>
        ) : (
          <div className="space-y-8">
            {/* Summary Cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
              <MetricCard
                title="Total Cards"
                value={summary?.metrics?.total_cards || 0}
              />
              <MetricCard
                title="Completed (30d)"
                value={summary?.metrics?.completed_last_30d || 0}
              />
              <MetricCard
                title="Avg Cycle Time"
                value={formatHours(cycleTime?.summary?.avg_hours || 0)}
                subtitle={`${cycleTime?.summary?.completed_cards || 0} cards`}
              />
              <MetricCard
                title="Avg Lead Time"
                value={formatHours(leadTime?.summary?.avg_hours || 0)}
                subtitle={`${leadTime?.summary?.completed_cards || 0} cards`}
              />
            </div>

            {/* Charts */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <CycleTimeChart
                data={cycleTime?.data || []}
                title="Cycle Time Trend"
              />
              <ThroughputChart
                data={throughput?.data || []}
                title="Throughput"
              />
            </div>

            {/* Column Distribution */}
            {summary?.column_distribution && (
              <div className="bg-white rounded-lg shadow p-6">
                <h3 className="text-lg font-medium text-gray-900 mb-4">Current Board State</h3>
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
                  {summary.column_distribution.map((col: any) => (
                    <div
                      key={col.id}
                      className="bg-gray-50 rounded-lg p-4 text-center"
                    >
                      <div className="text-2xl font-bold text-gray-900">
                        {col.count}
                        {col.wip_limit && (
                          <span className="text-sm font-normal text-gray-500">
                            /{col.wip_limit}
                          </span>
                        )}
                      </div>
                      <div className="text-sm text-gray-600 mt-1">{col.name}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  )
}
