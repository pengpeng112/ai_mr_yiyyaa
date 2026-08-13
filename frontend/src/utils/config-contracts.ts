export function omitBlankSecret(body: Record<string, unknown>, key: string): Record<string, unknown> {
  const result = { ...body }
  if (!String(result[key] || '').trim()) delete result[key]
  return result
}

export function parseNotifyConfig(text: string): Record<string, unknown> {
  const value: unknown = JSON.parse(text)
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('通知渠道 config 必须是 JSON 对象')
  return value as Record<string, unknown>
}

export function parseDeptCandidates(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String).filter(Boolean)
  if (!value || typeof value !== 'object') return []
  const record = value as Record<string, unknown>
  const list = record.departments ?? record.items
  return Array.isArray(list) ? list.map(String).filter(Boolean) : []
}

export function buildDifyTargetPayload(target: Record<string, any>, originalName?: string): Record<string, unknown> {
  if (originalName && originalName !== target.name && target.has_secret && !target.api_key.trim()) {
    throw new Error(`节点“${originalName}”已配置密钥，改名时必须输入新密钥，否则会丢失密钥`)
  }
  const body: Record<string, unknown> = { name: target.name, base_url: target.base_url, timeout_seconds: target.timeout_seconds, weight: target.weight, enabled: target.enabled }
  if (target.api_key.trim()) body.api_key = target.api_key.trim()
  return body
}

export function buildRelayConfigBody(input: { enabled: boolean; base_url: string; endpoint: string; secret_key: string; timeout_seconds: number; severity_levels: string[]; source: string; max_retry: number; retry_backoff_seconds: number; alert_dept_filter: string[] }): Record<string, unknown> {
  const body: Record<string, unknown> = { enabled: input.enabled, endpoint: input.endpoint, timeout_seconds: input.timeout_seconds, severity_levels: input.severity_levels, source: input.source, max_retry: input.max_retry, retry_backoff_seconds: input.retry_backoff_seconds, alert_dept_filter: input.alert_dept_filter }
  if (input.base_url.trim()) body.base_url = input.base_url.trim()
  if (input.secret_key.trim()) body.secret_key = input.secret_key.trim()
  return body
}
