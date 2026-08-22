// 三端路由 + 角色守卫
import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '../stores/user'

const routes = [
  { path: '/', redirect: '/login' },
  { path: '/login', name: 'login', component: () => import('../views/Login.vue') },
  { path: '/screen', name: 'screen', component: () => import('../views/Screen.vue'), meta: { title: '治理大屏' } },
  { path: '/stability', name: 'stability', component: () => import('../views/Stability.vue'), meta: { title: '系统稳定性演示' } },

  // 居民端
  {
    path: '/resident',
    component: () => import('../layouts/PortalLayout.vue'),
    meta: { role: 'resident' },
    children: [
      { path: '', redirect: '/resident/home' },
      { path: 'home', name: 'r-home', component: () => import('../views/resident/Home.vue'), meta: { title: '首页' } },
      { path: 'work-orders', name: 'r-issues', component: () => import('../views/resident/Issues.vue'), meta: { title: '报修' } },
      { path: 'work-orders/:id', name: 'r-issue-detail', component: () => import('../views/resident/IssueDetail.vue'), meta: { title: '工单详情' } },
      { path: 'work-orders/new', name: 'r-issue-new', component: () => import('../views/resident/IssueNew.vue'), meta: { title: '提交报修' } },
      { path: 'proposals', name: 'r-proposals', component: () => import('../views/resident/Proposals.vue'), meta: { title: '邻里议事' } },
      { path: 'proposals/:id', name: 'r-proposal-detail', component: () => import('../views/resident/ProposalDetail.vue'), meta: { title: '提案详情' } },
      { path: 'proposals/new', name: 'r-proposal-new', component: () => import('../views/resident/ProposalNew.vue'), meta: { title: '提交提案' } },
      { path: 'notices', name: 'r-notices', component: () => import('../views/resident/Notices.vue'), meta: { title: '通知' } },
      { path: 'qa', name: 'r-qa', component: () => import('../views/resident/QA.vue'), meta: { title: '政策问答' } },
      { path: 'health', name: 'r-health', component: () => import('../views/resident/Health.vue'), meta: { title: '健康防护' } },
      { path: 'weather', name: 'r-weather', component: () => import('../views/resident/Weather.vue'), meta: { title: '天气' } },
      { path: 'profile', name: 'r-profile', component: () => import('../views/resident/Profile.vue'), meta: { title: '我的' } },
      { path: 'messages', name: 'r-messages', component: () => import('../views/resident/Messages.vue'), meta: { title: '消息中心' } },
      { path: 'privacy', name: 'r-privacy', component: () => import('../views/resident/Privacy.vue'), meta: { title: '隐私政策' } },
    ],
  },

  // 网格员端
  {
    path: '/grid',
    component: () => import('../layouts/PortalLayout.vue'),
    meta: { role: 'grid' },
    children: [
      { path: '', redirect: '/grid/dashboard' },
      { path: 'dashboard', name: 'g-dashboard', component: () => import('../views/grid/Dashboard.vue'), meta: { title: '工作台' } },
      { path: 'work-orders', name: 'g-issues', component: () => import('../views/grid/Issues.vue'), meta: { title: '工单管理' } },
      { path: 'proposals', name: 'g-proposals', component: () => import('../views/grid/Proposals.vue'), meta: { title: '提案管理' } },
      { path: 'notices', name: 'g-notices', component: () => import('../views/grid/Notices.vue'), meta: { title: '通知管理' } },
      { path: 'qa', name: 'g-qa', component: () => import('../views/grid/QA.vue'), meta: { title: '政策问答管理' } },
      { path: 'weather', name: 'g-weather', component: () => import('../views/grid/Weather.vue'), meta: { title: '天气管理' } },
      { path: 'health', name: 'g-health', component: () => import('../views/grid/Health.vue'), meta: { title: '健康管理' } },
      { path: 'messages', name: 'g-messages', component: () => import('../views/grid/Messages.vue'), meta: { title: '消息中心' } },
      { path: 'elderly-care', name: 'g-elderly', component: () => import('../views/grid/ElderlyCare.vue'), meta: { title: '老年关怀管理' } },
    ],
  },

  // 老年端
  {
    path: '/elderly',
    component: () => import('../layouts/ElderlyLayout.vue'),
    meta: { role: 'elderly' },
    children: [
      { path: '', redirect: '/elderly/home' },
      { path: 'home', name: 'e-home', component: () => import('../views/elderly/Home.vue'), meta: { title: '首页' } },
      { path: 'agent', name: 'e-agent', component: () => import('../views/elderly/Agent.vue'), meta: { title: '社区小助手' } },
      { path: 'report', name: 'e-report', component: () => import('../views/elderly/Report.vue'), meta: { title: '语音报修' } },
      { path: 'medication', name: 'e-medication', component: () => import('../views/elderly/Medication.vue'), meta: { title: '用药提醒' } },
      { path: 'notices', name: 'e-notices', component: () => import('../views/elderly/Notices.vue'), meta: { title: '听通知' } },
      { path: 'contacts', name: 'e-contacts', component: () => import('../views/elderly/Contacts.vue'), meta: { title: '紧急联系人' } },
      { path: 'orders', name: 'e-orders', component: () => import('../views/elderly/Orders.vue'), meta: { title: '我的报修' } },
      { path: 'qa', name: 'e-qa', component: () => import('../views/elderly/QA.vue'), meta: { title: '政策问答' } },
    ],
  },

  { path: '/:pathMatch(.*)*', redirect: '/login' },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  const store = useUserStore()
  if (to.path === '/login' || to.path === '/screen') return true
  if (!store.token) return '/login'
  const required = to.meta.role
  if (required && store.role !== required) {
    // 角色不符 → 跳对应端首页
    const home = { resident: '/resident/home', grid: '/grid/dashboard', elderly: '/elderly/home' }
    return home[store.role] || '/login'
  }
  return true
})

export default router
