<template>
  <div class="page-relay">
    <PageHeader
      title="企微接收人配置"
      description="企微告警推送开关、前置机连接、科室接收人规则与护士长重点接收人维护（仅配置与只读预览，不触发真实发送）。"
    >
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </template>
    </PageHeader>

    <el-alert
      type="info"
      :closable="false"
      show-icon
      class="partial-save-alert"
      title="保存策略：与加载值做差异比对，只提交改动字段；前置机地址清空时不提交（防覆盖）；签名密钥留空不提交（保护已存密文）。"
    />

    <ErrorState v-if="error && !loading" :message="error" @retry="load" />
    <div v-else v-loading="loading">
      <el-tabs v-model="activeTab" class="relay-tabs">
        <!-- ── 页签 1：推送开关与前置机 ── -->
        <el-tab-pane label="推送开关与前置机" name="base">
          <el-form label-position="top" class="relay-form">
            <div class="relay-grid">
              <div class="relay-field"><span class="rf-label">启用企微告警推送</span>
                <el-switch v-model="form.enabled" />
              </div>
              <label class="relay-field"><span class="rf-label">前置机地址（base_url）</span>
                <el-input v-model="form.base_url" placeholder="如 http://10.20.1.153:3000" />
              </label>
              <label class="relay-field"><span class="rf-label">接口路径（endpoint）</span>
                <el-input v-model="form.endpoint" placeholder="/qc-record-alert" />
              </label>
              <label class="relay-field"><span class="rf-label">签名密钥（secret_key）</span>
                <el-input v-model="form.secret_key" type="password" show-password
                  :placeholder="form.has_secret ? '已配置，留空保留旧密文' : '未配置'" />
              </label>
              <label class="relay-field"><span class="rf-label">推送风险级别</span>
                <el-select v-model="form.severity_levels" multiple placeholder="选择需推送的风险等级">
                  <el-option label="高危（红灯）" value="high" />
                  <el-option label="中风险（黄灯）" value="medium" />
                  <el-option label="低风险（蓝灯）" value="low" />
                </el-select>
              </label>
              <label class="relay-field relay-field--full"><span class="rf-label">生效科室（不选表示全院生效）</span>
                <el-select
                  v-model="form.alert_dept_filter"
                  multiple
                  filterable
                  clearable
                  collapse-tags
                  collapse-tags-tooltip
                  allow-create
                  default-first-option
                  placeholder="不选 = 全院生效；可搜索/自定义科室名"
                  style="width: 100%"
                >
                  <el-option v-for="name in deptCandidates" :key="name" :label="name" :value="name" />
                </el-select>
              </label>
            </div>
          </el-form>
          <div class="relay-actions">
            <el-button :loading="testing" @click="testRelay">测试前置机连接</el-button>
            <el-button type="primary" :loading="saving" data-testid="save-relay-base" @click="saveBase">保存本页</el-button>
          </div>
          <TestResultCard v-if="testResult" :result="testResult" />
          <p class="rf-hint">基础配置保存与加载值做 diff：只提交改动字段；未改动字段不发（局部合并语义，与后端一致）。</p>
        </el-tab-pane>

        <!-- ── 页签 2：科室接收人规则 ── -->
        <el-tab-pane label="科室接收人规则" name="rules" lazy>
          <p class="rf-hint">三档风险各一组规则：接收对象类型（管床医生/病历创建医师/护士长/固定人员）、去重、最大接收人数。</p>
          <el-collapse v-model="rulesOpen">
            <el-collapse-item v-for="level in ['high', 'medium', 'low']" :key="level" :name="level">
              <template #title>
                <span class="rules-title">{{ levelTitle(level) }}规则</span>
                <el-tag size="small" type="info" class="rules-count">{{ rules[level].fixed_users.length }} 位固定人员</el-tag>
              </template>
              <div class="checks">
                <el-checkbox v-model="rules[level].attending_doctor">管床医生</el-checkbox>
                <el-checkbox v-model="rules[level].record_creator">病历创建医师</el-checkbox>
                <el-checkbox v-model="rules[level].nurse_head">护士长</el-checkbox>
                <el-checkbox v-model="rules[level].dedupe">去重</el-checkbox>
                <span class="rf-label">最大接收人数</span>
                <el-input-number v-model="rules[level].max_receivers" :min="0" :max="50" size="small" />
              </div>
              <div class="fixed-users">
                <el-tag v-for="u in rules[level].fixed_users" :key="u.userid" closable @close="removeFixed(level, u.userid)">
                  {{ u.user_name || u.userid }}
                </el-tag>
                <span v-if="!rules[level].fixed_users.length" class="rf-hint">暂无固定人员（在下方用户搜索中加入）</span>
              </div>
            </el-collapse-item>
          </el-collapse>

          <!-- 用户搜索与固定人员分配 -->
          <el-divider content-position="left">用户搜索与固定人员分配（远程搜索）</el-divider>
          <div class="search-row">
            <label class="relay-field"><span class="rf-label">姓名关键词</span>
              <el-input v-model="searchName" placeholder="输入姓名后搜索" style="width: 200px" @keyup.enter="searchUsers" />
            </label>
            <el-button :loading="searchLoading" @click="searchUsers">搜索</el-button>
          </div>
          <el-empty v-if="!searchLoading && searchName && !searchResults.length" description="未找到匹配用户" :image-size="60" />
          <div class="search-results">
            <div v-for="u in searchResults" :key="u.userid" class="search-user">
              <span>{{ u.user_name }}（{{ u.userid }}）</span>
              <el-button size="small" @click="addFixed('high', u)">加入高危组</el-button>
              <el-button size="small" @click="addFixed('medium', u)">加入中风险组</el-button>
              <el-button size="small" @click="addFixed('low', u)">加入低风险组</el-button>
            </div>
          </div>

          <!-- 只读接收人预览 -->
          <el-divider content-position="left">接收人预览（某条记录会推送给谁）</el-divider>
          <div class="search-row">
            <label class="relay-field"><span class="rf-label">质控记录编号（push_log_id）</span>
              <el-input v-model="previewForm.push_log_id" placeholder="正整数" style="width: 180px" />
            </label>
            <label class="relay-field"><span class="rf-label">风险等级</span>
              <el-select v-model="previewForm.severity" style="width: 150px">
                <el-option label="高危（红灯）" value="high" />
                <el-option label="中风险（黄灯）" value="medium" />
                <el-option label="低风险（蓝灯）" value="low" />
              </el-select>
            </label>
            <el-button :loading="previewLoading" @click="previewReceivers">查询预览</el-button>
          </div>
          <template v-if="preview">
            <div class="rf-hint">规则：{{ preview.rule || '未配置' }} · 去重后：{{ preview.receiver_debug?.deduped ?? '—' }}</div>
            <el-table :data="preview.receivers || []" size="small" border class="mt-sm">
              <el-table-column prop="source" label="来源" width="140" />
              <el-table-column prop="userid" label="userid" width="120" />
              <el-table-column prop="user_name" label="姓名" min-width="120" />
            </el-table>
            <div v-if="preview.receiver_debug?.skipped?.length" class="skipped mt-sm">
              <span class="rf-label">未纳入原因</span>
              <el-tag v-for="(item, i) in preview.receiver_debug.skipped" :key="i" type="warning">
                {{ receiverReasonLabels[item.reason] || item.reason }}：{{ item.userid || '' }}
              </el-tag>
            </div>
            <el-collapse class="debug-collapse">
              <el-collapse-item title="高级诊断" name="debug">
                <pre class="result">{{ JSON.stringify(preview.receiver_debug, null, 2) }}</pre>
              </el-collapse-item>
            </el-collapse>
          </template>

          <div class="relay-actions">
            <el-button type="primary" :loading="ruleSaving" data-testid="save-relay-rules" @click="saveRules">保存接收规则</el-button>
          </div>
        </el-tab-pane>

        <!-- ── 页签 3：护士长/重点接收人 ── -->
        <el-tab-pane label="护士长/重点接收人" name="nurse" lazy>
          <el-form label-position="top" class="relay-form">
            <div class="relay-grid">
              <label class="relay-field"><span class="rf-label">科室编码</span>
                <el-input v-model="nurseForm.dept_code" placeholder="如 040112" />
              </label>
              <label class="relay-field"><span class="rf-label">科室名称</span>
                <el-input v-model="nurseForm.dept_name" placeholder="如 耳鼻喉一科" />
              </label>
            </div>
            <el-button :loading="nurseLoading" @click="queryNurse">按科室查询护理负责人</el-button>
          </el-form>
          <template v-if="nurseResult">
            <el-result v-if="nurseResult.found" icon="success" title="已找到护士长">
              <template #sub-title>{{ nurseResult.nurse_head?.user_name || nurseResult.nurse_head?.userid || '已配置' }}</template>
            </el-result>
            <el-result v-else icon="warning" title="未找到护士长" />
            <el-collapse class="debug-collapse">
              <el-collapse-item title="高级诊断" name="nurse-debug">
                <pre class="result">{{ JSON.stringify(nurseResult, null, 2) }}</pre>
              </el-collapse-item>
            </el-collapse>
          </template>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup lang="ts">
// WP09（064 总计划）：企微接收人配置页重构——37 行压缩模板 → 正常缩进 3 页签。
// 全部既有端点与语义保留：GET /config/relay-alert、POST /config/relay-alert
// （**局部合并：与加载值 diff 只提交改动字段；base_url 清空/secret 留空不提交**，
// 复用 utils/mutation-contracts.buildRelayPartialUpdateBody 语义）、
// GET /relay/receiver-config、POST /relay/receiver-rules、GET /relay/search-user、
// POST /relay/preview-receivers、GET /relay/test-nurse-head；
// 生效科室改可搜索多选下拉（alert_dept_filter，不选=全院生效）；
// relay-contracts 纯函数继续复用。
import { onMounted, reactive, ref } from 'vue'
import PageHeader from '@/components/base/PageHeader.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import TestResultCard from './components/TestResultCard.vue'
import { apiGet, apiPost } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { buildRelayPartialBody, type RelayFormSnapshot } from '@/utils/relay-partial'
import {
  buildReceiverRulesPayload,
  dedupeFixedUsers,
  normalizeReceiverRules,
  parsePositiveInteger,
  receiverReasonLabels,
} from '@/utils/relay-contracts'
import { ElMessage, ElMessageBox } from 'element-plus'

type R = Record<string, any>

const activeTab = ref('base')
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const ruleSaving = ref(false)
const searchLoading = ref(false)
const previewLoading = ref(false)
const nurseLoading = ref(false)
const testing = ref(false)
const testResult = ref<R | null>(null)

/** 页面表单（加载时的快照用于 diff 局部保存）。 */
const form = reactive({
  enabled: false,
  base_url: '',
  endpoint: '',
  secret_key: '',
  has_secret: false,
  severity_levels: [] as string[],
  alert_dept_filter: [] as string[],
  source: '',
})
let loadedSnapshot: RelayFormSnapshot = {
  enabled: false,
  base_url: '',
  endpoint: '',
  secret_key: '',
  source: '',
  severity_levels: [] as string[],
  alert_dept_filter: [] as string[],
}
const deptCandidates = ref<string[]>([])

const rules = reactive<any>(normalizeReceiverRules({}))
const rulesOpen = ref<string[]>(['high'])
const searchName = ref('')
const searchResults = ref<R[]>([])
const preview = ref<R | null>(null)
const nurseResult = ref<R | null>(null)
const previewForm = reactive({ push_log_id: '', severity: 'high' })
const nurseForm = reactive({ dept_code: '', dept_name: '' })

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const [base, receiver] = await Promise.all([
      apiGet<R>('/config/relay-alert'),
      apiGet<R>('/relay/receiver-config'),
    ])
    Object.assign(form, {
      enabled: !!base.enabled,
      base_url: String(base.base_url || ''),
      endpoint: String(base.endpoint || ''),
      source: String(base.source || ''),
      has_secret: !!base.secret_key_masked,
      secret_key: '',
    })
    form.severity_levels = base.severity_levels || ['high']
    form.alert_dept_filter = base.alert_dept_filter || []
    loadedSnapshot = {
      enabled: form.enabled,
      base_url: form.base_url,
      endpoint: form.endpoint,
      secret_key: '',
      source: form.source,
      severity_levels: [...form.severity_levels],
      alert_dept_filter: [...form.alert_dept_filter],
    }
    Object.assign(rules, normalizeReceiverRules(receiver.receiver_rules))
  } catch (e) {
    error.value = toUserMessage(e, '加载告警推送配置失败')
  } finally {
    loading.value = false
  }
}

async function saveBase(): Promise<void> {
  if (saving.value) return
  const formSnapshot = {
    enabled: form.enabled,
    base_url: form.base_url,
    endpoint: form.endpoint,
    secret_key: form.secret_key,
    severity_levels: form.severity_levels,
    alert_dept_filter: form.alert_dept_filter,
    source: form.source,
  } satisfies RelayFormSnapshot
  const body = buildRelayPartialBody(loadedSnapshot, formSnapshot)
  const isNoop = Object.keys(body).length === 1 && 'enabled' in body
    && body.enabled === loadedSnapshot.enabled
  if (isNoop) {
    ElMessage.info('没有改动字段，无需保存')
    return
  }
  try {
    await ElMessageBox.confirm(
      '仅提交改动字段（局部合并），不会覆盖接收规则、护士长或详情页配置。确认保存？',
      '请确认', { type: 'warning' },
    )
  } catch { return }
  saving.value = true
  try {
    await apiPost('/config/relay-alert', body)
    form.secret_key = ''
    ElMessage.success('基础配置已保存（仅提交改动字段）')
    await load()
  } catch (e) {
    ElMessage.error(toUserMessage(e, '保存失败'))
  } finally {
    saving.value = false
  }
}

async function testRelay(): Promise<void> {
  if (!(await ElMessageBox.confirm('仅检查前置机可达性，不发送业务告警。继续？', '测试确认', { type: 'info' }))) return
  testing.value = true
  try {
    testResult.value = await apiPost<R>('/config/relay-alert/test')
  } catch (e) {
    ElMessage.error(toUserMessage(e, '前置机测试失败'))
  } finally {
    testing.value = false
  }
}

async function saveRules(): Promise<void> {
  if (ruleSaving.value) return
  try { await ElMessageBox.confirm('确认保存三档接收人规则？', '请确认', { type: 'warning' }) } catch { return }
  ruleSaving.value = true
  try {
    const result = await apiPost<R>('/relay/receiver-rules', buildReceiverRulesPayload(rules))
    Object.assign(rules, normalizeReceiverRules(result.rules))
    ElMessage.success('接收规则已保存')
  } catch (e) {
    ElMessage.error(toUserMessage(e, '规则保存失败'))
  } finally {
    ruleSaving.value = false
  }
}

async function searchUsers(): Promise<void> {
  if (!searchName.value.trim()) { ElMessage.warning('请输入姓名关键词'); return }
  if (searchLoading.value) return
  searchResults.value = []
  searchLoading.value = true
  try {
    const data = await apiGet<R>('/relay/search-user', { params: { name: searchName.value.trim() } })
    searchResults.value = data.results || []
  } catch (e) {
    ElMessage.error(toUserMessage(e, '用户搜索失败'))
  } finally {
    searchLoading.value = false
  }
}

function addFixed(level: string, user: R): void {
  rules[level].fixed_users = dedupeFixedUsers([
    ...rules[level].fixed_users,
    { userid: user.userid, user_name: user.user_name },
  ])
}

function removeFixed(level: string, userid: string): void {
  rules[level].fixed_users = rules[level].fixed_users.filter((u: R) => u.userid !== userid)
}

async function previewReceivers(): Promise<void> {
  const id = parsePositiveInteger(previewForm.push_log_id)
  if (!id) { ElMessage.warning('push_log_id 必须是正整数'); return }
  if (previewLoading.value) return
  preview.value = null
  previewLoading.value = true
  try {
    preview.value = await apiPost<R>('/relay/preview-receivers', { push_log_id: id, severity: previewForm.severity })
  } catch (e) {
    ElMessage.error(toUserMessage(e, '接收人预览失败'))
  } finally {
    previewLoading.value = false
  }
}

async function queryNurse(): Promise<void> {
  if (!nurseForm.dept_code.trim() && !nurseForm.dept_name.trim()) {
    ElMessage.warning('请填写科室编码或科室名称')
    return
  }
  if (nurseLoading.value) return
  nurseResult.value = null
  nurseLoading.value = true
  try {
    nurseResult.value = await apiGet<R>('/relay/test-nurse-head', { params: { ...nurseForm } })
  } catch (e) {
    ElMessage.error(toUserMessage(e, '护士长查询失败'))
  } finally {
    nurseLoading.value = false
  }
}

function levelTitle(level: string): string {
  return ({ high: '高风险（红灯）', medium: '中风险（黄灯）', low: '低风险（蓝灯）' })[level] || level
}

onMounted(() => {
  void load()
  void apiGet<R>('/config/departments/list')
    .then((res) => { deptCandidates.value = (res.items || []) as string[] })
    .catch(() => undefined)
})
</script>

<style scoped>
.page-relay { padding: 4px; }
.partial-save-alert { margin-bottom: 12px; }
.relay-tabs { margin-top: 4px; }
.relay-form { display: grid; gap: 10px; }
.relay-grid { display: grid; grid-template-columns: repeat(2, minmax(240px, 1fr)); gap: 12px 24px; align-items: end; }
.relay-field { display: grid; gap: 4px; min-width: 0; }
.relay-field--full { grid-column: 1 / -1; }
.rf-label { font-size: 12px; color: var(--el-text-color-secondary); }
.rf-hint { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.6; margin: 0; }
.relay-actions { display: flex; gap: 8px; align-items: center; margin-top: 12px; padding-top: 10px; border-top: 1px dashed var(--el-border-color-lighter); }
.checks { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 8px; }
.fixed-users { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; min-height: 28px; margin-top: 6px; }
.rules-title { font-size: 13px; font-weight: 600; }
.rules-count { margin-left: 8px; }
.search-row { display: flex; gap: 10px; align-items: flex-end; flex-wrap: wrap; margin-bottom: 8px; }
.search-results { display: grid; gap: 6px; margin-top: 8px; }
.search-user { display: flex; gap: 8px; align-items: center; padding: 6px 10px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; flex-wrap: wrap; }
.skipped { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.debug-collapse { margin-top: 8px; }
.result { max-height: 260px; overflow: auto; background: var(--el-fill-color-light); padding: 10px; white-space: pre-wrap; margin: 0; }
.mt-sm { margin-top: 8px; }
@media (max-width: 900px) {
  .relay-grid { grid-template-columns: 1fr; }
}
</style>
