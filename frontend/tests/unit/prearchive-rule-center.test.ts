import { describe, expect, it } from 'vitest'
import moduleSource from '@/api/endpoints/prearchiveAdmin.ts?raw'
import pageSource from '@/features/governance/AuditTypesPage.vue?raw'
import {
  prcContractTestApi,
  prcCreateDraftApi,
  prcPublishApi,
  prcRollbackApi,
  prcSettingsApi,
} from '@/api/endpoints/prearchiveAdmin'
import { prcDisabledReasonFromError, prcDisabledTitleFromReason } from '@/utils/prc-degradation'

describe('prearchive rule center API contracts (039 T8)', () => {
  it('routes every call through the BFF whitelist prefix', () => {
    // 源码级白名单锚：与后端 ALLOWED_TARGETS 对应，禁止直连预检服务
    expect(moduleSource).toContain("/prearchive-admin/settings")
    expect(moduleSource).toContain("/prearchive-admin/rules")
    expect(moduleSource).toContain("/prearchive-admin/destinations")
    expect(moduleSource).toContain("/prearchive-admin/outbox")
    expect(moduleSource).not.toContain(':8600')
    expect(moduleSource).not.toMatch(/https?:\/\//)
  })

  it('encodes path parameters for rule keys and outbox ids', () => {
    for (const fn of [prcPublishApi, prcRollbackApi, prcContractTestApi]) {
      expect(fn.toString()).toContain('encodeURIComponent')
    }
  })

  it('settings api takes no untrusted path input', () => {
    expect(prcSettingsApi).toBeInstanceOf(Function)
    expect(prcSettingsApi.length).toBe(0)
    expect(prcCreateDraftApi.length).toBe(1)
  })

  it('types cover lifecycle / destinations / outbox shapes', () => {
    expect(moduleSource).toContain('PrcRuleRow')
    expect(moduleSource).toContain('PrcSettings')
    expect(moduleSource).toContain('PrcDestination')
    expect(moduleSource).toContain('PrcOutboxRow')
    expect(moduleSource).toContain("'dead'")
    expect(moduleSource).toContain('preview_only: boolean')
  })
})

describe('prearchive rule center degradation copy (041 T6)', () => {
  const suffix = '。上方六类质控类型管理不受影响。'

  it('BFF 503/502 → 「规则中心不可用」（服务故障口径）', () => {
    for (const status of [502, 503]) {
      const reason = prcDisabledReasonFromError({ response: { status } })
      expect(reason).toContain('规则中心不可用')
      expect(prcDisabledTitleFromReason(reason, suffix)).toContain('规则中心不可用')
    }
  })

  it('BFF 403 → 「无访问权限」且不写成服务故障', () => {
    const reason = prcDisabledReasonFromError({ response: { status: 403 } })
    expect(reason).toContain('无访问权限')
    expect(reason).toContain('prearchive_rule_view')
    const title = prcDisabledTitleFromReason(reason, suffix)
    expect(title.startsWith('无访问权限')).toBe(true)
    expect(title).not.toContain('规则中心不可用')
  })

  it('page wires shared degradation copy and renders rule rows (mock 200 契约)', () => {
    // UI Next 页面复用共享口径，且 BFF 200 时规则表绑定 prcRules 渲染列表
    expect(pageSource).toContain('prcDisabledReasonFromError')
    expect(pageSource).toContain('prcDisabledTitleFromReason')
    expect(pageSource).toContain(':data="prcRules"')
    expect(pageSource).toContain('prcRules.value = data.items || []')
  })
})
