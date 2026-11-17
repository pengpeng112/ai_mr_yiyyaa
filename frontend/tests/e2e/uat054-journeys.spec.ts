import { expect, test, type Page } from '@playwright/test'

// 054 §10 旅程①②（uat054 增补）：真后端、真实页面动作、API 只读对账。
// 运行门：UAT054_E2E=true + PLAYWRIGHT_SKIP_WEBSERVER=1 +
//   PLAYWRIGHT_BASE_URL=http://127.0.0.1:18080/ui-next/（demo 主服务 18080）。
// 覆盖：H05/H07/H09/H10/H13/H14-UI/H15-UI/H17-真/H45/H46-过滤注入。
// 数据前提：demo showcase 数据 + SYNTH-FIX-01（合成 fixture 患者，2026-08-12 听觉植入科
//   progress_vs_nursing 候选=2 条，与 synthetic-demo-real 同源契约）。
// R3 断言收紧（round-8，2026-10-04）：导出审计精确对账 / 真实双击防重 /
//   任务终态与计数守恒 / H45 跨 UI 同记录逐字段比对——旧数据无法令新动作"假通过"。
test.skip(process.env.UAT054_E2E !== 'true',
  'requires demo main service + UAT054_E2E=true')

const DEMO_PASSWORD = 'Demo-12Dept!2026'
const FIXTURE = { date: '2026-08-12', dept: '听觉植入科', type: 'progress_vs_nursing', patient: 'SYNTH-FIX-01' }
// 单轮推送候选上限（spec 头注释契约）：双击防重断言的"不翻倍"基准
const SINGLE_RUN_CANDIDATES = 2
// 两套 UI 的推送状态文案一致（legacy formatters.js / ui-next utils/status.ts 同映射）
const PUSH_STATUS_LABELS: Record<string, string> = {
  success: '成功', failed: '失败', skipped: '跳过', pending: '待处理', error: '错误',
}

interface AuditLogItem {
  id: number
  username: string
  export_type: string
  export_format: string
  filter_criteria: string
  record_count: number
  status: string
}

interface PushLogItem {
  id: number
  push_time: string
  patient_id: string
  audit_type_code: string | null
  audit_type_name: string | null
  status: string
}

interface TaskProgress {
  task_id: string
  status: string
  total: number
  processed: number
  success: number
  failed: number
  skipped: number
}

async function loginAdmin(page: Page) {
  await page.goto('./#/login')
  await page.getByPlaceholder('请输入用户名').fill('demo_admin')
  await page.getByPlaceholder('请输入密码').fill(DEMO_PASSWORD)
  await page.getByRole('button', { name: '登录系统' }).click()
  await expect(page.locator('.app-shell')).toBeVisible({ timeout: 20_000 })
}

async function adminHeaders(page: Page) {
  const token = await page.evaluate(() => localStorage.getItem('auth_token'))
  expect(token).toBeTruthy()
  return { Authorization: `Bearer ${token}` }
}

async function fetchLogItems(page: Page, headers: Record<string, string>, query: string): Promise<PushLogItem[]> {
  const res = await page.request.get(`/api/logs${query}`, { headers })
  expect(res.ok()).toBeTruthy()
  const payload = (await res.json()) as { total: number; items: PushLogItem[] }
  return payload.items || []
}

test.describe.configure({ mode: 'serial' })

test('旅程① 登录→患者→质控记录筛选/分页/重置→详情结构化/原文→导出+审计对账（H05/H07/H09/H10/H46）', async ({ page }) => {
  test.setTimeout(180_000)
  await loginAdmin(page)
  const headers = await adminHeaders(page)

  // H05：概览工作台 → 患者列表
  await page.goto('./#/workbench')
  await expect(page.locator('#main-content').getByText('工作台').first()).toBeVisible({ timeout: 20_000 })
  await page.goto('./#/quality/patients')
  await expect(page.locator('#main-content').getByText('患者质控').first()).toBeVisible({ timeout: 20_000 })

  // H07：质控记录筛选（患者ID）+ 状态筛选 + 重置
  await page.goto('./#/quality/records')
  await expect(page.getByText('质控记录', { exact: true }).first()).toBeVisible({ timeout: 20_000 })
  await page.getByPlaceholder('患者ID').fill(FIXTURE.patient)
  await page.keyboard.press('Enter')
  await expect(page.locator('.el-table__row').first()).toBeVisible({ timeout: 20_000 })
  const rowCount = await page.locator('.el-table__row').count()
  expect(rowCount).toBeGreaterThan(0)
  // 行内患者列均为目标患者（筛选准确，不串患者）；患者列=第2列（选择框后）
  const cells = await page.locator('.el-table__row td:nth-child(2)').allTextContents()
  expect(cells.every((c) => c.includes(FIXTURE.patient))).toBe(true)
  // 状态筛选改动后仍返回（筛选组合不报错、空结果非错误态）
  // 注：Element Plus select 的 placeholder 渲染为 span，不能 getByPlaceholder，用结构定位
  await page.locator('.filter-row .el-select').first().click()
  await page.getByRole('option', { name: '失败' }).click()
  await page.waitForTimeout(1200)
  await page.getByRole('button', { name: '重置', exact: true }).click()
  await expect(page.locator('.el-table__row').first()).toBeVisible({ timeout: 20_000 })

  // H46（过滤输入注入）：HTML/公式字符串作为过滤词不执行、不致错
  await page.getByPlaceholder('患者姓名').fill('<img src=x onerror=window.__xss=1>=SUM(1+1)')
  await page.keyboard.press('Enter')
  await page.waitForTimeout(1200)
  expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined()
  await page.getByRole('button', { name: '重置', exact: true }).click()
  await expect(page.locator('.el-table__row').first()).toBeVisible({ timeout: 20_000 })

  // H09：详情抽屉——结构化/原文切换、中文/空值容忍
  await page.getByRole('button', { name: '详情' }).first().click()
  const detailDrawer = page.getByRole('dialog', { name: '质控记录详情' })
  await expect(detailDrawer).toBeVisible({ timeout: 20_000 })
  const drawerText = await detailDrawer.innerText()
  expect(drawerText).not.toMatch(/undefined|NaN\n/)
  const payloadTabs = detailDrawer.locator('.el-tabs__item')
  if (await payloadTabs.count() > 1) {
    await payloadTabs.nth(1).click()
    await page.waitForTimeout(600)
    await payloadTabs.first().click()
  }
  await page.keyboard.press('Escape')

  // H10：导出 CSV + ExportAuditLog 精确对账（R3 收紧：恰 1 条新增审计，ID/操作者/范围/条数匹配；
  //   旧断言"任意 csv 审计>0"可被历史记录满足。导出端点不收 patient_id——范围=全部当前结果行）
  const auditResBefore = await page.request.get('/api/audit/logs?limit=50', { headers })
  expect(auditResBefore.ok()).toBeTruthy()
  const auditIdsBefore = new Set(
    ((await auditResBefore.json()).items as AuditLogItem[]).map((i) => i.id),
  )
  const totalRes = await page.request.get('/api/logs?limit=1', { headers })
  expect(totalRes.ok()).toBeTruthy()
  const expectedExportRows = ((await totalRes.json()) as { total: number }).total
  expect(expectedExportRows).toBeGreaterThan(0)
  await page.getByRole('button', { name: '导出 CSV' }).click()
  await expect(page.getByText(/导出已开始/)).toBeVisible({ timeout: 20_000 })
  await expect.poll(async () => {
    const res = await page.request.get('/api/audit/logs?limit=50', { headers })
    const items = ((await res.json()).items as AuditLogItem[])
    return items.filter((i) => !auditIdsBefore.has(i.id) && i.export_format === 'csv').length
  }, { timeout: 15_000 }).toBe(1)
  const auditResAfter = await page.request.get('/api/audit/logs?limit=50', { headers })
  const newAudits = ((await auditResAfter.json()).items as AuditLogItem[]).filter((i) => !auditIdsBefore.has(i.id))
  expect(newAudits).toHaveLength(1)
  const audit = newAudits[0]
  expect(audit.username).toBe('demo_admin')          // 操作者=当前登录账号
  expect(audit.export_type).toBe('push_log')          // 导出对象=推送日志
  expect(audit.export_format).toBe('csv')
  expect(audit.status).toBe('success')
  expect(audit.record_count).toBe(expectedExportRows) // 条数=导出时全部当前结果行
  const criteria = JSON.parse(audit.filter_criteria || '{}') as { meta?: { semantics?: string } }
  expect(criteria.meta?.semantics).toBe('current-only') // 范围口径=仅当前结果

  // F18/F-1 修复回归（2026-10-04）：患者筛选态导出——导出范围与列表同分母，审计记录筛选条件
  await page.getByPlaceholder('患者ID').fill(FIXTURE.patient)
  await page.keyboard.press('Enter')
  await expect(page.locator('.el-table__row').first()).toBeVisible({ timeout: 20_000 })
  const filteredRes = await page.request.get(`/api/logs?patient_id=${FIXTURE.patient}&limit=1`, { headers })
  expect(filteredRes.ok()).toBeTruthy()
  const patientTotal = ((await filteredRes.json()) as { total: number }).total
  expect(patientTotal).toBeGreaterThan(0)
  const auditIdsBeforeFiltered = new Set(
    ((await (await page.request.get('/api/audit/logs?limit=50', { headers })).json()).items as AuditLogItem[]).map((i) => i.id),
  )
  await page.getByRole('button', { name: '导出 CSV' }).click()
  await expect(page.getByText(/导出已开始/)).toBeVisible({ timeout: 20_000 })
  await expect.poll(async () => {
    const res = await page.request.get('/api/audit/logs?limit=50', { headers })
    const items = ((await res.json()).items as AuditLogItem[])
    return items.filter((i) => !auditIdsBeforeFiltered.has(i.id) && i.export_format === 'csv').length
  }, { timeout: 15_000 }).toBe(1)
  const filteredAudits = ((await (await page.request.get('/api/audit/logs?limit=50', { headers })).json()).items as AuditLogItem[])
    .filter((i) => !auditIdsBeforeFiltered.has(i.id))
  expect(filteredAudits).toHaveLength(1)
  expect(filteredAudits[0].record_count).toBe(patientTotal) // 导出条数=列表同筛选 total（F-1 回归）
  const filteredCriteria = JSON.parse(filteredAudits[0].filter_criteria || '{}') as { patient_id?: string }
  expect(filteredCriteria.patient_id).toBe(FIXTURE.patient) // 审计记录含筛选条件（F-1 回归）
})

test('旅程② 推送（预览→执行）→任务进度→质控记录结果→反馈列表（H13/H15-UI/H17-真）', async ({ page }) => {
  test.setTimeout(300_000)
  await loginAdmin(page)
  const headers = await adminHeaders(page)

  // 手动推送页：单日 fixture 范围，先预览（不调 Dify）再执行
  await page.goto('./#/tasks/push')
  await expect(page.getByText('手动推送', { exact: true }).first()).toBeVisible({ timeout: 20_000 })
  await page.getByPlaceholder('选择日期').fill(FIXTURE.date)
  await page.locator('.form-item', { hasText: '审计类型' }).locator('.el-select').click()
  await page.getByRole('option', { name: /病程与护理/ }).first().click()
  await page.keyboard.press('Escape')
  await page.getByPlaceholder('逗号分隔，留空用系统配置').fill(FIXTURE.dept)
  // 预览模式（默认勾选则直接执行预览）；EP 复选框原生 input 隐藏，点外层 label
  const dryRunBox = page.getByRole('checkbox', { name: /预览模式/ })
  const dryRunLabel = page.locator('.el-checkbox', { hasText: '预览模式' })
  if (!(await dryRunBox.isChecked())) {
    await dryRunLabel.click()
  }
  await page.getByRole('button', { name: '预览数据' }).click()
  await page.getByRole('button', { name: '确定' }).click()
  await expect(page.getByText(/预览完成|候选/).first()).toBeVisible({ timeout: 60_000 })

  // 正式执行前置：启用异步执行（获得可对账的 /api/push/tasks/latest 任务进度），并记录本轮前结果行 ID 集
  await dryRunLabel.click() // 取消预览模式
  const asyncBox = page.getByRole('checkbox', { name: /异步执行/ })
  if (!(await asyncBox.isChecked())) {
    await page.locator('.el-checkbox', { hasText: '异步执行' }).click()
    await expect(asyncBox).toBeChecked()
  }
  const listQuery = `?audit_type_code=${FIXTURE.type}&limit=1000`
  const idsBefore = new Set((await fetchLogItems(page, headers, listQuery)).map((r) => r.id))

  // H15-UI 连点防重（R3 收紧 + F-2 修复回归，2026-10-04）：开始推送按钮真实快速双击——
  //   守卫前置到确认框之前后按钮即时禁用，第二击无效：仅一个确认框、一个任务、一批发量
  const pushBtn = page.getByRole('button', { name: '开始推送' })
  await pushBtn.dblclick()
  await expect(page.locator('.el-message-box')).toHaveCount(1) // 双击后仅一个确认框（F-2 回归）
  await page.getByRole('button', { name: '确定' }).click()
  await expect(page.getByText('已提交批量推送任务').first()).toBeVisible({ timeout: 120_000 })
  await expect(page.locator('.el-message-box')).toHaveCount(0) // 提交后无残留确认框

  // 任务进度闭环（R3 收紧：本次任务进入终态，计数与推送汇总一致；旧断言仅"正文非空"）
  let task: TaskProgress | null = null
  await expect.poll(async () => {
    const res = await page.request.get('/api/push/tasks/latest', { headers })
    expect(res.ok()).toBeTruthy()
    const data = (await res.json()) as TaskProgress
    task = data
    return ['completed', 'failed', 'cancelled'].includes(data.status) ? data.status : 'running'
  }, { timeout: 240_000 }).toBe('completed')
  expect(task).not.toBeNull()
  const t = task as TaskProgress
  expect(t.processed).toBe(t.total)                     // 终态前处理数守恒
  expect(t.success + t.failed + t.skipped).toBe(t.total) // 推送汇总=成功+失败+跳过
  expect(t.total).toBeLessThanOrEqual(SINGLE_RUN_CANDIDATES) // 双击未产生第二批发量

  // 任务进度页（H17 真后端）：页面可达且渲染（终态与计数由上方 API 对账，页面为其数据源）
  await page.goto('./#/tasks/progress')
  await expect(page.getByText('任务进度', { exact: true }).first()).toBeVisible({ timeout: 20_000 })
  await page.waitForTimeout(1500)

  // 新增结果行对账（R3）：本轮新增行数=任务处理总数；每行身份/状态合法，不被旧数据冒充。
  // 批次按日期+科室+类型圈定，含该科室当日多名合成患者（如 SYNTH-FIX-01-02）——身份断言按合成命名空间
  const rowsAfter = await fetchLogItems(page, headers, listQuery)
  const newRows = rowsAfter.filter((r) => !idsBefore.has(r.id))
  expect(newRows).toHaveLength(t.total)
  for (const row of newRows) {
    expect(row.patient_id.startsWith('SYNTH-FIX')).toBe(true)
    expect(['success', 'failed', 'skipped']).toContain(row.status)
  }

  // 质控记录：fixture 患者结果落库可见
  await page.goto('./#/quality/records')
  await expect(page.getByText('质控记录', { exact: true }).first()).toBeVisible({ timeout: 20_000 })
  await page.getByPlaceholder('患者ID').fill(FIXTURE.patient)
  await page.keyboard.press('Enter')
  await expect(page.locator('.el-table__row').first()).toBeVisible({ timeout: 20_000 })

  // 反馈列表可搜索该患者（旅程②尾部闭环入口）
  await page.goto('./#/closure/feedback')
  await expect(page.getByText('整改反馈', { exact: true }).first()).toBeVisible({ timeout: 20_000 })
  await page.getByPlaceholder('患者ID/姓名/住院号').fill(FIXTURE.patient)
  await page.keyboard.press('Enter')
  await page.waitForTimeout(1500)
})

test('H45 legacy 与 UI Next 同记录一致：同一条记录两边逐字段对账（身份/类型/状态/时间）', async ({ page }) => {
  test.setTimeout(180_000)
  await loginAdmin(page)
  const headers = await adminHeaders(page)
  // API 锚点：取定一条当前结果记录，两边 UI 打开同一条并逐字段比对
  const anchorItems = await fetchLogItems(page, headers, `?patient_id=${FIXTURE.patient}&limit=10`)
  expect(anchorItems.length).toBeGreaterThan(0)
  const anchor = anchorItems[0]
  const anchorTypeLabel = anchor.audit_type_name || anchor.audit_type_code || ''
  const anchorStatusLabel = PUSH_STATUS_LABELS[anchor.status] ?? anchor.status
  const anchorTime = anchor.push_time.replace('T', ' ').slice(0, 19) // 两边 UI 均渲染 YYYY-MM-DD HH:mm:ss

  // UI Next：质控记录页同筛选，首行=同一记录（同 /api/logs 默认排序）
  await page.goto('./#/quality/records')
  await expect(page.getByText('质控记录', { exact: true }).first()).toBeVisible({ timeout: 20_000 })
  await page.getByPlaceholder('患者ID').fill(FIXTURE.patient)
  await page.keyboard.press('Enter')
  const uiNextRow = page.locator('.el-table__row').first()
  await expect(uiNextRow).toBeVisible({ timeout: 20_000 })
  const uiNextText = (await uiNextRow.innerText()).replace(/\s+/g, ' ')
  expect(uiNextText).toContain(anchor.patient_id)      // 身份
  expect(anchorTypeLabel).not.toBe('')
  expect(uiNextText).toContain(anchorTypeLabel)        // 类型
  expect(uiNextText).toContain(anchorStatusLabel)      // 状态
  expect(uiNextText).toContain(anchorTime)             // 时间（到秒）

  // legacy：同源共享 auth_token——UI Next 已登录时 legacy 冷加载自动恢复会话，登录表单不再出现
  await page.goto('/index.html')
  const legacyMain = page.locator('.main-area')
  try {
    await legacyMain.waitFor({ timeout: 8_000 }) // 自动恢复会话直达主壳
  } catch {
    await expect(page.getByText('欢迎登录')).toBeVisible({ timeout: 20_000 })
    await page.getByPlaceholder('请输入用户名').fill('demo_admin')
    await page.getByPlaceholder('请输入密码').fill(DEMO_PASSWORD)
    await page.getByRole('button', { name: '登 录' }).click()
    await expect(legacyMain).toBeVisible({ timeout: 20_000 })
  }
  await expect(legacyMain).toBeVisible()
  await page.locator('.el-menu').getByText(/质控中心|质控/, { exact: true }).first().click()
  await page.locator('.el-menu-item', { hasText: '质控记录' }).first().click()
  await page.locator('.el-tabs__item', { hasText: '推送日志' }).first().click()
  await expect(page.locator('.page-view.page-logs, .page-logs').first()).toBeVisible({ timeout: 20_000 })
  // 审计页多 tab 共存 DOM（患者质控 tab 也有患者输入），按精确 placeholder 限定推送日志筛选框
  await page.locator('.page-logs').getByPlaceholder('患者ID', { exact: true }).fill(FIXTURE.patient)
  const legacyRow = page.locator('.page-logs .el-table__row').first()
  await expect(legacyRow).toContainText(anchor.patient_id, { timeout: 20_000 }) // 防抖自动刷新轮询
  const legacyText = (await legacyRow.innerText()).replace(/\s+/g, ' ')
  expect(legacyText).toContain(anchor.patient_id)
  expect(legacyText).toContain(anchorTypeLabel)
  expect(legacyText).toContain(anchorStatusLabel)
  expect(legacyText).toContain(anchorTime)
  // 两边同筛选同数据源；默认页容量不同（UI Next 10 / legacy 20）不比较总数，
  // 同一条记录的身份/类型/状态/时间一致性已在上方对两边首行逐项断言
  expect(await page.locator('.page-logs .el-table__row').count()).toBeGreaterThan(0)
})
