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

export interface TimelinessAccessDraft {
  scope: '' | 'home' | 'selected' | 'all'
  department_codes: string[]
  default_view: 'home' | 'all'
}

export function timelinessAccessDraft(saved?: TimelinessAccessDraft | null): TimelinessAccessDraft {
  return {
    scope: saved?.scope || '',
    department_codes: [...(saved?.department_codes || [])],
    default_view: saved?.default_view || 'home',
  }
}

export function timelinessAccessPayload(draft: TimelinessAccessDraft) {
  return draft.scope ? {
    ...draft,
    department_codes: draft.scope === 'selected' ? draft.department_codes : [],
  } : null
}

export function roleLabel(name: string): string {
  const labels: Record<string, string> = {
    admin: '系统管理员', dept_manager: '科室管理员', clinician: '临床人员',
    auditor: '质控审核员', timeliness_reader: '时效查看员', medical_affairs: '医疗部',
  }
  return labels[name] || name || '未分配'
}
export function buildUserPayload(input: { username?: string; password?: string; full_name?: string; email?: string; dept_id?: number | null; role_id?: number | null; is_active?: boolean }, create = false): Record<string, unknown> {
  const body: Record<string, unknown> = { full_name: input.full_name, email: input.email || null, dept_id: input.dept_id ?? null, role_id: input.role_id ?? null }
  if (create) Object.assign(body, { username: input.username, password: input.password })
  else if (input.is_active !== undefined) body.is_active = input.is_active
  return body
}
