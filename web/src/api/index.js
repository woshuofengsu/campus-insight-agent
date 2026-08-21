// API 封装：axios 实例 + token 拦截器
import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '/api/web',
  timeout: 20000,
})

// 请求带 token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('ci_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 统一响应解包 + 401 跳登录
api.interceptors.response.use(
  (res) => {
    // Blob（文件下载）直接返回，不做 JSON 解包
    if (res.data instanceof Blob) return res.data
    const body = res.data
    if (body && body.success === false) {
      return Promise.reject(new Error(body.error || body.message || '请求失败'))
    }
    return body ? body.data : null
  },
  (err) => {
    if (err.response && err.response.status === 401) {
      localStorage.removeItem('ci_token')
      localStorage.removeItem('ci_user')
      if (!location.pathname.startsWith('/login')) location.href = '/login'
    }
    return Promise.reject(err.response?.data?.error || err.message || '网络错误')
  },
)

// 认证
export const auth = {
  login: (username, password) => api.post('/auth/login', { username, password }),
  demo: (role) => api.post('/auth/demo', { role }),
  me: () => api.get('/auth/me'),
}

// 报修
export const issues = {
  list: (params) => api.get('/issues', { params }),
  detail: (id) => api.get(`/issues/${id}`),
  create: (data) => api.post('/issues', data),
  action: (id, data) => api.post(`/issues/${id}/action`, data),
  drafts: () => api.get('/issues/drafts'),
  saveDraft: (data) => api.post('/issues/drafts', data),
  deleteDraft: (id) => api.delete(`/issues/drafts/${id}`),
  safetyReminders: (params) => api.get('/issues/safety-reminders', { params }),
}

// 提案
export const proposals = {
  list: (params) => api.get('/proposals', { params }),
  detail: (id) => api.get(`/proposals/${id}`),
  create: (data) => api.post('/proposals', data),
  vote: (id, score) => api.post(`/proposals/${id}/vote`, { score }),
  action: (id, data) => api.post(`/proposals/${id}/action`, data),
  comments: (id) => api.get(`/proposals/${id}/comments`),
  addComment: (id, data) => api.post(`/proposals/${id}/comments`, data),
  drafts: () => api.get('/proposals/drafts'),
  saveDraft: (data) => api.post('/proposals/drafts', data),
  deleteDraft: (id) => api.delete(`/proposals/drafts/${id}`),
}

// 通知
export const notices = {
  list: (params) => api.get('/notices', { params }),
  manage: (params) => api.get('/notices/manage', { params }),
  detail: (id) => api.get(`/notices/${id}`),
  create: (data) => api.post('/notices', data),
  action: (id, data) => api.post(`/notices/${id}/action`, data),
}

// 天气
export const weather = {
  current: () => api.get('/weather/current'),
  alerts: () => api.get('/weather/alerts'),
  tasks: (params) => api.get('/weather/tasks', { params }),
  confirmTask: (id, data) => api.post(`/weather/check-task/${id}/confirm`, data),
  history: (params) => api.get('/weather/history', { params }),
  overview: (params) => api.get('/weather/overview', { params }),
  exceptionLogs: (params) => api.get('/weather/exception-logs', { params }),
}

// 政策
export const qa = {
  ask: (data) => api.post('/qa/ask', data),
  transfer: (qid, question) => api.post(`/qa/${qid}/transfer`, { question }),
  questions: (params) => api.get('/qa/questions', { params }),
  highFreq: () => api.get('/qa/high-freq'),
  stats: (params) => api.get('/qa/stats', { params }),
  getThreshold: () => api.get('/qa/threshold'),
  setThreshold: (threshold) => api.post('/qa/threshold', { threshold }),
  reply: (qid, data) => api.post(`/qa/questions/${qid}/reply`, data),
  feedback: (qid, data) => api.post(`/qa/questions/${qid}/feedback`, data),
  deleteQuestion: (qid) => api.delete(`/qa/questions/${qid}`),
}

export const knowledge = {
  list: (params) => api.get('/knowledge', { params }),
  create: (data) => api.post('/knowledge', data),
  action: (id, data) => api.post(`/knowledge/${id}/action`, data),
  versions: (id) => api.get(`/knowledge/${id}/versions`),
  newVersion: (id, data) => api.post(`/knowledge/${id}/new-version`, data),
}

// 健康
export const health = {
  articles: (params) => api.get('/health/articles', { params }),
  articleDetail: (id) => api.get(`/health/articles/${id}`),
  createArticle: (data) => api.post('/health/articles', data),
  articleAction: (id, data) => api.post(`/health/articles/${id}/action`, data),
  consults: (params) => api.get('/health/consults', { params }),
  consultDetail: (id) => api.get(`/health/consults/${id}`),
  createConsult: (data) => api.post('/health/consults', data),
  replyConsult: (id, data) => api.post(`/health/consults/${id}/reply`, data),
  toggleConsult: (id, data) => api.post(`/health/consults/${id}/toggle`, data),
  feedbackConsult: (id, data) => api.post(`/health/consults/${id}/feedback`, data),
  unread: () => api.get('/health/unread-reply-count'),
  linkageRecords: (params) => api.get('/health/linkage/records', { params }),
  linkageActive: (params) => api.get('/health/linkage/active', { params }),
  linkageThresholds: () => api.get('/health/linkage/thresholds'),
  setLinkageThresholds: (data) => api.post('/health/linkage/thresholds', data),
  linkageAction: (key, data) => api.post(`/health/linkage/${key}/action`, data),
}

// 消息中心
export const messages = {
  list: (params) => api.get('/messages', { params }),
  read: (id) => api.post(`/messages/${id}/read`),
}

// 老年端
export const elderly = {
  home: () => api.get('/elderly/home'),
  voiceReport: (data) => api.post('/elderly/voice-report', data),
  medications: () => api.get('/elderly/medications'),
  createMedication: (data) => api.post('/elderly/medications', data),
  toggleMedication: (id, action) => api.post(`/elderly/medications/${id}/toggle`, { action }),
  modifyMedication: (id, data) => api.post(`/elderly/medications/${id}/modify`, data),
  emergency: () => api.post('/elderly/emergency'),
  emergencyStatus: () => api.get('/elderly/emergency/status'),
  contactCall: (data) => api.post('/elderly/contact', data),
  contacts: () => api.get('/elderly/emergency-contacts'),
  addContact: (data) => api.post('/elderly/emergency-contacts', data),
  deleteContact: (id) => api.post(`/elderly/emergency-contacts/${id}/delete`),
  // 老年关怀管理（负责人）
  manageMeds: (params) => api.get('/elderly/manage/medications', { params }),
  auditMedication: (id, data) => api.post(`/elderly/manage/medications/${id}/audit`, data),
  manageContacts: (params) => api.get('/elderly/manage/contacts', { params }),
  auditContact: (id, data) => api.post(`/elderly/manage/contacts/${id}/audit`, data),
  manageSos: (params) => api.get('/elderly/manage/sos', { params }),
  sosAction: (id, data) => api.post(`/elderly/emergency/${id}/action`, data),
}

// 导出
export const exportApi = {
  issues: () => api.get('/export/issues', { responseType: 'blob' }),
  proposals: () => api.get('/export/proposals', { responseType: 'blob' }),
  notices: () => api.get('/export/notices', { responseType: 'blob' }),
  knowledge: () => api.get('/export/knowledge', { responseType: 'blob' }),
  healthContents: () => api.get('/export/health-contents', { responseType: 'blob' }),
  healthConsults: () => api.get('/export/health-consults', { responseType: 'blob' }),
  weatherTasks: () => api.get('/export/weather-tasks', { responseType: 'blob' }),
}

// 上传
export const upload = (files, folder = 'web') => {
  const fd = new FormData()
  files.forEach((f) => fd.append('files', f))
  return api.post(`/upload?folder=${folder}`, fd, { headers: { 'Content-Type': 'multipart/form-data' } })
}

export default api
