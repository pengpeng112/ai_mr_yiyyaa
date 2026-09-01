import { expect, test, type Page } from '@playwright/test'

// 035/RP6 legacy E2E：真实隔离后端（demo_env.py serve，端口默认 18080）。
// 运行前置：
//   python scripts/demo_env.py create && python scripts/demo_env.py serve
//   LEGACY_E2E=true npm --prefix frontend run test:e2e:legacy
test.skip(process.env.LEGACY_E2E !== 'true', 'requires scripts/demo_env.py serve + LEGACY_E2E=true')

const DEMO_ADMIN = 'demo_admin'
const DEMO_PASSWORD = 'Demo-12Dept!2026'

async function legacyLogin(page: Page) {
  // demo 环境 UI_DEFAULT_ENTRY=ui-next 会把 / 重定向到新前端；/index.html 恒为 legacy 首页
  await page.goto('/index.html')
  await expect(page.getByText('欢迎登录')).toBeVisible()
  await page.getByPlaceholder('请输入用户名').fill(DEMO_ADMIN)
  await page.getByPlaceholder('请输入密码').fill(DEMO_PASSWORD)
  await page.getByRole('button', { name: '登 录' }).click()
  // legacy 主壳：顶部工具条 + 侧边菜单出现
  await expect(page.locator('.main-area')).toBeVisible({ timeout: 20_000 })
}

async function openMenu(page: Page, groupLabel: string, itemLabel: string) {
  await page.locator('.el-menu').getByText(groupLabel, { exact: true }).first().click()
  await page.locator('.el-menu-item', { hasText: itemLabel }).first().click()
}

test('T1 登录 → 质控类型页 → prearchive 卡片渲染 14 条', async ({ page }) => {
  test.setTimeout(90_000)
  await legacyLogin(page)
  await openMenu(page, /规则与配置|治理/, '质控类型')

  const card = page.locator('.page-card', { hasText: '归档前预检规则' })
  await expect(card).toBeVisible({ timeout: 20_000 })
  // mark_item 类别渲染仓库内 14 条已授权规则；system_push 类别 0 条占位
  await expect(card.locator('.el-tag', { hasText: '14 条' })).toBeVisible()
  await expect(card.getByText('系统推送类报告规则')).toBeVisible()
  await expect(card.getByText(/0 条/)).toBeVisible()
})

test('T2 prearchive 目录不可用时 fail-open 提示', async ({ page }) => {
  test.setTimeout(90_000)
  await legacyLogin(page)
  await openMenu(page, /规则与配置|治理/, '质控类型')

  // mock 目录不可读（available=false）→ 点刷新 → fail-open 提示可见且不影响页面其余部分
  await page.route('**/api/audit-types/prearchive*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ available: false, reason: 'rules_dir_missing', categories: [] }),
    })
  })
  const card = page.locator('.page-card', { hasText: '归档前预检规则' })
  await card.getByRole('button', { name: '刷新' }).click()
  await expect(card.getByText('归档前预检规则目录不可读')).toBeVisible({ timeout: 15_000 })
  await expect(card.getByText('不影响六类推送质控')).toBeVisible()
})

test('T3 CSP 头存在且含 unsafe-eval（现状固化）', async ({ request }) => {
  const response = await request.get('/')
  expect(response.ok()).toBeTruthy()
  const csp = response.headers()['content-security-policy'] || ''
  expect(csp).toContain("script-src 'self' 'unsafe-eval'")
  expect(csp).toContain("default-src 'self'")
  expect(response.headers()['x-content-type-options']).toBe('nosniff')
})

test('T4 legacy 页面冒烟：统计口径行/质控记录/手动推送', async ({ page }) => {
  test.setTimeout(120_000)
  await legacyLogin(page)

  // 数据统计是"质控记录"页内的 tab（新版菜单树无独立菜单项）
  await openMenu(page, /质控中心|质控/, '质控记录')
  await page.locator('.el-tabs__item', { hasText: '数据统计' }).first().click()
  await expect(page.getByText('近30天推送趋势')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText('口径：仅当前结果')).toBeVisible()

  // 质控记录（logs tab，legacy 页签文案为"推送日志"）
  await page.locator('.el-tabs__item', { hasText: '推送日志' }).first().click()
  await expect(page.locator('.page-view.page-logs, .page-logs').first()).toBeVisible({ timeout: 20_000 })

  // 手动推送
  await openMenu(page, /任务中心|任务/, '手动推送')
  await expect(page.locator('.page-view.page-push, .page-push').first()).toBeVisible({ timeout: 20_000 })
})

test('T5 统计接口错误态：错误提示可见不白屏', async ({ page }) => {
  test.setTimeout(90_000)
  await legacyLogin(page)
  await page.route('**/api/stats/summary*', async (route) => {
    await route.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"boom"}' })
  })
  await openMenu(page, /质控中心|质控/, '质控记录')
  await page.locator('.el-tabs__item', { hasText: '数据统计' }).first().click()
  await expect(page.locator('.el-message--error').first()).toBeVisible({ timeout: 20_000 })
  // 页面壳仍在（不白屏）
  await expect(page.locator('.main-area')).toBeVisible()
})
