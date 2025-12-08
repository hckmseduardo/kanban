import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || '/api'

const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json'
  }
})

// Add auth token to requests
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

export const boardsApi = {
  list: () => api.get('/boards'),
  get: (id: string) => api.get(`/boards/${id}`),
  create: (data: { name: string; description?: string }) => api.post('/boards', data),
  update: (id: string, data: any) => api.patch(`/boards/${id}`, data),
  delete: (id: string) => api.delete(`/boards/${id}`)
}

export const columnsApi = {
  create: (data: { board_id: string; name: string; position: number }) => api.post('/columns', data),
  update: (id: string, data: any) => api.patch(`/columns/${id}`, data),
  delete: (id: string) => api.delete(`/columns/${id}`)
}

export const cardsApi = {
  create: (data: any) => api.post('/cards', data),
  get: (id: string) => api.get(`/cards/${id}`),
  update: (id: string, data: any) => api.patch(`/cards/${id}`, data),
  delete: (id: string) => api.delete(`/cards/${id}`),
  move: (id: string, columnId: string, position: number) =>
    api.post(`/cards/${id}/move`, null, { params: { column_id: columnId, position } }),
  // Checklist operations
  addChecklistItem: (cardId: string, text: string) =>
    api.post(`/cards/${cardId}/checklist`, { text }),
  updateChecklistItem: (cardId: string, itemId: string, data: { text?: string; completed?: boolean }) =>
    api.patch(`/cards/${cardId}/checklist/${itemId}`, data),
  deleteChecklistItem: (cardId: string, itemId: string) =>
    api.delete(`/cards/${cardId}/checklist/${itemId}`),
  toggleChecklistItem: (cardId: string, itemId: string) =>
    api.post(`/cards/${cardId}/checklist/${itemId}/toggle`),
  // Archive operations
  archive: (cardId: string) => api.post(`/cards/${cardId}/archive`),
  restore: (cardId: string, columnId?: string) =>
    api.post(`/cards/${cardId}/restore`, null, { params: columnId ? { column_id: columnId } : {} }),
  // Copy operation
  copy: (cardId: string, columnId?: string, includeComments?: boolean) =>
    api.post(`/cards/${cardId}/copy`, null, {
      params: { ...(columnId && { column_id: columnId }), include_comments: includeComments || false }
    }),
  // Bulk operations
  bulkMove: (cardIds: string[], columnId: string) =>
    api.post('/cards/bulk/move', { card_ids: cardIds, column_id: columnId }),
  bulkArchive: (cardIds: string[]) =>
    api.post('/cards/bulk/archive', { card_ids: cardIds }),
  bulkDelete: (cardIds: string[]) =>
    api.post('/cards/bulk/delete', { card_ids: cardIds })
}

export const webhooksApi = {
  list: () => api.get('/webhooks'),
  create: (data: any) => api.post('/webhooks', data),
  update: (id: string, data: any) => api.patch(`/webhooks/${id}`, data),
  delete: (id: string) => api.delete(`/webhooks/${id}`),
  test: (id: string) => api.post(`/webhooks/${id}/test`)
}

export const utilsApi = {
  getLinkPreview: (url: string) => api.get('/utils/link-preview', { params: { url } }),
  extractUrls: (text: string) => api.post('/utils/extract-urls', null, { params: { text } })
}

export const reportsApi = {
  getCycleTime: (boardId: string, params?: { from_date?: string; to_date?: string; group_by?: string }) =>
    api.get(`/boards/${boardId}/reports/cycle-time`, { params }),
  getLeadTime: (boardId: string, params?: { from_date?: string; to_date?: string; group_by?: string }) =>
    api.get(`/boards/${boardId}/reports/lead-time`, { params }),
  getThroughput: (boardId: string, params?: { from_date?: string; to_date?: string; group_by?: string }) =>
    api.get(`/boards/${boardId}/reports/throughput`, { params }),
  getSummary: (boardId: string) => api.get(`/boards/${boardId}/reports/summary`)
}

export const attachmentsApi = {
  list: (cardId: string) => api.get(`/cards/${cardId}/attachments`),
  upload: (cardId: string, file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post(`/cards/${cardId}/attachments`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },
  download: (cardId: string, attachmentId: string) =>
    api.get(`/cards/${cardId}/attachments/${attachmentId}`, { responseType: 'blob' }),
  delete: (cardId: string, attachmentId: string) =>
    api.delete(`/cards/${cardId}/attachments/${attachmentId}`)
}

export const commentsApi = {
  list: (cardId: string) => api.get(`/cards/${cardId}/comments`),
  create: (cardId: string, data: { text: string; author_name?: string }) =>
    api.post(`/cards/${cardId}/comments`, data),
  update: (cardId: string, commentId: string, data: { text: string }) =>
    api.patch(`/cards/${cardId}/comments/${commentId}`, data),
  delete: (cardId: string, commentId: string) =>
    api.delete(`/cards/${cardId}/comments/${commentId}`)
}

export const labelsApi = {
  colors: () => api.get('/labels/colors'),
  list: (boardId: string) => api.get(`/labels/boards/${boardId}/labels`),
  create: (boardId: string, data: { name: string; color: string }) =>
    api.post(`/labels/boards/${boardId}/labels`, data),
  update: (boardId: string, labelId: string, data: { name?: string; color?: string }) =>
    api.patch(`/labels/boards/${boardId}/labels/${labelId}`, data),
  delete: (boardId: string, labelId: string) =>
    api.delete(`/labels/boards/${boardId}/labels/${labelId}`)
}

export const membersApi = {
  list: () => api.get('/members'),
  get: (id: string) => api.get(`/members/${id}`)
}

export const activityApi = {
  getBoardActivity: (boardId: string, params?: { limit?: number; offset?: number; card_id?: string }) =>
    api.get(`/boards/${boardId}/activity`, { params }),
  getCardActivity: (cardId: string, limit?: number) =>
    api.get(`/cards/${cardId}/activity`, { params: { limit } })
}

export const exportApi = {
  exportBoard: (boardId: string, includeArchived?: boolean) =>
    api.get(`/boards/${boardId}/export`, {
      params: { include_archived: includeArchived || false },
      responseType: 'blob'
    }),
  importBoard: (data: any) => api.post('/boards/import', data)
}

export const templatesApi = {
  list: () => api.get('/templates'),
  get: (id: string) => api.get(`/templates/${id}`),
  create: (data: { name: string; description?: string; columns?: any[]; labels?: any[] }) =>
    api.post('/templates', data),
  createFromBoard: (boardId: string, name: string, description?: string) =>
    api.post(`/templates/from-board/${boardId}`, null, { params: { name, description } }),
  apply: (templateId: string, boardName: string, boardDescription?: string) =>
    api.post(`/templates/${templateId}/apply`, null, { params: { board_name: boardName, board_description: boardDescription } }),
  delete: (id: string) => api.delete(`/templates/${id}`)
}

export const remindersApi = {
  getBoardReminders: (boardId: string, params?: { days_ahead?: number; include_overdue?: boolean }) =>
    api.get(`/boards/${boardId}/reminders`, { params }),
  getAllReminders: (params?: { days_ahead?: number; include_overdue?: boolean }) =>
    api.get('/reminders/all', { params }),
  getSummary: () => api.get('/reminders/summary')
}

export const dependenciesApi = {
  getCardDependencies: (cardId: string) => api.get(`/cards/${cardId}/dependencies`),
  addBlocker: (cardId: string, blockerId: string) =>
    api.post(`/cards/${cardId}/blockers/${blockerId}`),
  removeBlocker: (cardId: string, blockerId: string) =>
    api.delete(`/cards/${cardId}/blockers/${blockerId}`),
  getBoardDependencyGraph: (boardId: string) => api.get(`/boards/${boardId}/dependency-graph`)
}

export const timeTrackingApi = {
  getEntries: (cardId: string) => api.get(`/cards/${cardId}/time-entries`),
  addEntry: (cardId: string, data: { minutes: number; description?: string; date?: string }) =>
    api.post(`/cards/${cardId}/time-entries`, data),
  deleteEntry: (cardId: string, entryId: string) =>
    api.delete(`/cards/${cardId}/time-entries/${entryId}`),
  setEstimate: (cardId: string, estimatedMinutes: number) =>
    api.put(`/cards/${cardId}/time-estimate`, { estimated_minutes: estimatedMinutes }),
  clearEstimate: (cardId: string) => api.delete(`/cards/${cardId}/time-estimate`),
  getBoardReport: (boardId: string) => api.get(`/boards/${boardId}/time-report`)
}

export const customFieldsApi = {
  // Board field definitions
  listFields: (boardId: string) => api.get(`/boards/${boardId}/fields`),
  createField: (boardId: string, data: {
    name: string
    field_type: 'text' | 'number' | 'date' | 'select' | 'checkbox'
    description?: string
    options?: { value: string; label: string; color?: string }[]
    required?: boolean
  }) => api.post(`/boards/${boardId}/fields`, data),
  updateField: (boardId: string, fieldId: string, data: {
    name?: string
    description?: string
    options?: { value: string; label: string; color?: string }[]
    required?: boolean
  }) => api.patch(`/boards/${boardId}/fields/${fieldId}`, data),
  deleteField: (boardId: string, fieldId: string) =>
    api.delete(`/boards/${boardId}/fields/${fieldId}`),
  // Card field values
  getCardFields: (cardId: string) => api.get(`/cards/${cardId}/fields`),
  setFieldValue: (cardId: string, fieldId: string, value: any) =>
    api.put(`/cards/${cardId}/fields/${fieldId}`, { value }),
  clearFieldValue: (cardId: string, fieldId: string) =>
    api.delete(`/cards/${cardId}/fields/${fieldId}`)
}

export const coversApi = {
  getColors: () => api.get('/covers/colors'),
  getCover: (cardId: string) => api.get(`/cards/${cardId}/cover`),
  setCover: (cardId: string, data: {
    type: 'image' | 'color' | 'url' | 'attachment'
    value: string
  }) => api.put(`/cards/${cardId}/cover`, data),
  removeCover: (cardId: string) => api.delete(`/cards/${cardId}/cover`),
  setCoverFromFirstAttachment: (cardId: string) =>
    api.post(`/cards/${cardId}/cover/from-first-attachment`)
}

export const searchApi = {
  search: (params: {
    q?: string
    board_id?: string
    labels?: string
    priority?: string
    assignee_id?: string
    due_from?: string
    due_to?: string
    has_due_date?: boolean
    is_overdue?: boolean
    is_blocked?: boolean
    has_attachments?: boolean
    include_archived?: boolean
    limit?: number
    offset?: number
  }) => api.get('/search', { params }),
  suggestions: (q: string) => api.get('/search/suggestions', { params: { q } }),
  filterOptions: (boardId?: string) => api.get('/filters/options', { params: { board_id: boardId } })
}

export const subtasksApi = {
  list: (cardId: string) => api.get(`/cards/${cardId}/subtasks`),
  create: (cardId: string, data: { title: string; description?: string; assignee_id?: string; due_date?: string }) =>
    api.post(`/cards/${cardId}/subtasks`, data),
  update: (cardId: string, subtaskId: string, data: { title?: string; completed?: boolean; position?: number }) =>
    api.patch(`/cards/${cardId}/subtasks/${subtaskId}`, data),
  delete: (cardId: string, subtaskId: string) => api.delete(`/cards/${cardId}/subtasks/${subtaskId}`),
  toggle: (cardId: string, subtaskId: string) => api.post(`/cards/${cardId}/subtasks/${subtaskId}/toggle`),
  convertToCard: (cardId: string, subtaskId: string, columnId?: string) =>
    api.post(`/cards/${cardId}/subtasks/convert/${subtaskId}`, null, { params: { column_id: columnId } })
}

export const cardLinksApi = {
  list: (cardId: string) => api.get(`/cards/${cardId}/links`),
  create: (cardId: string, data: { target_card_id: string; link_type?: string }) =>
    api.post(`/cards/${cardId}/links`, data),
  delete: (cardId: string, linkId: string) => api.delete(`/cards/${cardId}/links/${linkId}`),
  suggestions: (cardId: string, q?: string) => api.get(`/cards/${cardId}/links/suggestions`, { params: { q } })
}

export const notificationsApi = {
  list: (userId: string, params?: { unread_only?: boolean; limit?: number; offset?: number }) =>
    api.get('/notifications', { params: { user_id: userId, ...params } }),
  markRead: (notificationId: string) => api.post(`/notifications/${notificationId}/read`),
  markAllRead: (userId: string) => api.post('/notifications/read-all', null, { params: { user_id: userId } }),
  delete: (notificationId: string) => api.delete(`/notifications/${notificationId}`),
  clear: (userId: string, readOnly?: boolean) =>
    api.delete('/notifications', { params: { user_id: userId, read_only: readOnly } }),
  getPreferences: (userId: string) => api.get('/notifications/preferences', { params: { user_id: userId } }),
  updatePreferences: (userId: string, prefs: object) =>
    api.put('/notifications/preferences', prefs, { params: { user_id: userId } })
}

export const automationsApi = {
  list: (boardId: string) => api.get(`/boards/${boardId}/automations`),
  get: (boardId: string, automationId: string) => api.get(`/boards/${boardId}/automations/${automationId}`),
  create: (boardId: string, data: object) => api.post(`/boards/${boardId}/automations`, data),
  update: (boardId: string, automationId: string, data: object) =>
    api.patch(`/boards/${boardId}/automations/${automationId}`, data),
  delete: (boardId: string, automationId: string) => api.delete(`/boards/${boardId}/automations/${automationId}`),
  toggle: (boardId: string, automationId: string) =>
    api.post(`/boards/${boardId}/automations/${automationId}/toggle`),
  test: (boardId: string, automationId: string, cardId: string) =>
    api.post(`/boards/${boardId}/automations/${automationId}/test`, null, { params: { card_id: cardId } }),
  getTriggers: () => api.get('/automations/triggers'),
  getActions: () => api.get('/automations/actions')
}

export const analyticsApi = {
  overview: (boardId: string) => api.get(`/boards/${boardId}/analytics/overview`),
  burndown: (boardId: string, days?: number) => api.get(`/boards/${boardId}/analytics/burndown`, { params: { days } }),
  cumulativeFlow: (boardId: string, days?: number) =>
    api.get(`/boards/${boardId}/analytics/cumulative-flow`, { params: { days } }),
  velocity: (boardId: string, weeks?: number) => api.get(`/boards/${boardId}/analytics/velocity`, { params: { weeks } }),
  wipAging: (boardId: string) => api.get(`/boards/${boardId}/analytics/wip-aging`),
  labelDistribution: (boardId: string) => api.get(`/boards/${boardId}/analytics/labels`),
  assigneeWorkload: (boardId: string) => api.get(`/boards/${boardId}/analytics/assignees`)
}

export const cardTemplatesApi = {
  list: (boardId: string) => api.get(`/boards/${boardId}/card-templates`),
  get: (boardId: string, templateId: string) => api.get(`/boards/${boardId}/card-templates/${templateId}`),
  create: (boardId: string, data: object) => api.post(`/boards/${boardId}/card-templates`, data),
  update: (boardId: string, templateId: string, data: object) =>
    api.patch(`/boards/${boardId}/card-templates/${templateId}`, data),
  delete: (boardId: string, templateId: string) => api.delete(`/boards/${boardId}/card-templates/${templateId}`),
  apply: (boardId: string, templateId: string, columnId: string, titleOverride?: string) =>
    api.post(`/boards/${boardId}/card-templates/${templateId}/apply`, null, {
      params: { column_id: columnId, title_override: titleOverride }
    }),
  createFromCard: (boardId: string, cardId: string, name: string, description?: string) =>
    api.post(`/boards/${boardId}/card-templates/from-card/${cardId}`, null, { params: { name, description } })
}

export const recurringCardsApi = {
  list: (boardId: string) => api.get(`/boards/${boardId}/recurring-cards`),
  get: (boardId: string, recurringId: string) => api.get(`/boards/${boardId}/recurring-cards/${recurringId}`),
  create: (boardId: string, data: object) => api.post(`/boards/${boardId}/recurring-cards`, data),
  update: (boardId: string, recurringId: string, data: object) =>
    api.patch(`/boards/${boardId}/recurring-cards/${recurringId}`, data),
  delete: (boardId: string, recurringId: string) => api.delete(`/boards/${boardId}/recurring-cards/${recurringId}`),
  toggle: (boardId: string, recurringId: string) =>
    api.post(`/boards/${boardId}/recurring-cards/${recurringId}/toggle`),
  runNow: (boardId: string, recurringId: string) =>
    api.post(`/boards/${boardId}/recurring-cards/${recurringId}/run-now`),
  getDue: () => api.get('/recurring-cards/due')
}

export const permissionsApi = {
  listMembers: (boardId: string) => api.get(`/boards/${boardId}/members`),
  addMember: (boardId: string, data: { user_id: string; role: string }) =>
    api.post(`/boards/${boardId}/members`, data),
  updateMember: (boardId: string, memberId: string, data: { role: string }) =>
    api.patch(`/boards/${boardId}/members/${memberId}`, data),
  removeMember: (boardId: string, memberId: string) => api.delete(`/boards/${boardId}/members/${memberId}`),
  getUserPermissions: (boardId: string, userId: string) =>
    api.get(`/boards/${boardId}/members/${userId}/permissions`),
  transferOwnership: (boardId: string, newOwnerId: string) =>
    api.post(`/boards/${boardId}/transfer-ownership`, null, { params: { new_owner_id: newOwnerId } }),
  getUserBoards: (userId: string) => api.get(`/users/${userId}/boards`),
  listRoles: () => api.get('/permissions/roles')
}

export const teamApi = {
  // Team Members
  listMembers: (params?: { include_inactive?: boolean; role?: string }) =>
    api.get('/team/members', { params }),
  getMember: (memberId: string) => api.get(`/team/members/${memberId}`),
  addMember: (data: { email: string; name?: string; role?: string }) =>
    api.post('/team/members', data),
  updateMember: (memberId: string, data: { name?: string; role?: string; is_active?: boolean }) =>
    api.patch(`/team/members/${memberId}`, data),
  removeMember: (memberId: string, softDelete?: boolean) =>
    api.delete(`/team/members/${memberId}`, { params: { soft_delete: softDelete } }),

  // Invitations
  listInvitations: (status?: string) => api.get('/team/invitations', { params: { status } }),
  getInvitation: (token: string) => api.get('/team/invitations/by-token', { params: { token } }),
  createInvitation: (data: { email: string; role?: string; message?: string }, invitedBy?: string) =>
    api.post('/team/invitations', data, { params: { invited_by: invitedBy } }),
  resendInvitation: (invitationId: string) => api.post(`/team/invitations/${invitationId}/resend`),
  cancelInvitation: (invitationId: string) => api.delete(`/team/invitations/${invitationId}`),
  acceptInvitation: (token: string, userId?: string, userName?: string, userEmail?: string) =>
    api.post('/team/join', null, { params: { token, user_id: userId, user_name: userName, user_email: userEmail } }),

  // SSO Token exchange
  exchangeSSOToken: (ssoToken: string) => api.post('/auth/exchange', null, { params: { token: ssoToken } }),

  // Team Settings
  getSettings: () => api.get('/team/settings'),
  updateSettings: (data: { name?: string; allow_member_invites?: boolean; default_board_visibility?: string }) =>
    api.patch('/team/settings', null, { params: data })
}

export default api
