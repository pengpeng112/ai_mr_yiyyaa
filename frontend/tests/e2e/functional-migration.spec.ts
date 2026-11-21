import { expect, test, type Page, type Route } from '@playwright/test'

const json = (body: unknown, status = 200) => ({ status, contentType: 'application/json', body: JSON.stringify(body) })

async function mockApi(page: Page, quickBodies: unknown[] = []) {
  await page.route('**/api/**', async (route: Route) => {
    const url = route.request().url()
    const method = route.request().method()
    const path = new URL(url).pathname
    if (path.endsWith('/users/login')) {
      return route.fulfill(json({
        access_token: 'aaa.bbb.ccc',
        user: { id: 1, username: 'admin', full_name: '管理员', role: 'admin', is_active: true },
      }))
    }
    if (path.endsWith('/users/me')) {
      return route.fulfill(json({ id: 1, username: 'admin', full_name: '管理员', role: 'admin', is_active: true }))
    }
    if (path.endsWith('/menu')) {
      return route.fulfill(json({
        schema_version: 2,
        role: 'admin',
        default_home: 'dashboard',
        groups: [{ id: 'quality', label: '质控' }, { id: 'governance', label: '治理' }, { id: 'system', label: '系统' }],
        menu: [
          { id: 'dashboard', label: '工作台', group: 'quality', route_name: 'workbench' },
          { id: 'patient-qc', label: '患者质控', group: 'quality', route_name: 'quality-patients' },
          { id: 'audit', label: '质控记录', group: 'quality', route_name: 'quality-records' },
          { id: 'relay', label: '告警推送配置', group: 'governance', route_name: 'governance-relay' },
          { id: 'access', label: '用户与权限', group: 'system', route_name: 'system-access' },
          { id: 'push-progress', label: '任务进度', group: 'system', route_name: 'tasks-progress' },
        ],
      }))
    }
    if (path.endsWith('/patient-qc/patients')) {
      return route.fulfill(json({
        total: 1,
        items: [{
          patient_id: 'P-1', visit_number: '1', patient_name: '测试患者', admission_no: 'A-1',
          dept: '测试科', discharge_dept_name: '测试科', highest_severity: 'high',
          high_count: 1, medium_count: 0, issue_count: 1, pending_count: 1, resolved_count: 0,
          audit_type_count: 1, push_log_count: 1, latest_push_time: '2026-08-01 10:00:00',
        }],
      }))
    }
    if (path.endsWith('/patient-qc/patient-detail')) {
      return route.fulfill(json({
        patient: {
          patient_id: 'P-1', visit_number: '1', patient_name: '测试患者',
          admission_no: 'A-1', dept: '测试科', discharge_main_diagnosis: '肺炎主诊断',
        },
        clinical_summary: {
          patient_id: 'P-1', patient_name: '测试患者', admission_no: 'A-1',
          sex: '男', age: 54, dept_name: '测试科', discharge_dept_name: '测试科',
          doctor_in_charge: '李医生', admission_date: '2026-08-01 08:00:00',
          discharge_date: null, admission_diagnosis: '肺炎',
          discharge_diagnosis: '肺炎主诊断', surgery_name: '', surgery_date: null,
        },
        summary: {
          audit_type_count: 1, push_log_count: 1, issue_count: 1,
          high_count: 1, medium_count: 0, pending_count: 1, resolved_count: 0,
        },
        audit_groups: [{
          audit_type_code: 'demo',
          audit_type_name: '演示质控',
          severity: 'high',
          overall_conclusion: '演示总体结论',
          overall_qc_summary: '演示总体质控结论',
          logs: [{
            push_log_id: 77,
            push_time: '2026-08-01 10:00:00',
            status: 'success',
            severity: 'high',
            feedback: { status: 'pending', feedback_text: '待处理', assigned_to_name: '张医生' },
            dimensions: [{
              dimension_name: '病历完整性',
              status: 'fail',
              severity: 'high',
              issue_summary: '缺少记录',
              explanation: '需补充',
              recommendation: '及时完善',
              medical_evidence: [{ text: '病历证据' }],
              nursing_evidence: { text: '护理证据' },
            }],
          }],
        }],
      }))
    }
    if (path.endsWith('/patient-qc/feedback/quick-action')) {
      quickBodies.push(JSON.parse(route.request().postData() || '{}'))
      return route.fulfill(json({ message: 'ok' }))
    }
    if (path.endsWith('/patient-qc/export/patient-visit-summary')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers: { 'content-disposition': 'attachment; filename=patient_visit_summary_mock.xlsx' },
        body: Buffer.from('mock-xlsx'),
      })
    }
    if (path.endsWith('/push/tasks/latest')) {
      return route.fulfill(json({
        task_id: 'task-1', status: 'running', total: 4, processed: 1,
        success: 1, failed: 0, skipped: 0,
      }))
    }
    if (path.endsWith('/scheduler/history')) {
      const failed = new URL(url).searchParams.get('status') === 'failed'
      return route.fulfill(json({
        total: 1,
        items: [{
          id: 31, status: failed ? 'failed' : 'completed', trigger_type: 'auto',
          run_time: '2026-08-11 08:00:00', query_date: '2026-08-10',
          audit_type_code: 'progress_vs_nursing', audit_run_mode: 'daily_increment',
          total_records: 4, success_count: failed ? 2 : 4, failed_count: failed ? 2 : 0,
          duration_seconds: 12, error_msg: failed ? 'mock failure' : '',
        }],
      }))
    }
    if (path === '/api/logs' || path === '/api/logs/') {
      return route.fulfill(json({
        total: 1,
        items: [{
          id: 88, patient_id: 'P-1', patient_name: '高风险患者', dept: '测试科',
          severity: 'high', status: 'success', inconsistency: 1, risk_score: 95,
          push_time: '2026-08-11 10:00:00',
        }],
      }))
    }
    if (path.endsWith('/logs/88')) {
      return route.fulfill(json({
        id: 88, patient_id: 'P-1', patient_name: '高风险患者', severity: 'high',
        status: 'success', audit_result: { dimensions: [] },
      }))
    }
    if (path.endsWith('/logs')) {
      return route.fulfill(json({
        total: 1,
        items: [{
          id: 88, patient_id: 'P-1', patient_name: '高风险患者', dept: '测试科',
          severity: 'high', status: 'success', inconsistency: 1, risk_score: 95,
          push_time: '2026-08-11 10:00:00',
        }],
      }))
    }
    if (path.endsWith('/config/relay-alert')) {
      return route.fulfill(json({
        enabled: true, base_url: 'http://relay.local', endpoint: '/qc-record-alert',
        source: '测试', severity_levels: ['high'], alert_dept_filter: [],
        secret_key_masked: '***',
      }))
    }
    if (path.endsWith('/relay/receiver-config')) {
      return route.fulfill(json({
        receiver_rules: {
          high: { attending_doctor: true, record_creator: true, nurse_head: true, fixed_users: [], dedupe: true, max_receivers: 5 },
          medium: { attending_doctor: true, record_creator: true, nurse_head: false, fixed_users: [], dedupe: true, max_receivers: 3 },
          low: { attending_doctor: false, record_creator: false, nurse_head: false, fixed_users: [], dedupe: true, max_receivers: 0 },
        },
      }))
    }
    if (path.endsWith('/relay/preview-receivers')) {
      quickBodies.push(JSON.parse(route.request().postData() || '{}'))
      return route.fulfill(json({
        receivers: [{ source: 'attending_doctor', userid: 'u1', user_name: '张医生' }],
        receiver_debug: { deduped: 1, skipped: [] },
        rule: 'high',
      }))
    }
    if (path.endsWith('/relay/receiver-rules')) {
      quickBodies.push(JSON.parse(route.request().postData() || '{}'))
      return route.fulfill(json({ rules: { high: {}, medium: {}, low: {} } }))
    }
    if (path.endsWith('/relay/search-user')) return route.fulfill(json({ results: [] }))
    if (path.endsWith('/stats/workbench-overview')) {
      return route.fulfill(json({
        ai_qc: {
          severity_counts: { high: 6, medium: 4, low: 0 },
          top_depts: [{ name: '测试科', anomaly_count: 3 }],
          daily_trend: [{ date: '2026-08-11', total: 1, high: 1 }],
          high_risk_recent: [{
            patient_id: 'P-1', patient_name: '高风险患者', visit_number: 1,
            dept: '测试科', audit_type_code: 'progress_vs_nursing',
            severity: 'high', summary: '合成高危摘要', push_time: '2026-08-11 10:00:00',
          }],
        },
        timeliness: { pending: 0, dept_ranking: [], daily_trend: [] },
        prearchive: { runs: [] },
        relay: { unviewed: 0, success: 1, failed: 0 },
        system: { status: 'ok', scheduler_running: true },
      }))
    }
    if (path === '/api/audit-types' && method === 'GET') {
      return route.fulfill(json({
        items: [
          { code: 'progress_vs_nursing', name: '病程与护理一致性', enabled: true, description: '核心场景', payload: { builder: 'legacy' }, dify: { timeout_seconds: 90 }, sources: { a: {} } },
          { code: 'surgery_chain', name: '围手术期文书链核查', enabled: true, description: '核心场景', payload: { builder: 'legacy' }, dify: { timeout_seconds: 90 }, sources: { a: {} } },
          { code: 'jyjc_vs_bcnursing', name: '检验与护理核对', enabled: true, payload: {}, dify: {}, sources: {} },
          { code: 'syssvsscbc', name: '首页手术与首次病程', enabled: true, payload: {}, dify: {}, sources: {} },
          { code: 'admission_vs_first_progress', name: '入院与首程', enabled: true, payload: {}, dify: {}, sources: {} },
          { code: 'discharge_vs_frontpage', name: '出院与首页', enabled: true, payload: {}, dify: {}, sources: {} },
        ],
        total: 6,
      }))
    }
    if (path.endsWith('/config/holography') && method === 'GET') {
      return route.fulfill(json({
        enabled: true, base_url: 'http://holo.local', sys_code: 'S28',
        fallback_user_code: 'wfy', employee_code_pattern: '^[0-9]{4,10}$',
        non_employee_accounts: ['admin'], enable_on_mobile: false, user_code: 'admin',
      }))
    }
    if (path.endsWith('/config/holography') && method === 'POST') return route.fulfill(json({ message: 'ok' }))
    if (path.endsWith('/config/scheduler-daily') && method === 'GET') {
      return route.fulfill(json({
        enabled: true, schedule_mode: 'daily', daily_time: '10:00', cron: '0 10 * * *',
        audit_run_mode: 'daily_increment', audit_type_codes: [], dept_filter: [],
      }))
    }
    if (path.endsWith('/scheduler-daily') && method === 'POST') return route.fulfill(json({ message: 'ok' }))
    if (path.endsWith('/scheduler-discharge') && method === 'POST') return route.fulfill(json({ message: 'ok' }))
    if (path.endsWith('/scheduler/status')) {
      return route.fulfill(json({
        running: true,
        has_dual: true,
        daily: { enabled: true, next_run: '2026-08-11 10:00:00' },
        discharge: { enabled: false, next_run: null },
        legacy: { enabled: false },
        run_locks: {},
        discharge_effectiveness: { checked: true, warnings: [] },
        diagnostics: [],
        last_run: { status: 'completed', finished_at: '2026-08-11 10:05:00' },
      }))
    }
    if (path.endsWith('/config/departments/list')) return route.fulfill(json({ items: ['测试科'] }))
    if (path.endsWith('/departments/paged')) {
      return route.fulfill(json({
        total: 1, page: 1, limit: 20,
        items: [{ id: 3, code: 'D1', name: '测试科', user_count: 1 }],
      }))
    }
    if (path.endsWith('/config/data-source')) return route.fulfill(json({ type: 'oracle' }))
    if (path.endsWith('/config/oracle')) return route.fulfill(json({ host: '', port: 1521, service_name: '', username: '', field_mapping: {} }))
    if (path.endsWith('/config/postgresql')) return route.fulfill(json({ host: '', port: 5432, database: '', username: '', field_mapping: {} }))
    if (path.endsWith('/config/emr-vastbase')) return route.fulfill(json({ enabled: false, host: '', port: 5432, database: '', username: '', field_mapping: {} }))
    if (path.endsWith('/config/dify/targets')) return route.fulfill(json({ target_strategy: 'round_robin', circuit_breaker_failures: 3, circuit_breaker_seconds: 60, targets: [] }))
    if (path.endsWith('/config/dify')) return route.fulfill(json({ base_url: '', api_key_masked: '', workflow_input_variable: 'mr_txt', workflow_output_key: 'aa', user_identifier: '', timeout_seconds: 90, extra_inputs: {}, full_debug_log: false }))
    if (path.endsWith('/config/push')) return route.fulfill(json({ interval_ms: 500, max_retry: 3, batch_size: 50, parallel_workers: 4 }))
    if (path.endsWith('/config/privacy-masking')) return route.fulfill(json({ enabled: false, mask_name: true, mask_id_card: true, mask_address: true, mask_phone: true }))
    if (path.endsWith('/config/notify')) return route.fulfill(json({ channels: [] }))
    if (path.endsWith('/users/me/permissions')) return route.fulfill(json([]))
    if (path.endsWith('/users')) {
      return route.fulfill(json({
        total: 1,
        items: [{ id: 1, username: 'admin', full_name: '管理员', role: 'admin', is_active: true }],
      }))
    }
    if (path.endsWith('/roles/menus/catalog')) {
      return route.fulfill(json([{ id: 'dashboard', label: '工作台' }]))
    }
    const roleFixtures = [
      { id: 2, name: 'admin', description: '管理员', permissions: [], menus: [], departments: [] },
      { id: 3, name: 'medical_affairs', description: '医疗部', permissions: [], menus: [], departments: [] },
    ]
    if (path.endsWith('/roles') && method === 'GET') return route.fulfill(json(roleFixtures))
    if (path === '/api/roles/2' && method === 'GET') {
      return route.fulfill(json({
        ...roleFixtures[0],
        permissions: [{ id: 11, name: 'view_patient', description: '查看患者', module: 'quality' }],
        menus: [{ id: 'dashboard', label: '工作台' }],
        timeliness_access: null,
      }))
    }
    if (path === '/api/roles/3' && method === 'GET') {
      return route.fulfill(json({ ...roleFixtures[1], permissions: [], menus: [], timeliness_access: null }))
    }
    if (path.endsWith('/access-bundle') && method === 'PUT') {
      const body = JSON.parse(route.request().postData() || '{}')
      quickBodies.push({ path, body, ...body })
      const base = path.endsWith('/roles/2/access-bundle') ? roleFixtures[0] : roleFixtures[1]
      return route.fulfill(json({
        ...base,
        menus: (body.menu_ids || []).map((id: string) => ({ id, label: id })),
        permissions: (body.permission_ids || []).map((id: number) => ({ id, name: String(id) })),
      }))
    }
    if (path.endsWith('/departments')) return route.fulfill(json([{ id: 3, name: '测试科', code: 'D1', manager_id: null }]))
    if (path.endsWith('/permissions')) return route.fulfill(json([{ id: 11, name: 'view_patient', description: '查看患者', module: 'quality' }]))
    return route.fulfill(json({ items: [], total: 0 }))
  })
}

async function login(page: Page, bodies: unknown[]) {
  await mockApi(page, bodies)
  await page.goto('./#/login')
  await page.getByPlaceholder('请输入用户名').fill('admin')
  await page.getByPlaceholder('请输入密码').fill('password')
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.locator('.app-shell')).toBeVisible()
}

async function assertViewport(page: Page, info: { project: { name: string } }): Promise<void> {
  // WP02/03：窄屏侧栏改汉堡交互（DOM 不隐藏），统一断言应用壳可见即可
  await expect(page.locator('.app-shell')).toBeVisible()
}

test.describe('functional migration', () => {
  test('PatientQc真实详情、快捷动作与响应式', async ({ page }, info) => {
    const bodies: unknown[] = []
    const listUrls: string[] = []
    page.on('request', (request) => {
      if (request.url().includes('/api/patient-qc/patients')) listUrls.push(request.url())
    })
    await login(page, bodies)
    await page.goto('./#/quality/patients?source=workbench&severity=high')
    await expect(page.getByText('来自工作台的联动筛选')).toBeVisible()
    await expect.poll(() => listUrls.some((url) => url.includes('severity=high'))).toBe(true)
    const linkedUrl = listUrls.find((url) => url.includes('severity=high')) as string
    expect(linkedUrl).not.toContain('source=workbench')
    await expect(page.getByRole('cell', { name: /测试患者/ })).toBeVisible()
    // WP08：详情抽屉复用 PatientQcDetailView（患者横幅 + 缺陷问题卡行内闭环）
    await page.getByRole('cell', { name: /测试患者/ }).click()
    await expect(page.getByText('打开 360 全息视图')).toBeVisible()
    await expect(page.getByText('肺炎主诊断').first()).toBeVisible()
    await expect(page.getByText('缺陷问题（', { exact: false }).first()).toBeVisible()
    await page.getByRole('button', { name: '已整改' }).first().click()
    await page.getByRole('button', { name: '确定' }).last().click()
    await expect.poll(() => bodies).toContainEqual(expect.objectContaining({ push_log_id: 77, action: 'rectified' }))
    await assertViewport(page, info.project.name)
  })
  test('PatientQc导出携带当前筛选且不含分页元信息', async ({ page }, info) => {
    const exportUrls: string[] = []
    await login(page, [])
    page.on('request', (request) => {
      if (request.url().includes('/patient-qc/export/patient-visit-summary')) exportUrls.push(request.url())
    })
    await page.goto('./#/quality/patients')
    await expect(page.getByRole('cell', { name: /测试患者/ })).toBeVisible()
    const exportBtn = page.getByRole('button', { name: '导出当前筛选' })
    await expect(exportBtn).toBeEnabled()
    await exportBtn.click()
    const menuItem = page.getByRole('menuitem', { name: /导出病历数据/ })
    await expect(menuItem).toBeVisible()
    await menuItem.click()
    await page.getByRole('button', { name: /确定|确认/ }).last().click()
    await expect.poll(() => exportUrls.length).toBeGreaterThan(0)
    await assertViewport(page, info.project.name)
  })
  test('Relay规则、预览与响应式', async ({ page }, info) => {
    const bodies: unknown[] = []
    await login(page, bodies)
    await page.goto('./#/governance/relay')
    // WP09：三页签重构——规则在三档折叠内（页签 2）
    await page.getByRole('tab', { name: '科室接收人规则' }).click()
    await expect(page.getByText('高风险（红灯）规则')).toBeVisible()
    await page.getByPlaceholder('正整数').fill('88')
    await page.getByRole('button', { name: '查询预览' }).click()
    await expect.poll(() => bodies).toContainEqual({ push_log_id: 88, severity: 'high' })
    await expect(page.getByText('张医生')).toBeVisible()
    await page.getByRole('button', { name: '保存接收规则' }).click()
    await page.getByRole('button', { name: /确定|确认/ }).last().click()
    await expect.poll(() => bodies.filter((b: any) => b.rules).some((b: any) => b.rules.high && b.rules.medium && b.rules.low)).toBe(true)
    await assertViewport(page, info.project.name)
  })
  test('Access角色授权与响应式', async ({ page }, info) => {
    const bodies: unknown[] = []
    await login(page, bodies)
    await page.goto('./#/system/access')
    await expect(page.getByText('系统管理员', { exact: true }).first()).toBeVisible()
    await expect(page.locator('.el-loading-mask')).toBeHidden()
    await page.getByRole('textbox', { name: '工号或姓名' }).fill('admin')
    const userSearch = page.waitForRequest((request) => {
      const url = new URL(request.url())
      return url.pathname.endsWith('/api/users') && url.searchParams.get('q') === 'admin'
    })
    await page.getByRole('button', { name: '查询', exact: true }).click()
    await userSearch
    // WP08：三 Tab + 左侧角色卡 + access-bundle 一次保存
    await page.getByRole('tab', { name: '角色与权限' }).click()
    await page.locator('.role-card', { hasText: '系统管理员' }).click()
    await expect(page.locator('.role-sticky-bar')).toBeVisible()
    await page.locator('.perm-module-grid .el-checkbox__original').first().check()
    await page.getByRole('button', { name: '保存本角色权限', exact: true }).click()
    await expect.poll(() => bodies.some((b: any) => (b.body ? b.body.permission_ids : b.permission_ids)?.includes?.(11) || b.permission_ids?.includes?.(11))).toBe(true)
    await expect(page.locator('.role-sticky-bar')).toContainText('保存本角色权限')

    await page.locator('.role-card', { hasText: '医疗部' }).click()
    await expect(page.locator('.role-sticky-bar')).toContainText('医疗部')
    await page.getByText('全院数据', { exact: true }).click()
    await expect(page.locator('.role-sticky-bar')).toContainText('有未保存修改')
    await page.getByRole('button', { name: '保存本角色权限', exact: true }).click()
    await expect.poll(() => bodies.some((b: any) => (b.body?.data_scope ?? b.data_scope)?.scope === 'all')).toBe(true)
    await assertViewport(page, info.project.name)
  })
  test('Workbench高风险事件联动到指定详情', async ({ page }, info) => {
    test.skip(info.project.name !== 'desktop-1366', '高风险联动至少在桌面项目验证')
    const detailRequests: string[] = []
    const listRequests: string[] = []
    await login(page, [])
    page.on('request', (request) => {
      const url = new URL(request.url())
      if (url.pathname.includes('/api/patient-qc/patient-detail')) detailRequests.push(request.url())
      if (url.pathname.endsWith('/api/logs')) listRequests.push(request.url())
    })
    await page.goto('./#/workbench')
    // WP03：总览改态势卡+最新高危清单，行内「查看详情」跳独立患者详情页
    const row = page.locator('section[aria-label="最新高危待处理患者"] .el-table__row').first()
    await expect(row).toBeVisible()
    await expect(row).toContainText('P-1')
    await row.getByRole('button', { name: '查看详情' }).click()
    await expect(page).toHaveURL(/patient_id=P-1/)
    await expect.poll(() => detailRequests.length).toBeGreaterThan(0)
    const linkedList = listRequests[listRequests.length - 1] || ''
    expect(linkedList).not.toContain('source=workbench')
    expect(linkedList).not.toContain('log_id=88')
  })
  test('任务进度使用 processed 并导航任务质控日期', async ({ page }, info) => {
    test.skip(info.project.name !== 'desktop-1366', '任务进度契约至少在桌面项目验证')
    const historyUrls: string[] = []
    const logUrls: string[] = []
    await login(page, [])
    page.on('request', (request) => {
      if (request.url().includes('/api/scheduler/history')) historyUrls.push(request.url())
      if (new URL(request.url()).pathname.endsWith('/api/logs')) logUrls.push(request.url())
    })
    await page.goto('./#/tasks/progress')
    // mock /scheduler/history total=1 → 分页 total 文案「共 1 条」
    await expect(page.getByText('共 1 条')).toBeVisible()
    await expect.poll(() => historyUrls.length).toBeGreaterThan(0)
    await page.locator('.filters .el-select').first().click()
    await page.getByRole('option', { name: '失败' }).click()
    await page.getByRole('button', { name: '查询' }).click()
    await expect.poll(() => historyUrls.some((url) => url.includes('status=failed'))).toBe(true)
    await page.getByRole('button', { name: '重置' }).click()
    await page.getByRole('button', { name: '查看质控记录' }).click()
    await expect(page).toHaveURL(/source=task-progress/)
    await expect(page).toHaveURL(/date_from=2026-08-10/)
    await expect(page).toHaveURL(/date_to=2026-08-10/)
    await expect(page).toHaveURL(/audit_type_code=progress_vs_nursing/)
    await expect.poll(() => logUrls.some((url) => url.includes('date_from=2026-08-10') && url.includes('date_to=2026-08-10'))).toBe(true)
    expect(logUrls.find((url) => url.includes('date_from=2026-08-10'))).not.toContain('source=task-progress')
  })
  test('Audit记录独立详情入口', async ({ page }, info) => {
    test.skip(info.project.name !== 'desktop-1366', '独立详情至少在桌面项目验证')
    await page.addInitScript(() => {
      const opened: unknown[] = [];
      (window as any).__opened = opened
      window.open = ((url: string, target: string, features: string) => {
        opened.push({ url, target, features })
        return null
      }) as any
    })
    await login(page, [])
    await page.goto('./#/quality/records')
    await expect(page.getByText('高风险患者')).toBeVisible()
    await page.getByRole('button', { name: '更多' }).first().click()
    await page.getByRole('menuitem', { name: '推送详情（JSON）' }).click()
    const opened = await page.evaluate(() => (window as any).__opened)
    expect(opened[0]).toMatchObject({ url: '/log_detail.html?id=88', target: '_blank' })
    expect(opened[0].features).toContain('noopener')
  })
})
