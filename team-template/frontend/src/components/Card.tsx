import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useState, useMemo, useRef } from 'react'
import { useMutation, useQueryClient, useQuery } from '@tanstack/react-query'
import { cardsApi, attachmentsApi } from '../services/api'
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
  }
  boardId?: string
  isDragging?: boolean
}

const priorityColors: Record<string, string> = {
  high: 'bg-red-500',
  medium: 'bg-yellow-500',
  low: 'bg-green-500'
}

const labelColors = [
  'bg-red-200 text-red-800',
  'bg-blue-200 text-blue-800',
  'bg-green-200 text-green-800',
  'bg-purple-200 text-purple-800',
  'bg-yellow-200 text-yellow-800'
]

// Due date status helpers
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

export default function Card({ card, boardId, isDragging }: CardProps) {
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [showEdit, setShowEdit] = useState(false)
  const [isPreviewMode, setIsPreviewMode] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [editData, setEditData] = useState({
    title: card.title,
    description: card.description || ''
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

  // Attachments query and mutations
  const { data: attachments = [] } = useQuery<Attachment[]>({
    queryKey: ['attachments', card.id],
    queryFn: () => attachmentsApi.list(card.id).then(res => res.data),
    enabled: showEdit
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

  // Extract first URL from description for preview
  const previewUrl = useMemo(() => {
    if (!card.description) return null
    return extractFirstUrl(card.description)
  }, [card.description])

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

        {/* Link Preview */}
        {previewUrl && <LinkPreview url={previewUrl} compact />}

        {card.labels && card.labels.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-2">
            {card.labels.map((label, i) => (
              <span
                key={label}
                className={`px-2 py-0.5 text-xs rounded ${labelColors[i % labelColors.length]}`}
              >
                {label}
              </span>
            ))}
          </div>
        )}

        {/* Checklist and Attachment indicators */}
        {(card.checklist?.length || card.attachment_count) ? (
          <div className="flex items-center space-x-3 mt-2 text-xs text-gray-500">
            {card.checklist && card.checklist.length > 0 && (
              <div className="flex items-center space-x-1">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
                </svg>
                <span>
                  {card.checklist.filter(i => i.completed).length}/{card.checklist.length}
                </span>
              </div>
            )}
            {card.attachment_count ? (
              <div className="flex items-center space-x-1">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                </svg>
                <span>{card.attachment_count}</span>
              </div>
            ) : null}
          </div>
        ) : null}

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

      {showEdit && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-medium mb-4">Edit Card</h2>
            <div className="space-y-4">
              <input
                type="text"
                value={editData.title}
                onChange={e => setEditData({ ...editData, title: e.target.value })}
                className="w-full px-3 py-2 border rounded-lg"
              />

              {/* Description with Preview Toggle */}
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
                    rows={6}
                  />
                )}
                <p className="mt-1 text-xs text-gray-500">
                  Supports Markdown: **bold**, *italic*, `code`, ```code blocks```, - lists, [links](url)
                </p>
              </div>

              {/* Checklist */}
              <div className="border-t pt-4">
                <Checklist
                  cardId={card.id}
                  boardId={boardId}
                  items={card.checklist || []}
                />
              </div>

              {/* Attachments */}
              <div className="border-t pt-4">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-medium text-gray-700">Attachments</h3>
                  <input
                    type="file"
                    ref={fileInputRef}
                    onChange={handleFileSelect}
                    className="hidden"
                  />
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
                  <div className="mb-3 p-2 bg-red-50 text-red-600 text-sm rounded">
                    {uploadError}
                  </div>
                )}

                {attachments.length > 0 ? (
                  <div className="space-y-2">
                    {attachments.map((attachment) => (
                      <div
                        key={attachment.id}
                        className="flex items-center justify-between p-2 bg-gray-50 rounded hover:bg-gray-100"
                      >
                        <div className="flex items-center space-x-2 min-w-0 flex-1">
                          <span className="text-lg">{getFileIcon(attachment.content_type)}</span>
                          <div className="min-w-0 flex-1">
                            <button
                              onClick={() => handleDownload(attachment)}
                              className="text-sm text-blue-600 hover:text-blue-800 truncate block max-w-full text-left"
                              title={attachment.original_filename}
                            >
                              {attachment.original_filename}
                            </button>
                            <span className="text-xs text-gray-500">
                              {formatFileSize(attachment.size)}
                            </span>
                          </div>
                        </div>
                        <button
                          onClick={() => deleteAttachment.mutate(attachment.id)}
                          disabled={deleteAttachment.isPending}
                          className="ml-2 p-1 text-gray-400 hover:text-red-500"
                          title="Delete attachment"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-gray-400 italic">No attachments yet</p>
                )}
                <p className="mt-2 text-xs text-gray-400">
                  Max 10MB. Allowed: images, PDFs, documents, text files, archives
                </p>
              </div>

              <div className="flex justify-between pt-2 border-t">
                <button
                  onClick={() => deleteCard.mutate()}
                  className="text-red-600 hover:text-red-700"
                >
                  Delete
                </button>
                <div className="flex space-x-2">
                  <button
                    onClick={() => {
                      setShowEdit(false)
                      setIsPreviewMode(false)
                    }}
                    className="px-4 py-2 text-gray-600 hover:text-gray-800"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => updateCard.mutate(editData)}
                    className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700"
                  >
                    Save
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
