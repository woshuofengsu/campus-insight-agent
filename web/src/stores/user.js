// 用户状态（Pinia）：token + 角色 + 资料
import { defineStore } from 'pinia'
import { auth } from '../api'

export const useUserStore = defineStore('user', {
  state: () => ({
    token: localStorage.getItem('ci_token') || '',
    user: JSON.parse(localStorage.getItem('ci_user') || 'null'),
  }),
  getters: {
    role: (s) => s.user?.role || '',
    isGrid: (s) => s.user?.role === 'grid',
    isElderly: (s) => s.user?.role === 'elderly',
    isResident: (s) => s.user?.role === 'resident',
  },
  actions: {
    async login(username, password) {
      const data = await auth.login(username, password)
      this.setSession(data)
      return data
    },
    async demoLogin(role) {
      const data = await auth.demo(role)
      this.setSession(data)
      return data
    },
    setSession(data) {
      this.token = data.token
      this.user = data
      localStorage.setItem('ci_token', data.token)
      localStorage.setItem('ci_user', JSON.stringify(data))
    },
    logout() {
      this.token = ''
      this.user = null
      localStorage.removeItem('ci_token')
      localStorage.removeItem('ci_user')
    },
  },
})
