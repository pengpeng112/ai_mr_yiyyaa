import axios, {
  type AxiosError,
  type AxiosInstance,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from 'axios'
import { createApiError, type ApiError } from './errors'

const TOKEN_KEY = 'auth_token'

type UnauthorizedHandler = () => void

let unauthorizedHandler: UnauthorizedHandler | null = null

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null) {
  unauthorizedHandler = handler
}

export function getStoredToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

export function setStoredToken(token: string) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* ignore quota / private mode */
  }
}

export function clearStoredToken() {
  setStoredToken('')
}

export function isValidJwtToken(token: string): boolean {
  if (!token || typeof token !== 'string') return false
  return /^[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+$/.test(token)
}

function readRequestId(headers: Record<string, unknown> | undefined): string | undefined {
  if (!headers) return undefined
  const raw =
    headers['x-request-id'] ||
    headers['X-Request-Id'] ||
    headers['x-requestid'] ||
    headers['request-id']
  return raw ? String(raw) : undefined
}

function toApiError(error: AxiosError): ApiError {
  if (!error.response) {
    return createApiError({
      status: 0,
      message: '网络连接失败，请检查服务是否可达',
    })
  }
  const data = error.response.data as { detail?: unknown; message?: string } | undefined
  return createApiError({
    status: error.response.status,
    detail: data?.detail ?? data?.message,
    requestId: readRequestId(error.response.headers as Record<string, unknown>),
  })
}

export const apiClient: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 60_000,
  headers: {
    Accept: 'application/json',
  },
})

apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getStoredToken()
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    const apiError = toApiError(error)
    if (apiError.status === 401 && unauthorizedHandler) {
      unauthorizedHandler()
    }
    return Promise.reject(apiError)
  },
)

export async function apiGet<T = unknown>(url: string, config?: AxiosRequestConfig) {
  const res = await apiClient.get<T>(url, config)
  return res.data
}

export async function apiPost<T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig) {
  const res = await apiClient.post<T>(url, data, config)
  return res.data
}

export async function apiPut<T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig) {
  const res = await apiClient.put<T>(url, data, config)
  return res.data
}

export async function apiDelete<T = unknown>(url: string, config?: AxiosRequestConfig) {
  const res = await apiClient.delete<T>(url, config)
  return res.data
}

/** 导出下载：返回 Blob 与文件名；不把内容写入 console */
export async function apiDownload(
  url: string,
  config?: AxiosRequestConfig,
): Promise<{ blob: Blob; filename: string }> {
  const res = await apiClient.get(url, {
    ...config,
    responseType: 'blob',
  })
  const contentType = String(res.headers['content-type'] || 'application/octet-stream')
  const blob =
    res.data instanceof Blob ? res.data : new Blob([res.data], { type: contentType })

  if (!blob.size) {
    throw createApiError({ status: 400, message: '导出文件为空，请缩小筛选范围后重试' })
  }

  if (contentType.includes('application/json')) {
    const text = await blob.text()
    try {
      const data = JSON.parse(text) as { detail?: string; message?: string }
      throw createApiError({
        status: 400,
        detail: data.detail || data.message || '导出失败',
      })
    } catch (e) {
      if (e && typeof e === 'object' && 'code' in e) throw e
      throw createApiError({ status: 400, message: text || '导出失败' })
    }
  }

  const disposition = String(res.headers['content-disposition'] || '')
  const encodedMatch = disposition.match(/filename\*=UTF-8''([^;]+)/i)
  const plainMatch = disposition.match(/filename="?([^";]+)"?/i)
  const filename = encodedMatch
    ? decodeURIComponent(encodedMatch[1])
    : plainMatch?.[1]
      ? decodeURIComponent(plainMatch[1])
      : `export_${Date.now()}`

  return { blob, filename }
}

export function triggerBrowserDownload(blob: Blob, filename: string) {
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.style.display = 'none'
  document.body.appendChild(link)
  link.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }))
  window.setTimeout(() => {
    link.remove()
    window.URL.revokeObjectURL(url)
  }, 60_000)
}
