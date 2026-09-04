import { expect, test } from '@playwright/test'

// 默认跳过：该扫荡需要真后端 demo 环境（037 RP-I / O-5）。
// 复跑方式（真后端 demo）：
//   ONESHOT_E2E=true PLAYWRIGHT_SKIP_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:18080/ui-next/ \
//   npx playwright test -c playwright.config.ts oneshot-uinext-sweep --project=desktop-1366
test.skip(process.env.ONESHOT_E2E !== 'true', 'requires demo_env serve + ONESHOT_E2E=true')

import fs from 'node:fs'

const ROUTES = [
  'workbench', 'quality/patients', 'quality/records', 'closure/alerts', 'closure/feedback',
  'tasks/push', 'tasks/progress', 'tasks/scheduler', 'governance/audit-types',
  'governance/config', 'governance/relay', 'system/runtime', 'system/health', 'system/access',
  'system/debug',  // 只打开断言可渲染，禁止点击发送/探测类按钮
]

test('ui-next 全路由扫荡（真后端）', async ({ page }) => {
  test.setTimeout(300_000)
  const rows: Array<{ route: string; errors: string[]; failed: string[] }> = []
  let current = { route: '(login)', errors: [] as string[], failed: [] as string[] }
  rows.push(current)
  page.on('console', (m) => { if (m.type() === 'error') current.errors.push(m.text().slice(0, 200)) })
  page.on('response', (r) => { if (r.status() >= 400 && !r.url().includes('favicon')) current.failed.push(`${r.status()} ${r.url().slice(0, 160)}`) })

  await page.goto('./#/login')
  await page.getByPlaceholder('请输入用户名').fill('demo_admin')
  await page.getByPlaceholder('请输入密码').fill('Demo-12Dept!2026')
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.locator('.app-shell')).toBeVisible({ timeout: 20_000 })

  for (const route of ROUTES) {
    current = { route, errors: [], failed: [] }
    rows.push(current)
    await page.goto(`./#/${route}`)
    await page.waitForTimeout(1500)
    const blank = (await page.locator('main').count()) === 0 || !(await page.locator('main').first().isVisible().catch(() => false))
    if (blank) current.errors.push('[BLANK_PAGE] main 不可见')
  }

  const summary = rows.map(r => `${r.route} | errors=${r.errors.length} | failedApi=${r.failed.length}${r.errors[0] ? ' | first=' + r.errors[0] : ''}${r.failed[0] ? ' | api=' + r.failed[0] : ''}`)
  console.log('=== UINEXT SWEEP ===\n' + summary.join('\n'))
  fs.mkdirSync('../review/oneshot-20260901/附件', { recursive: true }); fs.writeFileSync('../review/oneshot-20260901/附件/uinext_sweep.txt', summary.join('\n'))
  const blanks = rows.filter(r => r.errors.some(e => e.startsWith('[BLANK_PAGE]')))
  expect(blanks.map(b => b.route)).toEqual([])
})
