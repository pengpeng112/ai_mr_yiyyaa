export type AuditTypeSourceMap = Record<string, Record<string, unknown>>
export function deepClone<T>(value: T): T {
  if (typeof structuredClone === 'function') return structuredClone(value)
  return JSON.parse(JSON.stringify(value)) as T
}

export function sourceCardsFromConfig(sources: unknown) {
  const map = (sources && typeof sources === 'object' ? sources : {}) as AuditTypeSourceMap
  return Object.entries(map).map(([name, value]) => ({ name, source: deepClone(value) }))
}

export function applySourceCardsToConfig(config: Record<string, unknown>, cards: Array<{ name: string; source: Record<string, unknown> }>) {
  const old = (config.sources && typeof config.sources === 'object' ? config.sources : {}) as AuditTypeSourceMap
  const sources: AuditTypeSourceMap = {}
  for (const card of cards) {
    const name = card.name.trim()
    if (!name) continue
    const { mapping_entries: _mappingEntries, fanout_params_json, ...visible } = card.source as Record<string, unknown> & { mapping_entries?: unknown; fanout_params_json?: string }
    const fieldMapping = Array.isArray(_mappingEntries) ? Object.fromEntries((_mappingEntries as Array<{ key: string; value: string }>).filter((entry) => entry.key?.trim()).map((entry) => [entry.key.trim(), entry.value])) : visible.field_mapping
    let fanoutParams = visible.fanout_params
    if (typeof fanout_params_json === 'string' && fanout_params_json.trim()) {
      try { fanoutParams = JSON.parse(fanout_params_json) } catch { throw new Error(`来源 ${name} 的 fanout_params JSON 无效`) }
    }
    sources[name] = { ...(old[name] || {}), ...visible, field_mapping: fieldMapping, ...(fanoutParams !== undefined ? { fanout_params: fanoutParams } : {}) }
  }
  return { ...config, sources }
}

export function responsePathError(response: unknown): string {
  const obj = (response && typeof response === 'object' ? response : {}) as Record<string, unknown>
  for (const [key, value] of Object.entries(obj)) {
    if ((key.endsWith('_path') || key === 'path' || key.endsWith('path')) && value !== '' && value != null && !String(value).startsWith('$')) {
      return `${key} 必须以 $ 开头`
    }
  }
  return ''
}

export function validateAuditTypeJson(body: Record<string, unknown>): string {
  const sources = body.sources as Record<string, unknown> | undefined
  if (!sources || !Object.keys(sources).length) return 'sources 不能为空'
  if (Object.prototype.hasOwnProperty.call(body.payload || {}, 'mr_txt')) return 'payload 禁止出现 mr_txt，builder 输出应为 mr_text'
  return responsePathError(body.response)
}

export function patchVisibleAuditFields(config: Record<string, unknown>, fields: Record<string, unknown>) {
  const result = { ...config, ...fields }
  for (const key of ['payload', 'dify', 'response']) {
    if (fields[key] && typeof fields[key] === 'object') {
      result[key] = { ...(config[key] as Record<string, unknown> || {}), ...(fields[key] as Record<string, unknown>) }
    }
  }
  return result
}
