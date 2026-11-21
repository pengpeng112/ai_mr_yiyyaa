/**
 * WP09：企微基础配置局部保存纯函数（页面 buildPartialBody 的载体，供单测直测）。
 * 语义：与加载快照 diff，只提交改动字段；
 * - base_url 清空（或未改动）→ 不提交（防覆盖旧地址）；
 * - secret_key 留空 → 不提交（保护 secret_key_enc）；
 * - 完全无改动 → 回退完整局部体（enabled 必发，保持旧契约）。
 */
export interface RelayFormSnapshot {
  enabled: boolean
  base_url: string
  endpoint: string
  secret_key: string
  severity_levels: string[]
  alert_dept_filter: string[]
  source: string
}

export function buildRelayPartialBody(
  loaded: RelayFormSnapshot,
  form: RelayFormSnapshot,
): Record<string, unknown> {
  const changed: Record<string, unknown> = {}
  if (form.enabled !== loaded.enabled) changed.enabled = form.enabled
  if (form.endpoint !== loaded.endpoint) changed.endpoint = form.endpoint
  if (form.source !== loaded.source) changed.source = form.source
  if (JSON.stringify(form.severity_levels) !== JSON.stringify(loaded.severity_levels)) {
    changed.severity_levels = form.severity_levels
  }
  if (JSON.stringify(form.alert_dept_filter) !== JSON.stringify(loaded.alert_dept_filter)) {
    changed.alert_dept_filter = form.alert_dept_filter
  }
  const base = String(form.base_url || '').trim()
  const loadedBase = String(loaded.base_url || '').trim()
  const baseChanged = base !== loadedBase
  if (baseChanged && base) changed.base_url = base
  // base 被清空：不加键 = 提交体不含 base_url（后端局部合并语义下旧地址保留且不被覆盖）
  const secret = String(form.secret_key || '').trim()
  if (secret) changed.secret_key = secret
  const secretChanged = secret !== String(loaded.secret_key || '').trim()
  const hasRealChange = Boolean(
    Object.keys(changed).some((key) => key !== 'enabled')
    || (form.enabled !== loaded.enabled)
    || baseChanged || secretChanged,
  )
  if (!hasRealChange) {
    // 完全无改动：仅回 enabled 最小体（页面据 keys==1 检测 noop 提示；不回完整体防误覆盖）
    return { enabled: form.enabled }
  }
  return changed
}
