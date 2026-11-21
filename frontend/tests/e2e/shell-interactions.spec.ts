import { expect, test, type Page, type Route } from '@playwright/test'

async function mockCore(page: Page) {
  await page.route('**/api/**', async (route: Route) => {
    const url = route.request().url()
    const method = route.request().method()
    if (url.includes('/api/users/login') && method === 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          access_token: 'aaa.bbb.ccc',
          user: { id: 1, username: 'admin', full_name: 'Admin', role: 'admin' },
        }),
      })
      return
    }
    if (url.includes('/api/users/me')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: 1, username: 'admin', full_name: 'Admin', role: 'admin' }),
      })
      return
    }
    if (url.includes('/api/menu') && !url.includes('all')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          schema_version: 2,
          role: 'admin',
          default_home: 'dashboard',
          groups: [
            { id: 'workbench', label: '工作台', order: 10 },
            { id: 'quality', label: '质控中心', order: 20 },
            { id: 'system', label: '系统管理', order: 60 },
          ],
          menu: [
            {
              id: 'dashboard',
              label: '工作台',
              group: 'workbench',
              order: 10,
              route_name: 'workbench',
            },
            {
              id: 'patient-qc',
              label: '患者质控',
              group: 'quality',
              order: 15,
              route_name: 'quality-patients',
            },
            {
              id: 'audit',
              label: '质控记录',
              group: 'quality',
              order: 20,
              route_name: 'quality-records',
            },
            {
              id: 'health',
              label: '系统健康',
              group: 'system',
              order: 20,
              route_name: 'system-health',
            },
            {
              id: 'push-progress',
              label: '任务进度',
              group: 'workbench',
              order: 30,
              route_name: 'tasks-progress',
            },
          ],
        }),
      })
      return
    }
    if (url.includes('/api/health')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'ok', components: { app: { status: 'ok' } } }),
      })
      return
    }
    if (url.includes('/api/push/tasks/latest')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ task_id: 't1', status: 'running', total: 10, done: 3, success: 2 }),
      })
      return
    }
    if (url.includes('/api/logs') && method === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [
            {
              id: 1,
              dept: '测试科',
              status: 'success',
              severity: 'low',
              audit_type_code: 'progress_vs_nursing',
              created_at: '2026-08-01T10:00:00',
            },
          ],
          total: 1,
        }),
      })
      return
    }
    if (url.includes('/api/stats/')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ total: 0, items: [] }),
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

async function login(page: Page) {
  await mockCore(page)
  await page.goto('./#/login')
  await page.getByPlaceholder('请输入用户名').fill('admin')
  await page.getByPlaceholder('请输入密码').fill('password')
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.locator('.app-shell')).toBeVisible({ timeout: 15_000 })
}

test.describe('shell interactions', () => {
  test('mobile opens menu drawer', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'mobile-390', 'drawer case for mobile only')
    await login(page)
    await page.getByRole('button', { name: '打开菜单' }).click()
    await expect(page.locator('.mobile-nav-drawer, .el-drawer').first()).toBeVisible()
  })

  test('quality records table and pagination shell', async ({ page }) => {
    await login(page)
    await page.goto('./#/quality/records')
    // WP08：旧路由重定向至内涵质控工作台流水视角（/api/patient-qc/patients 无 mock →
    // ErrorState 展示，不影响重定向链路断言）
    await page.waitForURL(/quality\/patients/)
    await expect(page.getByRole('heading', { name: '内涵质控工作台' })).toBeVisible()
    // WP08：流水视角 AuditRecordListPanel 有「重置」按钮（仅 GET logs 契约不变）
    await expect(page.getByRole('button', { name: '重置' })).toBeVisible()
    await page.getByRole('button', { name: '重置' }).click()
  })

  test('back/forward navigation works', async ({ page }) => {
    await login(page)
    await page.goto('./#/workbench')
    await page.goto('./#/system/health')
    await expect(page.getByRole('heading', { name: '系统健康' })).toBeVisible()
    await page.goBack()
    await expect(page).toHaveURL(/workbench/)
    await page.goForward()
    await expect(page).toHaveURL(/system\/health/)
  })

  test('lazy routes do not preload all page chunks on login', async ({ page }) => {
    const loaded: string[] = []
    page.on('response', (res) => {
      const u = res.url()
      if (u.includes('/assets/') && u.endsWith('.js')) loaded.push(u)
    })
    await login(page)
    await page.goto('./#/system/health')
    await expect(page.getByRole('heading', { name: '系统健康' })).toBeVisible()
    // 未访问的高风险页 chunk 不应全部出现
    const joined = loaded.join('\n')
    expect(joined).not.toMatch(/ManualPushPage/)
    expect(joined).not.toMatch(/DebugPage/)
  })
})
