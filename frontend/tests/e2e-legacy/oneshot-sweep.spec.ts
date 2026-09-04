import { expect, test } from '@playwright/test'
import fs from 'node:fs'

test.skip(process.env.LEGACY_E2E !== 'true', 'requires demo_env serve + LEGACY_E2E=true')

// 固定菜单标签导航（不迭代 DOM，防卡死）：每次点击 5s 超时，失败记录不中断
const PAGES = ['工作台', '患者质控', '质控记录', '告警记录', '整改反馈', '手动推送', '任务进度',
  '定时任务', '质控类型', '系统配置', '告警推送', '运行总览', '系统健康', '用户与权限', '调试']
const GROUPS = ['质控中心', '闭环管理', '任务中心', '规则与配置', '系统管理']

test('legacy 全页扫荡', async ({ page }) => {
  test.setTimeout(240_000)
  const rows: Array<{ page: string; consoleErrors: string[]; failedApi: string[]; navFail?: boolean }> = []
  let current = rows[0]
  page.on('console', (m) => { if (m.type() === 'error') current?.consoleErrors.push(m.text().slice(0, 200)) })
  page.on('response', (r) => { if (r.status() >= 400 && !r.url().includes('favicon')) current?.failedApi.push(`${r.status()} ${r.url().slice(0, 160)}`) })

  await page.goto('/index.html')
  await page.getByPlaceholder('请输入用户名').fill('demo_admin')
  await page.getByPlaceholder('请输入密码').fill('Demo-12Dept!2026')
  await page.getByRole('button', { name: '登 录' }).click()
  await expect(page.locator('.main-area')).toBeVisible({ timeout: 20_000 })

  for (const label of PAGES) {
    current = { page: label, consoleErrors: [], failedApi: [] }
    rows.push(current)
    const item = page.locator('.el-menu-item', { hasText: label }).first()
    if (!(await item.isVisible().catch(() => false))) {
      for (const g of GROUPS) {
        await page.locator('.el-sub-menu__title', { hasText: g }).first().click({ timeout: 2000 }).catch(() => {})
      }
      await page.waitForTimeout(400)
    }
    const ok = await item.isVisible().catch(() => false)
      ? await item.click({ timeout: 5000 }).then(() => true).catch(() => false)
      : false
    if (!ok) { current.navFail = true; continue }  // 菜单不存在/不可达：记录为覆盖缺口而非白屏
    await page.waitForTimeout(800)
    const alive = await page.locator('.main-area').isVisible().catch(() => false)
    if (!alive) current.consoleErrors.push('[BLANK_PAGE] .main-area 不可见')
  }
  // 质控记录页内两个 tab
  current = { page: 'audit-tab-stats', consoleErrors: [], failedApi: [] }
  rows.push(current)
  await page.locator('.el-tabs__item', { hasText: '数据统计' }).first().click({ timeout: 5000 }).catch(() => {})
  await page.waitForTimeout(800)
  current = { page: 'audit-tab-logs', consoleErrors: [], failedApi: [] }
  rows.push(current)
  await page.locator('.el-tabs__item', { hasText: '推送日志' }).first().click({ timeout: 5000 }).catch(() => {})
  await page.waitForTimeout(800)

  const summary = rows.map(r => `${r.page}${r.navFail ? ' [NAV_FAIL]' : ''} | errors=${r.consoleErrors.length} | failedApi=${r.failedApi.length}${r.consoleErrors[0] ? ' | first=' + r.consoleErrors[0] : ''}${r.failedApi[0] ? ' | api=' + r.failedApi[0] : ''}`)
  console.log('=== LEGACY SWEEP ===' + String.fromCharCode(10) + summary.join(String.fromCharCode(10)))
  fs.mkdirSync('../review/oneshot-20260901/附件', { recursive: true })
  fs.writeFileSync('../review/oneshot-20260901/附件/legacy_sweep.txt', summary.join(String.fromCharCode(10)))
  const blanks = rows.filter(r => r.consoleErrors.some(e => e.startsWith('[BLANK_PAGE]')))
  expect(blanks.map(b => b.page)).toEqual([])
})
