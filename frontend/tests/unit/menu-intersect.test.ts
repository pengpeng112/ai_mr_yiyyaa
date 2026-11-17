import { describe, expect, it } from 'vitest'
import { intersectMenuWithManifest, ROUTE_MANIFEST } from '@/router/route-manifest'

describe('server menu ∩ manifest', () => {
  it('filters unknown and keeps authorized known ids', () => {
    const server = [
      { id: 'dashboard', label: '质控总览' },
      { id: 'health', label: '系统健康状态' },
      { id: 'ghost-menu', label: '幽灵' },
    ]
    const { allowed, unknownIds } = intersectMenuWithManifest(server)
    expect(allowed.map((a) => a.id).sort()).toEqual(['dashboard', 'health'])
    expect(unknownIds).toEqual(['ghost-menu'])
    expect(allowed.every((a) => a.entry.component)).toBe(true)
  })

  // 2026-11-15 菜单重构：timeliness 分组（解锁审批/台账/月报）与 manifest 对齐
  it('timeliness group items intersect with manifest entries', () => {
    const server = [
      { id: 'timeliness-approvals', label: '解锁审批与豁免', group: 'timeliness' },
      { id: 'timeliness-events', label: '在院时效台账', group: 'timeliness' },
      { id: 'timeliness-monthly', label: '时效月度考核', group: 'timeliness' },
    ]
    const { allowed, unknownIds } = intersectMenuWithManifest(server)
    expect(allowed.map((a) => a.id)).toEqual(server.map((s) => s.id))
    expect(allowed.every((a) => a.entry.group === 'timeliness')).toBe(true)
    expect(unknownIds).toEqual([])
  })

  it('does not include placeholder menu ids in manifest', () => {
    const ids = new Set(ROUTE_MANIFEST.map((e) => e.menuId))
    expect(ids.has('oracle-status')).toBe(false)
    expect(ids.has('system-logs')).toBe(false)
  })
})
