import { describe, expect, it } from 'vitest'
import {
  ROUTE_MANIFEST,
  DIRECT_ACCESS_MENU_IDS,
  getManifestByMenuId,
  intersectMenuWithManifest,
} from '@/router/route-manifest'

describe('route manifest', () => {
  it('has unique menuIds and names', () => {
    const menuIds = ROUTE_MANIFEST.map((e) => e.menuId)
    const names = ROUTE_MANIFEST.map((e) => e.name)
    expect(new Set(menuIds).size).toBe(menuIds.length)
    expect(new Set(names).size).toBe(names.length)
  })

  it('every entry has lazy component and risk', () => {
    for (const entry of ROUTE_MANIFEST) {
      expect(typeof entry.component).toBe('function')
      expect(entry.path).toBeTruthy()
      expect(['readonly', 'business-write', 'system-write']).toContain(entry.risk)
    }
  })

  it('fail-closed on unknown menu id', () => {
    const { allowed, unknownIds } = intersectMenuWithManifest([
      { id: 'dashboard' },
      { id: 'not-a-real-menu' },
      { id: 'oracle-status' },
    ])
    expect(allowed.map((a) => a.id)).toEqual(['dashboard'])
    expect(unknownIds).toEqual(['not-a-real-menu', 'oracle-status'])
    expect(getManifestByMenuId('not-a-real-menu')).toBeUndefined()
  })

  it('covers core migrated pages', () => {
    for (const id of [
      'dashboard',
      'health',
      'config-runtime',
      'push-progress',
      'audit',
      'patient-qc',
      'feedback',
      'relay-alert-logs',
      'push',
      'scheduler',
      'config',
      'relay',
      'audit-types',
      'access',
      'debug',
    ]) {
      expect(getManifestByMenuId(id), id).toBeTruthy()
    }
  })

  // 2026-11-15 菜单重构：独立审批中心路由 + 侧栏隐藏兼容路由仍可直达
  it('timeliness-stats and prearchive-rules registered (WP02)', () => {
    expect(getManifestByMenuId('timeliness-stats')?.path).toBe('timeliness/stats')
    expect(getManifestByMenuId('prearchive-rules')?.path).toBe('governance/prearchive-rules')
  })

  it('timeliness-approvals exists at timeliness/approvals', () => {
    expect(getManifestByMenuId('timeliness-approvals')?.path).toBe('timeliness/approvals')
    expect(getManifestByMenuId('timeliness-approvals')?.group).toBe('timeliness')
  })

  it('hidden compat routes stay in manifest and direct-access allowlist', () => {
    for (const id of ['push-progress', 'config-runtime'] as const) {
      expect(getManifestByMenuId(id), id).toBeTruthy()
      expect(DIRECT_ACCESS_MENU_IDS.has(id)).toBe(true)
    }
  })
})
