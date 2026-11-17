import { describe, expect, it } from 'vitest'
import {
  DEFAULT_PENALTY_AMOUNT,
  NOTIFY_CHANNELS,
  ZERO_LIMIT_ALLOWED_RULE_CODES,
  buildDraft,
  diffVersions,
  draftToChanges,
  dryRunSummary,
  filterRowsToTriggerFilter,
  limitInputToMinutes,
  limitText,
  lockEmrAvailability,
  minutesToLimitInput,
  triggerFilterToFilterRows,
  validateDraft,
  validateLimit,
  type FilterRow,
  type RuleEditorDraft,
  type TlRule,
} from '@/features/timeliness/types'

// T6 §三.3：表单校验（时限必须 > 0，前置类规则如 PREOP_SUMMARY 允许 0）
describe('T6 时限校验与单位换算', () => {
  it('时限必须 > 0：0 被普通规则拒绝', () => {
    expect(validateLimit('FIRST_COURSE', { value: 0, unit: 'hour' })).toMatch('必须大于 0')
  })

  it('前置类规则 PREOP_SUMMARY 允许 0（截止=手术开始）', () => {
    expect(validateLimit('PREOP_SUMMARY', { value: 0, unit: 'minute' })).toBeNull()
    expect(ZERO_LIMIT_ALLOWED_RULE_CODES).toContain('PREOP_SUMMARY')
  })

  it('负数与非整数拒绝；空值拒绝', () => {
    expect(validateLimit('FIRST_COURSE', { value: -1, unit: 'hour' })).toMatch('负数')
    expect(validateLimit('FIRST_COURSE', { value: 1.5, unit: 'hour' })).toMatch('整数')
    expect(validateLimit('FIRST_COURSE', { value: null, unit: 'hour' })).toMatch('不能为空')
  })

  it('单位换算：分钟/小时/天/工作日 → limit_minutes（工作日同步 workday_only）', () => {
    expect(limitInputToMinutes({ value: 30, unit: 'minute' })).toBe(30)
    expect(limitInputToMinutes({ value: 8, unit: 'hour' })).toBe(480)
    expect(limitInputToMinutes({ value: 1, unit: 'day' })).toBe(1440)
    expect(limitInputToMinutes({ value: 5, unit: 'workday' })).toBe(7200)
    expect(limitInputToMinutes({ value: null, unit: 'hour' })).toBeNull()
  })

  it('反向换算：DEATH_DISCUSS 种子 7200 分钟 + workday_only → 5 工作日', () => {
    expect(minutesToLimitInput(7200, true)).toEqual({ value: 5, unit: 'workday' })
    expect(minutesToLimitInput(480, false)).toEqual({ value: 8, unit: 'hour' })
    expect(minutesToLimitInput(null, false)).toEqual({ value: null, unit: 'hour' })
    expect(limitText(7200, true)).toBe('5 工作日')
    expect(limitText(null, false)).toBe('时限待定')
  })
})

// T6 §三.3：LOCK_EMR 禁用逻辑（D8 规则 / 后端写开关）
describe('T6 LOCK_EMR 可选性判定', () => {
  const d8Codes = ['ADM_REC', 'CHIEF_FIRST_ROUND']

  it('D8 限制规则即使写开关已开也禁用，并给出 D8 原因', () => {
    for (const code of d8Codes) {
      const check = lockEmrAvailability(code, { d8NoLockCodes: d8Codes, jhemrWriteEnabled: true })
      expect(check.allowed).toBe(false)
      expect(check.reason).toContain('D8')
    }
  })

  it('后端写开关未开时其余规则同样禁用', () => {
    const check = lockEmrAvailability('FIRST_COURSE', { d8NoLockCodes: d8Codes, jhemrWriteEnabled: false })
    expect(check.allowed).toBe(false)
    expect(check.reason).toContain('jhemr_write.enabled')
  })

  it('非 D8 规则 + 写开关已开 → 允许（后端仍要求 timeliness_admin）', () => {
    expect(
      lockEmrAvailability('FIRST_COURSE', { d8NoLockCodes: d8Codes, jhemrWriteEnabled: true }).allowed,
    ).toBe(true)
  })

  it('整表校验：D8 规则选 LOCK_EMR 直接报错', () => {
    const draft = makeDraft({ rule_code: 'ADM_REC', action_mode: 'LOCK_EMR' })
    const errors = validateDraft(draft, { d8NoLockCodes: d8Codes, jhemrWriteEnabled: true })
    expect(errors.some((e) => e.includes('LOCK_EMR 当前不可选'))).toBe(true)
  })
})

// T6 §三.1 区块2：字段+运算符+值 行编辑器（不让用户手写 SQL）
describe('T6 触发过滤行编辑器 ⇄ trigger_filter_json', () => {
  it('eq 行 → 标量；in 行 → 数组（逗号/中文逗号/分号拆分）', () => {
    const rows: FilterRow[] = [
      { field: 'dept_code', op: 'eq', value: '0101' },
      { field: 'operation_scale', op: 'in', value: '三级,四级；二级' },
    ]
    expect(filterRowsToTriggerFilter(rows)).toEqual({
      dept_code: '0101',
      operation_scale: ['三级', '四级', '二级'],
    })
  })

  it('空字段/空值行被丢弃；只提供引擎支持的两种运算符', () => {
    expect(filterRowsToTriggerFilter([{ field: ' ', op: 'eq', value: '1' }, { field: 'a', op: 'eq', value: ' ' }])).toEqual({})
  })

  it('对象 → 行编辑器往返一致（标量与数组两种引擎形态）', () => {
    const filter = { dept_code: '0101', mr_class: ['EMR10.00.01', 'EMR10.00.03'] }
    const rows = triggerFilterToFilterRows(filter)
    expect(filterRowsToTriggerFilter(rows)).toEqual(filter)
  })
})

// T6 §三.1 区块4：未开通通道置灰提示「未授权」
describe('T6 通知通道授权表', () => {
  it('当前三通道均未授权且带「未授权」原因（D6/T8/FILEVERIFY 待批）', () => {
    expect(NOTIFY_CHANNELS.map((c) => c.code)).toEqual(['WECOM', 'JHEMR_TODO', 'FILEVERIFY'])
    for (const channel of NOTIFY_CHANNELS) {
      expect(channel.authorized).toBe(false)
      expect(channel.unauthorizedReason).toContain('未授权')
    }
  })
})

// T6 §三.1：草稿构建与版本改动载荷
describe('T6 草稿 → 版本改动（draftToChanges）', () => {
  it('默认扣罚 200 元；工作日单位置 workday_only；科室空列表=全院', () => {
    const draft = makeDraft({ limit: { value: 5, unit: 'workday' } })
    const changes = draftToChanges(draft)
    expect(changes.limit_minutes).toBe(7200)
    expect(changes.workday_only).toBe(true)
    expect(changes.dept_scope_json).toEqual([])
    expect(changes.penalty_amount).toBe(200)
    expect(DEFAULT_PENALTY_AMOUNT).toBe(200)
  })

  it('指定科室写入 dept_scope_json；time_ge_t0 显式入 target_json（键序无关比较）', () => {
    const draft = makeDraft({
      deptScopeAll: false,
      deptScopeCodes: ['0101', '0102'],
      timeGeT0: false,
      trigger_type: 'OPERATION_END',
    })
    const changes = draftToChanges(draft)
    expect(changes.dept_scope_json).toEqual(['0101', '0102'])
    const target = changes.target_json as Record<string, unknown>
    expect(target.time_ge_t0).toBe(false)
    expect(target.mr_class).toEqual(['EMR10.00.15'])
    expect(target.description).toBe('EMR10.00.15')
  })

  it('buildDraft 从规则+当前版本初始化（含 workday 反解与启用状态）', () => {
    const rule = makeRule()
    const draft = buildDraft(rule)
    expect(draft.rule_code).toBe('DEATH_DISCUSS')
    expect(draft.limit).toEqual({ value: 5, unit: 'workday' })
    expect(draft.enabled).toBe(false)
    expect(draft.titleKeywords).toEqual([])
  })
})

// T6 §三.3：版本差异弹窗
describe('T6 版本差异（diffVersions）', () => {
  it('仅返回有实际差异的字段（时限/单位/处置模式），文案含前后值', () => {
    const current = makeRule().current_version!
    const changes = draftToChanges(
      makeDraft({ limit: { value: 7, unit: 'day' }, action_mode: 'WARN_ONLY', timeGeT0: false }),
    )
    const rows = diffVersions(current, changes)
    expect(rows.map((r) => r.field)).toEqual(['limit_minutes', 'workday_only', 'action_mode'])
    const limitRow = rows[0]
    expect(limitRow.before).toBe('7200')
    expect(limitRow.after).toBe('10080')
    expect(limitRow.label).toBe('时限（分钟）')
  })

  it('JSON 字段按键序无关比较；无差异时返回空数组（弹窗提示内容一致）', () => {
    const current = makeRule().current_version!
    const changes = draftToChanges(
      makeDraft({
        limit: { value: 5, unit: 'workday' },
        mrClass: ['EMR10.00.15'],
        titleKeywords: [],
        monitorCode: 'JH04.02.013',
        annualTally: true,
        timeGeT0: false,
      }),
    )
    expect(diffVersions(current, changes)).toEqual([])
  })
})

// T6 §三.3：试算结果渲染
describe('T6 试算摘要（dryRunSummary）', () => {
  it('命中统计 + 状态直方图（按数量降序）+ 数据源不可用降级提示', () => {
    const summary = dryRunSummary({
      rule_code: 'FIRST_COURSE',
      base_version_no: 1,
      dry_run: true,
      data_source: 'unavailable',
      source_note: 'psycopg2 driver missing',
      patients_scanned: 0,
      stats: { events: 5, would_create: 3, would_update: 2, status_histogram: { PENDING: 2, OVERDUE: 3 } },
      samples: [],
      sample_truncated: false,
    })
    expect(summary.headline).toBe('命中 5 例：新增 3 / 更新 2（扫描患者 0 人）')
    expect(summary.histogram).toEqual([
      { status: 'OVERDUE', label: '超时未完成', count: 3 },
      { status: 'PENDING', label: '未到期', count: 2 },
    ])
    expect(summary.dataSourceNote).toContain('空数据试算')
    expect(summary.dataSourceNote).toContain('psycopg2 driver missing')
  })
})

// ---- 测试工厂 ----

function makeDraft(overrides: Partial<RuleEditorDraft> = {}): RuleEditorDraft {
  return {
    rule_code: 'DEATH_DISCUSS',
    rule_name: '死亡病例讨论',
    category: 'TIMELINESS',
    enabled: false,
    deptScopeAll: true,
    deptScopeCodes: [],
    trigger_type: 'DEATH',
    filterRows: [],
    mrClass: ['EMR10.00.15'],
    titleKeywords: [],
    signerTitleKeywords: [],
    timeGeT0: true,
    monitorCode: 'JH04.02.013',
    completion_basis: 'FIRST_SIGN',
    limit: { value: 5, unit: 'workday' },
    warnBefore: { value: 1, unit: 'hour' },
    channels: [],
    action_mode: 'SHADOW',
    penaltyAmount: DEFAULT_PENALTY_AMOUNT,
    annualTally: true,
    description: 'EMR10.00.15',
    ...overrides,
  }
}

function makeRule(): TlRule {
  return {
    id: 1,
    rule_code: 'DEATH_DISCUSS',
    rule_name: '死亡病例讨论',
    category: 'TIMELINESS',
    enabled: false,
    current_version_id: 11,
    created_at: '2026-11-10T10:00:00',
    updated_at: '2026-11-10T10:00:00',
    current_version: {
      id: 11,
      rule_id: 1,
      version_no: 1,
      trigger_type: 'DEATH',
      trigger_filter_json: '{}',
      // 与 draftToChanges(makeDraft()) 产物归一化后一致（键序无关；2026-11-14 P0：
      // 默认空态键——signer_title_contains_any/time_ge_t0/annual_penalty_tally——
      // 未显式存在时不再写出，current 版本同步移除以保持零差异口径）。
      target_json: JSON.stringify({
        description: 'EMR10.00.15',
        mr_class: ['EMR10.00.15'],
        title_contains_any: [],
        monitor_code: 'JH04.02.013',
      }),
      completion_basis: 'FIRST_SIGN',
      limit_minutes: 7200,
      workday_only: true,
      warn_before_minutes: 60,
      action_mode: 'SHADOW',
      channels_json: '[]',
      dept_scope_json: '[]',
      jhemr_monitor_code: 'JH04.02.013',
      penalty_amount: 200,
      note: null,
      created_by: 'system_seed',
      created_at: '2026-11-10T10:00:00',
    },
  }
}

// ---- 2026-11-14 P0：七规则真实种子往返零丢失 + not_in 过滤 + 高级键透传 ----

describe('P0：七规则种子 buildDraft→draftToChanges 往返零丢失', () => {
  /** 后端 2026-11-14 七规则轮 RULE_SEEDS 的 target_json/trigger_filter_json 真实口径。 */
  const SEVEN_RULES: Array<{
    code: string
    target_json: string
    trigger_filter_json?: string
  }> = [
    {
      code: 'ATTENDING_FIRST_ROUND',
      target_json:
        '{"description":"EMR10.00.03（审签身份校验，排除术后日常查房）","mr_class":["EMR10.00.03"],"title_contains_any":[],"title_excludes_any":["术后"],"require_signer_titles":["主治医师","副主任医师","主任医师"]}',
    },
    {
      code: 'RESCUE_REC',
      target_json:
        '{"description":"EMR10.00.08/EMR10.00.02，标题含“抢救”","mr_class":["EMR10.00.08","EMR10.00.02"],"title_contains_any":["抢救"],"title_excludes_any":["有创"]}',
    },
    {
      code: 'OP_REC',
      target_json:
        '{"description":"EMR05.01.02/EMR10.00.16（主刀审签）","mr_class":["EMR05.01.02","EMR10.00.16"],"title_contains_any":[],"require_surgeon_sign":true}',
      trigger_filter_json: '{"field_not_in":{"operation_type":["0"]}}',
    },
    {
      code: 'POSTOP_FIRST_COURSE',
      target_json:
        '{"description":"EMR10.00.12（排除交班/转科/出院）","mr_class":["EMR10.00.12"],"title_contains_any":[],"title_excludes_any":["交班","转科","出院"]}',
      trigger_filter_json: '{"field_not_in":{"operation_type":["0"]}}',
    },
    {
      code: 'PREOP_SUMMARY',
      target_json:
        '{"description":"EMR10.00.10（三合一豁免+连台卡口）","mr_class":["EMR10.00.10"],"title_contains_any":[],"preop_exemption":true,"require_after_prev_op_end":true}',
    },
    {
      code: 'DEATH_DISCUSS',
      target_json: '{"description":"EMR10.00.15","mr_class":["EMR10.00.15"],"title_contains_any":[]}',
    },
    {
      code: 'DEATH_REC',
      target_json:
        '{"description":"EMR10.00.14/EMR09.00.03","mr_class":["EMR10.00.14","EMR09.00.03"],"title_contains_any":[]}',
    },
  ]

  const makeVersion = (spec: { code: string; target_json: string; trigger_filter_json?: string }) =>
    ({
      id: 1,
      version_no: 1,
      trigger_type:
        spec.code === 'RESCUE_REC'
          ? 'RESCUE_ORDER'
          : spec.code === 'OP_REC' || spec.code === 'POSTOP_FIRST_COURSE'
            ? 'OPERATION_END'
            : spec.code === 'PREOP_SUMMARY'
              ? 'OPERATION_START'
              : 'ADMISSION',
      trigger_filter_json: spec.trigger_filter_json || '{}',
      target_json: spec.target_json,
      completion_basis: 'FIRST_SIGN',
      limit_minutes: 1440,
      workday_only: false,
      warn_before_minutes: null,
      action_mode: 'SHADOW',
      channels_json: '[]',
      dept_scope_json: '[]',
      jhemr_monitor_code: null,
      penalty_amount: 200,
      note: '',
      created_by: 'system_seed',
      created_at: '2026-11-14T00:00:00',
    }) as never

  const RECURRING_TRIGGER_DEFAULTS: Record<string, boolean> = {
    RESCUE_ORDER: true,
    OPERATION_END: true,
    OPERATION_START: false,
    ADMISSION: false,
  }

  it.each(SEVEN_RULES)('$code：未编辑直接保存 diffVersions === []（高级键零丢失）', (spec) => {
    const version = makeVersion(spec)
    const rule = {
      rule_code: spec.code,
      rule_name: spec.code,
      category: 'TIMELINESS',
      enabled: true,
      current_version: version,
    } as never
    const draft = buildDraft(rule)
    const changes = draftToChanges(draft)
    const rows = diffVersions(version, changes)
    expect(rows).toEqual([])
    // target_json 深比较：解析后与原种子完全一致（含扩展键/键序无关）。
    const before = JSON.parse(spec.target_json)
    const after = JSON.parse(JSON.stringify(changes.target_json))
    expect(after).toEqual(before)
  })

  it('未知高级扩展键（未来新增）经 rawTargetExtras 无损透传', () => {
    const version = makeVersion({
      code: 'FIRST_COURSE',
      target_json:
        '{"description":"x","mr_class":["EMR10.00.01"],"title_contains_any":[],"future_key":{"nested":[1,2]},"allow_apply_treat_time":false}',
    })
    const rule = { rule_code: 'FIRST_COURSE', rule_name: 'x', category: 'TIMELINESS', enabled: true, current_version: version } as never
    const after = JSON.parse(JSON.stringify(draftToChanges(buildDraft(rule)).target_json))
    expect(after.future_key).toEqual({ nested: [1, 2] })
    expect(after.allow_apply_treat_time).toBe(false)
  })
})

describe('P0：field_not_in 过滤运算符', () => {
  it('triggerFilterToFilterRows 还原 field_not_in 为 not_in 行（无 [object Object]）', () => {
    const rows = triggerFilterToFilterRows({
      field_not_in: { operation_type: ['0'] },
      apply_type: '2',
      consult_class: ['1', '2'],
    })
    expect(rows).toContainEqual({ field: 'operation_type', op: 'not_in', value: '0' })
    expect(rows).toContainEqual({ field: 'apply_type', op: 'eq', value: '2' })
    expect(rows).toContainEqual({ field: 'consult_class', op: 'in', value: '1,2' })
    expect(JSON.stringify(rows)).not.toContain('[object Object]')
  })

  it('filterRowsToTriggerFilter 聚合 not_in 回 field_not_in 嵌套形态', () => {
    const filter = filterRowsToTriggerFilter([
      { field: 'operation_type', op: 'not_in', value: '0, 9' },
      { field: 'apply_type', op: 'eq', value: '2' },
    ])
    expect(filter).toEqual({
      field_not_in: { operation_type: ['0', '9'] },
      apply_type: '2',
    })
  })

  it('OP_REC 种子过滤条件往返零丢失', () => {
    const seed = { field_not_in: { operation_type: ['0'] } }
    const round = filterRowsToTriggerFilter(triggerFilterToFilterRows(seed))
    expect(round).toEqual(seed)
  })
})
