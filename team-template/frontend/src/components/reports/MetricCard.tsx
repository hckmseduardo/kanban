interface MetricCardProps {
  title: string
  value: string | number
  subtitle?: string
  trend?: 'up' | 'down' | 'neutral'
}

export function MetricCard({ title, value, subtitle, trend }: MetricCardProps) {
  const trendColors = {
    up: 'text-green-500',
    down: 'text-red-500',
    neutral: 'text-gray-500'
  }

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h3 className="text-sm font-medium text-gray-500 uppercase tracking-wide">
        {title}
      </h3>
      <div className="mt-2 flex items-baseline">
        <span className="text-3xl font-semibold text-gray-900">
          {value}
        </span>
        {subtitle && (
          <span className={`ml-2 text-sm ${trend ? trendColors[trend] : 'text-gray-500'}`}>
            {subtitle}
          </span>
        )}
      </div>
    </div>
  )
}
