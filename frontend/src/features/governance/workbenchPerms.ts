/**
 * 核查工作台写按钮权限判定（054 U2：permissions 缺失 fail-closed）。
 *
 * 契约：
 * - permissions 为数组（含空数组）时按精确成员判定，不回退角色名近似；
 *   空数组/显式撤权 = 无写按钮。
 * - permissions 缺失（字段不在 / 未加载）= unavailable：写按钮一律不显示，
 *   页面提供「重新加载权限」重试入口（auth.refreshUser 重拉 /users/me）。
 * - 未认证 = anonymous：同 unavailable，不显示写动作。
 * - 后端 403 仍是最终门；本判定只决定按钮可见性，不代替服务端授权。
 */

export type PermsState = 'anonymous' | 'unavailable' | 'ready'

export interface PermsUserLike {
  permissions?: string[]
}

export function permsStateOf(
  user: PermsUserLike | null | undefined,
  isAuthenticated: boolean,
): PermsState {
  if (!isAuthenticated) return 'anonymous'
  if (!user || !Array.isArray(user.permissions)) return 'unavailable'
  return 'ready'
}

/** 只有 permissions 明确包含该权限才返回 true；缺失/空数组/未认证一律 false。 */
export function canUsePerm(
  user: PermsUserLike | null | undefined,
  isAuthenticated: boolean,
  permission: string,
): boolean {
  if (permsStateOf(user, isAuthenticated) !== 'ready') return false
  return (user as PermsUserLike & { permissions: string[] }).permissions.includes(permission)
}
