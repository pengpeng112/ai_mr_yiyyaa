export const defaultReceiverRules = {
  high: { attending_doctor: true, record_creator: true, nurse_head: true, fixed_users: [], dedupe: true, max_receivers: 5 },
  medium: { attending_doctor: true, record_creator: true, nurse_head: false, fixed_users: [], dedupe: true, max_receivers: 3 },
  low: { attending_doctor: false, record_creator: false, nurse_head: false, fixed_users: [], dedupe: true, max_receivers: 0 },
}
export function normalizeReceiverRules(input: any) {
  const result: any = {}
  for (const level of ['high', 'medium', 'low']) result[level] = { ...defaultReceiverRules[level as keyof typeof defaultReceiverRules], ...(input?.[level] || {}), fixed_users: dedupeFixedUsers(input?.[level]?.fixed_users || []) }
  return result
}
export function dedupeFixedUsers(users: Array<{ userid?: string; user_name?: string }>) { const seen = new Set<string>(); return users.filter((u) => { const id = String(u.userid || '').trim(); if (!id || seen.has(id)) return false; seen.add(id); return true }).map((u) => ({ userid: String(u.userid).trim(), user_name: String(u.user_name || '') })) }
export function buildReceiverRulesPayload(rules: any) { const normalized = normalizeReceiverRules(rules); return { rules: Object.fromEntries(['high', 'medium', 'low'].map((level) => [level, normalized[level]])) } }
export function parsePositiveInteger(value: unknown): number | null { const text = String(value ?? '').trim(); if (!/^\d+$/.test(text)) return null; const number = Number(text); return Number.isSafeInteger(number) && number > 0 ? number : null }
export const receiverReasonLabels: Record<string, string> = { empty_userid: '缺少用户 ID', duplicate_userid: '重复用户已去重', max_receivers_exceeded: '超过最大接收人数', not_configured: '未配置该接收来源' }
