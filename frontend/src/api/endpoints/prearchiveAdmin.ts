import { apiGet, apiPost, apiPut } from '../client'

/** 039 归档前规则中心：全部经主服务白名单 BFF（/api/prearchive-admin/*），
 *  不直连预检服务；BFF 关闭（默认）时返回 503 由调用方降级展示。 */

export interface PrcRuleRow {
  rule_key: string
  domain: string
  track: string
  origin: string
  rule_version: string
  set_version: string
  status: 'draft' | 'validated' | 'approved' | 'published' | 'retired'
  content: Record<string, unknown>
  content_sha256: string
  draft_edit_version: number
  created_by: string
  published_version?: string
}

export interface PrcSettings {
  mode: 'file' | 'compare' | 'registry'
  require_separate_approver: boolean
  governance: {
    pilot_dept_codes: string[]
    action_policy: 'notify_only' | 'deduct' | 'block'
    notify_severities: string[]
  }
}

export interface PrcDestination {
  code: string
  kind: string
  enabled: boolean
  base_url: string
  endpoint: string
  auth_type: string
  secret_ref: string
  secret_configured: boolean
  schema_version: string
  timeout_seconds: number
  max_attempts: number
  send_severities: string[]
  allow_insecure_internal_http: boolean
  config_version: number
}

export interface PrcOutboxRow {
  id: string
  event_id: string
  destination_code: string
  status: 'pending' | 'sending' | 'sent' | 'retry' | 'dead' | 'disabled'
  attempts: number
  next_retry_at?: string | null
  last_http_status?: number | null
  last_error: string
  created_at?: string | null
}

export function prcSettingsApi() {
  return apiGet<PrcSettings>('/prearchive-admin/settings')
}

export function prcListRulesApi(params: { domain?: string; status?: string; page?: number } = {}) {
  return apiGet<{ total: number; items: PrcRuleRow[] }>('/prearchive-admin/rules', { params })
}

export function prcCreateDraftApi(body: Record<string, unknown>) {
  return apiPost<PrcRuleRow>('/prearchive-admin/rules', body)
}

export function prcUpdateDraftApi(ruleKey: string, body: Record<string, unknown>) {
  return apiPut<PrcRuleRow>(`/prearchive-admin/rules/${encodeURIComponent(ruleKey)}/draft`, body)
}

export function prcValidateApi(ruleKey: string, ruleVersion: string) {
  return apiPost<{ valid: boolean; errors: string[] }>(
    `/prearchive-admin/rules/${encodeURIComponent(ruleKey)}/validate`, { rule_version: ruleVersion })
}

export function prcDryRunApi(ruleKey: string, ruleVersion: string) {
  return apiPost<{ ok: boolean; fixture_results?: Array<{ patient_id: string; visit_id: string; problem_count: number }>; reason?: string }>(
    `/prearchive-admin/rules/${encodeURIComponent(ruleKey)}/dry-run`, { rule_version: ruleVersion })
}

export function prcApproveApi(ruleKey: string, ruleVersion: string, reason = '') {
  return apiPost<PrcRuleRow>(`/prearchive-admin/rules/${encodeURIComponent(ruleKey)}/approve`,
    { rule_version: ruleVersion, reason })
}

export function prcPublishApi(ruleKey: string, ruleVersion: string) {
  return apiPost<{ rule_key: string; rule_version: string; sha256: string; pointer_version: number }>(
    `/prearchive-admin/rules/${encodeURIComponent(ruleKey)}/publish`, { rule_version: ruleVersion })
}

export function prcRollbackApi(ruleKey: string, toVersion: string, reason = '') {
  return apiPost<{ from: string; to: string }>(
    `/prearchive-admin/rules/${encodeURIComponent(ruleKey)}/rollback`,
    { to_version: toVersion, reason })
}

export function prcVersionsApi(ruleKey: string) {
  return apiGet<{ items: PrcRuleRow[] }>(`/prearchive-admin/rules/${encodeURIComponent(ruleKey)}/versions`)
}

export function prcDiffApi(ruleKey: string, versionA: string, versionB: string) {
  return apiGet<{ changed_keys: string[]; changes: Array<{ key: string; from: unknown; to: unknown }> }>(
    `/prearchive-admin/rules/${encodeURIComponent(ruleKey)}/diff`,
    { params: { version_a: versionA, version_b: versionB } })
}

export function prcDestinationsApi() {
  return apiGet<{ items: PrcDestination[] }>('/prearchive-admin/destinations')
}

export function prcUpsertDestinationApi(body: Record<string, unknown>) {
  return apiPost<PrcDestination>('/prearchive-admin/destinations', body)
}

export function prcContractTestApi(code: string) {
  return apiPost<{ ok: boolean; event_id: string; preview_only: boolean }>(
    `/prearchive-admin/destinations/${encodeURIComponent(code)}/contract-test`)
}

export function prcOutboxApi(params: { status?: string } = {}) {
  return apiGet<{ items: PrcOutboxRow[] }>('/prearchive-admin/outbox', { params })
}

export function prcRetryOutboxApi(outboxId: string) {
  return apiPost<{ ok: boolean }>(`/prearchive-admin/outbox/${encodeURIComponent(outboxId)}/retry`)
}
