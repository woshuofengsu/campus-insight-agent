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
    // 注意：必须 reject 一个 **Error**（而不是字符串）：页面里普遍写的是
    // `catch (e) { message.error(e.message) }`，如果这里 reject 字符串，
    // `e.message` 就是 undefined —— 结果"接口 500 / 断网"时**什么都不提示**，
    // 页面还常常显示"暂无数据"，等于把失败说成了"没有数据"（实测踩到：
    // 老人端「我的报修」接口 500 时显示"还没有报修记录"）。
    const msg = err.response?.data?.error || err.message || '网络错误'
    const e2 = new Error(msg)
    e2.status = err.response?.status
    return Promise.reject(e2)
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
  // 工单知识（v52 沉淀）：同类处置画像 + 单条工单的字段来源
  knowledge: (params) => api.get('/issues/knowledge', { params }),
  // 人工修正对照清单（第 7 阶段）：系统建议分类 vs 人工最终分类（含覆盖率）
  categoryCorrections: (params) => api.get('/issues/category-corrections', { params }),
  fieldSources: (id) => api.get(`/issues/${id}/field-sources`),
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
  // 升级通知名单（超时后第 2 层通知谁）：按社区配置，候选人只来自本社区负责人
  seniorManagers: () => api.get('/weather/senior-managers'),
  setSeniorManagers: (ids) => api.post('/weather/senior-managers', { ids }),
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
  // 报修契约（v3 卡1）：先出结构化摘要（缺什么就说缺什么）→ 老人确认后再提交。
  // answers 是老人对追问的**补充值**（重查时上行，服务端照样要判合不合用）——
  // 不带它的话"缺位置→补充→再看"永远还是缺，提交按钮出不来。
  reportDraft: (text, answers = {}) => api.post('/elderly/report/draft', { text, ...answers }),
  reportDraftCurrent: () => api.get('/elderly/report/draft/current'),
  saveReportDraft: (data) => api.post('/elderly/report/draft/save', data),
  clearReportDraft: () => api.delete('/elderly/report/draft/current'),
  reportSubmit: (data) => api.post('/elderly/report/submit', data),
  // 「我刚才到底提交成功了吗」：断网/超时后按幂等 token 查真实结果（§6-I5）
  reportStatus: (token) => api.get('/elderly/report/status', { params: { token } }),
  // 老人端「我的报修」：服务端附上**老人看得懂的进度**（现在到哪步/下一步谁做/还要多久/是否超时）
  orders: (params) => api.get('/elderly/orders', { params }),
  medications: () => api.get('/elderly/medications'),
  createMedication: (data) => api.post('/elderly/medications', data),
  toggleMedication: (id, action) => api.post(`/elderly/medications/${id}/toggle`, { action }),
  modifyMedication: (id, data) => api.post(`/elderly/medications/${id}/modify`, data),
  emergency: () => api.post('/elderly/emergency'),
  emergencyStatus: () => api.get('/elderly/emergency/status'),
  contactCall: (data) => api.post('/elderly/contact', data),
  // 诚实呼叫第二步（v3 复核 §6-B2）：把**手机上真实发生的事**回填
  // （dialer_opened=已打开拨号盘 / cancelled=取消 / failed=失败；没有 connected——网页拿不到通话结果）
  contactOutcome: (callId, stage) => api.post(`/elderly/contact/${callId}/outcome`, { stage }),
  contacts: () => api.get('/elderly/emergency-contacts'),
  addContact: (data) => api.post('/elderly/emergency-contacts', data),
  deleteContact: (id) => api.post(`/elderly/emergency-contacts/${id}/delete`),
  // 老年关怀管理（负责人）
  manageMeds: (params) => api.get('/elderly/manage/medications', { params }),
  auditMedication: (id, data) => api.post(`/elderly/manage/medications/${id}/audit`, data),
  manageContacts: (params) => api.get('/elderly/manage/contacts', { params }),
  auditContact: (id, data) => api.post(`/elderly/manage/contacts/${id}/audit`, data),
  manageSos: (params) => api.get('/elderly/manage/sos', { params }),
  // P3 安全闭环：久未互动老人（后端 /elderly/manage/inactive 早就有，前端此前没有方法 → 孤儿接口）
  manageInactive: (params) => api.get('/elderly/manage/inactive', { params }),
  sosAction: (id, data) => api.post(`/elderly/emergency/${id}/action`, data),
  // P4 健康记录（血压 / 血糖）
  vitals: (params) => api.get('/elderly/vitals', { params }),
  addVital: (data) => api.post('/elderly/vitals', data),
  vitalsSummary: (params) => api.get('/elderly/vitals/summary', { params }),
  manageVitals: (params) => api.get('/elderly/manage/vitals', { params }),
  manageElders: () => api.get('/elderly/manage/elders'),
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

// Agent 统一入口
export const agent = {
  chat: (data) => api.post('/agent/chat', data),
  elderlyChat: (data) => api.post('/agent/elderly/chat', data),
  history: () => api.get('/agent/history'),
  deleteHistory: (id) => api.delete(`/agent/history/${id}`),
  clearHistory: () => api.delete('/agent/history'),
  logs: (params) => api.get('/agent/logs', { params }),
  // 我没提交完的草稿（只返回自己的）：用于「上次有一条没提交的，要继续吗？」
  drafts: () => api.get('/agent/drafts'),
  handoffs: (params) => api.get('/agent/handoffs', { params }),
  // 卡11 / v3 卡7：人工处理包流转（claim 领取 / ask 补问 / reply 回复 / close 关闭）
  handoffAction: (id, data) => api.post(`/agent/handoffs/${id}/action`, data),
  resolveHandoff: (id) => api.post(`/agent/handoffs/${id}/resolve`),
  llmUsage: (params) => api.get('/agent/llm-usage', { params }),
  selfResolution: (params) => api.get('/agent/self-resolution', { params }),
  governanceMetrics: (params) => api.get('/agent/governance-metrics', { params }),
  // 治理情景模拟器（v4 收敛方案第 5 阶段）：诉求量涨 X% 要多少工时、折算几个人（只读）
  governanceSimulation: (params) => api.get('/agent/governance-simulation', { params }),
  saveSimSettings: (data) => api.post('/agent/governance-simulation/settings', data),
  kbHealth: (params) => api.get('/agent/kb-health', { params }),
  careMetrics: (params) => api.get('/agent/care-metrics', { params }),
  kgEntity: (name, params) => api.get('/agent/kg/entity', { params: { name, ...(params || {}) } }),
  kgStats: (params) => api.get('/agent/kg/stats', { params }),
  board: (params) => api.get('/agent/board', { params }),
  satisfactionDrilldown: (params) => api.get('/agent/satisfaction-drilldown', { params }),
  analytics: (params) => api.get('/agent/analytics', { params }),
  exportLogs: () => api.get('/export/agent-logs', { responseType: 'blob' }),
}

// 批量操作（P2-E2-01）
export const batch = {
  dispatch: (issueIds, assigneeName, assigneePhone) => api.post('/batch/dispatch', { issue_ids: issueIds, assignee_name: assigneeName, assignee_phone: assigneePhone }),
  close: (issueIds, reason) => api.post('/batch/close', { issue_ids: issueIds, reason }),
  reply: (questionIds, reply) => api.post('/batch/reply', { question_ids: questionIds, reply }),
}

// 舆情监测（P3-01）
export const opinions = {
  list: (params) => api.get('/opinions', { params }),
  create: (data) => api.post('/opinions', data),
  convert: (id) => api.post(`/opinions/${id}/convert`),
  brief: (params) => api.get('/opinions/brief', { params }),
}

export default api
