import { describe, expect, it } from 'vitest'
import pageSource from '@/features/tasks/ManualPushPage.vue?raw'

// F-2 修复契约（2026-10-04）：推送入口的 pushLoading 置位必须发生在 ElMessageBox.confirm
// 之前——否则确认框打开期间按钮未禁用，快速双击会并发两个确认框并可能双提交。
function pushFunctionBody(source: string, name: string): string {
  const start = source.indexOf(`async function ${name}`)
  expect(start, `源码中找不到 ${name}`).toBeGreaterThanOrEqual(0)
  const next = source.indexOf('async function', start + 1)
  return source.slice(start, next < 0 ? source.length : next)
}

describe('F-2：推送入口守卫在确认框之前（双击不重入）', () => {
  it('doPush：入口守卫存在且 pushLoading 置位先于 ElMessageBox.confirm', () => {
    const body = pushFunctionBody(pageSource, 'doPush')
    expect(body).toContain('if (pushLoading.value) return')
    const setLoading = body.indexOf('pushLoading.value = true')
    const confirm = body.indexOf('ElMessageBox.confirm')
    expect(setLoading, 'doPush 应显式置位 pushLoading').toBeGreaterThanOrEqual(0)
    expect(confirm, 'doPush 应有确认框').toBeGreaterThanOrEqual(0)
    expect(setLoading).toBeLessThan(confirm)
  })

  it('pushSelected：同款守卫前置', () => {
    const body = pushFunctionBody(pageSource, 'pushSelected')
    expect(body).toContain('if (pushLoading.value) return')
    const setLoading = body.indexOf('pushLoading.value = true')
    const confirm = body.indexOf('ElMessageBox.confirm')
    expect(setLoading).toBeGreaterThanOrEqual(0)
    expect(confirm).toBeGreaterThanOrEqual(0)
    expect(setLoading).toBeLessThan(confirm)
  })

  it('两个入口均在 finally 复位 pushLoading（取消确认后可重试）', () => {
    for (const name of ['doPush', 'pushSelected']) {
      const body = pushFunctionBody(pageSource, name)
      expect(body).toContain('finally {')
      expect(body).toContain('pushLoading.value = false')
    }
  })
})
