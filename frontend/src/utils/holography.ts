/**
 * 360 全息视图工具（WP02 T3，064 D1 拍板）：
 * - 全部参数后台可配（base_url/sys_code/user_code 由后端统一计算下发）；
 * - 前端不做任何工号判断，直接用后端返回的 cfg.user_code；
 * - DEFAULT_HOLOGRAPHY_CONFIG.enabled=false：未加载成功前不渲染按钮，避免误显示。
 */
import { ElMessage } from 'element-plus'
import { apiGet } from '@/api/client'

export interface HolographyConfig {
  enabled: boolean
  base_url: string
  sys_code: string
  enable_on_mobile: boolean
  user_code: string
}

export const DEFAULT_HOLOGRAPHY_CONFIG: HolographyConfig = {
  enabled: false,
  base_url: '',
  sys_code: 'S28',
  enable_on_mobile: false,
  user_code: '',
}

let cachedPromise: Promise<HolographyConfig> | null = null

/** 清空 360 全息配置缓存（登出 / 切换账号 / 保存配置后调用）。 */
export function resetHolographyCache(): void {
  cachedPromise = null
}

/** 模块级缓存 Promise，走统一 apiGet（兼容 Cookie/Bearer）；失败时重置缓存防永久锁死。 */
export function loadHolographyConfig(force = false): Promise<HolographyConfig> {
  if (!force && cachedPromise) return cachedPromise
  const req = apiGet<Partial<HolographyConfig>>('/config/holography')
    .then((data) => ({
      enabled: data?.enabled === true,
      base_url: String(data?.base_url || ''),
      sys_code: String(data?.sys_code || 'S28'),
      enable_on_mobile: data?.enable_on_mobile === true,
      user_code: String(data?.user_code || ''),
    }))
    .catch(() => {
      if (cachedPromise === req) cachedPromise = null
      return { ...DEFAULT_HOLOGRAPHY_CONFIG }
    })
  cachedPromise = req
  return req
}

/**
 * 精确规则（任务书 §三.3.2）：
 * enabled=false / user_code 空 / patientId 空 → null；
 * 否则 new URL(base_url) 依次 set patientId/userCode/sysCode。
 */
export function buildHolographyUrl(patientId: string | null | undefined, cfg: HolographyConfig): string | null {
  if (!cfg?.enabled) return null
  if (!cfg.user_code) return null
  const pid = String(patientId || '').trim()
  if (!pid) return null
  try {
    const url = new URL(cfg.base_url)
    url.searchParams.set('patientId', pid)
    url.searchParams.set('userCode', cfg.user_code)
    url.searchParams.set('sysCode', cfg.sys_code || 'S28')
    return url.toString()
  } catch {
    return null
  }
}

/** 新窗口打开；被拦截时友好提示。 */
export function openHolography360(patientId: string | null | undefined, cfg: HolographyConfig): void {
  const url = buildHolographyUrl(patientId, cfg)
  if (!url) return
  const win = window.open(url, '_blank', 'noopener,noreferrer')
  if (!win) {
    ElMessage.warning('浏览器拦截了新窗口，请允许本站弹出窗口后重试')
  }
}
