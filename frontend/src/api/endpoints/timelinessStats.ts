/**
 * 病历时效统计分析 API（WP03；GET /api/timeliness/stats/analytics）。
 */
import { apiGet } from '../client'

export interface TimelinessSummary {
  total_events: number
  on_time_count: number
  late_completed_count: number
  overdue_count: number
  warning_count: number
  on_time_rate: number
  locked_count: number
  locked_pending: number
  unlocked_count: number
  exempt_count: number
  penalty_amount_total: number
  avg_overdue_hours: number
}

export interface DeptRankingRow {
  dept_code: string
  dept_name: string
  locked_count: number
  locked_pending: number
  overdue_count: number
  total_events: number
  on_time_rate: number
  penalty_amount_total: number
}

export interface DoctorRankingRow {
  doctor_code: string
  doctor_name: string
  dept_code: string
  dept_name: string
  locked_count: number
  overdue_count: number
  total_events: number
  on_time_rate: number
  avg_overdue_hours: number
  penalty_amount_total: number
}

export interface RuleBreakdownRow {
  rule_code: string
  rule_name: string
  overdue_count: number
  late_completed_count: number
  total_events: number
}

export interface DailyTrendRow {
  date: string
  total: number
  overdue: number
  locked: number
  on_time_rate: number
}

export interface TimelinessAnalytics {
  date_from: string
  date_to: string
  scope_label: string
  summary: TimelinessSummary
  dept_ranking: DeptRankingRow[]
  doctor_ranking: DoctorRankingRow[]
  rule_breakdown: RuleBreakdownRow[]
  daily_trend: DailyTrendRow[]
}

export function fetchTimelinessAnalytics(params: {
  date_from?: string
  date_to?: string
  dept?: string
  top_n?: number
} = {}): Promise<TimelinessAnalytics> {
  const query = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && `${v}`.trim() !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join('&')
  return apiGet<TimelinessAnalytics>(`/timeliness/stats/analytics${query ? `?${query}` : ''}`)
}
