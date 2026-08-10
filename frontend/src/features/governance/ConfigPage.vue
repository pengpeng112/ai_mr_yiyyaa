<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import PageHeader from '@/components/base/PageHeader.vue'
import { apiGet, apiPost } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { ElMessage, ElMessageBox } from 'element-plus'

const activeTab = ref('datasource')
const loading = ref(false)

// 数据源
const dataSourceType = ref('oracle')
const testResults = reactive<Record<string, { status: string; latency?: number }>>({})

// Oracle
const oracleForm = reactive({
  host: '', port: 1521, service_name: '', username: '', password: '', password_masked: '',
  instant_client_dir: '', query_sql: '', dept_sql: '',
  field_mapping: { patient_id: '患者ID', visit_number: '次数', patient_name: '患者姓名', dept: '所在科室名称', admission_no: '住院号' },
})
// PostgreSQL
const pgForm = reactive({
  host: 'localhost', port: 5432, database: '', username: '', password: '', password_masked: '',
  query_sql: '', dept_sql: '',
  field_mapping: { patient_id: '患者ID', visit_number: '次数', patient_name: '患者姓名', dept: '所在科室名称', admission_no: '住院号' },
})
// Dify
const difyForm = reactive({
  base_url: '', api_key: '', api_key_masked: '', workflow_input_variable: 'mr_txt',
  workflow_output_key: 'aa', user_identifier: 'med-audit-system', timeout_seconds: 90,
  extra_inputs_text: '', full_debug_log: false,
})
const difyPool = reactive({
  target_strategy: 'round_robin', circuit_breaker_failures: 3, circuit_breaker_seconds: 60,
  targets: [] as Array<{ name: string; base_url: string; api_key: string; api_key_masked: string; has_secret: boolean; timeout_seconds: number; weight: number; enabled: boolean }>,
})
// 推送
const pushForm = reactive({ interval_ms: 500, max_retry: 3, batch_size: 50, parallel_workers: 4 })
// 隐私
const privacyForm = reactive({ enabled: false, mask_name: true, mask_id_card: true, mask_address: true, mask_phone: true })
// 科室
const deptForm = reactive({ mode: 'include', listText: '' })
const deptCandidates = ref<string[]>([])
// 前置机
const relayForm = reactive({
  enabled: false, base_url: '', endpoint: '/qc-record-alert', secret_key: '', secret_key_masked: '',
  timeout_seconds: 10, severity_levels: ['high'], source: '病历质控系统',
  max_retry: 3, retry_backoff_seconds: 5, alert_dept_filter: [] as string[],
})
// 运行总览
const runtimeSummary = ref<Record<string, unknown> | null>(null)

const saving = ref<Record<string, boolean>>({})
function setSaving(key: string, val: boolean) { (saving.value as Record<string, boolean>)[key] = val }

async function loadAll() {
  loading.value = true
  try {
    const [ds, oracle, pg, dify, targets, push, privacy, dept, relay] = await Promise.all([
      apiGet<Record<string, unknown>>('/config/data-source').catch(() => ({})),
      apiGet<Record<string, unknown>>('/config/oracle').catch(() => ({})),
      apiGet<Record<string, unknown>>('/config/postgresql').catch(() => ({})),
      apiGet<Record<string, unknown>>('/config/dify').catch(() => ({})),
      apiGet<Record<string, unknown>>('/config/dify/targets').catch(() => ({})),
      apiGet<Record<string, unknown>>('/config/push').catch(() => ({})),
      apiGet<Record<string, unknown>>('/config/privacy-masking').catch(() => ({})),
      apiGet<Record<string, unknown>>('/config/departments').catch(() => ({})),
      apiGet<Record<string, unknown>>('/config/relay-alert').catch(() => ({})),
    ])
    dataSourceType.value = String((ds as Record<string, unknown>).type || 'oracle')
    applyOracle(oracle as Record<string, unknown>)
    applyPg(pg as Record<string, unknown>)
    applyDify(dify as Record<string, unknown>)
    applyTargets(targets as Record<string, unknown>)
    Object.assign(pushForm, (push as Record<string, unknown>))
    Object.assign(privacyForm, (privacy as Record<string, unknown>))
    deptForm.mode = String((dept as Record<string, unknown>).mode || 'include')
    deptForm.listText = Array.isArray((dept as Record<string, unknown>).list) ? ((dept as Record<string, unknown>).list as string[]).join('\n') : ''
    applyRelay(relay as Record<string, unknown>)

    // 科室候选
    const deptListResp = await apiGet<{ items?: string[] }>('/config/departments/list').catch(() => ({ items: [] }))
    deptCandidates.value = (deptListResp.items || []) as string[]
  } catch (e) {
    ElMessage.error(toUserMessage(e, '加载配置失败'))
  } finally {
    loading.value = false
  }
}

function applyOracle(d: Record<string, unknown>) {
  if (!d.host) return
  oracleForm.host = String(d.host || ''); oracleForm.port = Number(d.port || 1521)
  oracleForm.service_name = String(d.service_name || ''); oracleForm.username = String(d.username || '')
  oracleForm.password_masked = String(d.password_masked || ''); oracleForm.password = ''
  oracleForm.instant_client_dir = String(d.instant_client_dir || '')
  oracleForm.query_sql = String(d.query_sql || ''); oracleForm.dept_sql = String(d.dept_sql || '')
  const fm = d.field_mapping as Record<string, string> | undefined
  if (fm) Object.assign(oracleForm.field_mapping, fm)
}
function applyPg(d: Record<string, unknown>) {
  if (!d.host) return
  pgForm.host = String(d.host || 'localhost'); pgForm.port = Number(d.port || 5432)
  pgForm.database = String(d.database || ''); pgForm.username = String(d.username || '')
  pgForm.password_masked = String(d.password_masked || ''); pgForm.password = ''
  pgForm.query_sql = String(d.query_sql || ''); pgForm.dept_sql = String(d.dept_sql || '')
  const fm = d.field_mapping as Record<string, string> | undefined
  if (fm) Object.assign(pgForm.field_mapping, fm)
}
function applyDify(d: Record<string, unknown>) {
  difyForm.base_url = String(d.base_url || ''); difyForm.api_key_masked = String(d.api_key_masked || '')
  difyForm.workflow_input_variable = String(d.workflow_input_variable || 'mr_txt')
  difyForm.workflow_output_key = String(d.workflow_output_key || 'aa')
  difyForm.user_identifier = String(d.user_identifier || 'med-audit-system')
  difyForm.timeout_seconds = Number(d.timeout_seconds || 90)
  difyForm.extra_inputs_text = d.extra_inputs ? JSON.stringify(d.extra_inputs, null, 2) : ''
  difyForm.full_debug_log = !!d.full_debug_log
}
function applyTargets(d: Record<string, unknown>) {
  difyPool.target_strategy = String(d.target_strategy || 'round_robin')
  difyPool.circuit_breaker_failures = Number(d.circuit_breaker_failures || 3)
  difyPool.circuit_breaker_seconds = Number(d.circuit_breaker_seconds || 60)
  const rawTargets = d.targets as Array<Record<string, unknown>> | undefined
  difyPool.targets = (rawTargets || []).map((t) => ({
    name: String(t.name || ''), base_url: String(t.base_url || ''),
    api_key: '', api_key_masked: String(t.api_key_masked || ''),
    has_secret: !!t.api_key || !!t.api_key_masked,
    timeout_seconds: Number(t.timeout_seconds || 90), weight: Number(t.weight || 1),
    enabled: t.enabled !== false,
  }))
}
function applyRelay(d: Record<string, unknown>) {
  relayForm.enabled = !!d.enabled; relayForm.base_url = String(d.base_url || '')
  relayForm.endpoint = String(d.endpoint || '/qc-record-alert')
  relayForm.secret_key_masked = String(d.secret_key_masked || ''); relayForm.secret_key = ''
  relayForm.timeout_seconds = Number(d.timeout_seconds || 10)
  relayForm.severity_levels = (d.severity_levels as string[]) || ['high']
  relayForm.source = String(d.source || '病历质控系统')
  relayForm.max_retry = Number(d.max_retry || 3)
  relayForm.retry_backoff_seconds = Number(d.retry_backoff_seconds || 5)
  relayForm.alert_dept_filter = (d.alert_dept_filter as string[]) || []
}

async function saveDataSource() {
  try {
    await ElMessageBox.confirm(`确认切换数据源到 ${dataSourceType.value}？`, '切换确认', { type: 'warning' })
    await apiPost('/config/data-source', { type: dataSourceType.value })
    ElMessage.success('数据源已切换')
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(toUserMessage(e, '切换失败'))
  }
}
async function save(section: string, url: string, body: Record<string, unknown>) {
  setSaving(section, true)
  try {
    await apiPost(url, body)
    ElMessage.success(`${section} 配置已保存`)
  } catch (e) {
    ElMessage.error(toUserMessage(e, `保存${section}失败`))
  } finally {
    setSaving(section, false)
  }
}

function saveOracle() {
  const body: Record<string, unknown> = { ...oracleForm }
  if (!body.password) delete body.password
  delete (body as Record<string, unknown>).password_masked
  void save('Oracle', '/config/oracle', body)
}
function savePg() {
  const body: Record<string, unknown> = { ...pgForm }
  if (!body.password) delete body.password
  delete (body as Record<string, unknown>).password_masked
  void save('PostgreSQL', '/config/postgresql', body)
}
function saveDify() {
  let extraInputs = {}
  if (difyForm.extra_inputs_text.trim()) {
    try { extraInputs = JSON.parse(difyForm.extra_inputs_text) }
    catch { ElMessage.error('extra_inputs JSON 格式错误'); return }
  }
  const body: Record<string, unknown> = {
    base_url: difyForm.base_url, workflow_input_variable: difyForm.workflow_input_variable,
    workflow_output_key: difyForm.workflow_output_key, user_identifier: difyForm.user_identifier,
    timeout_seconds: difyForm.timeout_seconds, extra_inputs: extraInputs, full_debug_log: difyForm.full_debug_log,
  }
  if (difyForm.api_key) body.api_key = difyForm.api_key
  void save('Dify', '/config/dify', body)
}
function saveTargets() {
  for (const t of difyPool.targets) {
    if (t.enabled && !t.name.trim()) { ElMessage.warning('启用节点必须有名称'); return }
    if (t.enabled && !t.base_url.trim()) { ElMessage.warning('启用节点必须有 base_url'); return }
  }
  const body = {
    target_strategy: difyPool.target_strategy,
    circuit_breaker_failures: difyPool.circuit_breaker_failures,
    circuit_breaker_seconds: difyPool.circuit_breaker_seconds,
    targets: difyPool.targets.map((t) => ({
      name: t.name, base_url: t.base_url, api_key: t.api_key || undefined,
      timeout_seconds: t.timeout_seconds, weight: t.weight, enabled: t.enabled,
    })),
  }
  void save('节点池', '/config/dify/targets', body)
}
function addTarget() {
  if (difyPool.targets.length >= 10) { ElMessage.warning('最多 10 个节点'); return }
  difyPool.targets.push({ name: '', base_url: '', api_key: '', api_key_masked: '', has_secret: false, timeout_seconds: 90, weight: 1, enabled: true })
}
function removeTarget(idx: number) { difyPool.targets.splice(idx, 1) }
function savePush() { void save('推送参数', '/config/push', { ...pushForm }) }
function savePrivacy() { void save('隐私脱敏', '/config/privacy-masking', { ...privacyForm }) }
function saveDept() {
  const list = deptForm.listText.split(/[\n,，;；]+/).map((s) => s.trim()).filter(Boolean)
  void save('科室管理', '/config/departments', { mode: deptForm.mode, list })
}
function saveRelay() {
  const body: Record<string, unknown> = {
    enabled: relayForm.enabled, base_url: relayForm.base_url, endpoint: relayForm.endpoint,
    timeout_seconds: relayForm.timeout_seconds, severity_levels: relayForm.severity_levels,
    source: relayForm.source, max_retry: relayForm.max_retry, retry_backoff_seconds: relayForm.retry_backoff_seconds,
    alert_dept_filter: relayForm.alert_dept_filter,
  }
  if (relayForm.secret_key) body.secret_key = relayForm.secret_key
  void save('前置机', '/config/relay-alert', body)
}

async function testConnection(type: 'oracle' | 'postgresql' | 'dify') {
  try {
    const data = await apiPost<{ status?: string; latency_ms?: number; message?: string }>(`/config/${type}/test`)
    testResults[type] = { status: String(data.status || 'unknown'), latency: data.latency_ms }
    if (data.status === 'up') ElMessage.success(`${type} 连接成功 (${data.latency_ms}ms)`)
    else ElMessage.error(`${type} 连接失败：${data.message || ''}`)
  } catch (e) {
    testResults[type] = { status: 'down' }
    ElMessage.error(toUserMessage(e, `${type} 测试失败`))
  }
}

async function loadRuntime() {
  try { runtimeSummary.value = await apiGet<Record<string, unknown>>('/config/runtime-summary') }
  catch (e) { ElMessage.error(toUserMessage(e, '加载运行总览失败')) }
}

function appendDept(name: string) {
  const list = deptForm.listText.split(/[\n,，]/).map((s) => s.trim()).filter(Boolean)
  if (!list.includes(name)) list.push(name)
  deptForm.listText = list.join('\n')
}

onMounted(() => { void loadAll() })
</script>

<template>
  <div class="page-config">
    <PageHeader title="系统配置" description="数据源、Dify 节点池、推送参数、隐私脱敏、科室管理、前置机告警配置。">
      <template #actions><el-button :loading="loading" @click="loadAll">刷新</el-button></template>
    </PageHeader>

    <el-tabs v-model="activeTab" type="border-card">
      <!-- 数据源 -->
      <el-tab-pane label="数据源" name="datasource">
        <div class="cfg-row"><label>当前数据源</label><el-tag>{{ dataSourceType }}</el-tag></div>
        <div class="cfg-row mt-sm">
          <label>切换</label>
          <el-radio-group v-model="dataSourceType" size="small">
            <el-radio value="oracle">Oracle</el-radio>
            <el-radio value="postgresql">PostgreSQL</el-radio>
          </el-radio-group>
          <el-button size="small" type="warning" @click="saveDataSource">切换数据源</el-button>
        </div>
      </el-tab-pane>

      <!-- Oracle -->
      <el-tab-pane label="Oracle" name="oracle">
        <div class="form-grid">
          <div class="cfg-row"><label>Host</label><el-input v-model="oracleForm.host" size="small" /></div>
          <div class="cfg-row"><label>Port</label><el-input-number v-model="oracleForm.port" size="small" /></div>
          <div class="cfg-row"><label>服务名</label><el-input v-model="oracleForm.service_name" size="small" /></div>
          <div class="cfg-row"><label>用户名</label><el-input v-model="oracleForm.username" size="small" /></div>
          <div class="cfg-row"><label>密码</label><el-input v-model="oracleForm.password" type="password" show-password placeholder="留空保留" size="small" /></div>
          <div v-if="oracleForm.password_masked" class="cfg-row"><label>当前密码</label><el-tag size="small">{{ oracleForm.password_masked }}</el-tag></div>
          <div class="cfg-row"><label>Instant Client</label><el-input v-model="oracleForm.instant_client_dir" size="small" /></div>
        </div>
        <el-collapse class="mt-sm">
          <el-collapse-item title="查询 SQL / 字段映射" name="sql">
            <div class="cfg-row"><label>病历查询SQL</label><el-input v-model="oracleForm.query_sql" type="textarea" :rows="5" size="small" /></div>
            <div class="cfg-row mt-sm"><label>科室查询SQL</label><el-input v-model="oracleForm.dept_sql" size="small" /></div>
            <div class="form-grid mt-sm">
              <div v-for="(_v, k) in oracleForm.field_mapping" :key="k" class="cfg-row">
                <label>{{ k }}</label><el-input v-model="(oracleForm.field_mapping as Record<string,string>)[k]" size="small" />
              </div>
            </div>
          </el-collapse-item>
        </el-collapse>
        <div class="action-bar mt-sm">
          <el-button size="small" type="primary" :loading="saving.Oracle" @click="saveOracle">保存</el-button>
          <el-button size="small" @click="testConnection('oracle')">测试连接</el-button>
          <el-tag v-if="testResults.oracle" size="small" :type="testResults.oracle.status === 'up' ? 'success' : 'danger'">{{ testResults.oracle.status }} {{ testResults.oracle.latency ? testResults.oracle.latency + 'ms' : '' }}</el-tag>
        </div>
      </el-tab-pane>

      <!-- PostgreSQL -->
      <el-tab-pane label="PostgreSQL" name="postgresql">
        <div class="form-grid">
          <div class="cfg-row"><label>Host</label><el-input v-model="pgForm.host" size="small" /></div>
          <div class="cfg-row"><label>Port</label><el-input-number v-model="pgForm.port" size="small" /></div>
          <div class="cfg-row"><label>数据库</label><el-input v-model="pgForm.database" size="small" /></div>
          <div class="cfg-row"><label>用户名</label><el-input v-model="pgForm.username" size="small" /></div>
          <div class="cfg-row"><label>密码</label><el-input v-model="pgForm.password" type="password" show-password placeholder="留空保留" size="small" /></div>
        </div>
        <el-collapse class="mt-sm">
          <el-collapse-item title="查询 SQL / 字段映射" name="sql">
            <div class="cfg-row"><label>病历查询SQL</label><el-input v-model="pgForm.query_sql" type="textarea" :rows="5" size="small" /></div>
            <div class="cfg-row mt-sm"><label>科室查询SQL</label><el-input v-model="pgForm.dept_sql" size="small" /></div>
          </el-collapse-item>
        </el-collapse>
        <div class="action-bar mt-sm">
          <el-button size="small" type="primary" :loading="saving.PostgreSQL" @click="savePg">保存</el-button>
          <el-button size="small" @click="testConnection('postgresql')">测试连接</el-button>
        </div>
      </el-tab-pane>

      <!-- Dify -->
      <el-tab-pane label="Dify" name="dify">
        <div class="form-grid">
          <div class="cfg-row"><label>Base URL</label><el-input v-model="difyForm.base_url" size="small" /></div>
          <div class="cfg-row"><label>API Key</label><el-input v-model="difyForm.api_key" type="password" show-password placeholder="留空保留" size="small" /></div>
          <div v-if="difyForm.api_key_masked" class="cfg-row"><label>当前Key</label><el-tag size="small">{{ difyForm.api_key_masked }}</el-tag></div>
          <div class="cfg-row"><label>输入变量</label><el-input v-model="difyForm.workflow_input_variable" size="small" /></div>
          <div class="cfg-row"><label>输出Key</label><el-input v-model="difyForm.workflow_output_key" size="small" /></div>
          <div class="cfg-row"><label>用户标识</label><el-input v-model="difyForm.user_identifier" size="small" /></div>
          <div class="cfg-row"><label>超时(秒)</label><el-input-number v-model="difyForm.timeout_seconds" size="small" /></div>
          <div class="cfg-row"><label>完整调试日志</label><el-switch v-model="difyForm.full_debug_log" size="small" /></div>
        </div>
        <div class="cfg-row mt-sm"><label>额外参数(JSON)</label><el-input v-model="difyForm.extra_inputs_text" type="textarea" :rows="3" size="small" placeholder='{"key":"value"}' /></div>
        <div class="action-bar mt-sm">
          <el-button size="small" type="primary" :loading="saving.Dify" @click="saveDify">保存</el-button>
          <el-button size="small" @click="testConnection('dify')">测试连接</el-button>
        </div>

        <!-- 多节点池 -->
        <el-divider>多节点池</el-divider>
        <div class="form-grid">
          <div class="cfg-row"><label>分配策略</label>
            <el-select v-model="difyPool.target_strategy" size="small" style="width: 140px">
              <el-option label="轮询" value="round_robin" />
              <el-option label="权重随机" value="weighted_random" />
            </el-select>
          </div>
          <div class="cfg-row"><label>熔断次数</label><el-input-number v-model="difyPool.circuit_breaker_failures" :min="1" :max="20" size="small" /></div>
          <div class="cfg-row"><label>熔断冷却(秒)</label><el-input-number v-model="difyPool.circuit_breaker_seconds" :min="1" :max="3600" size="small" /></div>
        </div>
        <div v-for="(t, idx) in difyPool.targets" :key="idx" class="target-card mt-sm">
          <div class="target-head">
            <el-switch v-model="t.enabled" size="small" />
            <el-input v-model="t.name" placeholder="节点名称" size="small" style="width: 120px" />
            <el-input v-model="t.base_url" placeholder="Base URL" size="small" style="flex: 1" />
            <el-input v-model="t.api_key" type="password" show-password placeholder="API Key（留空保留）" size="small" style="width: 160px" />
            <el-input-number v-model="t.weight" :min="1" size="small" style="width: 80px" />
            <el-button size="small" type="danger" plain @click="removeTarget(idx)">删除</el-button>
          </div>
        </div>
        <div class="action-bar mt-sm">
          <el-button size="small" @click="addTarget">+ 添加节点</el-button>
          <el-button size="small" type="primary" :loading="saving.节点池" @click="saveTargets">保存节点池</el-button>
          <span v-if="difyPool.targets.length" class="target-count">共 {{ difyPool.targets.length }} 个，启用 {{ difyPool.targets.filter(t => t.enabled).length }} 个</span>
        </div>
      </el-tab-pane>

      <!-- 推送参数 -->
      <el-tab-pane label="推送参数" name="push">
        <div class="form-grid">
          <div class="cfg-row"><label>推送间隔(ms)</label><el-input-number v-model="pushForm.interval_ms" :min="100" :step="100" size="small" /></div>
          <div class="cfg-row"><label>最大重试</label><el-input-number v-model="pushForm.max_retry" :min="0" :max="10" size="small" /></div>
          <div class="cfg-row"><label>批量大小</label><el-input-number v-model="pushForm.batch_size" :min="1" :max="500" size="small" /></div>
          <div class="cfg-row"><label>并发线程</label><el-input-number v-model="pushForm.parallel_workers" :min="1" :max="16" size="small" /></div>
        </div>
        <el-button size="small" type="primary" :loading="saving.推送参数" @click="savePush" class="mt-sm">保存</el-button>
      </el-tab-pane>

      <!-- 隐私脱敏 -->
      <el-tab-pane label="隐私脱敏" name="privacy">
        <div class="switch-list">
          <div class="cfg-row"><label>启用脱敏</label><el-switch v-model="privacyForm.enabled" size="small" /></div>
          <div class="cfg-row"><label>脱敏姓名</label><el-switch v-model="privacyForm.mask_name" size="small" /></div>
          <div class="cfg-row"><label>脱敏身份证</label><el-switch v-model="privacyForm.mask_id_card" size="small" /></div>
          <div class="cfg-row"><label>脱敏地址</label><el-switch v-model="privacyForm.mask_address" size="small" /></div>
          <div class="cfg-row"><label>脱敏电话</label><el-switch v-model="privacyForm.mask_phone" size="small" /></div>
        </div>
        <el-button size="small" type="primary" :loading="saving.隐私脱敏" @click="savePrivacy" class="mt-sm">保存</el-button>
      </el-tab-pane>

      <!-- 科室管理 -->
      <el-tab-pane label="科室管理" name="dept">
        <div class="cfg-row">
          <label>模式</label>
          <el-radio-group v-model="deptForm.mode" size="small">
            <el-radio value="include">仅包含</el-radio>
            <el-radio value="exclude">排除</el-radio>
          </el-radio-group>
        </div>
        <div class="cfg-row mt-sm">
          <label>科室列表</label>
          <el-input v-model="deptForm.listText" type="textarea" :rows="8" placeholder="每行一个科室，或用逗号分隔" size="small" />
        </div>
        <div v-if="deptCandidates.length" class="dept-tags mt-sm">
          <span class="dept-tags-label">候选科室（点击添加）：</span>
          <el-tag v-for="d in deptCandidates" :key="d" class="dept-tag" size="small" @click="appendDept(d)">{{ d }}</el-tag>
        </div>
        <el-button size="small" type="primary" :loading="saving.科室管理" @click="saveDept" class="mt-sm">保存</el-button>
      </el-tab-pane>

      <!-- 前置机告警 -->
      <el-tab-pane label="前置机告警" name="relay">
        <div class="switch-list">
          <div class="cfg-row"><label>启用</label><el-switch v-model="relayForm.enabled" size="small" /></div>
        </div>
        <div class="form-grid mt-sm">
          <div class="cfg-row"><label>Base URL</label><el-input v-model="relayForm.base_url" size="small" /></div>
          <div class="cfg-row"><label>Endpoint</label><el-input v-model="relayForm.endpoint" size="small" /></div>
          <div class="cfg-row"><label>Secret Key</label><el-input v-model="relayForm.secret_key" type="password" show-password placeholder="留空保留" size="small" /></div>
          <div v-if="relayForm.secret_key_masked" class="cfg-row"><label>当前密钥</label><el-tag size="small">{{ relayForm.secret_key_masked }}</el-tag></div>
          <div class="cfg-row"><label>超时(秒)</label><el-input-number v-model="relayForm.timeout_seconds" size="small" /></div>
          <div class="cfg-row"><label>来源标识</label><el-input v-model="relayForm.source" size="small" /></div>
          <div class="cfg-row"><label>最大重试</label><el-input-number v-model="relayForm.max_retry" size="small" /></div>
          <div class="cfg-row"><label>重试退避(秒)</label><el-input-number v-model="relayForm.retry_backoff_seconds" size="small" /></div>
        </div>
        <div class="cfg-row mt-sm">
          <label>告警严重度</label>
          <el-select v-model="relayForm.severity_levels" multiple size="small" style="width: 250px">
            <el-option label="高危" value="high" />
            <el-option label="中危" value="medium" />
            <el-option label="低危" value="low" />
          </el-select>
        </div>
        <div class="cfg-row mt-sm">
          <label>告警科室过滤</label>
          <el-select v-model="relayForm.alert_dept_filter" multiple filterable allow-create size="small" style="width: 350px" placeholder="留空为全部科室">
            <el-option v-for="d in deptCandidates" :key="d" :label="d" :value="d" />
          </el-select>
        </div>
        <el-button size="small" type="primary" :loading="saving.前置机" @click="saveRelay" class="mt-sm">保存</el-button>
      </el-tab-pane>

      <!-- 运行总览 -->
      <el-tab-pane label="运行总览" name="runtime">
        <el-button size="small" @click="loadRuntime">加载运行总览</el-button>
        <template v-if="runtimeSummary">
          <el-alert v-for="(w, i) in ((runtimeSummary as Record<string, unknown>).warnings as Array<Record<string, unknown>> || [])" :key="i"
            :type="String(w.level || 'info') as 'error' | 'warning' | 'info'" :closable="false" show-icon class="mt-sm">
            <template #title>{{ w.message }}</template>
            <template #default><span class="warn-path">{{ w.code }} · {{ w.path }}</span></template>
          </el-alert>
          <el-table v-if="((runtimeSummary as Record<string, unknown>).audit_types as unknown[])?.length" :data="(runtimeSummary as Record<string, unknown>).audit_types as Array<Record<string, unknown>>" border size="small" class="mt-sm" style="width: 100%">
            <el-table-column prop="code" label="类型" width="160" show-overflow-tooltip />
            <el-table-column prop="name" label="名称" width="120" />
            <el-table-column label="启用" width="50"><template #default="{ row }"><el-tag size="small" :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '是' : '否' }}</el-tag></template></el-table-column>
            <el-table-column prop="builder" label="Builder" width="180" show-overflow-tooltip />
            <el-table-column prop="dify_target" label="Dify目标" width="100" />
          </el-table>
        </template>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.cfg-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.cfg-row label { font-size: 12px; color: var(--el-text-color-secondary); min-width: 90px; flex-shrink: 0; }
.form-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 4px; }
.switch-list { display: flex; flex-direction: column; gap: 4px; }
.action-bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.target-card { padding: 10px; border: 1px solid var(--el-border-color); border-radius: 8px; }
.target-head { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.target-count { font-size: 12px; color: var(--el-text-color-secondary); }
.dept-tags { display: flex; gap: 4px; flex-wrap: wrap; align-items: center; }
.dept-tags-label { font-size: 12px; color: var(--el-text-color-secondary); width: 100%; margin-bottom: 4px; }
.dept-tag { cursor: pointer; }
.mt-sm { margin-top: 8px; }
.warn-path { font-size: 11px; color: var(--el-text-color-disabled); font-family: monospace; }
</style>
