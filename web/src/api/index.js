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
}

// 通知
export const notices = {
  list: (params) => api.get('/notices', { params }),
  manage: (params) => api.get('/notices/manage', { params }),
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
}

// 政策
export const qa = {
  ask: (data) => api.post('/qa/ask', data),
  transfer: (qid, question) => api.post(`/qa/${qid}/transfer`, { question }),
  questions: (params) => api.get('/qa/questions', { params }),
  highFreq: () => api.get('/qa/high-freq'),
  stats: () => api.get('/qa/stats'),
  getThreshold: () => api.get('/qa/threshold'),
  setThreshold: (threshold) => api.post('/qa/threshold', { threshold }),
}

export const knowledge = {
  list: (params) => api.get('/knowledge', { params }),
}

// 健康
export const health = {
  articles: (params) => api.get('/health/articles', { params }),
  consults: (params) => api.get('/health/consults', { params }),
  createConsult: (data) => api.post('/health/consults', data),
  replyConsult: (id, data) => api.post(`/health/consults/${id}/reply`, data),
  toggleConsult: (id, data) => api.post(`/health/consults/${id}/toggle`, data),
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
  emergency: () => api.post('/elderly/emergency'),
  emergencyStatus: () => api.get('/elderly/emergency/status'),
  contacts: () => api.get('/elderly/emergency-contacts'),
  addContact: (data) => api.post('/elderly/emergency-contacts', data),
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
}

// 上传
export const upload = (files, folder = 'web') => {
  const fd = new FormData()
  files.forEach((f) => fd.append('files', f))
  return api.post(`/upload?folder=${folder}`, fd, { headers: { 'Content-Type': 'multipart/form-data' } })
}

export default api
