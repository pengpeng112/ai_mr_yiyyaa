/**
 * 手机端 H5 真实渲染冒烟测试（2026-11-17 转圈根修守护）。
 *
 * 在 jsdom 里加载 vue.global.prod.js + timeliness_h5.js（IIFE 真实执行），
 * stub fetch 序列（ping → empno 免登 → 业务接口），断言 DOM 从 loading 真实
 * 切换到主界面/登录页——守护 mount、Vue.reactive(state) 响应式、免登链路三件套。
 */
import { describe, expect, it, beforeEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const ROOT = resolve(process.cwd(), '..')
const vueCode = readFileSync(resolve(ROOT, 'frontend', 'node_modules', 'vue', 'dist', 'vue.global.prod.js'), 'utf-8')
const h5Js = readFileSync(resolve(ROOT, 'static', 'scripts', 'mobile', 'timeliness_h5.js'), 'utf-8')
const h5Html = readFileSync(resolve(ROOT, 'static', 'templates', 'mobile', 'timeliness_h5.html'), 'utf-8')

function appDivFromHtml(html: string): string {
  const m = html.match(/<div id="app"[\s\S]*<\/div>\s*<\/body>/)
  return m ? m[0].replace(/<\/body>[\s\S]*$/, '') : ''
}

type StubRoute = { match: (url: string, init: RequestInit) => boolean; status?: number; body: unknown }

function bootWithFetchStub(routes: StubRoute[]) {
  const calls: { url: string; init: RequestInit }[] = []
  // JSON 响应 stub（形如最小 Response）
  ;(window as any).fetch = ((url: any, init: RequestInit = {}) => {
    const urlText = String(url)
    calls.push({ url: urlText, init })
    const hit = routes.find((r) => r.match(urlText, init))
    const status = hit ? hit.status ?? 200 : 404
    const body = hit ? hit.body : {}
    return Promise.resolve({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    } as any)
  }) as any
  return calls
}

function installEnv(appHtml: string): void {
  document.body.innerHTML = `<div id="app">${appHtml.replace(/^<div id="app"[^>]*>/, '').replace(/<\/div>\s*$/, '')}</div>`
  // 加载 Vue 全局构建（UMD 走 window 分支挂 window.Vue）
  ;(window as any).eval(vueCode)
}

function runH5Script(): void {
  ;(window as any).eval(h5Js)
}

const ROUTES_SUCCESS: StubRoute[] = [
  { match: (u) => u.includes('/ping'), body: { ok: true, service: 'mobile-timeliness' } },
  { match: (u) => u.includes('/login/empno'), body: { access_token: 'his-token-abc', token_type: 'bearer', user: { username: '003966', full_name: '测试医师' }, his_employee: true } },
  { match: (u) => u.includes('/me'), body: { user: { username: '003966', full_name: '测试医师', role: 'his_employee', role_label: '临床员工（HIS 工号直登）', dept_name: '耳鼻喉一科' }, capabilities: { can_approve: false, can_exempt: false, jhemr_write_enabled: false } } },
  { match: (u) => u.includes('/dicts'), body: { departments: [{ code: '040112', name: '耳鼻喉一科' }], monitor_items: [], rules: [] } },
  { match: (u) => u.includes('/overview'), body: { pending_approvals: 2, today_approvals: 1, month_approvals_total: 5, month_approved: 3, month_exempt: 1, month_penalty_amount: 500, in_hosp_overdue: 3, in_hosp_warning: 1, in_hosp_applying: 0, last_scan_at: null, jhemr_write_enabled: false } },
  { match: (u) => u.includes('/events'), body: { total: 1, items: [{ id: 1, event_uid: 'x', rule_code: 'FIRST_COURSE', rule_name: '首次病程', patient_id: 'P1', visit_id: '1', dept_code: '040112', dept_name: '耳鼻喉一科', status: 'OVERDUE', status_label: '已超时未签', remain_text: '已超时 4.2 小时', t0: null, deadline: null, responsible_doctor_id: '', responsible_doctor_name: '' }] } },
  { match: (u) => u.includes('/approvals'), body: { total: 1, items: [{ id: 9, patient_id: 'A1', visit_id: '1', monitor_code: 'JH04.02.002', monitor_label: '首次病程记录', flag: '1', flag_label: '待审批锁定', type: '1', type_label: '草稿审签拦截', apply_user_id: 'u1', apply_user_name: '李医生', apply_reason: '测试', apply_date_time: null, dept_code: '040112', dept_name: '耳鼻喉一科', rule_name: '', penalty_amount: 200, penalty_exempt: false, effective_penalty: 200, approve_channel: null, approve_channel_label: '', apply_user_name2: '' }] } },
  { match: (u) => u.includes('/stats'), body: { summary: { month: '2026-11', total: 4, completed_on_time: 1, completed_late: 0, overdue: 2, warning: 0, pending: 0, on_time_rate: 25, approval_count: 5, approved_unlock_count: 3, exempt_count: 1, penalty_amount_total: 500 }, dept_ranking: [], rule_breakdown: [], doctor_penalties: [] } },
]

const ROUTES_LOGIN_FAIL: StubRoute[] = [
  { match: (u) => u.includes('/ping'), body: { ok: true } },
  { match: (u) => u.includes('/login/empno'), status: 401, body: { detail: 'empno not bound to an active system account' } },
]

async function flushDom(): Promise<void> {
  // 微任务 + 定时器多轮冲刷（启动链全异步）
  for (let i = 0; i < 6; i += 1) {
    await Promise.resolve()
    await new Promise((r) => setTimeout(r, 10))
  }
}

describe('手机端 H5 真实渲染冒烟（转圈根修守护）', () => {
  beforeEach(() => {
    window.localStorage.clear()
    window.history.replaceState(null, '', '/mobile/qc/timeliness?empno=003966')
  })

  it('免登成功：DOM 从 loading 真实切换到主界面（mount + reactive 响应式守护）', async () => {
    installEnv(appDivFromHtml(h5Html))
    const calls = bootWithFetchStub([
      { match: (u, init) => u.endsWith('/me') && !init.headers, status: 403, body: {} },
      ...ROUTES_SUCCESS,
    ])
    runH5Script()

    await flushDom()
    await flushDom()

    const html = document.getElementById('app')?.innerHTML || ''
    expect(html).toContain('待审批锁定')      // KPI 指标带（主界面）
    expect(html).toContain('超时解锁')        // 底部导航
    expect(html).not.toContain('正在连接服务') // loading 已消失
    expect(calls.some(call => call.url.includes('/login/empno'))).toBe(true)
  })

  it('优先使用企微 Cookie，并在 PCCM 与全院间切换', async () => {
    window.history.replaceState(null, '', '/mobile/qc/timeliness')
    window.localStorage.setItem('med_audit_mobile_token', 'stale-session')
    installEnv(appDivFromHtml(h5Html))
    const calls = bootWithFetchStub([
      { match: u => u.endsWith('/dicts'), body: { departments: [{ code: '040112', name: 'PCCM' }], default_dept: '040112', all_hospital: true, monitor_items: [], rules: [] } },
      ...ROUTES_SUCCESS,
    ])
    runH5Script()
    await flushDom()

    for (const path of ['/events?', '/approvals?', '/stats?']) {
      const request = calls.find(call => call.url.includes(path))
      expect(request?.url).toContain('dept=040112')
      expect(request?.init.headers).not.toHaveProperty('Authorization')
    }
    const all = Array.from(document.querySelectorAll('button')).find(button => button.textContent?.trim() === '全院')
    expect(all).toBeDefined()
    all?.click()
    await flushDom()
    expect(calls.filter(call => call.url.includes('/approvals?')).at(-1)?.url).not.toContain('dept=')
  })

  it('免登失败（工号未绑定）：落回手动登录页并显示原因（不白屏不转圈）', async () => {
    installEnv(appDivFromHtml(h5Html))
    bootWithFetchStub(ROUTES_LOGIN_FAIL)
    runH5Script()

    await flushDom()
    await flushDom()

    const html = document.getElementById('app')?.innerHTML || ''
    expect(html).toContain('登录系统')            // 登录视图
    expect(html).toContain('工号免登失败')        // 失败原因
    expect(html).not.toContain('正在连接服务')
  })

  it('源码守卫：state 经 Vue.reactive 包装且 mount 在启动探测之前', () => {
    expect(h5Js).toContain('state = Vue.reactive(state)')
    expect(h5Js.indexOf('Vue.reactive(state)')).toBeLessThan(h5Js.indexOf("APP.mount('#app')"))
    expect(h5Js.indexOf("APP.mount('#app')")).toBeLessThan(h5Js.indexOf('detectBase().then'))
  })
})
