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
    api.post(`/cards/${cardId}/checklist/${itemId}/toggle`)
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

export default api
