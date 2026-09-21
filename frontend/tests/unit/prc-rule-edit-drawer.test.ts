import { describe, expect, it } from 'vitest'
import drawerSource from '@/features/governance/components/PrcRuleEditDrawer.vue?raw'
import pageSource from '@/features/governance/AuditTypesPage.vue?raw'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
const legacySource = readFileSync(
  resolve(process.cwd(), '../static/scripts/modules/prearchive_rule_center.js'), 'utf-8')

describe('046 T4/F10: 两套前端新建/编辑入口与非法 JSON 契约', () => {
  it('ui-next 抽屉存在且经 BFF API（不直连预检服务）', () => {
    expect(drawerSource).toContain('prcCreateDraftApi')
    expect(drawerSource).toContain('prcUpdateDraftApi')
    expect(drawerSource).not.toContain(':8600')
    expect(drawerSource).not.toMatch(/https?:\/\//)
  })

  it('ui-next 非法 JSON 拒绝保存（不静默回落 {}）', () => {
    // 严格校验：JSON.parse 失败 → 拒绝（不再 catch 后置 {}）
    expect(drawerSource).toContain('不会静默清空')
    const silentFallback = /catch\s*\{\s*(content\.(trigger|match)\s*=\s*\{\}|match\s*=\s*\{\})/
    expect(drawerSource).not.toMatch(silentFallback)
  })

  it('ui-next 表单化优先 + JSON 仅高级入口', () => {
    expect(drawerSource).toContain('高级：整段 JSON')
    expect(drawerSource).toContain('content_json')
  })

  it('AuditTypesPage 提供新建/编辑/复制三个入口', () => {
    expect(pageSource).toContain('openPrcCreate')
    expect(pageSource).toContain('openPrcEdit')
    expect(pageSource).toContain('openPrcCopy')
    expect(pageSource).toContain('PrcRuleEditDrawer')
  })

  it('legacy 同契约：非法 JSON 拒绝提交（046 T4 迁移）', () => {
    expect(legacySource).toContain('不会静默清空')
    const silentFallback = /catch\s*\{\s*content\.(trigger|match)\s*=\s*\{\}\s*\}/
    expect(legacySource).not.toMatch(silentFallback)
  })
})
