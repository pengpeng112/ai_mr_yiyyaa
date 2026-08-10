import { apiGet, apiPost } from '../client'
import type { LoginResponse, UserInfo } from '../types'

export function loginApi(username: string, password: string) {
  return apiPost<LoginResponse>('/users/login', { username, password })
}

export function logoutApi() {
  return apiPost('/users/logout')
}

export function meApi() {
  return apiGet<UserInfo>('/users/me')
}
