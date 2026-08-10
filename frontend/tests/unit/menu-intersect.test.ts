import { describe, expect, it } from 'vitest'
import { intersectMenuWithManifest, ROUTE_MANIFEST } from '@/router/route-manifest'

describe('server menu ∩ manifest', () => {
  it('filters unknown and keeps authorized known ids', () => {
    const server = [
      { id: 'dashboard', label: '工作台' },
      { id: 'health', label: '系统健康' },
      { id: 'ghost-menu', label: '幽灵' },
    ]
    const { allowed, unknownIds } = intersectMenuWithManifest(server)
    expect(allowed.map((a) => a.id).sort()).toEqual(['dashboard', 'health'])
    expect(unknownIds).toEqual(['ghost-menu'])
    expect(allowed.every((a) => a.entry.component)).toBe(true)
  })

  it('does not include placeholder menu ids in manifest', () => {
    const ids = new Set(ROUTE_MANIFEST.map((e) => e.menuId))
    expect(ids.has('oracle-status')).toBe(false)
    expect(ids.has('system-logs')).toBe(false)
  })
})
