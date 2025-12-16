import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useState, useRef, useEffect } from 'react'
import { useMutation, useQueryClient, useQuery } from '@tanstack/react-query'
import { cardsApi, attachmentsApi, commentsApi, labelsApi, membersApi, activityApi, boardsApi } from '../services/api'
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

interface Column {
  id: string
  name: string
  position: number
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
    archived?: boolean
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
  const [isEditingDescription, setIsEditingDescription] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [newComment, setNewComment] = useState('')
  const [showLabelPicker, setShowLabelPicker] = useState(false)
  const [activeTool, setActiveTool] = useState<'comments' | 'checklist' | 'settings' | 'attachments' | 'activity' | 'move' | null>(null)
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

  // Escape key handler to close modal
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && showEdit) {
        if (isEditingDescription) {
          setIsEditingDescription(false)
        } else {
          setShowEdit(false)
          setActiveTool(null)
        }
      }
    }
    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [showEdit, isEditingDescription])

  // Auto-enter edit mode for description when card has no description
  useEffect(() => {
    if (showEdit && !card.description) {
      setIsEditingDescription(true)
    }
  }, [showEdit, card.description])

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

  const { data: boardData } = useQuery<{ columns: Column[] }>({
    queryKey: ['board', boardId],
    queryFn: () => boardsApi.get(boardId!).then((res: { data: { columns: Column[] } }) => res.data),
    enabled: showEdit && !!boardId
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

  const moveCard = useMutation({
    mutationFn: (columnId: string) => cardsApi.move(card.id, columnId, 0),
    onSuccess: () => {
      if (boardId) {
        queryClient.invalidateQueries({ queryKey: ['board', boardId] })
      }
      setActiveTool(null)
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
      <div className="bg-white rounded p-2 shadow-lg opacity-80 rotate-3">
        <p className="font-medium text-xs">{card.title}</p>
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
        className={`bg-white rounded p-2 shadow-sm hover:shadow cursor-grab active:cursor-grabbing ${card.archived ? 'opacity-60 border-2 border-dashed border-yellow-400' : ''}`}
        onClick={() => setShowEdit(true)}
      >
        {card.archived && (
          <div className="flex items-center gap-1 text-[10px] text-yellow-600 bg-yellow-50 px-1 rounded mb-1">
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4" />
            </svg>
            Archived
          </div>
        )}
        {card.priority && !card.archived && (
          <div className={`w-6 h-0.5 ${priorityColors[card.priority]} rounded mb-1`} />
        )}

        <p className={`font-medium text-xs leading-tight ${card.archived ? 'text-gray-500' : ''}`}>{card.title}</p>

        {card.labels && card.labels.length > 0 && (
          <div className="flex flex-wrap gap-0.5 mt-1">
            {card.labels.slice(0, 3).map((label) => (
              <span
                key={label}
                className="px-1 py-0 text-[10px] rounded font-medium"
                style={getLabelStyle(label)}
              >
                {label}
              </span>
            ))}
            {card.labels.length > 3 && (
              <span className="text-[10px] text-gray-400">+{card.labels.length - 3}</span>
            )}
          </div>
        )}

        {/* Compact indicators row */}
        {(card.checklist?.length || card.attachment_count || card.comment_count || card.due_date) && (
          <div className="flex items-center flex-wrap gap-1.5 mt-1 text-[10px] text-gray-500">
            {card.checklist && card.checklist.length > 0 && (
              <div className="flex items-center gap-0.5">
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
                </svg>
                <span>{card.checklist.filter(i => i.completed).length}/{card.checklist.length}</span>
              </div>
            )}
            {card.attachment_count ? (
              <div className="flex items-center gap-0.5">
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                </svg>
                <span>{card.attachment_count}</span>
              </div>
            ) : null}
            {card.comment_count ? (
              <div className="flex items-center gap-0.5">
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                </svg>
                <span>{card.comment_count}</span>
              </div>
            ) : null}
            {card.due_date && (() => {
              const status = getDueDateStatus(card.due_date)
              const styles = getDueDateStyles(status)
              return (
                <div className={`flex items-center gap-0.5 px-1 rounded ${styles.bg}`}>
                  <svg className={`w-3 h-3 ${styles.icon}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                  </svg>
                  <span className={`font-medium ${styles.text}`}>
                    {new Date(card.due_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                  </span>
                </div>
              )
            })()}
          </div>
        )}
      </div>

      {/* Edit Modal */}
      {showEdit && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg w-full h-full max-w-[95vw] max-h-[95vh] overflow-hidden flex flex-col" onClick={e => e.stopPropagation()}>
            {/* Header with Title and Tools */}
            <div className="border-b p-4">
              <div className="flex items-start justify-between gap-4">
                <input
                  type="text"
                  value={editData.title}
                  onChange={e => setEditData({ ...editData, title: e.target.value })}
                  className="flex-1 px-3 py-2 text-xl font-semibold border rounded-lg"
                  placeholder="Card title"
                />
                <button onClick={() => setShowEdit(false)} className="text-gray-400 hover:text-gray-600 p-2">
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>

              {/* Tool buttons */}
              <div className="flex gap-1 mt-3">
                <button
                  onClick={() => setActiveTool(activeTool === 'comments' ? null : 'comments')}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm ${
                    activeTool === 'comments' ? 'bg-primary-100 text-primary-700' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                  }`}
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                  </svg>
                  <span>{comments.length}</span>
                </button>
                <button
                  onClick={() => setActiveTool(activeTool === 'checklist' ? null : 'checklist')}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm ${
                    activeTool === 'checklist' ? 'bg-primary-100 text-primary-700' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                  }`}
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
                  </svg>
                  <span>{card.checklist?.length || 0}</span>
                </button>
                <button
                  onClick={() => setActiveTool(activeTool === 'settings' ? null : 'settings')}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm ${
                    activeTool === 'settings' ? 'bg-primary-100 text-primary-700' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                  }`}
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z" />
                  </svg>
                  <span>Labels</span>
                </button>
                <button
                  onClick={() => setActiveTool(activeTool === 'attachments' ? null : 'attachments')}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm ${
                    activeTool === 'attachments' ? 'bg-primary-100 text-primary-700' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                  }`}
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                  </svg>
                  <span>{attachments.length}</span>
                </button>
                <button
                  onClick={() => setActiveTool(activeTool === 'activity' ? null : 'activity')}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm ${
                    activeTool === 'activity' ? 'bg-primary-100 text-primary-700' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                  }`}
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <span>Activity</span>
                </button>
                <button
                  onClick={() => setActiveTool(activeTool === 'move' ? null : 'move')}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm ${
                    activeTool === 'move' ? 'bg-primary-100 text-primary-700' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                  }`}
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
                  </svg>
                  <span>Move</span>
                </button>
              </div>
            </div>

            {/* Main Content Area */}
            <div className="flex-1 flex overflow-hidden">
              {/* Description - Main Focus */}
              <div className="flex-1 p-4 overflow-y-auto">
                {isEditingDescription ? (
                  <div className="h-full flex flex-col">
                    <textarea
                      value={editData.description}
                      onChange={e => setEditData({ ...editData, description: e.target.value })}
                      placeholder="Write a description... (Markdown supported)"
                      className="flex-1 w-full px-4 py-3 border rounded-lg font-mono text-sm resize-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                      autoFocus
                    />
                    <div className="flex justify-end gap-2 mt-3">
                      <button
                        onClick={() => setIsEditingDescription(false)}
                        className="px-4 py-2 text-gray-600 hover:text-gray-800 text-sm"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={() => setIsEditingDescription(false)}
                        className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 text-sm"
                      >
                        Done
                      </button>
                    </div>
                  </div>
                ) : (
                  <div
                    onDoubleClick={() => setIsEditingDescription(true)}
                    className="h-full p-4 border rounded-lg bg-gray-50 cursor-text hover:bg-gray-100 transition-colors overflow-y-auto"
                  >
                    {editData.description ? (
                      <Markdown content={editData.description} />
                    ) : (
                      <p className="text-gray-400 italic">Double-click to edit description...</p>
                    )}
                  </div>
                )}
              </div>

              {/* Tool Panel - Slides in from right */}
              {activeTool && (
                <div className="w-80 border-l bg-gray-50 overflow-y-auto flex-shrink-0">
                  <div className="p-4">
                    {/* Comments Panel */}
                    {activeTool === 'comments' && (
                      <div>
                        <h3 className="font-medium text-gray-900 mb-4">Comments</h3>
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
                            className="px-3 py-2 bg-primary-600 text-white rounded-lg text-sm hover:bg-primary-700 disabled:opacity-50"
                          >
                            Post
                          </button>
                        </div>
                        <div className="space-y-3">
                          {comments.map(comment => (
                            <div key={comment.id} className="bg-white rounded-lg p-3 border">
                              <div className="flex items-center justify-between mb-1">
                                <span className="text-sm font-medium text-gray-700">{comment.author_name}</span>
                                <div className="flex items-center gap-2">
                                  <span className="text-xs text-gray-400">{formatRelativeTime(comment.created_at)}</span>
                                  <button onClick={() => deleteComment.mutate(comment.id)} className="text-gray-400 hover:text-red-500">
                                    <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                    </svg>
                                  </button>
                                </div>
                              </div>
                              <p className="text-sm text-gray-600">{comment.text}</p>
                            </div>
                          ))}
                          {comments.length === 0 && <p className="text-sm text-gray-400 italic">No comments yet</p>}
                        </div>
                      </div>
                    )}

                    {/* Checklist Panel */}
                    {activeTool === 'checklist' && (
                      <div>
                        <h3 className="font-medium text-gray-900 mb-4">Checklist</h3>
                        <Checklist cardId={card.id} boardId={boardId} items={card.checklist || []} />
                      </div>
                    )}

                    {/* Settings Panel (Labels, Priority, Due Date, Assignee) */}
                    {activeTool === 'settings' && (
                      <div className="space-y-4">
                        <h3 className="font-medium text-gray-900">Card Settings</h3>

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
                            <button onClick={() => setShowLabelPicker(!showLabelPicker)} className="px-2 py-1 text-sm bg-gray-100 text-gray-600 rounded hover:bg-gray-200">
                              + Add
                            </button>
                          </div>
                          {showLabelPicker && (
                            <div className="mt-2 p-2 border rounded-lg bg-white">
                              <div className="flex flex-wrap gap-2">
                                {boardLabels.filter(l => !editData.labels.includes(l.name)).map(label => (
                                  <button key={label.id} onClick={() => toggleLabel(label.name)} className="px-2 py-1 text-sm rounded font-medium hover:opacity-80" style={{ backgroundColor: label.bg, color: label.text }}>
                                    {label.name}
                                  </button>
                                ))}
                              </div>
                              <div className="mt-2">
                                <input type="text" placeholder="New label name" className="w-full px-2 py-1 text-sm border rounded" onKeyDown={e => { if (e.key === 'Enter' && e.currentTarget.value) { createLabel.mutate({ name: e.currentTarget.value, color: 'blue' }); e.currentTarget.value = '' } }} />
                              </div>
                            </div>
                          )}
                        </div>

                        {/* Priority */}
                        <div>
                          <label className="text-sm font-medium text-gray-700 mb-1 block">Priority</label>
                          <select value={editData.priority} onChange={e => setEditData({ ...editData, priority: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm">
                            {priorityOptions.map(opt => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
                          </select>
                        </div>

                        {/* Due Date */}
                        <div>
                          <label className="text-sm font-medium text-gray-700 mb-1 block">Due Date</label>
                          <input type="date" value={editData.due_date} onChange={e => setEditData({ ...editData, due_date: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm" />
                        </div>

                        {/* Assignee */}
                        <div>
                          <label className="text-sm font-medium text-gray-700 mb-1 block">Assignee</label>
                          <select value={editData.assignee_id} onChange={e => setEditData({ ...editData, assignee_id: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm">
                            <option value="">Unassigned</option>
                            {members.map(member => <option key={member.id} value={member.id}>{member.name}</option>)}
                          </select>
                        </div>
                      </div>
                    )}

                    {/* Attachments Panel */}
                    {activeTool === 'attachments' && (
                      <div>
                        <div className="flex items-center justify-between mb-4">
                          <h3 className="font-medium text-gray-900">Attachments</h3>
                          <input type="file" ref={fileInputRef} onChange={handleFileSelect} className="hidden" />
                          <button onClick={() => fileInputRef.current?.click()} disabled={uploadAttachment.isPending} className="px-3 py-1.5 text-sm bg-primary-600 text-white rounded hover:bg-primary-700 disabled:opacity-50">
                            {uploadAttachment.isPending ? 'Uploading...' : '+ Add File'}
                          </button>
                        </div>
                        {uploadError && <div className="mb-3 p-2 bg-red-50 text-red-600 text-sm rounded">{uploadError}</div>}
                        <div className="space-y-2">
                          {attachments.map((attachment) => (
                            <div key={attachment.id} className="flex items-center justify-between p-2 bg-white rounded border hover:bg-gray-50">
                              <div className="flex items-center space-x-2 min-w-0 flex-1">
                                <span className="text-base">{getFileIcon(attachment.content_type)}</span>
                                <div className="min-w-0 flex-1">
                                  <button onClick={() => handleDownload(attachment)} className="text-sm text-blue-600 hover:text-blue-800 truncate block max-w-full text-left">
                                    {attachment.original_filename}
                                  </button>
                                  <span className="text-xs text-gray-500">{formatFileSize(attachment.size)}</span>
                                </div>
                              </div>
                              <button onClick={() => deleteAttachment.mutate(attachment.id)} className="ml-2 p-1 text-gray-400 hover:text-red-500">
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                </svg>
                              </button>
                            </div>
                          ))}
                          {attachments.length === 0 && <p className="text-sm text-gray-400 italic">No attachments</p>}
                        </div>
                      </div>
                    )}

                    {/* Activity Panel */}
                    {activeTool === 'activity' && (
                      <div>
                        <h3 className="font-medium text-gray-900 mb-4">Activity</h3>
                        <div className="space-y-3">
                          {activities.map((activity) => (
                            <div key={activity.id} className="flex items-start gap-2 p-2 bg-white rounded border">
                              <div className="w-6 h-6 bg-gray-200 rounded-full flex items-center justify-center flex-shrink-0">
                                {activity.action === 'created' && <svg className="w-3 h-3 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" /></svg>}
                                {activity.action === 'moved' && <svg className="w-3 h-3 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" /></svg>}
                              </div>
                              <div className="flex-1 min-w-0">
                                <p className="text-xs text-gray-700">
                                  {activity.action === 'created' && 'Card created'}
                                  {activity.action === 'moved' && <>Moved to <span className="font-medium">{activity.to_column_name}</span></>}
                                  {activity.action === 'archived' && 'Card archived'}
                                  {activity.action === 'restored' && 'Card restored'}
                                </p>
                                <p className="text-xs text-gray-400">{formatRelativeTime(activity.timestamp)}</p>
                              </div>
                            </div>
                          ))}
                          {activities.length === 0 && <p className="text-sm text-gray-400 italic">No activity recorded</p>}
                        </div>
                      </div>
                    )}

                    {/* Move Panel */}
                    {activeTool === 'move' && (
                      <div>
                        <h3 className="font-medium text-gray-900 mb-4">Move to Column</h3>
                        <div className="space-y-2">
                          {boardData?.columns?.map((column) => (
                            <button
                              key={column.id}
                              onClick={() => moveCard.mutate(column.id)}
                              disabled={moveCard.isPending}
                              className="w-full text-left px-3 py-2 bg-white rounded border hover:bg-primary-50 hover:border-primary-300 transition-colors disabled:opacity-50"
                            >
                              <span className="text-sm font-medium text-gray-700">{column.name}</span>
                            </button>
                          ))}
                          {(!boardData?.columns || boardData.columns.length === 0) && (
                            <p className="text-sm text-gray-400 italic">No columns available</p>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="flex justify-between p-4 border-t bg-gray-50">
              <div className="flex items-center gap-2">
                {showDeleteConfirm ? (
                  <div className="flex items-center gap-2 bg-red-50 px-3 py-1 rounded-lg border border-red-200">
                    <span className="text-sm text-red-700">Delete?</span>
                    <button onClick={() => { deleteCard.mutate(); setShowDeleteConfirm(false) }} disabled={deleteCard.isPending} className="text-red-600 hover:text-red-700 text-sm font-medium">
                      {deleteCard.isPending ? '...' : 'Yes'}
                    </button>
                    <button onClick={() => setShowDeleteConfirm(false)} className="text-gray-600 hover:text-gray-700 text-sm">No</button>
                  </div>
                ) : (
                  <button onClick={() => setShowDeleteConfirm(true)} className="text-red-600 hover:text-red-700 text-sm">Delete</button>
                )}
                <span className="text-gray-300">|</span>
                <button onClick={() => archiveCard.mutate()} className="text-yellow-600 hover:text-yellow-700 text-sm" disabled={archiveCard.isPending}>
                  {archiveCard.isPending ? 'Archiving...' : 'Archive'}
                </button>
                <span className="text-gray-300">|</span>
                <button onClick={() => copyCard.mutate(false)} className="text-blue-600 hover:text-blue-700 text-sm" disabled={copyCard.isPending}>
                  {copyCard.isPending ? 'Copying...' : 'Copy'}
                </button>
              </div>
              <div className="flex space-x-2">
                <button onClick={() => { setShowEdit(false); setActiveTool(null); setIsEditingDescription(false) }} className="px-4 py-2 text-gray-600 hover:text-gray-800 text-sm">
                  Cancel
                </button>
                <button onClick={() => { updateCard.mutate(editData); setIsEditingDescription(false) }} className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 text-sm">
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
