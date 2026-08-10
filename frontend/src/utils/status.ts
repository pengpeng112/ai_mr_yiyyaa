export type SeverityKey = 'high' | 'medium' | 'low' | 'unknown'
export type StatusKey =
  | 'success'
  | 'failed'
  | 'skipped'
  | 'pending'
  | 'running'
  | 'cancelled'
  | 'unknown'

const SEVERITY_LABEL: Record<SeverityKey, string> = {
  high: '高危',
  medium: '中危',
  low: '低危',
  unknown: '未知',
}

const STATUS_LABEL: Record<StatusKey, string> = {
  success: '成功',
  failed: '失败',
  skipped: '跳过',
  pending: '待处理',
  running: '运行中',
  cancelled: '已取消',
  unknown: '未知',
}

export function normalizeSeverity(raw: unknown): SeverityKey {
  const v = String(raw ?? '')
    .trim()
    .toLowerCase()
  if (!v || v === 'null' || v === 'none') return 'unknown'
  if (['high', '严重', '高', '高危', 'critical'].includes(v)) return 'high'
  if (['medium', '中', '中危', 'warning', 'warn'].includes(v)) return 'medium'
  if (['low', '低', '低危', 'info', '正常'].includes(v)) return 'low'
  return 'unknown'
}

export function normalizeStatus(raw: unknown): StatusKey {
  const v = String(raw ?? '')
    .trim()
    .toLowerCase()
  if (!v) return 'unknown'
  if (['success', 'ok', 'succeeded', '成功', 'completed'].includes(v)) return 'success'
  if (['failed', 'fail', 'error', '失败'].includes(v)) return 'failed'
  if (['skipped', 'skip', '跳过'].includes(v)) return 'skipped'
  if (['pending', 'waiting', 'queued', '待处理'].includes(v)) return 'pending'
  if (['running', 'processing', 'in_progress', '运行中'].includes(v)) return 'running'
  if (['cancelled', 'canceled', '已取消'].includes(v)) return 'cancelled'
  return 'unknown'
}

export function severityLabel(raw: unknown): string {
  return SEVERITY_LABEL[normalizeSeverity(raw)]
}

export function statusLabel(raw: unknown): string {
  return STATUS_LABEL[normalizeStatus(raw)]
}

/** 非法 severity 不得显示为“正常” */
export function severityTagType(raw: unknown): 'danger' | 'warning' | 'success' | 'info' {
  const s = normalizeSeverity(raw)
  if (s === 'high') return 'danger'
  if (s === 'medium') return 'warning'
  if (s === 'low') return 'success'
  return 'info'
}

export function statusTagType(
  raw: unknown,
): 'success' | 'danger' | 'warning' | 'info' | undefined {
  const s = normalizeStatus(raw)
  if (s === 'success') return 'success'
  if (s === 'failed') return 'danger'
  if (s === 'skipped' || s === 'cancelled') return 'info'
  if (s === 'pending' || s === 'running') return 'warning'
  return undefined
}
