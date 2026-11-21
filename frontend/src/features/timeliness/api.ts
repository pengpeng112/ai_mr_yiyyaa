/**
 * 病历时效质控前端 API（T6）。
 *
 * 全部经主服务 `/api/timeliness/*`（T5 路由），复用 apiClient（自动带 Authorization、
 * /api 前缀归一）；不直连任何 JHEMR/中继地址；规则编码入参统一 encodeURIComponent。
 */
import { apiGet, apiPost, apiDownload, triggerBrowserDownload } from '@/api/client'
import type {
  ApprovalListParams,
  ApprovalStatusCounts,
  DryRunResult,
  MonthlyStats,
  Paged,
  TlApproval,
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
  /** WP04：责任医生（工号精确或姓名模糊）。 */
  doctor?: string
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

/** 事件人工豁免（2026-11-15 P0-2；timeliness_admin；原因必填，终态化并写 History+ActionLog）。 */
export function exemptEventApi(
  eventId: number,
  exemptReason: string,
): Promise<{ message: string; data: Record<string, unknown> }> {
  return apiPost(`/timeliness/events/${encodeURIComponent(String(eventId))}/exempt`, {
    exempt_reason: exemptReason,
  })
}

/** WP04：考核统计查询参数（month 与 date_from/date_to 二选一，区间优先；page 缺省=全量）。 */
export interface MonthlyStatsParams {
  month?: string
  date_from?: string
  date_to?: string
  dept?: string
  doctor?: string
  page?: number
  limit?: number
}

export function fetchMonthlyStatsApi(
  month?: string,
  dept?: string,
  extra?: Omit<MonthlyStatsParams, 'month' | 'dept'>,
): Promise<MonthlyStats> {
  return apiGet<MonthlyStats>('/timeliness/stats/monthly', {
    params: { month, dept: dept || undefined, ...(extra || {}) },
  })
}

/** WP04：区间/分页版考核统计查询（page/limit/date_from/date_to/doctor）。 */
export function fetchMonthlyRangeStatsApi(params: MonthlyStatsParams): Promise<MonthlyStats> {
  return apiGet<MonthlyStats>('/timeliness/stats/monthly', { params })
}

/** 导出考核统计（默认 CSV；WP04 新增 format=xlsx 真 Excel）；后端写 ExportAuditLog。 */
export async function exportMonthlyApi(
  month: string,
  dept?: string,
  options?: { date_from?: string; date_to?: string; doctor?: string; format?: 'csv' | 'xlsx' },
): Promise<void> {
  const params = new URLSearchParams({ month })
  if (dept) params.set('dept', dept)
  if (options?.date_from) params.set('date_from', options.date_from)
  if (options?.date_to) params.set('date_to', options.date_to)
  if (options?.doctor) params.set('doctor', options.doctor)
  params.set('format', options?.format || 'csv')
  const { blob, filename } = await apiDownload(
    `/timeliness/export/monthly?${params}`,
  )
  triggerBrowserDownload(blob, filename)
}

/** WP04：立即同步 JHEMR 审批（POST /approvals/sync，timeliness_admin；只读源未配置 503）。 */
export async function syncApprovalsApi(): Promise<{ message: string; synced: number; data: Record<string, unknown> }> {
  const body = await apiPost<{ message: string; data: Record<string, unknown> }>(
    '/timeliness/approvals/sync',
  )
  const data = body.data || {}
  const synced = Number(data.created || 0) + Number(data.updated || 0)
  return { message: body.message, synced, data }
}

export function fetchDepartmentsApi(): Promise<DepartmentOption[]> {
  return apiGet<DepartmentOption[]>('/departments')
}

// ---- 审批与扣罚台账（2026-11-13 返工；对接 T9 既有端点） ----

/** 超时审批/扣罚台账列表（WP04：含 status_counts 状态汇总；无 timeliness_view 权限 403）。 */
export function fetchApprovalsApi(
  params: ApprovalListParams,
): Promise<Paged<TlApproval> & { status_counts?: ApprovalStatusCounts }> {
  const query = Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== null && `${value}`.trim() !== '')
    .map(([key, value]) => `${key}=${encodeURIComponent(String(value))}`)
    .join('&')
  return apiGet<Paged<TlApproval> & { status_counts?: ApprovalStatusCounts }>(
    `/timeliness/approvals${query ? `?${query}` : ''}`,
  )
}

/** 豁免/取消豁免扣罚（timeliness_admin；原因必填入审计；cancel=true 为取消豁免）。 */
export function exemptApprovalApi(
  approvalId: number,
  exemptReason: string,
  options?: { cancel?: boolean },
): Promise<{ message: string; data: Record<string, unknown> }> {
  return apiPost(`/timeliness/approvals/${encodeURIComponent(String(approvalId))}/exempt`, {
    exempt_reason: exemptReason,
    cancel: Boolean(options?.cancel),
  })
}

/** 审批解锁回写 JHEMR（默认 dry_run=true 演练预览；网关未开时后端 409 并带提示）。 */
export function approveApprovalApi(
  approvalId: number,
  dryRun: boolean,
): Promise<{ message: string; data: Record<string, unknown> }> {
  return apiPost(
    `/timeliness/approvals/${encodeURIComponent(String(approvalId))}/approve`,
    { dry_run: dryRun },
  )
}
