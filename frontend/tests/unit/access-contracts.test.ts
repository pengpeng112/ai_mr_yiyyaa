import { describe, expect, it } from 'vitest'
import { buildUserPayload, hasAssignment, relationCount, requiresOldPassword, roleIdByName } from '@/utils/access-contracts'
describe('access contracts', () => {
  it('maps role name and assignment membership', () => {
    expect(roleIdByName([{ id: 2, name: 'admin' }], 'admin')).toBe(2)
    expect(hasAssignment([{ id: 'x' }], 'x')).toBe(true)
  })
  it('counts department users and builds mutation payload', () => {
    expect(relationCount([{ dept_id: 3 }, { dept_id: 3 }, { dept_id: 4 }], 3)).toBe(2)
    expect(buildUserPayload({ username: 'u', password: 'secret1', full_name: 'U', role_id: 2 }, true)).toMatchObject({ username: 'u', password: 'secret1', role_id: 2 })
  })
  it('requires old password only when changing own password', () => {
    expect(requiresOldPassword(2, 2)).toBe(true)
    expect(requiresOldPassword(3, 2)).toBe(false)
  })
})
