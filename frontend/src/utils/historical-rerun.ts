export interface HistoricalScope {
  query_date?: string | null
  date_from?: string | null
  date_to?: string | null
  date_dimension: string
  audit_type_codes?: string[] | null
  dept_filter?: string[] | null
}

export function buildHistoricalPreviewPayload(scope: HistoricalScope, audit_run_mode: string, shard_limit = 100) {
  return { ...scope, audit_run_mode, shard_limit }
}

export function buildHistoricalCreatePayload(
  scope: HistoricalScope,
  options: { audit_run_mode: string; candidate_hash: string; reaudit_reason: string; alert_policy: string; include_rectified: boolean; auto_start?: boolean },
) {
  return {
    ...scope,
    audit_run_mode: options.audit_run_mode,
    confirm_candidate_hash: options.candidate_hash,
    reaudit_reason: options.reaudit_reason,
    alert_policy: options.alert_policy,
    include_rectified: options.include_rectified,
    auto_start: options.auto_start ?? true,
  }
}
