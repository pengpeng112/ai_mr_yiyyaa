import { toUserMessage } from '@/api/errors'

/**
 * 041 T3：归档前规则中心降级文案（Legacy 与 UI Next 共用口径）。
 * - 403 = 权限问题（不是服务故障），提示点名缺失权限；
 * - 502/503 = 服务不可用/未启用；
 * - 其余沿用错误消息兜底。
 */
export function prcDisabledReasonFromError(e: unknown, fallback = '预检管理服务不可用'): string {
  const status = (e as { response?: { status?: number } })?.response?.status
  if (status === 403) {
    return '无访问权限（缺少 prearchive_rule_view 权限，请联系管理员开通）'
  }
  if (status === 502 || status === 503) {
    return '规则中心不可用（BFF 未启用：PREARCHIVE_ADMIN_ENABLED=false，或预检服务未启动）'
  }
  return toUserMessage(e, fallback)
}

/** 403 不套「规则中心不可用」前缀，避免把权限问题写成服务故障。 */
export function prcDisabledTitleFromReason(reason: string, suffix: string): string {
  return reason.startsWith('无访问权限')
    ? reason + suffix
    : `规则中心不可用：${reason}${suffix}`
}
