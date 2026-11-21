/**
 * 质控总览聚合 API（WP03；WP01 后端 GET /api/stats/workbench-overview）。
 */
import { apiGet } from '../client'

export interface AiQcOverview {
  today_pushed: number
  today_success: number
  today_failed: number
  today_high_risk: number
  severity_counts: { high: number; medium: number; low: number; none: number }
  daily_trend: Array<{ date: string; total: number; high: number; medium: number; low: number }>
  top_depts: Array<{ name: string; anomaly_count: number; high_count: number }>
  high_risk_recent: Array<{
    id: number
    patient_id: string
    patient_name: string
    visit_number: number | string
    dept: string
    audit_type_code: string
    audit_type_name: string
    severity: string
    push_time: string | null
    summary: string
    reviewed_flag: boolean
  }>
}

export interface TimelinessOverview {
  inpatient_warning: number
  inpatient_overdue: number
  locked_pending: number
  month_locked_total: number
  month_unlocked: number
  month_on_time_rate: number
  month_total_events: number
  last_scan_at: string | null
  last_scan_duration_ms: number | null
}

export interface PrearchiveOverview {
  available: boolean
  mode: string
  total_checked: number
  issue_records: number
  pending_review: number
  rules_active: number
  status_message: string
}

export interface RelayOverview {
  total: number
  success: number
  failed: number
  pending: number
  viewed: number
  unviewed: number
}

export interface SystemOverview {
  status: string
  scheduler_running: boolean
  daily_next_run: string | null
  discharge_next_run: string | null
}

export interface WorkbenchOverview {
  cached_at: string
  days: number
  scope_label: string
  ai_qc: AiQcOverview
  timeliness: TimelinessOverview
  prearchive: PrearchiveOverview
  relay: RelayOverview
  system: SystemOverview
}

export function fetchWorkbenchOverview(
  options: { days?: number; force_refresh?: boolean } = {},
): Promise<WorkbenchOverview> {
  const params = new URLSearchParams()
  params.set('days', String(options.days ?? 30))
  if (options.force_refresh) params.set('force_refresh', 'true')
  return apiGet<WorkbenchOverview>(`/stats/workbench-overview?${params.toString()}`)
}
