import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  clearStoredToken,
  getStoredToken,
  isValidJwtToken,
  setStoredToken,
  setUnauthorizedHandler,
} from '@/api/client'
import { loginApi, logoutApi, meApi } from '@/api/endpoints/auth'
import type { UserInfo } from '@/api/types'
import { toUserMessage } from '@/api/errors'
import { useNavigationStore } from './navigation'
import { useTaskStore } from './task'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(getStoredToken())
  const user = ref<UserInfo | null>(null)
  const isAuthenticated = ref(false)
  const restoring = ref(false)
  const loginLoading = ref(false)
  const loginHint = ref('')

  const displayName = computed(
    () => user.value?.full_name || user.value?.username || '用户',
  )
  const roleName = computed(() => user.value?.role || '')

  function clearAuthState() {
    token.value = ''
    user.value = null
    isAuthenticated.value = false
    clearStoredToken()
    const tasks = useTaskStore()
    tasks.stopPolling()
    tasks.clear()
  }

  function bindUnauthorized() {
    setUnauthorizedHandler(() => {
      clearAuthState()
      loginHint.value = '登录已失效，请重新登录。'
    })
  }

  bindUnauthorized()

  async function login(username: string, password: string) {
    if (!username || !password) {
      loginHint.value = '请输入用户名和密码'
      throw new Error(loginHint.value)
    }
    loginLoading.value = true
    try {
      const res = await loginApi(username, password)
      const access = res.access_token || ''
      if (!isValidJwtToken(access)) {
        throw new Error('登录返回的 Token 格式无效')
      }
      token.value = access
      setStoredToken(access)
      user.value = res.user || null
      isAuthenticated.value = true
      loginHint.value = '登录成功'
      if (!user.value) {
        await restoreSession()
      }
      return true
    } catch (e) {
      clearAuthState()
      loginHint.value = toUserMessage(e, '登录失败')
      throw e
    } finally {
      loginLoading.value = false
    }
  }

  async function restoreSession() {
    const stored = getStoredToken()
    if (!stored || !isValidJwtToken(stored)) {
      clearAuthState()
      return false
    }
    restoring.value = true
    token.value = stored
    try {
      const me = await meApi()
      user.value = me
      isAuthenticated.value = true
      return true
    } catch {
      clearAuthState()
      return false
    } finally {
      restoring.value = false
    }
  }

  async function logout() {
    try {
      if (token.value) await logoutApi()
    } catch {
      /* ignore */
    }
    clearAuthState()
    const nav = useNavigationStore()
    nav.reset()
    loginHint.value = '已退出，请重新登录。'
  }

  return {
    token,
    user,
    isAuthenticated,
    restoring,
    loginLoading,
    loginHint,
    displayName,
    roleName,
    login,
    logout,
    restoreSession,
    clearAuthState,
  }
})
