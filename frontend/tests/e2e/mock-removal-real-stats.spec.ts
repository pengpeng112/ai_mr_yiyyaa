import { expect, test, type Page } from '@playwright/test'

// 061 T1（2026-10-06）：撤销演示覆盖（MOCK-20260813）后的真实统计断言。
// 运行门：MOCK_REMOVAL_E2E=true + PLAYWRIGHT_SKIP_WEBSERVER=1 +
//   PLAYWRIGHT_BASE_URL=http://127.0.0.1:18080/ui-next/（demo 主服务 18080）。
// 断言口径：三页统计条数字/比率必须与对应 API 实测值逐项相等（真实数据而非固定值）；
//   整改反馈闭环率按 2026-08-13 与用户确认的口径 (已确认+已整改+已关闭)/总量 计算。
const DEMO_PASSWORD = 'Demo-12Dept!2026'

// 从统计条/指标区提取 (标签, 数值) 对：标签=去掉 <b> 后的文本，数值=<b> 文本
async function readPairs(page: import('@playwright/test').Page, selector: string) {
  return page.locator(selector).evaluate((el) =>
    Array.from(el.querySelectorAll('button.meta, .stat-item')).map((it) => {
      const b = it.querySelector('b')
      const label = (it.textContent || '').replace(b?.textContent || '', '').trim()
      return { label, value: (b?.textContent || '').trim() }
    }),
  )
}

test('T1 真实统计：工作台/告警记录/整改反馈统计条与 API 实测逐项一致', async ({ page }, testInfo) => {
  test.skip(process.env.MOCK_REMOVAL_E2E !== 'true', 'requires demo main service + MOCK_REMOVAL_E2E=true')
  test.skip(testInfo.project.name !== 'desktop-1366', '统计断言只跑桌面视口一次')
  test.setTimeout(120_000)

  // UI 登录（显式填写，避免预填时序问题）；登录为异步请求，轮询等待 token 落库
  await page.goto('./#/login')
  await page.getByPlaceholder('请输入用户名').fill('demo_admin')
  await page.getByPlaceholder('请输入密码').fill(DEMO_PASSWORD)
  await page.getByRole('button', { name: '登录系统' }).click()
  await expect.poll(() => page.evaluate(() => localStorage.getItem('auth_token'))).toBeTruthy()

  const token = await page.evaluate(() => localStorage.getItem('auth_token'))
  expect(token).toBeTruthy()
  const headers = { Authorization: `Bearer ${token}` }

  // API 实测真值：前置机告警汇总
  const summaryResp = await page.request.get('/api/patient-qc/relay-alert/summary', { headers })
  expect(summaryResp.ok()).toBeTruthy()
  const s = (await summaryResp.json()) as Record<string, number>
  const relay = {
    total: Number(s.total || 0),
    success: Number(s.success || 0),
    failed: Number(s.failed || 0),
    viewed: Number(s.viewed || 0),
    unviewed: Number(s.unviewed || 0),
  }
  // 页面兜底口径：API 给 success_rate 用之，否则 success/total（total=0 → null → '--'）
  const apiRate = s.success_rate ?? (relay.total ? (relay.success / relay.total) * 100 : null)
  const expectedWorkbenchRate = apiRate === null || apiRate === undefined ? '--' : Number(apiRate).toFixed(1) + '%'

  // 1) 工作台：前置机失败 / 医生未查看 / 前置机成功率 与 relay summary 一致
  await page.goto('./#/workbench')
  await expect(page.locator('.meta-grid')).toBeVisible({ timeout: 20_000 })
  const metaBy = async (label: string) => (await readPairs(page, '.meta-grid')).find((p) => p.label === label)?.value
  await expect.poll(async () => metaBy('前置机失败')).toBe(String(relay.failed))
  await expect.poll(async () => metaBy('医生未查看')).toBe(String(relay.unviewed))
  await expect.poll(async () => metaBy('前置机成功率')).toBe(expectedWorkbenchRate)

  // 2) 告警记录：统计条 6 数字 + 成功率/查看率 == summary 实测（真实计算而非写死 98.5%/100%）
  await page.goto('./#/closure/alerts')
  await expect(page.locator('.stat-bar')).toBeVisible({ timeout: 20_000 })
  const alertBy = async (label: string) => (await readPairs(page, '.stat-bar')).find((p) => p.label === label)?.value
  await expect.poll(async () => alertBy('总量')).toBe(String(relay.total))
  await expect.poll(async () => alertBy('成功')).toBe(String(relay.success))
  await expect.poll(async () => alertBy('失败')).toBe(String(relay.failed))
  await expect.poll(async () => alertBy('已查看')).toBe(String(relay.viewed))
  await expect.poll(async () => alertBy('未查看')).toBe(String(relay.unviewed))
  const expSuccessRate = relay.total ? ((relay.success / relay.total) * 100).toFixed(1) + '%' : '-'
  const expViewRate = relay.total ? ((relay.viewed / relay.total) * 100).toFixed(1) + '%' : '-'
  await expect.poll(async () => alertBy('成功率')).toBe(expSuccessRate)
  await expect.poll(async () => alertBy('查看率')).toBe(expViewRate)

  // 3) 整改反馈：统计条 == /qc/feedback/cases 默认参数 stats；闭环率按已确认口径计算
  const fbResp = await page.request.get('/api/qc/feedback/cases', {
    headers,
    params: { page: 1, limit: 20, status: 'pending', days: 30 },
  })
  expect(fbResp.ok()).toBeTruthy()
  const fbStats = ((await fbResp.json()) as { stats?: Record<string, number> }).stats || {}
  const fb = {
    total: Number(fbStats.total || 0),
    high: Number(fbStats.high || 0),
    pending: Number(fbStats.pending || 0),
    acknowledged: Number(fbStats.acknowledged || 0),
    rectified: Number(fbStats.rectified || 0),
    closed: Number(fbStats.closed || 0),
  }
  await page.goto('./#/closure/feedback')
  await expect(page.locator('.stat-bar')).toBeVisible({ timeout: 20_000 })
  const fbBy = async (label: string) => (await readPairs(page, '.stat-bar')).find((p) => p.label === label)?.value
  await expect.poll(async () => fbBy('近期不一致')).toBe(String(fb.total))
  await expect.poll(async () => fbBy('高风险')).toBe(String(fb.high))
  await expect.poll(async () => fbBy('待处理')).toBe(String(fb.pending))
  await expect.poll(async () => fbBy('已确认')).toBe(String(fb.acknowledged))
  await expect.poll(async () => fbBy('已整改')).toBe(String(fb.rectified))
  await expect.poll(async () => fbBy('已关闭')).toBe(String(fb.closed))
  // 闭环率口径（2026-08-13 用户确认，T1 保留）：(已确认+已整改+已关闭)/总量 四舍五入取整
  const expClosure = fb.total ? Math.round(((fb.acknowledged + fb.rectified + fb.closed) / fb.total) * 100) : 0
  await expect.poll(async () => fbBy('闭环率')).toBe(`${expClosure}%`)
})

// 普通 full 必跑的确定性负例：接口含失败/未读/空摘要，页面不得覆盖成已完成。
// 与上面的隔离 demo 真后端验收分开，浏览器请求全部在本机拦截。
async function installRegressionApi(page: Page) {
  const requests: URL[] = []
  const user = { id: 1, username: 'admin', full_name: '合成管理员', role: 'admin', is_active: true }
  const alert = (id: number, status: string, viewed: number) => ({
    id, patient_id: `SYN-${id}`, patient_name: `合成患者${id}`, dept: '合成科室',
    severity: 'high', status, viewed_flag: viewed, view_count: viewed,
    viewer_name: viewed ? '合成查看者' : '', doctor_name: '禁止冒用的主管医师',
    evidence_summary: '', feedback_action: '', last_error: status === 'failed' ? '合成发送失败原因' : '',
    retry_count: 0, created_at: '2026-10-08 09:00:00', last_viewed_at: '',
  })
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    requests.push(url)
    const path = url.pathname
    let body: unknown = { items: [], total: 0 }
    if (path.endsWith('/users/login')) body = { access_token: 'aaa.bbb.ccc', user }
    else if (path.endsWith('/users/me')) body = user
    else if (path.endsWith('/menu')) body = {
      schema_version: 2, role: 'admin', default_home: 'dashboard',
      groups: [{ id: 'workbench', label: '工作台' }, { id: 'closure', label: '闭环管理' }],
      menu: [
        { id: 'dashboard', label: '工作台', group: 'workbench', route_name: 'workbench' },
        { id: 'relay-alert-logs', label: '告警记录', group: 'closure', route_name: 'closure-alerts' },
        { id: 'feedback', label: '整改反馈', group: 'closure', route_name: 'closure-feedback' },
      ],
    }
    else if (path.endsWith('/health')) body = { status: 'degraded', components: {} }
    else if (path.endsWith('/stats/today')) body = { total: 10, success: 4, skipped: 0 }
    else if (path.endsWith('/relay-alert/summary')) body = {
      total: 10, success: 4, failed: 3, pending: 3, viewed: 2, unviewed: 8, success_rate: 40, view_rate: 20,
    }
    else if (path.endsWith('/relay-alert/logs')) {
      const params = url.searchParams
      const filtered = params.get('status') === 'success' && params.get('viewed_flag') === '0'
      body = { total: filtered ? 1 : 21, items: filtered ? [alert(202, 'success', 0)]
        : params.get('page') === '2' ? [alert(203, 'pending', 0)]
          : [alert(201, 'failed', 0), alert(204, 'success', 1)] }
    }
    else if (path.endsWith('/qc/feedback/cases')) body = {
      total: 0, items: [], stats: { total: 10, high: 6, pending: 3, acknowledged: 2, rectified: 4, closed: 1 },
    }
    else if (path.endsWith('/audit-types/options')) body = { items: [{ code: 'progress_vs_nursing', name: '合成审计类型' }] }
    else if (path.endsWith('/departments')) body = { data: [] }
    else if (path.endsWith('/qc/feedback/export/excel')) {
      return route.fulfill({ status: 200, contentType: 'application/octet-stream',
        headers: { 'content-disposition': 'attachment; filename=synthetic-export.xlsx' }, body: 'synthetic export' })
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('./#/login')
  await page.getByPlaceholder('请输入用户名').fill('admin')
  await page.getByPlaceholder('请输入密码').fill('synthetic-password')
  await page.getByRole('button', { name: '登录系统' }).click()
  await expect(page.locator('.app-shell')).toBeVisible()
  return requests
}

test('演示撤销回归：异常健康、三页真实统计及反馈导出筛选', async ({ page }) => {
  const requests = await installRegressionApi(page)
  await page.goto('./#/workbench')
  await expect(page.getByText('部分异常', { exact: true })).toBeVisible()
  const stat = async (selector: string, label: string) => (await readPairs(page, selector)).find((p) => p.label === label)?.value
  await expect.poll(() => stat('.meta-grid', '医生未查看')).toBe('8')
  await expect.poll(() => stat('.meta-grid', '前置机成功率')).toBe('40.0%')
  await page.goto('./#/closure/alerts')
  for (const [label, value] of Object.entries({ 总量: '10', 成功: '4', 失败: '3', 已查看: '2', 未查看: '8', 成功率: '40.0%', 查看率: '20.0%' })) {
    await expect.poll(() => stat('.stat-bar', label)).toBe(value)
  }
  await page.goto('./#/closure/feedback')
  for (const [label, value] of Object.entries({ 近期不一致: '10', 高风险: '6', 待处理: '3', 已确认: '2', 已整改: '4', 已关闭: '1', 闭环率: '70%' })) {
    await expect.poll(() => stat('.stat-bar', label)).toBe(value)
  }
  await page.locator('.filter-bar .el-select').filter({ hasText: '审计类型' }).click()
  await page.getByRole('option', { name: '合成审计类型' }).click()
  await page.getByPlaceholder('患者ID/姓名/住院号').fill('SYN-FILTER')
  await page.getByPlaceholder('患者ID/姓名/住院号').press('Enter')
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出 Excel' }).click()
  expect((await downloadPromise).suggestedFilename()).toBe('synthetic-export.xlsx')
  const exported = requests.findLast((url) => url.pathname.endsWith('/qc/feedback/export/excel'))!
  const listed = requests.findLast((url) => url.pathname.endsWith('/qc/feedback/cases'))!
  for (const key of ['audit_type_code', 'keyword', 'status', 'days']) {
    expect(exported.searchParams.get(key)).toBe(listed.searchParams.get(key))
  }
  expect(exported.searchParams.get('keyword')).toBe('SYN-FILTER')
  expect(exported.searchParams.has('page')).toBe(false)
  expect(exported.searchParams.has('limit')).toBe(false)
})

test('演示撤销回归：第一页失败未读不覆盖，详情、翻页、筛选一致', async ({ page }) => {
  const requests = await installRegressionApi(page)
  await page.goto('./#/closure/alerts')
  const rows = page.locator('.el-table__body-wrapper .el-table__row')
  const failed = rows.filter({ hasText: 'SYN-201' })
  await expect(failed.locator('[data-status="failed"]')).toBeVisible()
  await expect(failed.getByText('未查看', { exact: true })).toBeVisible()
  await expect(failed).not.toContainText('禁止冒用的主管医师')
  await expect(failed).not.toContainText('已查看')
  await expect(failed).not.toContainText('安排核对整改')
  await failed.getByRole('button', { name: '详情', exact: true }).click()
  const drawer = page.getByRole('dialog', { name: '告警详情' })
  await expect(drawer.locator('[data-status="failed"]')).toBeVisible()
  await expect(drawer.getByText('合成发送失败原因', { exact: true })).toBeVisible()
  await expect(drawer.getByText('核查摘要', { exact: true })).toHaveCount(0)
  await expect(drawer).not.toContainText('禁止冒用的主管医师')
  await drawer.locator('.el-drawer__close-btn').click()
  await page.locator('.el-pagination .btn-next').click()
  await expect(rows.filter({ hasText: 'SYN-203' }).locator('[data-status="pending"]')).toBeVisible()
  await expect.poll(() => requests.some((url) => url.pathname.endsWith('/relay-alert/logs') && url.searchParams.get('page') === '2')).toBe(true)
  await page.getByRole('button', { name: '已发送未查看', exact: true }).click()
  const unread = rows.filter({ hasText: 'SYN-202' })
  await expect(unread.locator('[data-status="success"]')).toBeVisible()
  await expect(unread.getByText('未查看', { exact: true })).toBeVisible()
  const filtered = requests.findLast((url) => url.pathname.endsWith('/relay-alert/logs'))!
  expect(Object.fromEntries(filtered.searchParams)).toMatchObject({ page: '1', status: 'success', viewed_flag: '0' })
  await page.getByRole('button', { name: '重置', exact: true }).click()
  await expect(failed.locator('[data-status="failed"]')).toBeVisible()
})
