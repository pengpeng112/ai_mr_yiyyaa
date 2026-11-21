import { deepClone } from '@/utils/audit-types'
// WP06：form/rawExtras 无损往返转换（导出供单测与页面复用）。
// ruleToForm 把后端完整规则 JSON 拆成「表单接管键 + rawExtras（抽屉未接管的底层
// 扩展键）」；formToPayload 保存时 { ...rawExtras, ...mappedForm } 深合并写回，
// 保证未修改的高级配置字段（sources/sql/jsonpath/field_mapping/未知扩展键）
// 100% 零丢失（audit-type-roundtrip.test.ts 以真实 config.json.template 验证）。

/** 抽屉接管的 dify / response 叶子键（其余子键留在 rawExtras 原样透传）。 */
export const FORM_DIFY_KEYS = [
  'base_url', 'api_key', 'workflow_input_variable', 'workflow_output_key',
  'user_identifier', 'timeout_seconds',
] as const
export const FORM_RESPONSE_KEYS = [
  'parse_strategy', 'result_path', 'inconsistency_path', 'severity_path', 'risk_score_path',
] as const
const TOP_SCALAR_KEYS = [
  'code', 'name', 'description', 'enabled', 'default_for_schedule',
  'sort_order', 'dimension_codes',
] as const

export const DEFAULT_MESSAGE_TEMPLATE =
  '【AI内涵质控提醒】发现{severity}风险（{audit_type_name}）：{summary}'

export interface WizardForm {
  code: string
  name: string
  description: string
  enabled: boolean
  default_for_schedule: boolean
  sort_order: number
  dimension_codes: string
  builder: string
  base_url: string
  api_key: string
  workflow_input_variable: string
  workflow_output_key: string
  user_identifier: string
  timeout_seconds: number
  parse_strategy: string
  result_path: string
  inconsistency_path: string
  severity_path: string
  risk_score_path: string
  reminder_enabled: boolean
  delivery_mode: 'pull_api' | 'fileverify_write' | 'both'
  severities: string[]
  trigger_stage: 'before_submit' | 'on_save' | 'before_discharge'
  block_submit: boolean
  exclude_reviewed: boolean
  message_template: string
}

export function ruleToForm(cfg: Record<string, any>): { form: WizardForm; rawExtras: Record<string, any> } {
  const dify = (cfg?.dify || {}) as Record<string, unknown>
  const response = (cfg?.response || {}) as Record<string, unknown>
  const payload = (cfg?.payload || {}) as Record<string, unknown>
  const policy = (cfg?.jhemr_reminder_policy || {}) as Record<string, unknown>
  const form: WizardForm = {
    code: String(cfg?.code || ''),
    name: String(cfg?.name || ''),
    description: String(cfg?.description || ''),
    enabled: cfg?.enabled !== false,
    default_for_schedule: !!cfg?.default_for_schedule,
    sort_order: Number(cfg?.sort_order ?? 100),
    dimension_codes: Array.isArray(cfg?.dimension_codes) ? cfg.dimension_codes.join(',') : '',
    builder: String(payload.builder || ''),
    // 明文密钥绝不回显：输入框恒空，留空保存=保留旧密文
    api_key: '',
    base_url: String(dify.base_url || ''),
    workflow_input_variable: String(dify.workflow_input_variable || 'mr_txt'),
    workflow_output_key: String(dify.workflow_output_key || 'aa'),
    user_identifier: String(dify.user_identifier || 'med-audit-system'),
    timeout_seconds: Number(dify.timeout_seconds ?? 90),
    parse_strategy: String(response.parse_strategy || ''),
    result_path: String(response.result_path || ''),
    inconsistency_path: String(response.inconsistency_path || ''),
    severity_path: String(response.severity_path || ''),
    risk_score_path: String(response.risk_score_path || ''),
    reminder_enabled: !!policy.enabled,
    delivery_mode: (String(policy.delivery_mode || 'pull_api') as WizardForm['delivery_mode']),
    severities: Array.isArray(policy.severities) && policy.severities.length
      ? policy.severities.map(String)
      : ['high'],
    trigger_stage: (String(policy.trigger_stage || 'before_submit') as WizardForm['trigger_stage']),
    block_submit: !!policy.block_submit,
    exclude_reviewed: policy.exclude_reviewed !== false,
    message_template: String(policy.message_template || DEFAULT_MESSAGE_TEMPLATE),
  }
  // rawExtras：深拷贝后只深删除被接管的叶子键，兄弟扩展键（payload.dual_source、
  // dify.targets/extra_inputs、response 其它键、display、sources、join_rules 等）全保留
  const rawExtras = deepClone(cfg || {})
  delete rawExtras.jhemr_reminder_policy
  if (rawExtras.dify && typeof rawExtras.dify === 'object') {
    for (const key of FORM_DIFY_KEYS) delete rawExtras.dify[key]
  }
  if (rawExtras.response && typeof rawExtras.response === 'object') {
    for (const key of FORM_RESPONSE_KEYS) delete rawExtras.response[key]
  }
  if (rawExtras.payload && typeof rawExtras.payload === 'object') {
    delete rawExtras.payload.builder
  }
  for (const key of TOP_SCALAR_KEYS) delete rawExtras[key]
  return { form, rawExtras }
}

export function formToPayload(
  form: WizardForm,
  rawExtras: Record<string, any> | null,
): Record<string, any> {
  const out = deepClone(rawExtras || {})
  out.code = String(form.code || '')
  out.name = String(form.name || '')
  out.description = String(form.description || '')
  out.enabled = !!form.enabled
  out.default_for_schedule = !!form.default_for_schedule
  out.sort_order = Number(form.sort_order ?? 100)
  out.dimension_codes = String(form.dimension_codes || '')
    .split(',').map((s) => s.trim()).filter(Boolean)

  // payload.builder 接管；builder 为空且原无其他 payload 键时不强造空对象
  const payloadRest = (out.payload && typeof out.payload === 'object') ? out.payload : {}
  const builder = String(form.builder || '').trim()
  if (builder || Object.keys(payloadRest).length) {
    out.payload = { ...payloadRest, ...(builder ? { builder } : {}) }
  } else {
    delete out.payload
  }

  const difyRest = (out.dify && typeof out.dify === 'object') ? out.dify : {}
  const dify: Record<string, unknown> = {
    ...difyRest,
    base_url: String(form.base_url || ''),
    workflow_input_variable: String(form.workflow_input_variable || 'mr_txt'),
    workflow_output_key: String(form.workflow_output_key || 'aa'),
    user_identifier: String(form.user_identifier || 'med-audit-system'),
    timeout_seconds: Number(form.timeout_seconds ?? 90),
  }
  // 密钥留空=保留 rawExtras 里的 api_key_enc（后端 keep-existing 语义），绝不覆盖明文
  const plainKey = String(form.api_key || '').trim()
  if (plainKey) dify.api_key = plainKey
  out.dify = dify

  const responseRest = (out.response && typeof out.response === 'object') ? out.response : {}
  out.response = {
    ...responseRest,
    parse_strategy: String(form.parse_strategy || ''),
    result_path: String(form.result_path || ''),
    inconsistency_path: String(form.inconsistency_path || ''),
    severity_path: String(form.severity_path || ''),
    risk_score_path: String(form.risk_score_path || ''),
  }

  out.jhemr_reminder_policy = {
    enabled: !!form.reminder_enabled,
    delivery_mode: form.delivery_mode || 'pull_api',
    severities: (form.severities || ['high']).slice(),
    trigger_stage: form.trigger_stage || 'before_submit',
    block_submit: !!form.block_submit,
    exclude_reviewed: form.exclude_reviewed !== false,
    message_template: String(form.message_template || DEFAULT_MESSAGE_TEMPLATE),
  }
  return out
}

