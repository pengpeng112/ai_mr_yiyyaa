/** 统一 API 错误模型（页面可展示，不含敏感正文） */

export type ApiErrorCode =
  | 'unauthorized'
  | 'forbidden'
  | 'not_found'
  | 'conflict'
  | 'validation'
  | 'rate_limited'
  | 'server'
  | 'network'
  | 'unknown'

export interface ApiError {
  status: number
  code: ApiErrorCode
  message: string
  requestId?: string
  fieldErrors?: Record<string, string[]>
  rawDetail?: unknown
}

const STATUS_MESSAGES: Record<number, string> = {
  400: '请求参数不正确',
  401: '登录已失效，请重新登录',
  403: '当前账号无权执行此操作',
  404: '请求的资源不存在',
  409: '操作冲突，请刷新后重试',
  422: '提交内容未通过校验',
  429: '请求过于频繁，请稍后重试',
  500: '服务暂时不可用，请稍后重试',
  502: '上游服务异常，请稍后重试',
  503: '服务繁忙，请稍后重试',
}

function statusToCode(status: number): ApiErrorCode {
  if (status === 401) return 'unauthorized'
  if (status === 403) return 'forbidden'
  if (status === 404) return 'not_found'
  if (status === 409) return 'conflict'
  if (status === 422) return 'validation'
  if (status === 429) return 'rate_limited'
  if (status >= 500) return 'server'
  if (status === 0) return 'network'
  return 'unknown'
}

function extractDetailMessage(detail: unknown): string {
  if (!detail) return ''
  if (typeof detail === 'string') {
    // 不向用户暴露 SQL/驱动细节
    if (/ORA-\d+|sqlalchemy|traceback|psycopg|cx_Oracle/i.test(detail)) {
      return '服务处理失败，请联系管理员'
    }
    return detail
  }
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === 'string') return item
        if (item && typeof item === 'object' && 'msg' in item) {
          return String((item as { msg: unknown }).msg)
        }
        return ''
      })
      .filter(Boolean)
    return parts.join('；')
  }
  if (typeof detail === 'object' && detail !== null && 'message' in detail) {
    return String((detail as { message: unknown }).message)
  }
  return ''
}

export function createApiError(input: {
  status?: number
  detail?: unknown
  message?: string
  requestId?: string
  fieldErrors?: Record<string, string[]>
}): ApiError {
  const status = input.status ?? 0
  const fromDetail = extractDetailMessage(input.detail)
  const message =
    input.message ||
    fromDetail ||
    STATUS_MESSAGES[status] ||
    (status === 0 ? '网络连接失败，请检查服务是否可达' : '请求失败')

  return {
    status,
    code: statusToCode(status),
    message,
    requestId: input.requestId,
    fieldErrors: input.fieldErrors,
    rawDetail: input.detail,
  }
}

export function isApiError(error: unknown): error is ApiError {
  return (
    !!error &&
    typeof error === 'object' &&
    'status' in error &&
    'code' in error &&
    'message' in error
  )
}

export function toUserMessage(error: unknown, fallback = '请求失败'): string {
  if (isApiError(error)) return error.message || fallback
  if (error instanceof Error) return error.message || fallback
  return fallback
}
