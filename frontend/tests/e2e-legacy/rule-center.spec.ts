import { expect, test, type Page, type Response } from '@playwright/test'

// 041 T6 归档前规则中心 Legacy E2E（真实隔离后端 demo_env.py serve:18080 + 可选 sidecar:18600）。
//
// 正向轮编排（042 抄送的两步命令）：
//   # 终端 A：python scripts/run_prearchive_demo_sidecar_20260904.py --serve --import-rules
//   # 终端 B：python scripts/demo_env.py serve --run-id <run_id>   （首次先 create）
//   LEGACY_E2E=true npx --prefix frontend playwright test -c frontend/playwright.legacy.config.ts tests/e2e-legacy/rule-center.spec.ts
//
// 降级轮：停掉终端 A（sidecar 不在），主服务仍 DEMO_MODE，加 RULE_CENTER_SIDECAR=0 跑同 spec：
//   RULE_CENTER_SIDECAR=0 LEGACY_E2E=true npx --prefix frontend playwright test -c frontend/playwright.legacy.config.ts tests/e2e-legacy/rule-center.spec.ts
test.skip(process.env.LEGACY_E2E !== 'true', 'requires scripts/demo_env.py serve + LEGACY_E2E=true')

const DEGRADED = process.env.RULE_CENTER_SIDECAR === '0'
const DEMO_ADMIN = 'demo_admin'
const DEMO_PASSWORD = 'Demo-12Dept!2026'

function trackFailedApi(page: Page): string[] {
  const failedApi: string[] = []
  page.on('response', (response: Response) => {
    if (response.status() >= 400 && response.url().includes('/api/')) {
      failedApi.push(`${response.status()} ${response.url()}`)
    }
  })
  return failedApi
}

async function legacyLogin(page: Page) {
  await page.goto('/index.html')
  await expect(page.getByText('欢迎登录')).toBeVisible()
  await page.getByPlaceholder('请输入用户名').fill(DEMO_ADMIN)
  await page.getByPlaceholder('请输入密码').fill(DEMO_PASSWORD)
  await page.getByRole('button', { name: '登 录' }).click()
  await expect(page.locator('.main-area')).toBeVisible({ timeout: 20_000 })
}

async function openAuditTypesPage(page: Page) {
  await page.locator('.el-menu').getByText(/规则与配置|治理/, { exact: true }).first().click()
  await page.locator('.el-menu-item', { hasText: '质控类型' }).first().click()
}

test('规则中心正向：sidecar 在 → 列表 14 条 + 试运行可用', async ({ page }) => {
  test.skip(DEGRADED, 'degradation round (RULE_CENTER_SIDECAR=0) skips positive case')
  test.setTimeout(120_000)
  const failedApi = trackFailedApi(page)

  await legacyLogin(page)
  await openAuditTypesPage(page)
  const card = page.locator('.page-card', { hasText: '归档前规则中心' })
  await expect(card).toBeVisible({ timeout: 30_000 })

  // 表非空：14 条已授权正式规则（published）
  const rows = card.locator('.el-table__row')
  await expect(rows).toHaveCount(14, { timeout: 30_000 })
  await expect(card.locator('.el-tag', { hasText: 'published' }).first()).toBeVisible()

  // 打开一条 → 试运行可点（demo fixtures，零真实患者）
  await rows.first().getByRole('button', { name: '试运行' }).click()
  const dialog = page.locator('.el-message-box', { hasText: '试运行（demo 虚构数据）' })
  await expect(dialog).toBeVisible({ timeout: 20_000 })
  await expect(dialog.getByText(/TEST\d+\/\d+: \d+ 问题/).first()).toBeVisible()
  // Element Plus alert 弹窗唯一确认按钮（默认文案随 locale，不按名字定位）
  await dialog.locator('.el-message-box__btns button').click()

  // 正向口径：failedApi 不得包含 /api/prearchive-admin/ 前缀的 ≥400
  const prcFailures = failedApi.filter((entry) => entry.includes('/api/prearchive-admin/'))
  expect(prcFailures).toEqual([])
})

test('规则中心降级：sidecar 停 → 502/503 文案 + 零白屏零异常', async ({ page }) => {
  test.skip(!DEGRADED, 'positive round skips degradation case; set RULE_CENTER_SIDECAR=0')
  test.setTimeout(120_000)
  const failedApi = trackFailedApi(page)
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(String(error)))

  await legacyLogin(page)
  await openAuditTypesPage(page)
  const card = page.locator('.page-card', { hasText: '归档前规则中心' })
  await expect(card).toBeVisible({ timeout: 30_000 })

  // 降级文案可见（BFF 502 → 规则中心不可用），且明确不影响六类 CRUD
  const alert = card.locator('.el-alert', { hasText: '规则中心不可用' })
  await expect(alert).toBeVisible({ timeout: 20_000 })
  await expect(alert.getByText('不受影响')).toBeVisible()
  // 规则表不渲染（避免半真半假数据）
  await expect(card.locator('.el-table__row')).toHaveCount(0)

  // 六类审计类型区域与只读预检规则卡片不受影响（零白屏证据）
  await expect(page.locator('.page-card', { hasText: '归档前预检规则' })).toBeVisible()

  // failedApi 口径（本 spec 自管）：
  // - /api/prearchive-admin/ 的 502/503 与 favicon 同等豁免（sidecar 未起是编排预期）；
  // - /api/users/me 的 403 是 legacy 冷加载 restoreSession 的未认证探测（既有行为，非本轮回归）
  const others = failedApi.filter((entry) => {
    if (entry.includes('/api/prearchive-admin/')) return false
    if (entry.includes('favicon')) return false
    if (entry.includes('/api/users/me')) return false
    return true
  })
  expect(others).toEqual([])
  // 且被豁免的规则中心失败只能是 502/503（服务未起），不能是 4xx
  for (const entry of failedApi.filter((e) => e.includes('/api/prearchive-admin/'))) {
    expect(['502', '503']).toContain(entry.split(' ')[0])
  }
  expect(pageErrors).toEqual([])
})
