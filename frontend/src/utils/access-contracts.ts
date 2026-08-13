export function roleIdByName(roles: Array<{ id?: number; name?: string }>, name: unknown): number | null {
  const role = roles.find((item) => item.name === name)
  return role?.id == null ? null : Number(role.id)
}
export function hasAssignment(items: Array<{ id?: number | string }>, id: number | string): boolean {
  return items.some((item) => String(item.id) === String(id))
}
export function relationCount(users: Array<{ dept_id?: number | null }>, deptId: number): number {
  return users.filter((user) => Number(user.dept_id) === deptId).length
}
export function requiresOldPassword(targetId: number, currentId: number | undefined): boolean { return Number(targetId) === Number(currentId) }
export function buildUserPayload(input: { username?: string; password?: string; full_name?: string; email?: string; dept_id?: number | null; role_id?: number | null; is_active?: boolean }, create = false): Record<string, unknown> {
  const body: Record<string, unknown> = { full_name: input.full_name, email: input.email || null, dept_id: input.dept_id ?? null, role_id: input.role_id ?? null }
  if (create) Object.assign(body, { username: input.username, password: input.password })
  else if (input.is_active !== undefined) body.is_active = input.is_active
  return body
}
