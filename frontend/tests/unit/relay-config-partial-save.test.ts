/**
 * WP09：企微接收人配置局部保存测试（任务书 §六）。
 * 直测 utils/relay-partial.ts（页面 buildRelayPartialBody 的纯函数载体）：
 * 只改「生效科室」→ 提交体仅含 alert_dept_filter；base_url 清空不提交；
 * secret_key 留空不提交；无改动 noop（回退完整局部体 enabled 必发）。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { buildRelayPartialBody, type RelayFormSnapshot } from '@/utils/relay-partial'
import pageSource from '@/features/governance/RelayConfigPage.vue?raw'

const pagePath = resolve(process.cwd(), 'src/features/governance/RelayConfigPage.vue')
const page = readFileSync(pagePath, 'utf-8')

function snap(overrides: Partial<RelayFormSnapshot> = {}): RelayFormSnapshot {
  return {
    enabled: false,
    base_url: 'http://10.20.1.153:3000',
    endpoint: '/qc-record-alert',
    secret_key: '',
    severity_levels: ['high'],
    alert_dept_filter: [],
    source: '病历质控系统',
    ...overrides,
  }
}

describe('WP09：局部保存 diff（buildRelayPartialBody 纯函数）', () => {
  it('只改「生效科室」时提交体仅含 alert_dept_filter', () => {
    const body = buildRelayPartialBody(snap(), snap({ alert_dept_filter: ['听觉植入科'] }))
    expect(Object.keys(body)).toEqual(['alert_dept_filter'])
    expect(body.alert_dept_filter).toEqual(['听觉植入科'])
  })

  it('base_url 清空（或未改动）时提交体不含 base_url（防覆盖）', () => {
    const body = buildRelayPartialBody(snap(), snap({ base_url: '' }))
    expect('base_url' in body).toBe(false)
    const body2 = buildRelayPartialBody(snap(), snap())
    expect('base_url' in body2).toBe(false)
    // 改为非空新地址 → 提交
    const body3 = buildRelayPartialBody(snap(), snap({ base_url: 'http://10.20.1.154:3000' }))
    expect(body3.base_url).toBe('http://10.20.1.154:3000')
  })

  it('secret_key 留空不提交（保护 secret_key_enc）；有值才提交', () => {
    const body = buildRelayPartialBody(snap(), snap({ secret_key: '' }))
    expect('secret_key' in body).toBe(false)
    const body2 = buildRelayPartialBody(snap(), snap({ secret_key: 'new-secret' }))
    expect(body2.secret_key).toBe('new-secret')
  })

  it('多项改动合并提交（enabled+severity_levels+alert_dept_filter）', () => {
    const body = buildRelayPartialBody(snap(), snap({
      enabled: true,
      severity_levels: ['high', 'medium'],
      alert_dept_filter: ['耳鼻喉一科'],
    }))
    expect(body.enabled).toBe(true)
    expect(body.severity_levels).toEqual(['high', 'medium'])
    expect(body.alert_dept_filter).toEqual(['耳鼻喉一科'])
    expect('base_url' in body).toBe(false)
    expect('secret_key' in body).toBe(false)
    expect('endpoint' in body).toBe(false)
  })

  it('页面接入 util：loadedSnapshot 快照 diff + 无改动 noop 提示 + 只提交改动字段文案', () => {
    expect(page).toContain("from '@/utils/relay-partial'")
    expect(page).toContain('loadedSnapshot: RelayFormSnapshot')
    expect(page).toContain('没有改动字段，无需保存')
    expect(page).toContain('只提交改动字段')
  })
})

describe('WP09：RelayConfigPage 三页签与端点契约', () => {
  it('三页签（推送开关与前置机/科室接收人规则/护士长重点接收人）', () => {
    for (const label of ['推送开关与前置机', '科室接收人规则', '护士长/重点接收人']) {
      expect(page).toContain(label)
    }
    expect(page).toContain('el-tabs v-model="activeTab"')
  })

  it('生效科室多选 filterable（alert_dept_filter，不选=全院）', () => {
    expect(page).toContain('生效科室（不选表示全院生效）')
    expect(page).toContain('multiple')
    expect(page).toContain('filterable')
    expect(page).toContain('allow-create')
  })

  it('全部既有端点保留（relay-alert/receiver-config/receiver-rules/search-user/preview/test-nurse-head）', () => {
    for (const endpoint of [
      "'/config/relay-alert'",
      "'/relay/receiver-config'",
      "'/relay/receiver-rules'",
      "'/relay/search-user'",
      "'/relay/preview-receivers'",
      "'/relay/test-nurse-head'",
    ]) {
      expect(page).toContain(endpoint)
    }
  })

  it('规则表三档折叠 + 固定人员 closable tag + 接收人预览未纳入原因', () => {
    expect(page).toContain('levelTitle(level)')
    expect(page).toContain('高风险（红灯）')
    expect(page).toContain('closable')
    expect(page).toContain('receiverReasonLabels')
    expect(page).toContain('查询预览')
  })
})
