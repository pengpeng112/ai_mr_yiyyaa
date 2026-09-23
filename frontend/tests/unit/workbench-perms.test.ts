import { describe, expect, it } from 'vitest'
import { canUsePerm, permsStateOf } from '@/features/governance/workbenchPerms'

// 054 U2 / H04：permissions 缺失 fail-closed；空数组/撤权不回退；仅精确成员命中。
describe('workbenchPerms（H04 权限判定契约）', () => {
  it('未认证 → anonymous，任何权限都不可用', () => {
    expect(permsStateOf({ permissions: ['prearchive_issue_review'] }, false)).toBe('anonymous')
    expect(canUsePerm({ permissions: ['prearchive_issue_review'] }, false, 'prearchive_issue_review')).toBe(false)
  })

  it('user 为 null → unavailable（不回退角色名）', () => {
    expect(permsStateOf(null, true)).toBe('unavailable')
    expect(canUsePerm(null, true, 'prearchive_issue_review')).toBe(false)
  })

  it('permissions 字段缺失（undefined）→ unavailable，写按钮 fail-closed', () => {
    expect(permsStateOf({}, true)).toBe('unavailable')
    expect(canUsePerm({}, true, 'prearchive_issue_feedback')).toBe(false)
  })

  it('permissions 为空数组 → ready 但无权限（不被当"字段缺失"回退）', () => {
    expect(permsStateOf({ permissions: [] }, true)).toBe('ready')
    expect(canUsePerm({ permissions: [] }, true, 'prearchive_issue_review')).toBe(false)
    expect(canUsePerm({ permissions: [] }, true, 'prearchive_issue_feedback')).toBe(false)
  })

  it('撤权（列表不含目标权限）→ false，即使角色名像管理员', () => {
    const revokedReview = { permissions: ['view_dashboard', 'prearchive_issue_feedback'] }
    expect(canUsePerm(revokedReview, true, 'prearchive_issue_review')).toBe(false)
    expect(canUsePerm(revokedReview, true, 'prearchive_issue_feedback')).toBe(true)
  })

  it('review-only（auditor 形）与 feedback-only（clinician 形）各自只开放对应动作', () => {
    const auditorLike = { permissions: ['prearchive_check_view', 'prearchive_issue_review'] }
    expect(canUsePerm(auditorLike, true, 'prearchive_issue_review')).toBe(true)
    expect(canUsePerm(auditorLike, true, 'prearchive_issue_feedback')).toBe(false)
    const clinicianLike = { permissions: ['prearchive_check_view', 'prearchive_issue_feedback'] }
    expect(canUsePerm(clinicianLike, true, 'prearchive_issue_review')).toBe(false)
    expect(canUsePerm(clinicianLike, true, 'prearchive_issue_feedback')).toBe(true)
  })

  it('管理员遵循后端契约：双权限齐 → 双动作可用', () => {
    const adminLike = { permissions: ['prearchive_issue_review', 'prearchive_issue_feedback'] }
    expect(canUsePerm(adminLike, true, 'prearchive_issue_review')).toBe(true)
    expect(canUsePerm(adminLike, true, 'prearchive_issue_feedback')).toBe(true)
  })
})
