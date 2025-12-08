import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useState, useMemo, useRef } from 'react'
import { useMutation, useQueryClient, useQuery } from '@tanstack/react-query'
import { cardsApi, attachmentsApi, commentsApi, labelsApi, membersApi, activityApi } from '../services/api'
import LinkPreview, { extractFirstUrl } from './LinkPreview'
import Markdown from './Markdown'
import Checklist from './Checklist'

interface Attachment {
  id: string
  card_id: string
  filename: string
  original_filename: string
  size: number
  content_type: string
  uploaded_at: string
}

interface Comment {
  id: string
  card_id: string
  text: string
  author_name: string
  created_at: string
  updated_at: string
}

interface Label {
  id: string
  name: string
  color: string
  bg: string
  text: string
}

interface Member {
  id: string
  name: string
  email: string
}

interface Activity {
  id: string
  card_id: string
  action: string
  from_column_name?: string
  to_column_name?: string
  timestamp: string
  details?: Record<string, any>
}

interface ChecklistItem {
  id: string
  text: string
  completed: boolean
}

interface CardProps {
  card: {
    id: string
    title: string
    description?: string
    labels?: string[]
    priority?: string
    due_date?: string
    assignee_id?: string
    checklist?: ChecklistItem[]
    attachment_count?: number
    comment_count?: number
  }
  boardId?: string
  isDragging?: boolean
}

const priorityColors: Record<string, string> = {
  high: 'bg-red-500',
  medium: 'bg-yellow-500',
  low: 'bg-green-500'
}

const priorityOptions = [
  { value: '', label: 'None' },
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' }
]

// Due date helpers
function getDueDateStatus(dueDate: string): 'overdue' | 'today' | 'soon' | 'upcoming' | 'future' {
  const due = new Date(dueDate)
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const dueDay = new Date(due.getFullYear(), due.getMonth(), due.getDate())
  const diffDays = Math.ceil((dueDay.getTime() - today.getTime()) / (1000 * 60 * 60 * 24))

  if (diffDays < 0) return 'overdue'
  if (diffDays === 0) return 'today'
  if (diffDays <= 2) return 'soon'
  if (diffDays <= 7) return 'upcoming'
  return 'future'
}

function getDueDateStyles(status: string): { bg: string; text: string; icon: string } {
  switch (status) {
    case 'overdue':
      return { bg: 'bg-red-100', text: 'text-red-700', icon: 'text-red-500' }
    case 'today':
      return { bg: 'bg-orange-100', text: 'text-orange-700', icon: 'text-orange-500' }
    case 'soon':
      return { bg: 'bg-yellow-100', text: 'text-yellow-700', icon: 'text-yellow-500' }
    case 'upcoming':
      return { bg: 'bg-blue-100', text: 'text-blue-700', icon: 'text-blue-500' }
    default:
      return { bg: 'bg-gray-100', text: 'text-gray-600', icon: 'text-gray-400' }
  }
}

function formatDueDate(dueDate: string, status: string): string {
  const due = new Date(dueDate)
  if (status === 'overdue') return `Overdue (${due.toLocaleDateString()})`
  if (status === 'today') return 'Due today'
  if (status === 'soon') return `Due ${due.toLocaleDateString()}`
  return `Due ${due.toLocaleDateString()}`
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function getFileIcon(contentType: string): string {
  if (contentType.startsWith('image/')) return '🖼️'
  if (contentType === 'application/pdf') return '📄'
  if (contentType.includes('spreadsheet') || contentType.includes('excel')) return '📊'
  if (contentType.includes('document') || contentType.includes('word')) return '📝'
  if (contentType.includes('presentation') || contentType.includes('powerpoint')) return '📽️'
  if (contentType.includes('zip') || contentType.includes('tar') || contentType.includes('gz')) return '📦'
  return '📎'
}

function formatRelativeTime(dateString: string): string {
  const date = new Date(dateString)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays < 7) return `${diffDays}d ago`
  return date.toLocaleDateString()
}

export default function Card({ card, boardId, isDragging }: CardProps) {
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [showEdit, setShowEdit] = useState(false)
  const [isPreviewMode, setIsPreviewMode] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [newComment, setNewComment] = useState('')
  const [showLabelPicker, setShowLabelPicker] = useState(false)
  const [activeTab, setActiveTab] = useState<'details' | 'activity'>('details')
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [editData, setEditData] = useState({
    title: card.title,
    description: card.description || '',
    labels: card.labels || [],
    priority: card.priority || '',
    due_date: card.due_date || '',
    assignee_id: card.assignee_id || ''
  })

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition
  } = useSortable({ id: card.id })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition
  }

  // Queries
  const { data: attachments = [] } = useQuery<Attachment[]>({
    queryKey: ['attachments', card.id],
    queryFn: () => attachmentsApi.list(card.id).then((res: { data: Attachment[] }) => res.data),
    enabled: showEdit
  })

  const { data: comments = [] } = useQuery<Comment[]>({
    queryKey: ['comments', card.id],
    queryFn: () => commentsApi.list(card.id).then((res: { data: Comment[] }) => res.data),
    enabled: showEdit
  })

  const { data: boardLabels = [] } = useQuery<Label[]>({
    queryKey: ['labels', boardId],
    queryFn: () => labelsApi.list(boardId!).then((res: { data: Label[] }) => res.data),
    enabled: showEdit && !!boardId
  })

  const { data: members = [] } = useQuery<Member[]>({
    queryKey: ['members'],
    queryFn: () => membersApi.list().then((res: { data: Member[] }) => res.data),
    enabled: showEdit
  })

  const { data: activities = [] } = useQuery<Activity[]>({
    queryKey: ['activity', card.id],
    queryFn: () => activityApi.getCardActivity(card.id).then((res: { data: Activity[] }) => res.data),
    enabled: showEdit
  })

  // Mutations
  const updateCard = useMutation({
    mutationFn: (data: any) => cardsApi.update(card.id, data),
    onSuccess: () => {
      if (boardId) {
        queryClient.invalidateQueries({ queryKey: ['board', boardId] })
      }
      setShowEdit(false)
    }
  })

  const deleteCard = useMutation({
    mutationFn: () => cardsApi.delete(card.id),
    onSuccess: () => {
      if (boardId) {
        queryClient.invalidateQueries({ queryKey: ['board', boardId] })
      }
    }
  })

  const uploadAttachment = useMutation({
    mutationFn: (file: File) => attachmentsApi.upload(card.id, file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['attachments', card.id] })
      if (boardId) {
        queryClient.invalidateQueries({ queryKey: ['board', boardId] })
      }
      setUploadError(null)
    },
    onError: (error: any) => {
      setUploadError(error.response?.data?.detail || 'Failed to upload file')
    }
  })

  const deleteAttachment = useMutation({
    mutationFn: (attachmentId: string) => attachmentsApi.delete(card.id, attachmentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['attachments', card.id] })
      if (boardId) {
        queryClient.invalidateQueries({ queryKey: ['board', boardId] })
      }
    }
  })

  const createComment = useMutation({
    mutationFn: (text: string) => commentsApi.create(card.id, { text }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['comments', card.id] })
      setNewComment('')
    }
  })

  const deleteComment = useMutation({
    mutationFn: (commentId: string) => commentsApi.delete(card.id, commentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['comments', card.id] })
    }
  })

  const createLabel = useMutation({
    mutationFn: (data: { name: string; color: string }) => labelsApi.create(boardId!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['labels', boardId] })
    }
  })

  const archiveCard = useMutation({
    mutationFn: () => cardsApi.archive(card.id),
    onSuccess: () => {
      if (boardId) {
        queryClient.invalidateQueries({ queryKey: ['board', boardId] })
      }
      setShowEdit(false)
    }
  })

  const copyCard = useMutation({
    mutationFn: (includeComments: boolean) => cardsApi.copy(card.id, undefined, includeComments),
    onSuccess: () => {
      if (boardId) {
        queryClient.invalidateQueries({ queryKey: ['board', boardId] })
      }
      setShowEdit(false)
    }
  })

  // Handlers
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      setUploadError(null)
      uploadAttachment.mutate(file)
    }
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const handleDownload = async (attachment: Attachment) => {
    try {
      const response = await attachmentsApi.download(card.id, attachment.id)
      const url = window.URL.createObjectURL(new Blob([response.data]))
      const link = document.createElement('a')
      link.href = url
      link.download = attachment.original_filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (error) {
      console.error('Download failed:', error)
    }
  }

  const toggleLabel = (labelName: string) => {
    const newLabels = editData.labels.includes(labelName)
      ? editData.labels.filter((l: string) => l !== labelName)
      : [...editData.labels, labelName]
    setEditData({ ...editData, labels: newLabels })
  }

  // Extract first URL from description for preview
  const previewUrl = useMemo(() => {
    if (!card.description) return null
    return extractFirstUrl(card.description)
  }, [card.description])

  // Get label styles for card preview
  const getLabelStyle = (labelName: string) => {
    const label = boardLabels.find((l: Label) => l.name === labelName)
    if (label) {
      return { backgroundColor: label.bg, color: label.text }
    }
    // Fallback colors
    const colors = [
      { bg: '#FEE2E2', text: '#991B1B' },
      { bg: '#DBEAFE', text: '#1E40AF' },
      { bg: '#DCFCE7', text: '#166534' },
      { bg: '#F3E8FF', text: '#6B21A8' },
      { bg: '#FEF9C3', text: '#854D0E' }
    ]
    const index = labelName.length % colors.length
    return { backgroundColor: colors[index].bg, color: colors[index].text }
  }

  if (isDragging) {
    return (
      <div className="bg-white rounded-lg p-3 shadow-lg opacity-80 rotate-3">
        <p className="font-medium">{card.title}</p>
      </div>
    )
  }

  return (
    <>
      <div
        ref={setNodeRef}
        style={style}
        {...attributes}
        {...listeners}
        className="bg-white rounded-lg p-3 shadow-sm hover:shadow cursor-grab active:cursor-grabbing"
        onClick={() => setShowEdit(true)}
      >
        {card.priority && (
          <div className={`w-8 h-1 ${priorityColors[card.priority]} rounded mb-2`} />
        )}

        <p className="font-medium text-sm">{card.title}</p>

        {card.description && (
          <p className="text-xs text-gray-500 mt-1 line-clamp-2">{card.description}</p>
        )}

        {previewUrl && <LinkPreview url={previewUrl} compact />}

        {card.labels && card.labels.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-2">
            {card.labels.map((label) => (
              <span
                key={label}
                className="px-2 py-0.5 text-xs rounded font-medium"
                style={getLabelStyle(label)}
              >
                {label}
              </span>
            ))}
          </div>
        )}

        {/* Indicators row */}
        <div className="flex items-center flex-wrap gap-2 mt-2">
          {card.checklist && card.checklist.length > 0 && (
            <div className="flex items-center space-x-1 text-xs text-gray-500">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
              </svg>
              <span>{card.checklist.filter(i => i.completed).length}/{card.checklist.length}</span>
            </div>
          )}
          {card.attachment_count ? (
            <div className="flex items-center space-x-1 text-xs text-gray-500">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
              </svg>
              <span>{card.attachment_count}</span>
            </div>
          ) : null}
          {card.comment_count ? (
            <div className="flex items-center space-x-1 text-xs text-gray-500">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
              </svg>
              <span>{card.comment_count}</span>
            </div>
          ) : null}
        </div>

        {card.due_date && (() => {
          const status = getDueDateStatus(card.due_date)
          const styles = getDueDateStyles(status)
          return (
            <div className={`flex items-center space-x-1.5 mt-2 px-2 py-1 rounded ${styles.bg}`}>
              <svg className={`w-3.5 h-3.5 ${styles.icon}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
              </svg>
              <span className={`text-xs font-medium ${styles.text}`}>
                {formatDueDate(card.due_date, status)}
              </span>
            </div>
          )
        })()}
      </div>

      {/* Edit Modal */}
      {showEdit && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col" onClick={e => e.stopPropagation()}>
            {/* Header with Tabs */}
            <div className="border-b">
              <div className="flex items-center justify-between p-4 pb-0">
                <h2 className="text-lg font-medium">Edit Card</h2>
                <button onClick={() => setShowEdit(false)} className="text-gray-400 hover:text-gray-600">
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <div className="flex gap-4 px-4 mt-2">
                <button
                  onClick={() => setActiveTab('details')}
                  className={`pb-2 text-sm font-medium border-b-2 ${
                    activeTab === 'details'
                      ? 'border-primary-600 text-primary-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700'
                  }`}
                >
                  Details
                </button>
                <button
                  onClick={() => setActiveTab('activity')}
                  className={`pb-2 text-sm font-medium border-b-2 ${
                    activeTab === 'activity'
                      ? 'border-primary-600 text-primary-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700'
                  }`}
                >
                  Activity ({activities.length})
                </button>
              </div>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {activeTab === 'activity' ? (
                /* Activity Tab */
                <div className="space-y-3">
                  {activities.length > 0 ? (
                    activities.map((activity) => (
                      <div key={activity.id} className="flex items-start gap-3 p-3 bg-gray-50 rounded-lg">
                        <div className="w-8 h-8 bg-gray-200 rounded-full flex items-center justify-center flex-shrink-0">
                          {activity.action === 'created' && (
                            <svg className="w-4 h-4 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                            </svg>
                          )}
                          {activity.action === 'moved' && (
                            <svg className="w-4 h-4 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
                            </svg>
                          )}
                          {activity.action === 'archived' && (
                            <svg className="w-4 h-4 text-yellow-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4" />
                            </svg>
                          )}
                          {activity.action === 'restored' && (
                            <svg className="w-4 h-4 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                            </svg>
                          )}
                          {!['created', 'moved', 'archived', 'restored'].includes(activity.action) && (
                            <svg className="w-4 h-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                          )}
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-gray-700">
                            {activity.action === 'created' && 'Card created'}
                            {activity.action === 'moved' && (
                              <>
                                Moved from <span className="font-medium">{activity.from_column_name}</span> to{' '}
                                <span className="font-medium">{activity.to_column_name}</span>
                              </>
                            )}
                            {activity.action === 'archived' && 'Card archived'}
                            {activity.action === 'restored' && 'Card restored'}
                            {activity.action === 'deleted' && 'Card deleted'}
                            {activity.details?.copied_from && ' (copied)'}
                          </p>
                          <p className="text-xs text-gray-400 mt-0.5">{formatRelativeTime(activity.timestamp)}</p>
                        </div>
                      </div>
                    ))
                  ) : (
                    <p className="text-sm text-gray-400 italic text-center py-8">No activity recorded</p>
                  )}
                </div>
              ) : (
                /* Details Tab */
                <>
              {/* Title */}
              <input
                type="text"
                value={editData.title}
                onChange={e => setEditData({ ...editData, title: e.target.value })}
                className="w-full px-3 py-2 text-lg font-medium border rounded-lg"
                placeholder="Card title"
              />

              {/* Labels */}
              <div>
                <label className="text-sm font-medium text-gray-700 mb-2 block">Labels</label>
                <div className="flex flex-wrap gap-2">
                  {editData.labels.map(label => (
                    <span
                      key={label}
                      className="px-2 py-1 text-sm rounded font-medium flex items-center gap-1 cursor-pointer hover:opacity-80"
                      style={getLabelStyle(label)}
                      onClick={() => toggleLabel(label)}
                    >
                      {label}
                      <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </span>
                  ))}
                  <button
                    onClick={() => setShowLabelPicker(!showLabelPicker)}
                    className="px-2 py-1 text-sm bg-gray-100 text-gray-600 rounded hover:bg-gray-200"
                  >
                    + Add Label
                  </button>
                </div>
                {showLabelPicker && (
                  <div className="mt-2 p-2 border rounded-lg bg-gray-50">
                    <div className="flex flex-wrap gap-2">
                      {boardLabels.filter(l => !editData.labels.includes(l.name)).map(label => (
                        <button
                          key={label.id}
                          onClick={() => toggleLabel(label.name)}
                          className="px-2 py-1 text-sm rounded font-medium hover:opacity-80"
                          style={{ backgroundColor: label.bg, color: label.text }}
                        >
                          {label.name}
                        </button>
                      ))}
                    </div>
                    {boardLabels.length === 0 && (
                      <p className="text-sm text-gray-500">No labels defined. Create one below:</p>
                    )}
                    <div className="mt-2 flex gap-2">
                      <input
                        type="text"
                        placeholder="New label name"
                        className="flex-1 px-2 py-1 text-sm border rounded"
                        onKeyDown={e => {
                          if (e.key === 'Enter' && e.currentTarget.value) {
                            createLabel.mutate({ name: e.currentTarget.value, color: 'blue' })
                            e.currentTarget.value = ''
                          }
                        }}
                      />
                    </div>
                  </div>
                )}
              </div>

              {/* Priority & Due Date Row */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-sm font-medium text-gray-700 mb-1 block">Priority</label>
                  <select
                    value={editData.priority}
                    onChange={e => setEditData({ ...editData, priority: e.target.value })}
                    className="w-full px-3 py-2 border rounded-lg"
                  >
                    {priorityOptions.map(opt => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-sm font-medium text-gray-700 mb-1 block">Due Date</label>
                  <input
                    type="date"
                    value={editData.due_date}
                    onChange={e => setEditData({ ...editData, due_date: e.target.value })}
                    className="w-full px-3 py-2 border rounded-lg"
                  />
                </div>
              </div>

              {/* Assignee */}
              <div>
                <label className="text-sm font-medium text-gray-700 mb-1 block">Assignee</label>
                <select
                  value={editData.assignee_id}
                  onChange={e => setEditData({ ...editData, assignee_id: e.target.value })}
                  className="w-full px-3 py-2 border rounded-lg"
                >
                  <option value="">Unassigned</option>
                  {members.map(member => (
                    <option key={member.id} value={member.id}>{member.name}</option>
                  ))}
                </select>
              </div>

              {/* Description */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-sm font-medium text-gray-700">Description</label>
                  <div className="flex rounded-md shadow-sm">
                    <button
                      type="button"
                      onClick={() => setIsPreviewMode(false)}
                      className={`px-3 py-1 text-xs font-medium rounded-l-md border ${
                        !isPreviewMode
                          ? 'bg-primary-600 text-white border-primary-600'
                          : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                      }`}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      onClick={() => setIsPreviewMode(true)}
                      className={`px-3 py-1 text-xs font-medium rounded-r-md border-t border-r border-b ${
                        isPreviewMode
                          ? 'bg-primary-600 text-white border-primary-600'
                          : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                      }`}
                    >
                      Preview
                    </button>
                  </div>
                </div>

                {isPreviewMode ? (
                  <div className="w-full min-h-[120px] p-3 border rounded-lg bg-gray-50">
                    {editData.description ? (
                      <Markdown content={editData.description} />
                    ) : (
                      <p className="text-gray-400 italic text-sm">No description</p>
                    )}
                  </div>
                ) : (
                  <textarea
                    value={editData.description}
                    onChange={e => setEditData({ ...editData, description: e.target.value })}
                    placeholder="Description (supports Markdown)"
                    className="w-full px-3 py-2 border rounded-lg font-mono text-sm"
                    rows={4}
                  />
                )}
              </div>

              {/* Checklist */}
              <div className="border-t pt-4">
                <Checklist cardId={card.id} boardId={boardId} items={card.checklist || []} />
              </div>

              {/* Attachments */}
              <div className="border-t pt-4">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-medium text-gray-700">Attachments ({attachments.length})</h3>
                  <input type="file" ref={fileInputRef} onChange={handleFileSelect} className="hidden" />
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={uploadAttachment.isPending}
                    className="px-3 py-1 text-sm bg-gray-100 text-gray-700 rounded hover:bg-gray-200 disabled:opacity-50"
                  >
                    {uploadAttachment.isPending ? 'Uploading...' : '+ Add File'}
                  </button>
                </div>

                {uploadError && (
                  <div className="mb-3 p-2 bg-red-50 text-red-600 text-sm rounded">{uploadError}</div>
                )}

                {attachments.length > 0 ? (
                  <div className="space-y-2">
                    {attachments.map((attachment) => (
                      <div key={attachment.id} className="flex items-center justify-between p-2 bg-gray-50 rounded hover:bg-gray-100">
                        <div className="flex items-center space-x-2 min-w-0 flex-1">
                          <span className="text-lg">{getFileIcon(attachment.content_type)}</span>
                          <div className="min-w-0 flex-1">
                            <button
                              onClick={() => handleDownload(attachment)}
                              className="text-sm text-blue-600 hover:text-blue-800 truncate block max-w-full text-left"
                            >
                              {attachment.original_filename}
                            </button>
                            <span className="text-xs text-gray-500">{formatFileSize(attachment.size)}</span>
                          </div>
                        </div>
                        <button
                          onClick={() => deleteAttachment.mutate(attachment.id)}
                          className="ml-2 p-1 text-gray-400 hover:text-red-500"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-gray-400 italic">No attachments</p>
                )}
              </div>

              {/* Comments */}
              <div className="border-t pt-4">
                <h3 className="text-sm font-medium text-gray-700 mb-3">Comments ({comments.length})</h3>

                {/* Add comment */}
                <div className="flex gap-2 mb-4">
                  <input
                    type="text"
                    value={newComment}
                    onChange={e => setNewComment(e.target.value)}
                    placeholder="Write a comment..."
                    className="flex-1 px-3 py-2 border rounded-lg text-sm"
                    onKeyDown={e => {
                      if (e.key === 'Enter' && newComment.trim()) {
                        createComment.mutate(newComment)
                      }
                    }}
                  />
                  <button
                    onClick={() => newComment.trim() && createComment.mutate(newComment)}
                    disabled={!newComment.trim() || createComment.isPending}
                    className="px-4 py-2 bg-primary-600 text-white rounded-lg text-sm hover:bg-primary-700 disabled:opacity-50"
                  >
                    Post
                  </button>
                </div>

                {/* Comment list */}
                {comments.length > 0 ? (
                  <div className="space-y-3">
                    {comments.map(comment => (
                      <div key={comment.id} className="bg-gray-50 rounded-lg p-3">
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-sm font-medium text-gray-700">{comment.author_name}</span>
                          <div className="flex items-center gap-2">
                            <span className="text-xs text-gray-400">{formatRelativeTime(comment.created_at)}</span>
                            <button
                              onClick={() => deleteComment.mutate(comment.id)}
                              className="text-gray-400 hover:text-red-500"
                            >
                              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                              </svg>
                            </button>
                          </div>
                        </div>
                        <p className="text-sm text-gray-600">{comment.text}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-gray-400 italic">No comments yet</p>
                )}
              </div>
                </>
              )}
            </div>

            {/* Footer */}
            <div className="flex justify-between p-4 border-t bg-gray-50">
              <div className="flex items-center gap-2">
                {showDeleteConfirm ? (
                  <div className="flex items-center gap-2 bg-red-50 px-3 py-1 rounded-lg border border-red-200">
                    <span className="text-sm text-red-700">Delete this card?</span>
                    <button
                      onClick={() => {
                        deleteCard.mutate()
                        setShowDeleteConfirm(false)
                      }}
                      disabled={deleteCard.isPending}
                      className="text-red-600 hover:text-red-700 text-sm font-medium"
                    >
                      {deleteCard.isPending ? 'Deleting...' : 'Yes'}
                    </button>
                    <button
                      onClick={() => setShowDeleteConfirm(false)}
                      className="text-gray-600 hover:text-gray-700 text-sm"
                    >
                      No
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setShowDeleteConfirm(true)}
                    className="text-red-600 hover:text-red-700 text-sm"
                  >
                    Delete
                  </button>
                )}
                <span className="text-gray-300">|</span>
                <button
                  onClick={() => archiveCard.mutate()}
                  className="text-yellow-600 hover:text-yellow-700 text-sm"
                  disabled={archiveCard.isPending}
                >
                  {archiveCard.isPending ? 'Archiving...' : 'Archive'}
                </button>
                <span className="text-gray-300">|</span>
                <button
                  onClick={() => copyCard.mutate(false)}
                  className="text-blue-600 hover:text-blue-700 text-sm"
                  disabled={copyCard.isPending}
                >
                  {copyCard.isPending ? 'Copying...' : 'Copy'}
                </button>
              </div>
              <div className="flex space-x-2">
                <button
                  onClick={() => {
                    setShowEdit(false)
                    setIsPreviewMode(false)
                    setActiveTab('details')
                  }}
                  className="px-4 py-2 text-gray-600 hover:text-gray-800 text-sm"
                >
                  Cancel
                </button>
                <button
                  onClick={() => updateCard.mutate(editData)}
                  className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 text-sm"
                >
                  Save Changes
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
