import { expect, test } from '@playwright/test'


test.skip(process.env.SYNTHETIC_DEMO_E2E !== 'true', 'requires scripts/demo_env.py serve')

test('真实隔离环境登录、12科室、患者质控和水印', async ({ page }) => {
  test.setTimeout(90_000)
  await page.goto('./#/login')
  await expect(page.getByText('SYNTHETIC TEST DATA / 脱敏合成测试数据')).toBeVisible()
  await expect(page.getByPlaceholder('请输入用户名')).toHaveValue('demo_admin')
  await expect(page.getByPlaceholder('请输入密码')).toHaveValue('Demo-12Dept!2026')
  await page.getByRole('button', { name: '登录系统' }).click()
  await expect(page).toHaveURL(/\/ui-next\/(workbench)?/)
  await expect(page.locator('.synthetic-banner')).toContainText('12科室隔离功能测试')

  const token = await page.evaluate(() => localStorage.getItem('auth_token'))
  expect(token).toBeTruthy()
  const departments = await page.request.get('/api/departments', {
    headers: { Authorization: `Bearer ${token}` },
  })
  expect(departments.ok()).toBeTruthy()
  const departmentPayload = await departments.json()
  expect(Array.isArray(departmentPayload) ? departmentPayload : departmentPayload.items).toHaveLength(12)

  await page.goto('/ui-next/quality/patients')
  await expect(page.locator('.synthetic-banner')).toBeVisible()
  await expect(page.locator('#main-content').getByText('患者质控').first()).toBeVisible()
  await expect.poll(async () => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2)).toBe(true)
})

test('真实 fixture 推送、Relay H5反馈与科室RBAC负例', async ({ page }, testInfo) => {
  test.setTimeout(90_000)
  test.skip(testInfo.project.name !== 'desktop-1366', '有状态闭环只串行执行一次')
  const adminLogin = await page.request.post('/api/users/login', { data: { username: 'demo_admin', password: 'Demo-12Dept!2026' } })
  expect(adminLogin.ok()).toBeTruthy()
  const adminToken = (await adminLogin.json()).access_token as string
  const adminHeaders = { Authorization: `Bearer ${adminToken}` }
  const body = {
    query_date: '2026-08-12',
    date_dimension: 'record_create_date',
    dept_filter: ['听觉植入科'],
    audit_type_codes: ['progress_vs_nursing'],
    dry_run: false,
    async_mode: false,
    parallel_workers: 1,
    skip_already_succeeded: false,
  }
  const preview = await page.request.post('/api/push/query-preview', { headers: adminHeaders, data: { ...body, page: 1, page_size: 20 } })
  expect(preview.ok()).toBeTruthy()
  expect((await preview.json()).total_rows).toBe(2)

  const push = await page.request.post('/api/push/manual', { headers: adminHeaders, data: body })
  expect(push.ok()).toBeTruthy()
  const pushed = await push.json()
  expect(pushed.success).toBe(2)
  expect(pushed.failed).toBe(0)

  const logs = await page.request.get('/api/logs?patient_id=SYNTH-FIX-01&limit=20', { headers: adminHeaders })
  expect(logs.ok()).toBeTruthy()
  expect((await logs.json()).total).toBeGreaterThanOrEqual(2)

  const messages = await page.request.get('http://127.0.0.1:18082/api/mock/messages')
  expect(messages.ok()).toBeTruthy()
  const messageItems = (await messages.json()).items as Array<{ body: { alert_id: number; detail_url: string } }>
  expect(messageItems.length).toBeGreaterThan(0)
  const message = messageItems[messageItems.length - 1].body
  const detailUrl = new URL(message.detail_url)
  const token = detailUrl.searchParams.get('token') || ''
  const detail = await page.request.get(message.detail_url)
  expect(detail.ok()).toBeTruthy()
  expect(await detail.text()).toContain('脱敏合成测试数据')
  const feedbackBody = {
    alert_id: message.alert_id,
    token,
    action: 'rectified',
    rectification_text: 'Playwright 脱敏合成测试整改',
    viewer_userid: 'synthetic-e2e',
    viewer_name: '测试医生',
  }
  const feedback = await page.request.post('/api/mobile/qc-feedback', { data: feedbackBody })
  expect(feedback.status()).toBe(200)
  const duplicate = await page.request.post('/api/mobile/qc-feedback', { data: feedbackBody })
  expect(duplicate.status()).toBe(409)

  const clinicianLogin = await page.request.post('/api/users/login', { data: { username: 'clinician_d001', password: 'Demo-12Dept!2026' } })
  expect(clinicianLogin.ok()).toBeTruthy()
  const clinicianToken = (await clinicianLogin.json()).access_token as string
  const clinicianHeaders = { Authorization: `Bearer ${clinicianToken}` }
  const visibleDepartments = await page.request.get('/api/logs/dept-options', { headers: clinicianHeaders })
  expect(visibleDepartments.ok()).toBeTruthy()
  const departmentPayload = await visibleDepartments.json()
  expect(departmentPayload.items).toHaveLength(1)
  expect(departmentPayload.items[0].value).toBe('听觉植入科')
  const forbiddenDepartment = await page.request.get(`/api/logs?dept=${encodeURIComponent('耳内科')}`, { headers: clinicianHeaders })
  expect(forbiddenDepartment.ok()).toBeTruthy()
  expect((await forbiddenDepartment.json()).total).toBe(0)
})
