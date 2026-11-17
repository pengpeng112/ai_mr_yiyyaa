/**
 * 病历时效质控（T6）共享类型与纯函数。
 *
 * - 类型与后端 app/routers/timeliness.py 的响应 dict 逐字段对齐；
 * - 表单校验 / LOCK_EMR 禁用判定 / 通道授权表 / 版本差异 / 试算摘要等纯函数集中在此，
 *   供 RuleEditorDrawer 等组件与单元测试共用（本仓库单测以纯函数 + 源码锚为主，不挂载组件）；
 * - target_json 兼作规则策略扩展位（annual_penalty_tally 等策略键）：
 *   引擎 file_matches_target 只读已知键，未知键安全忽略（app/timeliness/engine/matchers.py）。
 */

// ---- 后端响应类型（与 _rule_dict/_version_dict/_event_dict 对齐） ----

export type CompletionBasis = 'FIRST_SIGN' | 'CREATE'
export type ActionMode = 'SHADOW' | 'WARN_ONLY' | 'LOCK_EMR'
export type RuleCategory = 'TIMELINESS' | 'FREQUENCY' | 'CONTENT'

export interface TlVersion {
  id: number | null
  rule_id?: number
  version_no: number
  trigger_type: string
  trigger_filter_json: string
  target_json: string
  completion_basis: CompletionBasis
  limit_minutes: number | null
  workday_only: boolean
  warn_before_minutes: number | null
  action_mode: ActionMode
  channels_json: string
  dept_scope_json: string
  jhemr_monitor_code: string | null
  penalty_amount: number | null
  note: string | null
  created_by: string | null
  created_at: string | null
}

export interface TlRule {
  id: number
  rule_code: string
  rule_name: string
  category: RuleCategory | string
  enabled: boolean
  current_version_id: number | null
  created_at: string | null
  updated_at: string | null
  current_version: TlVersion | null
}

export interface TlEvent {
  id: number
  event_uid: string
  rule_code: string
  rule_version_id: number
  patient_id: string
  visit_id: string
  dept_code: string | null
  responsible_doctor_id: string | null
  /** 2026-11-14 P0：中文展示字段（后端 /dicts+STAFF_DICT 解析，可缺省）。 */
  dept_name?: string
  responsible_doctor_name?: string
  rule_name?: string
  /** 2026-11-15：患者姓名/住院号（本地无患者字典时为空串，前端回退 patient_id）。 */
  patient_name?: string
  inp_no?: string
  t0: string | null
  deadline: string | null
  status: string
  matched_file_unique_id: string | null
  completed_at: string | null
  overdue_minutes: number | null
  warn_sent_at: string | null
  last_scan_at: string | null
  created_at: string | null
  updated_at: string | null
}

export interface TlEventHistoryRow {
  id: number
  from_status: string | null
  to_status: string
  reason: string | null
  scan_run_id: number | null
  created_at: string | null
}

export interface TlActionLogRow {
  id: number
  action_type: string
  mode: string
  target: string | null
  operator: string | null
  result: string | null
  created_at: string | null
}

export interface TlEventDetail extends TlEvent {
  history: TlEventHistoryRow[]
  action_logs: TlActionLogRow[]
}

export interface DictOption {
  code: string
  label: string
}

export interface MrClassOption extends DictOption {
  sample_topic?: string
}

export interface MonitorItemOption {
  code: string
  label: string
  limit: string
  jhemr_generated: boolean
}

export interface TlDicts {
  trigger_types: DictOption[]
  mr_class: MrClassOption[]
  monitor_items: {
    source: string
    full_dictionary: string
    items: MonitorItemOption[]
  }
  completion_bases: string[]
  action_modes: string[]
  event_statuses: string[]
  d8_no_lock_rule_codes: string[]
  d8_note: string
  /** 2026-11-14 P0：后端写开关/通知模式现值透传（抽屉禁用态对齐后端）。 */
  jhemr_write_enabled?: boolean
  notify_mode?: string
}

export interface Paged<T> {
  total: number
  page: number
  limit: number
  items: T[]
}

export interface DryRunSample {
  event_uid: string
  patient_id: string
  visit_id: string
  dept_code: string | null
  t0: string
  deadline: string | null
  status: string
}

export interface DryRunResult {
  rule_code: string
  base_version_no: number
  dry_run: boolean
  data_source: string
  source_note: string
  patients_scanned: number
  stats: {
    events: number
    would_create: number
    would_update: number
    status_histogram: Record<string, number>
  }
  samples: DryRunSample[]
  sample_truncated: boolean
}

export interface MonthlyTotals {
  total: number
  completed_on_time: number
  completed_late: number
  overdue: number
  pending: number
  warning: number
  other: number
  /** 2026-11-13 返工新增（当月 tl_approval 扣罚口径，向后兼容字段）。 */
  approval_count: number
  approved_unlock_count: number
  exempt_count: number
  penalty_amount_total: number
}

export interface MonthlyRow {
  dept_code: string
  responsible_doctor_id: string
  /** 2026-11-14 P0：中文展示字段。 */
  dept_name?: string
  responsible_doctor_name?: string
  total: number
  completed_on_time: number
  completed_late: number
  overdue: number
  pending: number
  warning: number
  other: number
  /** 2026-11-13 返工新增：当月超时申请/解锁/豁免/应扣金额（元，与事件行同键合并）。 */
  approval_count: number
  approved_unlock_count: number
  exempt_count: number
  penalty_amount_total: number
}

export interface MonthlyStats {
  month: string
  totals: MonthlyTotals
  rows: MonthlyRow[]
}

// ---- 审批与扣罚台账（2026-11-13 返工；对齐后端 _approval_dict） ----

export type ApprovalFlag = '1' | '2' | string | null

export interface TlApproval {
  id: number
  patient_id: string
  visit_id: string
  monitor_code: string
  apply_date_time: string | null
  type: string
  flag: ApprovalFlag
  apply_user_id: string | null
  apply_reason: string | null
  /** 2026-11-14 P0：中文展示字段。 */
  apply_user_name?: string
  dept_name?: string
  /** 2026-11-15：患者/规则中文展示（后端查不到时为空串，前端回退编码）。 */
  patient_name?: string
  inp_no?: string
  rule_name?: string
  approve_user_id: string | null
  approve_date_time: string | null
  approve_channel: string | null
  dept_code: string | null
  penalty_amount: number | null
  penalty_exempt: boolean
  exempt_reason: string | null
  synced_at: string | null
}

export interface ApprovalListParams {
  page?: number
  limit?: number
  patient_id?: string
  monitor_code?: string
  flag?: string
  dept?: string
}

export interface DepartmentOption {
  id: number
  name: string
  code?: string | null
}

// ---- 常量：分类 / 单位 / 前置类规则 / 通道授权 / D8 ----

export const RULE_CATEGORY_OPTIONS: Array<{ value: RuleCategory; label: string }> = [
  { value: 'TIMELINESS', label: '时效锁定类' },
  { value: 'FREQUENCY', label: '形式频次类' },
  { value: 'CONTENT', label: '内涵规则类' },
]

export type LimitUnit = 'minute' | 'hour' | 'day' | 'workday'

export const LIMIT_UNIT_OPTIONS: Array<{ value: LimitUnit; label: string }> = [
  { value: 'minute', label: '分钟' },
  { value: 'hour', label: '小时' },
  { value: 'day', label: '天' },
  { value: 'workday', label: '工作日' },
]

const UNIT_MINUTES: Record<LimitUnit, number> = {
  minute: 1,
  hour: 60,
  day: 1440,
  // 工作日与后端存储口径一致：DEATH_DISCUSS 种子 = 5×1440 且 workday_only=true
  workday: 1440,
}

/**
 * 前置类规则：时限允许 0（截止时刻=触发时刻，如 PREOP_SUMMARY 术前小结——
 * 必须在手术开始前完成）。其余规则时限必须 > 0。
 */
export const ZERO_LIMIT_ALLOWED_RULE_CODES = ['PREOP_SUMMARY']

/** 通知通道（§11.1 区块4）。authorized=false 的通道在界面置灰并提示「未授权」。
 *
 * 当前三通道均未开通，置灰原因：
 * - WECOM：中继新消息类型契约（D6）未确认（§15.1 阻塞项，T7 只做 LOG_ONLY）；
 * - JHEMR_TODO：JHEMR 写通道未交付（T8）且 timeliness.jhemr_write.enabled 默认 false；
 * - FILEVERIFY：目标库方案待批（056 冻结口径）。
 * 授权落地后改此处 authorized 即可（后续任务可改为后端字典下发）。
 */
export type ChannelCode = 'WECOM' | 'JHEMR_TODO' | 'FILEVERIFY'

export interface ChannelDef {
  code: ChannelCode
  label: string
  authorized: boolean
  unauthorizedReason: string
}

export const NOTIFY_CHANNELS: ChannelDef[] = [
  {
    code: 'WECOM',
    label: '企业微信卡片（管床医生）',
    authorized: false,
    unauthorizedReason: '未授权：中继新消息类型契约（D6）未确认',
  },
  {
    code: 'JHEMR_TODO',
    label: 'JHEMR 待书写病历提醒（红橙倒计时）',
    authorized: false,
    unauthorizedReason: '未授权：JHEMR 写通道未开通（T8 未交付）',
  },
  {
    code: 'FILEVERIFY',
    label: 'FILEVERIFY 通道',
    authorized: false,
    unauthorizedReason: '未授权：FILEVERIFY 目标库方案待批复',
  },
]

export const ACTION_MODE_LABELS: Record<ActionMode, string> = {
  SHADOW: '影子记录（只记录不处置）',
  WARN_ONLY: '仅预警与纳入月度考核',
  LOCK_EMR: '强制锁定 JHEMR 病历（需医疗部审批解锁）',
}

/** 默认扣罚金额（元）：医疗部《住院病历时效节点信息化锁定管理规定》200 元/次（§4.3）。 */
export const DEFAULT_PENALTY_AMOUNT = 200

// ---- 时限校验与换算 ----

export interface LimitInput {
  value: number | null
  unit: LimitUnit
}

/** 时限输入 → limit_minutes + workday_only；value 为空返回 null（调用方按校验拦截）。 */
export function limitInputToMinutes(input: LimitInput): number | null {
  if (input.value === null || input.value === undefined || Number.isNaN(input.value)) return null
  return Math.round(input.value * UNIT_MINUTES[input.unit])
}

/** limit_minutes + workday_only → 表单输入（workday_only 优先按工作日展示）。 */
export function minutesToLimitInput(
  minutes: number | null,
  workdayOnly: boolean,
): LimitInput {
  if (minutes === null || minutes === undefined) return { value: null, unit: 'hour' }
  if (workdayOnly && minutes > 0 && minutes % 1440 === 0) {
    return { value: minutes / 1440, unit: 'workday' }
  }
  if (minutes % 1440 === 0) return { value: minutes / 1440, unit: 'day' }
  if (minutes % 60 === 0) return { value: minutes / 60, unit: 'hour' }
  return { value: minutes, unit: 'minute' }
}

export function limitText(minutes: number | null, workdayOnly: boolean): string {
  if (minutes === null || minutes === undefined) return '时限待定'
  const { value, unit } = minutesToLimitInput(minutes, workdayOnly)
  const label = LIMIT_UNIT_OPTIONS.find((o) => o.value === unit)?.label || unit
  return value === null ? '时限待定' : `${value} ${label}`
}

/**
 * 表单校验：时限必须 > 0；前置类规则（PREOP_SUMMARY 等）允许 0。
 * 返回错误文案；合法返回 null。
 */
export function validateLimit(ruleCode: string, input: LimitInput): string | null {
  if (input.value === null || input.value === undefined || Number.isNaN(input.value)) {
    return '时限不能为空（未定时限规则请先与医疗部确认后再配置）'
  }
  if (!Number.isInteger(input.value)) return '时限必须为整数'
  if (input.value < 0) return '时限不能为负数'
  if (input.value === 0 && !ZERO_LIMIT_ALLOWED_RULE_CODES.includes(ruleCode)) {
    return '时限必须大于 0（前置类规则如 PREOP_SUMMARY 才允许 0）'
  }
  return null
}

// ---- LOCK_EMR 禁用判定（D8 / 后端写开关） ----

export interface LockEmrCheck {
  allowed: boolean
  reason: string
}

/**
 * LOCK_EMR 可选性（§18.1 D8 / §18.4）：
 * - D8 限制规则（ADM_REC / CHIEF_FIRST_ROUND）：幽灵行原因查清前一律禁用（后端同口径 400）；
 * - 其余规则：需后端写开关 timeliness.jhemr_write.enabled=true 才可选
 *   （后端还要求 timeliness_admin 权限，前端禁用只是第一道防呆）。
 */
export function lockEmrAvailability(
  ruleCode: string,
  opts: { d8NoLockCodes: string[]; jhemrWriteEnabled: boolean },
): LockEmrCheck {
  if (opts.d8NoLockCodes.includes(ruleCode)) {
    return {
      allowed: false,
      reason: 'D8：幽灵监控行原因查清前，该规则禁止 LOCK_EMR，只能选择 SHADOW / WARN_ONLY',
    }
  }
  if (!opts.jhemrWriteEnabled) {
    return {
      allowed: false,
      reason: '后端未开写开关（timeliness.jhemr_write.enabled=false），LOCK_EMR 不可选',
    }
  }
  return { allowed: true, reason: '' }
}

// ---- 触发过滤条件：字段 + 运算符 + 值 行编辑器（不让用户手写 SQL） ----

/**
 * 引擎 apply_trigger_filter 只支持两种语义（app/timeliness/engine/triggers.py）：
 * 标量相等 / 列表任一命中。运算符集合与引擎严格对齐，不提供引擎不支持的比较符。
 */
export type FilterOperator = 'eq' | 'in' | 'not_in'

export const FILTER_OPERATOR_OPTIONS: Array<{ value: FilterOperator; label: string }> = [
  { value: 'eq', label: '等于' },
  { value: 'in', label: '属于（任一命中）' },
  { value: 'not_in', label: '不属于（排除任一命中）' },
]

export interface FilterRow {
  field: string
  op: FilterOperator
  value: string
}

/**
 * 行编辑器 → trigger_filter_json 对象。
 * - in / not_in 运算符按逗号/分号拆分为数组；
 * - not_in 聚合到引擎的 `field_not_in: {字段: [值...]}` 嵌套形态（2026-11-14 P0：
 *   旧版会把该对象 String() 成 "[object Object]" 损坏过滤条件）。
 */
export function filterRowsToTriggerFilter(
  rows: FilterRow[],
): Record<string, string | string[] | Record<string, string[]>> {
  const result: Record<string, string | string[] | Record<string, string[]>> = {}
  const notIn: Record<string, string[]> = {}
  for (const row of rows) {
    const field = row.field.trim()
    if (!field) continue
    const value = row.value.trim()
    if (!value) continue
    const list = value.split(/[,;，；]/).map((item) => item.trim()).filter(Boolean)
    if (row.op === 'in') {
      result[field] = list
    } else if (row.op === 'not_in') {
      notIn[field] = list
    } else {
      result[field] = value
    }
  }
  if (Object.keys(notIn).length > 0) result['field_not_in'] = notIn
  return result
}

/**
 * trigger_filter_json 对象 → 行编辑器。
 * 回读三种引擎形态：标量 / 数组 / `field_not_in` 嵌套对象（展开为 not_in 行）；
 * 其余未知嵌套对象跳过（不产生 "[object Object]" 脏值）。
 */
export function triggerFilterToFilterRows(filter: unknown): FilterRow[] {
  if (!filter || typeof filter !== 'object' || Array.isArray(filter)) return []
  const rows: FilterRow[] = []
  for (const [field, value] of Object.entries(filter as Record<string, unknown>)) {
    if (field === 'field_not_in' && value && typeof value === 'object' && !Array.isArray(value)) {
      for (const [innerField, innerValue] of Object.entries(value as Record<string, unknown>)) {
        const list = Array.isArray(innerValue) ? innerValue : [innerValue]
        rows.push({ field: innerField, op: 'not_in', value: list.map((v) => String(v)).join(',') })
      }
      continue
    }
    if (Array.isArray(value)) {
      rows.push({ field, op: 'in', value: value.map((v) => String(v)).join(',') })
    } else if (value !== null && value !== undefined && typeof value !== 'object') {
      rows.push({ field, op: 'eq', value: String(value) })
    }
  }
  return rows
}

// ---- 目标文书 target_json（含策略扩展键） ----

export interface TargetConfig {
  description?: string
  mr_class: string[]
  title_contains_any: string[]
  /** 职称关键词：按签名医师职称匹配的预留位，引擎当前版本忽略该键（见文件头注释）。 */
  signer_title_contains_any?: string[]
  /** 显式声明是否要求完成时间 >= t0（不写则引擎按触发类型默认值）。 */
  time_ge_t0?: boolean
  /** 策略扩展键：是否计入个人年度累计处分榜（§11.1 区块5；引擎忽略）。 */
  annual_penalty_tally?: boolean
  monitor_code?: string | string[]
  [key: string]: unknown
}

/** 引擎 REQUIRE_TIME_GE_T0_DEFAULTS 的前端镜像（app/timeliness/engine/evaluate.py）。 */
export const REQUIRE_TIME_GE_T0_DEFAULTS: Record<string, boolean> = {
  ADMISSION: false,
  DISCHARGE: false,
  DEATH: false,
  OPERATION_START: false,
  OPERATION_END: true,
  CONSULT_APPLY: true,
  RESCUE_ORDER: true,
  CRITICAL_VALUE: true,
  TRANSFUSION: true,
  ANESTHESIA_END: true,
  MANUAL_OR_INDICATOR: false,
}

export function parseTargetJson(targetJson: string | null | undefined): TargetConfig {
  if (!targetJson || !targetJson.trim()) return { mr_class: [], title_contains_any: [], signer_title_contains_any: [] }
  try {
    const parsed = JSON.parse(targetJson) as Record<string, unknown>
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { mr_class: [], title_contains_any: [], signer_title_contains_any: [] }
    }
    return parsed as TargetConfig
  } catch {
    return { mr_class: [], title_contains_any: [], signer_title_contains_any: [] }
  }
}

export function parseJsonArray(text: string | null | undefined): string[] {
  if (!text || !text.trim()) return []
  try {
    const parsed = JSON.parse(text)
    return Array.isArray(parsed) ? parsed.map((item) => String(item)) : []
  } catch {
    return []
  }
}

// ---- 编辑器草稿与版本改动 ----

export interface RuleEditorDraft {
  rule_code: string
  rule_name: string
  category: RuleCategory | string
  enabled: boolean
  deptScopeAll: boolean
  deptScopeCodes: string[]
  trigger_type: string
  filterRows: FilterRow[]
  mrClass: string[]
  titleKeywords: string[]
  signerTitleKeywords: string[]
  timeGeT0: boolean
  monitorCode: string
  completion_basis: CompletionBasis
  limit: LimitInput
  warnBefore: LimitInput
  channels: ChannelCode[]
  action_mode: ActionMode
  penaltyAmount: number
  annualTally: boolean
  /** 目标文书描述（种子/历史版本遗留的 description 键），往返保留避免误报差异。 */
  description: string
  // ---- 2026-11-14 P0：七规则高级字段显式接管 + 无损透传底盘 ----
  /** 标题排除词（title_excludes_any，如 术后/交班/有创）。 */
  titleExcludes: string[]
  /** 主治及以上职称审签（require_signer_titles）。 */
  requireSignerTitles: string[]
  /** 手术主刀本人审签（require_surgeon_sign）。 */
  requireSurgeonSign: boolean
  /** 术前小结三合一自动豁免（preop_exemption）。 */
  preopExemption: boolean
  /** 连台手术时间卡口（require_after_prev_op_end）。 */
  requireAfterPrevOpEnd: boolean
  /**
   * 表单未接管的 target_json 其余键（含未来新增高级键）——draftToChanges 原样
   * 合并回写，保证任何未知扩展键往返 100% 不丢失（P0 根因修复）。
   */
  rawTargetExtras: Record<string, unknown>
  /** 原 target 中已存在的表单接管键名（输出时决定是否写回显式值）。 */
  ownedTargetKeys: string[]
}

/** 由规则 + 当前版本初始化表单草稿。 */
/** 表单显式接管的 target_json 键（rawTargetExtras 剔除集合）。 */
export const DRAFT_OWNED_TARGET_KEYS = [
  'mr_class',
  'title_contains_any',
  'title_excludes_any',
  'require_signer_titles',
  'require_surgeon_sign',
  'preop_exemption',
  'require_after_prev_op_end',
  'signer_title_contains_any',
  'time_ge_t0',
  'annual_penalty_tally',
  'monitor_code',
  'description',
  // allow_apply_treat_time 无表单控件（会诊回退开关未实装 UI）→ 走 rawTargetExtras 透传。
] as const

export function buildDraft(rule: TlRule): RuleEditorDraft {
  const version = rule.current_version
  const target = parseTargetJson(version?.target_json)
  const deptCodes = parseJsonArray(version?.dept_scope_json)
  const channels = parseJsonArray(version?.channels_json) as ChannelCode[]
  const triggerType = version?.trigger_type || 'ADMISSION'
  const rawTargetExtras: Record<string, unknown> = {}
  const ownedTargetKeys: string[] = []
  for (const [key, value] of Object.entries(target)) {
    if ((DRAFT_OWNED_TARGET_KEYS as readonly string[]).includes(key)) {
      ownedTargetKeys.push(key)
    } else {
      rawTargetExtras[key] = value
    }
  }
  return {
    rule_code: rule.rule_code,
    rule_name: rule.rule_name,
    category: rule.category,
    enabled: rule.enabled,
    deptScopeAll: deptCodes.length === 0,
    deptScopeCodes: deptCodes,
    trigger_type: triggerType,
    filterRows: triggerFilterToFilterRows(parseTargetJson(version?.trigger_filter_json)),
    mrClass: Array.isArray(target.mr_class) ? target.mr_class : [],
    titleKeywords: Array.isArray(target.title_contains_any) ? target.title_contains_any : [],
    signerTitleKeywords: Array.isArray(target.signer_title_contains_any)
      ? target.signer_title_contains_any
      : [],
    timeGeT0:
      typeof target.time_ge_t0 === 'boolean'
        ? target.time_ge_t0
        : REQUIRE_TIME_GE_T0_DEFAULTS[triggerType] ?? false,
    monitorCode: version?.jhemr_monitor_code || '',
    completion_basis: (version?.completion_basis as CompletionBasis) || 'FIRST_SIGN',
    limit: minutesToLimitInput(version?.limit_minutes ?? null, Boolean(version?.workday_only)),
    warnBefore: minutesToLimitInput(version?.warn_before_minutes ?? null, false),
    channels,
    action_mode: (version?.action_mode as ActionMode) || 'SHADOW',
    penaltyAmount: version?.penalty_amount ?? DEFAULT_PENALTY_AMOUNT,
    annualTally: typeof target.annual_penalty_tally === 'boolean' ? target.annual_penalty_tally : true,
    description: typeof target.description === 'string' ? target.description : '',
    titleExcludes: Array.isArray(target.title_excludes_any) ? target.title_excludes_any : [],
    requireSignerTitles: Array.isArray(target.require_signer_titles)
      ? target.require_signer_titles
      : [],
    requireSurgeonSign: target.require_surgeon_sign === true,
    preopExemption: target.preop_exemption === true,
    requireAfterPrevOpEnd: target.require_after_prev_op_end === true,
    rawTargetExtras,
    ownedTargetKeys,
  }
}

/**
 * 草稿 → 提交后端的版本改动（POST /rules/{code}/versions 与 dry-run 共用）。
 *
 * 2026-11-14 P0：target_json = { ...rawTargetExtras（未接管键无损透传）, ...显式字段 }。
 * 表单接管的布尔/数组键仅在与原 target 语义有变化时写入（ownedTargetKeys 记录原
 * 存在性；未存在且值为默认空态则不写键），保证未编辑直接保存往返 diffVersions===[]
 * 且七规则高级键（preop_exemption/require_surgeon_sign 等）不被洗掉。
 */
export function draftToChanges(draft: RuleEditorDraft): Record<string, unknown> {
  // 兼容旧调用方手工构造的 draft（缺新字段时按默认空态处理）。
  const owned = new Set(draft.ownedTargetKeys || [])
  const titleExcludes = draft.titleExcludes || []
  const requireSignerTitles = draft.requireSignerTitles || []
  const requireSurgeonSign = draft.requireSurgeonSign === true
  const preopExemption = draft.preopExemption === true
  const requireAfterPrevOpEnd = draft.requireAfterPrevOpEnd === true
  const timeDefault = REQUIRE_TIME_GE_T0_DEFAULTS[draft.trigger_type] ?? false
  const target: TargetConfig = {
    ...(draft.rawTargetExtras || {}),
    mr_class: draft.mrClass,
    title_contains_any: draft.titleKeywords,
    signer_title_contains_any: draft.signerTitleKeywords,
    time_ge_t0: draft.timeGeT0,
    annual_penalty_tally: draft.annualTally,
  }
  // 接管键“原不存在且现值等于默认空态”→ 删除（保持与原 target 键集合一致）。
  if (!owned.has('signer_title_contains_any') && (draft.signerTitleKeywords || []).length === 0) {
    delete target.signer_title_contains_any
  }
  // annual_penalty_tally 同策略：原键不存在且保持默认 true → 不写（键集合与原一致）。
  if (!owned.has('annual_penalty_tally') && draft.annualTally === true) {
    delete target.annual_penalty_tally
  }
  if (!owned.has('time_ge_t0') && draft.timeGeT0 === timeDefault) {
    delete target.time_ge_t0
  }
  if (!owned.has('title_excludes_any') && titleExcludes.length === 0) {
    delete target.title_excludes_any
  } else {
    target.title_excludes_any = titleExcludes
  }
  if (!owned.has('require_signer_titles') && requireSignerTitles.length === 0) {
    delete target.require_signer_titles
  } else {
    target.require_signer_titles = requireSignerTitles
  }
  if (!owned.has('require_surgeon_sign') && requireSurgeonSign === false) {
    delete target.require_surgeon_sign
  } else {
    target.require_surgeon_sign = requireSurgeonSign
  }
  if (!owned.has('preop_exemption') && preopExemption === false) {
    delete target.preop_exemption
  } else {
    target.preop_exemption = preopExemption
  }
  if (!owned.has('require_after_prev_op_end') && requireAfterPrevOpEnd === false) {
    delete target.require_after_prev_op_end
  } else {
    target.require_after_prev_op_end = requireAfterPrevOpEnd
  }
  if (draft.description.trim()) target.description = draft.description.trim()
  if (draft.monitorCode) target.monitor_code = draft.monitorCode
  return {
    trigger_type: draft.trigger_type,
    trigger_filter_json: filterRowsToTriggerFilter(draft.filterRows),
    target_json: target,
    completion_basis: draft.completion_basis,
    limit_minutes: limitInputToMinutes(draft.limit),
    workday_only: draft.limit.unit === 'workday',
    warn_before_minutes: limitInputToMinutes(draft.warnBefore),
    action_mode: draft.action_mode,
    channels_json: draft.channels,
    dept_scope_json: draft.deptScopeAll ? [] : draft.deptScopeCodes,
    jhemr_monitor_code: draft.monitorCode || null,
    penalty_amount: draft.penaltyAmount,
  }
}

/** 草稿整表校验：返回错误文案数组（空数组=通过）。 */
export function validateDraft(
  draft: RuleEditorDraft,
  opts: { d8NoLockCodes: string[]; jhemrWriteEnabled: boolean },
): string[] {
  const errors: string[] = []
  if (!draft.rule_name.trim()) errors.push('规则名称不能为空')
  if (!draft.trigger_type) errors.push('触发源不能为空')
  if (draft.mrClass.length === 0) errors.push('目标文书（MR_CLASS）至少选择一项')
  const limitError = validateLimit(draft.rule_code, draft.limit)
  if (limitError) errors.push(limitError)
  if (draft.warnBefore.value !== null && draft.warnBefore.value < 0) {
    errors.push('提醒提前量不能为负数')
  }
  if (draft.action_mode === 'LOCK_EMR' && !lockEmrAvailability(draft.rule_code, opts).allowed) {
    errors.push('LOCK_EMR 当前不可选：' + lockEmrAvailability(draft.rule_code, opts).reason)
  }
  if (draft.penaltyAmount < 0) errors.push('扣罚金额不能为负数')
  return errors
}

// ---- 版本差异（保存前确认弹窗） ----

export interface VersionDiffRow {
  field: string
  label: string
  before: string
  after: string
}

const DIFF_FIELD_LABELS: Record<string, string> = {
  trigger_type: '触发源',
  trigger_filter_json: '触发过滤条件',
  target_json: '目标文书与策略',
  completion_basis: '完成判定基准',
  limit_minutes: '时限（分钟）',
  workday_only: '按工作日计时',
  warn_before_minutes: '提醒提前量（分钟）',
  action_mode: '超时处置模式',
  channels_json: '提醒通道',
  dept_scope_json: '适用科室',
  jhemr_monitor_code: 'JHEMR 监控码',
  penalty_amount: '扣罚金额（元）',
  note: '备注',
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '（空）'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'object') return JSON.stringify(value, null, 0)
  return String(value)
}

/**
 * 当前版本 vs 待保存改动 → 差异行。
 * changes 为 draftToChanges 产物（对象形态）；*_json 字段与当前版本 JSON 字符串解析后比较，
 * 键序无关；仅返回有实际差异的字段。
 */
export function diffVersions(
  current: TlVersion | null,
  changes: Record<string, unknown>,
): VersionDiffRow[] {
  const rows: VersionDiffRow[] = []
  const jsonFields = new Set(['trigger_filter_json', 'target_json', 'channels_json', 'dept_scope_json'])
  for (const [field, after] of Object.entries(changes)) {
    if (!(field in DIFF_FIELD_LABELS)) continue
    let before: unknown
    if (current) {
      const raw = (current as unknown as Record<string, unknown>)[field]
      before = jsonFields.has(field) ? parseJsonLoose(raw) : raw
    }
    const afterNorm = jsonFields.has(field) ? normalizeComparable(after) : after
    const beforeNorm = jsonFields.has(field) ? normalizeComparable(before) : before
    if (JSON.stringify(beforeNorm) !== JSON.stringify(afterNorm)) {
      rows.push({
        field,
        label: DIFF_FIELD_LABELS[field],
        before: jsonFields.has(field) ? prettyJson(beforeNorm) : displayValue(beforeNorm),
        after: jsonFields.has(field) ? prettyJson(afterNorm) : displayValue(afterNorm),
      })
    }
  }
  return rows
}

function parseJsonLoose(raw: unknown): unknown {
  if (typeof raw !== 'string' || !raw.trim()) return raw ?? null
  try {
    return JSON.parse(raw)
  } catch {
    return raw
  }
}

/** JSON 值归一化：数组排序、对象键排序后返回（比较口径与后端 sort_keys 序列化一致）。 */
function normalizeComparable(value: unknown): unknown {
  const normalized = parseJsonLoose(value)
  return sortDeep(normalized)
}

function sortDeep(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortDeep)
  if (value && typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) =>
      a.localeCompare(b),
    )
    const result: Record<string, unknown> = {}
    for (const [key, item] of entries) result[key] = sortDeep(item)
    return result
  }
  return value
}

function prettyJson(value: unknown): string {
  const sorted = sortDeep(parseJsonLoose(value))
  if (sorted === null || sorted === undefined) return '（空）'
  if (typeof sorted !== 'object') return String(sorted)
  return JSON.stringify(sorted)
}

// ---- 试算结果摘要（DryRunPanel 渲染辅助，纯函数便于单测） ----

export const EVENT_STATUS_LABELS: Record<string, string> = {
  PENDING: '未到期',
  WARNING: '预警中',
  OVERDUE: '超时未完成',
  APPLYING: '解锁申请中',
  APPROVED: '已批准待补写',
  COMPLETED_ON_TIME: '按时完成',
  COMPLETED_LATE: '超时完成',
  CANCELLED: '已取消',
  EXEMPT: '已豁免',
}

export function eventStatusLabel(status: string): string {
  return EVENT_STATUS_LABELS[status] || status
}

// ---- 时间线动作日志中文化（2026-11-15 P1-1，纯函数供页面与单测共用） ----

/** 动作类型中文映射：通知/写入/审批回写/扣罚豁免/事件人工豁免；未知原样返回。 */
export function actionTypeLabel(actionType: string | null | undefined): string {
  const map: Record<string, string> = {
    NOTIFY: '企微预警通知',
    TIMELINESS_NOTIFY: '企微预警通知',
    JHEMR_INSERT_MONITOR: '写入病历锁定项',
    JHEMR_APPROVE: '回写解锁审批',
    APPROVAL_EXEMPT: '扣罚豁免',
    APPROVAL_EXEMPT_CANCEL: '取消扣罚豁免',
    EVENT_EXEMPT: '事件人工豁免',
  }
  const text = String(actionType ?? '').trim()
  return map[text] || (text || '—')
}

/** 动作执行模式中文映射（供 el-tag 展示）。 */
export function actionModeExecLabel(mode: string | null | undefined): string {
  const map: Record<string, string> = {
    EXECUTED: '已执行',
    DRY_RUN: '演练预览',
    LOG_ONLY: '仅记日志(影子)',
    BLOCKED: '网关已拦截',
  }
  const text = String(mode ?? '').trim()
  return map[text] || (text || '—')
}

/** 动作执行模式 → el-tag 语义色（已知模式映射，未知 info）。 */
export function actionModeTagType(
  mode: string | null | undefined,
): 'success' | 'warning' | 'info' | 'danger' {
  const text = String(mode ?? '').trim().toUpperCase()
  if (text === 'EXECUTED') return 'success'
  if (text === 'DRY_RUN') return 'warning'
  if (text === 'BLOCKED') return 'danger'
  return 'info'
}

export interface DryRunSummary {
  headline: string
  histogram: Array<{ status: string; label: string; count: number }>
  dataSourceNote: string
}

export function dryRunSummary(result: DryRunResult): DryRunSummary {
  const { stats } = result
  const headline = `命中 ${stats.events} 例：新增 ${stats.would_create} / 更新 ${stats.would_update}（扫描患者 ${result.patients_scanned} 人）`
  const histogram = Object.entries(stats.status_histogram)
    .map(([status, count]) => ({ status, label: eventStatusLabel(status), count }))
    .sort((a, b) => b.count - a.count || a.status.localeCompare(b.status))
  const dataSourceNote =
    result.data_source === 'unavailable'
      ? `只读数据源不可用，本次对空数据试算（${result.source_note || '原因未提供'}）`
      : ''
  return { headline, histogram, dataSourceNote }
}

// ---- 审批与扣罚台账辅助（2026-11-13 返工，纯函数供页面与单测共用） ----

/** JHEMR 审批 flag：1=已申请解锁，2=审批通过（解锁），空=未申请。 */
export const APPROVAL_FLAG_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '1', label: '已申请解锁' },
  { value: '2', label: '审批通过（已解锁）' },
]

export function approvalFlagLabel(flag: string | null | undefined): string {
  const text = String(flag ?? '').trim()
  if (text === '1') return '已申请解锁'
  if (text === '2') return '审批通过'
  return '未申请'
}

export function approvalChannelLabel(channel: string | null | undefined): string {
  const map: Record<string, string> = {
    JHEMR_NATIVE: 'JHEMR 原生画布',
    PC_WEB: 'PC 网页端',
    WECOM_H5: '企微 H5',
  }
  const text = String(channel ?? '').trim()
  return map[text] || (text || '—')
}

/** 应扣金额显示：未配置金额按医疗部口径兜底 200 元；豁免显示「已豁免」。 */
export function approvalPenaltyText(approval: {
  penalty_amount?: number | null
  penalty_exempt?: boolean
}): string {
  if (approval.penalty_exempt) return '已豁免'
  const amount = approval.penalty_amount ?? DEFAULT_PENALTY_AMOUNT
  return `${amount} 元`
}
