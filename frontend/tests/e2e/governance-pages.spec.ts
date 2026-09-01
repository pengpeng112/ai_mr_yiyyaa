import { expect, test, type Page, type Route } from '@playwright/test'

// 035/RP6 ui-next 新增用例（基线 46 不回退 + 新增 ≥2）：
// 1) 治理-质控类型页渲染（既有 e2e 未覆盖 governance/audit-types）
// 2) 登录错误凭据错误态（既有用例只覆盖成功登录与 403 路由）

const AUDIT_TYPES = [
  { code: 'progress_vs_nursing', name: '病程与护理核查', enabled: true },
  { code: 'jyjc_vs_bcnursing', name: '检验检查与护理核查', enabled: true },
  { code: 'admission_vs_first_progress', name: '入院与首次病程核查', enabled: true },
  { code: 'surgery_chain', name: '围手术期文书链核查', enabled: false },
]

const MENU_PAYLOAD = {
  schema_version: 2,
  role: 'admin',
  menu: [
    { id: 'dashboard', label: '工作台', group: 'workbench', order: 10, route_name: 'workbench' },
    { id: 'audit-types', label: '质控类型', group: 'governance', order: 10, route_name: 'governance-audit-types' },
  ],
  groups: [
    { id: 'workbench', label: '工作台', order: 10 },
    { id: 'governance', label: '规则与配置', order: 50 },
  ],
  default_home: 'dashboard',
}

async function mockLoginOk(page: Page) {
  await page.route('**/api/**', async (route: Route) => {
    const url = route.request().url()
    const method = route.request().method()
    if (url.includes('/api/menu') && !url.includes('/menu/all')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MENU_PAYLOAD),
      })
      return
    }
    if (url.includes('/api/users/login') && method === 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ access_token: 'aaa.bbb.ccc', user: { id: 1, username: 'admin', full_name: 'admin', role: 'admin' } }),
      })
      return
    }
    if (url.includes('/api/users/me')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: 1, username: 'admin', full_name: 'admin', role: 'admin' }),
      })
      return
    }
    if (url.includes('/api/audit-types') && !url.includes('prearchive')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: AUDIT_TYPES }),
      })
      return
    }
    if (method === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{"success":true}' })
  })
}

test('governance audit-types page lists catalog rows', async ({ page }) => {
  await mockLoginOk(page)
  await page.goto('./#/login')
  await page.getByPlaceholder('请输入用户名').fill('admin')
  await page.getByPlaceholder('请输入密码').fill('password')
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.locator('.app-shell')).toBeVisible({ timeout: 15_000 })

  await page.goto('./#/governance/audit-types')
  await expect(page.getByText('progress_vs_nursing').first()).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('围手术期文书链核查').first()).toBeVisible()
  await expect(page.locator('main .el-table').first()).toBeVisible()
})

test('wrong password shows error and stays on login', async ({ page }) => {
  await page.route('**/api/users/login', async (route: Route) => {
    await route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: 'Incorrect username or password' }) })
  })
  await page.route('**/api/**', async (route: Route) => {
    if (route.request().url().includes('/api/users/login')) return route.fallback()
    if (route.request().method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{"success":true}' })
  })
  await page.goto('./#/login')
  await page.getByPlaceholder('请输入用户名').fill('admin')
  await page.getByPlaceholder('请输入密码').fill('wrong-password')
  await page.getByRole('button', { name: '登录' }).click()
  // 错误提示出现且停留在登录页（不进入 app-shell）
  await expect(page.locator('.el-message--error').first()).toBeVisible({ timeout: 10_000 })
  await expect(page.locator('.app-shell')).toHaveCount(0)
  await expect(page).toHaveURL(/#\/login/)
})
