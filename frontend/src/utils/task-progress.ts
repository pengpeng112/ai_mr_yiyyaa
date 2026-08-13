export interface CurrentTask {
  task_id: string
  status: string
  total: number
  processed: number
  success: number
  failed: number
  skipped: number
  cancelled?: boolean
  percent: number
  trigger_type: 'manual'
  run_time: string
  query_date: string
  audit_type_code: string
  audit_run_mode: string
  error_msg: string
}

export interface TaskHistoryRow {
  id: number | string
  status: string
  trigger_type: string
  run_time: string
  query_date: string
  audit_type_code: string
  audit_run_mode: string
  total_records: number
  success_count: number
  failed_count: number
  duration_seconds: number
  error_msg: string
  source?: 'current' | 'history'
  processed?: number
  skipped?: number
}

export function normalizeCurrentTask(raw: Record<string, unknown> | null | undefined): CurrentTask | null {
  const taskId = String(raw?.task_id || '').trim()
  const status = String(raw?.status || '').trim()
  if (!taskId || status === 'not_found') return null
  const total = Math.max(0, Number(raw?.total || 0))
  const processed = Math.max(0, Number(raw?.processed || 0))
  return { task_id: taskId, status, total, processed, success: Number(raw?.success || 0), failed: Number(raw?.failed || 0), skipped: Number(raw?.skipped || 0), cancelled: Boolean(raw?.cancelled), percent: total ? Math.min(100, Math.round((processed / total) * 100)) : 0, trigger_type: 'manual', run_time: '', query_date: '', audit_type_code: String(raw?.audit_type_code || ''), audit_run_mode: String(raw?.audit_run_mode || ''), error_msg: String(raw?.error_msg || '') }
}

export function isPollableStatus(status: unknown): boolean { return ['running', 'pending', 'processing'].includes(String(status || '').toLowerCase()) }

export function mergeCurrentTask(current: CurrentTask | null, rows: TaskHistoryRow[], filters: { status?: string; trigger_type?: string; date_from?: string; date_to?: string; audit_run_mode?: string }, page = 1): TaskHistoryRow[] {
  if (page !== 1) return rows
  if (!current || filters.date_from || filters.date_to) return rows
  if (filters.trigger_type && filters.trigger_type !== 'manual') return rows
  if (filters.status && filters.status !== current.status) return rows
  if (filters.audit_run_mode && filters.audit_run_mode !== current.audit_run_mode) return rows
  return [{ id: current.task_id, status: current.status, trigger_type: 'manual', run_time: '', query_date: '', audit_type_code: current.audit_type_code, audit_run_mode: current.audit_run_mode, total_records: current.total, success_count: current.success, failed_count: current.failed, duration_seconds: 0, error_msg: current.error_msg, source: 'current', processed: current.processed, skipped: current.skipped }, ...rows]
}

export function summarizeTaskRows(rows: TaskHistoryRow[]) {
  const running = rows.filter((r) => isPollableStatus(r.status)).length
  const completed = rows.filter((r) => r.status === 'completed').length
  const failed = rows.filter((r) => r.status === 'failed').length
  const durations = rows.map((r) => Number(r.duration_seconds || 0)).filter((n) => n > 0)
  return { running, completed, failed, averageDuration: durations.length ? Math.round(durations.reduce((a, b) => a + b, 0) / durations.length) : 0 }
}

export function historyProcessed(row: { success_count?: unknown; failed_count?: unknown }): number {
  return Math.max(0, Number(row.success_count || 0) + Number(row.failed_count || 0))
}
