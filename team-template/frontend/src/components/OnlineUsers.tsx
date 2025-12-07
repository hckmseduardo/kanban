interface OnlineUser {
  user_id: string
  user_name: string
}

interface OnlineUsersProps {
  users: OnlineUser[]
  currentUserId?: string
}

export default function OnlineUsers({ users, currentUserId }: OnlineUsersProps) {
  // Filter out current user and get unique users
  const otherUsers = users.filter(u => u.user_id !== currentUserId)
  const displayUsers = otherUsers.slice(0, 4)
  const extraCount = otherUsers.length - 4

  if (otherUsers.length === 0) return null

  return (
    <div className="flex items-center gap-1">
      <div className="flex -space-x-2">
        {displayUsers.map((user) => (
          <div
            key={user.user_id}
            className="relative w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center text-white text-sm font-medium ring-2 ring-white dark:ring-gray-800"
            title={user.user_name}
          >
            {user.user_name?.charAt(0)?.toUpperCase() || '?'}
            <span className="absolute bottom-0 right-0 w-2.5 h-2.5 bg-green-500 rounded-full ring-2 ring-white dark:ring-gray-800" />
          </div>
        ))}
        {extraCount > 0 && (
          <div className="w-8 h-8 rounded-full bg-gray-300 dark:bg-gray-600 flex items-center justify-center text-xs font-medium text-gray-600 dark:text-gray-300 ring-2 ring-white dark:ring-gray-800">
            +{extraCount}
          </div>
        )}
      </div>
      <span className="text-sm text-gray-500 dark:text-gray-400 ml-2">
        {otherUsers.length} online
      </span>
    </div>
  )
}
