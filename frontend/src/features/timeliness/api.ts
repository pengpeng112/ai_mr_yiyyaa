/**
 * 病历时效质控前端 API（T6）。
 *
 * 全部经主服务 `/api/timeliness/*`（T5 路由），复用 apiClient（自动带 Authorization、
 * /api 前缀归一）；不直连任何 JHEMR/中继地址；规则编码入参统一 encodeURIComponent。
 */
import { apiGet, apiPost, apiDownload, triggerBrowserDownload } from '@/api/client'
import type {
  DryRunResult,
  MonthlyStats,
  Paged,
  TlDicts,
  TlEvent,
  TlEventDetail,
  TlRule,
  TlVersion,
  DepartmentOption,
} from './types'

export function fetchTimelinessDictsApi(): Promise<TlDicts> {
  return apiGet<TlDicts>('/timeliness/dicts')
}

export function fetchTimelinessRulesApi(): Promise<Paged<TlRule>> {
  return apiGet<Paged<TlRule>>('/timeliness/rules')
}

export function fetchRuleVersionsApi(ruleCode: string): Promise<Paged<TlVersion>> {
  return apiGet<Paged<TlVersion>>(
    `/timeliness/rules/${encodeURIComponent(ruleCode)}/versions`,
  )
}

export function createRuleVersionApi(
  ruleCode: string,
  changes: Record<string, unknown>,
): Promise<{ message: string; rule_code: string; version: TlVersion }> {
  return apiPost(`/timeliness/rules/${encodeURIComponent(ruleCode)}/versions`, changes)
}

export function toggleRuleApi(
  ruleCode: string,
  enabled: boolean,
): Promise<{ message: string; data: { rule_code: string; enabled: boolean } }> {
  return apiPost(`/timeliness/rules/${encodeURIComponent(ruleCode)}/toggle`, { enabled })
}

/** 试算待保存版本（绝不写库）；changes 传空对象=按当前版本口径试算。 */
export function dryRunRuleApi(
  ruleCode: string,
  changes: Record<string, unknown>,
): Promise<DryRunResult> {
  return apiPost<DryRunResult>(
    `/timeliness/rules/${encodeURIComponent(ruleCode)}/dry-run`,
    changes,
  )
}

export interface EventListParams {
  page?: number
  limit?: number
  dept?: string
  rule_code?: string
  status?: string
  patient_id?: string
  date_from?: string
  date_to?: string
}

export function fetchTimelinessEventsApi(
  params: EventListParams,
): Promise<Paged<TlEvent>> {
  const query = Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== null && `${value}`.trim() !== '')
    .map(([key, value]) => `${key}=${encodeURIComponent(String(value))}`)
    .join('&')
  return apiGet<Paged<TlEvent>>(`/timeliness/events${query ? `?${query}` : ''}`)
}

export function fetchTimelinessEventApi(eventId: number): Promise<TlEventDetail> {
  return apiGet<TlEventDetail>(`/timeliness/events/${encodeURIComponent(String(eventId))}`)
}

export function fetchMonthlyStatsApi(month?: string): Promise<MonthlyStats> {
  const query = month ? `?month=${encodeURIComponent(month)}` : ''
  return apiGet<MonthlyStats>(`/timeliness/stats/monthly${query}`)
}

/** 导出月度统计 CSV（后端写 ExportAuditLog）；无 timeliness_export 权限时后端 403。 */
export async function exportMonthlyApi(month: string): Promise<void> {
  const { blob, filename } = await apiDownload(
    `/timeliness/export/monthly?month=${encodeURIComponent(month)}`,
  )
  triggerBrowserDownload(blob, filename)
}

export function fetchDepartmentsApi(): Promise<DepartmentOption[]> {
  return apiGet<DepartmentOption[]>('/departments')
}
