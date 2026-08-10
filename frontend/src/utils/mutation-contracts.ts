/**
 * 写操作请求体构建 — 与 legacy static/scripts 对齐，供页面与单元测试共用。
 * 禁止为界面简化丢字段或把空 secret 写成覆盖。
 */

export function splitCsv(text: string): string[] {
  return String(text || '')
    .split(/[,，\s\n]+/)
    .map((s) => s.trim())
    .filter(Boolean)
}

/** Relay 部分更新：secret 空不提交；base_url 空不提交（防覆盖） */
export function buildRelayPartialUpdateBody(input: {
  enabled: boolean
  endpoint?: string
  source?: string
  base_url?: string
  secret_key?: string
  severity_levels?: string[] | string
  alert_dept_filter?: string[] | string
}): Record<string, unknown> {
  const severity =
    typeof input.severity_levels === 'string'
      ? splitCsv(input.severity_levels)
      : Array.isArray(input.severity_levels)
        ? input.severity_levels.filter(Boolean)
        : ['high']
  const depts =
    typeof input.alert_dept_filter === 'string'
      ? splitCsv(input.alert_dept_filter)
      : Array.isArray(input.alert_dept_filter)
        ? input.alert_dept_filter.filter(Boolean)
        : []

  const body: Record<string, unknown> = {
    enabled: !!input.enabled,
    endpoint: input.endpoint || '/qc-record-alert',
    source: input.source || '病历质控系统',
    severity_levels: severity.length ? severity : ['high'],
    alert_dept_filter: depts,
  }

  const base = String(input.base_url || '').trim()
  if (base) body.base_url = base

  const secret = String(input.secret_key || '').trim()
  if (secret) body.secret_key = secret

  return body
}

/** Dify 配置：api_key 留空不提交；base_url 可提交（后端另有空串保护） */
export function buildDifySaveBody(input: {
  base_url?: string
  workflow_input_variable?: string
  api_key?: string
}): Record<string, unknown> {
  const body: Record<string, unknown> = {
    base_url: String(input.base_url || ''),
    workflow_input_variable: String(input.workflow_input_variable || 'mr_txt'),
  }
  const key = String(input.api_key || '').trim()
  if (key) body.api_key = key
  return body
}

/** 调度立即触发：与 legacy 一致使用 query params，audit_run_mode 而非 body.mode */
export function buildSchedulerTriggerParams(input: {
  query_date?: string
  audit_type_codes?: string[] | string
  dept_filter?: string[] | string
  audit_run_mode?: 'daily_increment' | 'discharge_final' | string
}): Record<string, string> {
  const params: Record<string, string> = {}
  const qd = String(input.query_date || '').trim()
  if (qd) params.query_date = qd

  const codes =
    typeof input.audit_type_codes === 'string'
      ? splitCsv(input.audit_type_codes)
      : Array.isArray(input.audit_type_codes)
        ? input.audit_type_codes.map(String).filter(Boolean)
        : []
  if (codes.length) params.audit_type_codes = codes.join(',')

  const depts =
    typeof input.dept_filter === 'string'
      ? splitCsv(input.dept_filter)
      : Array.isArray(input.dept_filter)
        ? input.dept_filter.map(String).filter(Boolean)
        : []
  if (depts.length) params.dept_filter = depts.join(',')

  const mode = String(input.audit_run_mode || '').trim()
  if (mode === 'daily_increment' || mode === 'discharge_final') {
    params.audit_run_mode = mode
  }
  return params
}

/** 手动推送核心字段（首期对齐常用路径；全量 UI 字段可后续扩展） */
export function buildManualPushBody(input: {
  query_date?: string
  date_from?: string | null
  date_to?: string | null
  date_dimension?: string
  dept_filter?: string[] | string
  audit_type_codes?: string[] | string
  dry_run?: boolean
  async_mode?: boolean
  replace_current?: boolean
  allow_rectified?: boolean
  skip_already_succeeded?: boolean
  selected_record_keys?: string[] | null
}): Record<string, unknown> {
  const codes =
    typeof input.audit_type_codes === 'string'
      ? splitCsv(input.audit_type_codes)
      : Array.isArray(input.audit_type_codes)
        ? input.audit_type_codes.filter(Boolean)
        : []
  const depts =
    typeof input.dept_filter === 'string'
      ? splitCsv(input.dept_filter)
      : Array.isArray(input.dept_filter)
        ? input.dept_filter.filter(Boolean)
        : []

  const replace = !!input.replace_current
  const dryRun = !!input.dry_run

  return {
    query_date: input.query_date || null,
    date_from: input.date_from ?? null,
    date_to: input.date_to ?? null,
    date_dimension: input.date_dimension || 'query_date',
    dept_filter: depts.length ? depts : null,
    dry_run: dryRun,
    async_mode: !!input.async_mode && !dryRun,
    audit_type_codes: codes.length ? codes : null,
    selected_record_keys: input.selected_record_keys?.length
      ? input.selected_record_keys
      : null,
    existing_result_policy: replace ? 'replace_current' : 'skip_success',
    alert_policy: replace ? 'suppress' : 'default',
    allow_rectified: !!input.allow_rectified,
    skip_already_succeeded: replace ? false : !!input.skip_already_succeeded,
  }
}

/** 确保 mutation body 不含明文 secret 回显字段名误用 */
export function assertNoSecretEchoFields(body: Record<string, unknown>): string[] {
  const bad: string[] = []
  for (const key of Object.keys(body)) {
    if (/_enc$|_masked$|password_hash/i.test(key)) bad.push(key)
  }
  return bad
}
