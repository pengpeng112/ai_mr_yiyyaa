<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import PageHeader from '@/components/base/PageHeader.vue'
import DataTableShell from '@/components/base/DataTableShell.vue'
import DetailDrawer from '@/components/base/DetailDrawer.vue'
import { apiDelete, apiGet, apiPost, apiPut } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { prcDisabledReasonFromError, prcDisabledTitleFromReason } from '@/utils/prc-degradation'
import {
  prcApproveApi,
  prcContractTestApi,
  prcDestinationsApi,
  prcDiffApi,
  prcDryRunApi,
  prcListRulesApi,
  prcOutboxApi,
  prcPublishApi,
  prcRetryOutboxApi,
  prcRollbackApi,
  prcSettingsApi,
  prcUpsertDestinationApi,
  prcValidateApi,
  prcVersionsApi,
  type PrcDestination,
  type PrcOutboxRow,
  type PrcRuleRow,
  type PrcSettings,
} from '@/api/endpoints/prearchiveAdmin'
import { displayText } from '@/utils/format'
import { ElMessage, ElMessageBox } from 'element-plus'
import { applySourceCardsToConfig, deepClone, patchVisibleAuditFields, sourceCardsFromConfig, validateAuditTypeJson } from '@/utils/audit-types'

interface AuditTypeRow {
  code: string
  name?: string
  enabled?: boolean
  [key: string]: unknown
}

const loading = ref(false)
const error = ref('')
const items = ref<AuditTypeRow[]>([])
const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<AuditTypeRow | null>(null)
const editJson = ref('')
const saving = ref(false)
const actionLoading = ref('')
const testDate = ref('')
const testDifySample = ref('')
const testResult = ref<Record<string, unknown> | null>(null)
const sourceCards = ref<Array<{ name: string; source: Record<string, any> }>>([])
const visual = reactive({ name: '', description: '', enabled: true, default_for_schedule: false, sort_order: 100, group_key: '', dimension_codes: '', builder: '', base_url: '', api_key: '', workflow_input_variable: 'mr_txt', workflow_output_key: 'aa', user_identifier: 'med-audit-system', timeout_seconds: 90, parse_strategy: '', result_path: '', inconsistency_path: '', severity_path: '', risk_score_path: '' })
const testDateDimension = ref('query_date')
const testDept = ref('')
const createDialog = ref(false)
const cloneDialog = ref(false)
const createForm = reactive({ code: '', name: '', description: '', backend: 'oracle', query_sql: '' })
const cloneForm = reactive({ code: '', name: '' })
function addSource() { sourceCards.value.push({ name: `source_${sourceCards.value.length + 1}`, source: { type: 'sql', backend: 'default', data_source: '', document_kind: '', load_strategy: 'bulk', required: true, query_sql: '', field_mapping: {}, mapping_entries: [] } }) }
function copySource(index: number) { const card = sourceCards.value[index]; sourceCards.value.splice(index + 1, 0, { name: `${card.name}_copy`, source: deepClone(card.source) }) }
function removeSource(index: number) { sourceCards.value.splice(index, 1) }
function addMapping(source: Record<string, unknown>) { const rows = (source.mapping_entries as Array<{ key: string; value: string }>) || []; rows.push({ key: '', value: '' }); source.mapping_entries = rows }
function removeMapping(source: Record<string, unknown>, index: number) { const rows = (source.mapping_entries as Array<{ key: string; value: string }>) || []; rows.splice(index, 1); source.mapping_entries = rows }
function isDialogCancelled(error: unknown): boolean { return error === 'cancel' || error === 'close' }
function syncCardsFromJson() {
  try {
    const parsed = JSON.parse(editJson.value) as Record<string, unknown>
    sourceCards.value = sourceCardsFromConfig(parsed.sources).map((card) => ({ ...card, source: { ...card.source, fanout_params_json: JSON.stringify(card.source.fanout_params || {}), mapping_entries: Object.entries((card.source.field_mapping as Record<string, string>) || {}).map(([key, value]) => ({ key, value })) } }))
    ElMessage.success('已从 JSON 同步来源卡片')
  } catch { ElMessage.error('JSON 格式无效，未覆盖来源卡片') }
}
function applyCardsToJson() {
  try {
    const parsed = JSON.parse(editJson.value) as Record<string, unknown>
    editJson.value = JSON.stringify(applySourceCardsToConfig(parsed, sourceCards.value), null, 2)
    ElMessage.success('已将来源卡片应用到 JSON')
  } catch (e) { ElMessage.error(e instanceof Error ? e.message : 'JSON 格式无效，未覆盖 JSON') }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await apiGet<{ items?: AuditTypeRow[] } | AuditTypeRow[]>('/audit-types')
    items.value = Array.isArray(data) ? data : data.items || []
  } catch (e) {
    error.value = toUserMessage(e, '加载质控类型失败')
  } finally {
    loading.value = false
  }
}

async function openDetail(row: AuditTypeRow) {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    const full = await apiGet<AuditTypeRow>(`/audit-types/${row.code}`)
    detail.value = full
    // 脱敏后的配置；secret 以 mask 形式存在，保存时留空保留
    editJson.value = JSON.stringify(full, null, 2)
    sourceCards.value = sourceCardsFromConfig(full.sources).map((card) => ({ ...card, source: { ...card.source, fanout_params_json: JSON.stringify(card.source.fanout_params || {}), mapping_entries: Object.entries((card.source.field_mapping as Record<string, string>) || {}).map(([key, value]) => ({ key, value })) } }))
    const response = (full.response || {}) as Record<string, unknown>
    Object.assign(visual, { name: full.name || '', description: full.description || '', enabled: full.enabled !== false, default_for_schedule: !!full.default_for_schedule, sort_order: Number(full.sort_order || 100), group_key: Array.isArray(full.group_key) ? full.group_key.join(',') : '', dimension_codes: Array.isArray(full.dimension_codes) ? full.dimension_codes.join(',') : '', builder: String((full.payload as Record<string, unknown>)?.builder || ''), base_url: String((full.dify as Record<string, unknown>)?.base_url || ''), api_key: '', workflow_input_variable: String((full.dify as Record<string, unknown>)?.workflow_input_variable || 'mr_txt'), workflow_output_key: String((full.dify as Record<string, unknown>)?.workflow_output_key || 'aa'), user_identifier: String((full.dify as Record<string, unknown>)?.user_identifier || 'med-audit-system'), timeout_seconds: Number((full.dify as Record<string, unknown>)?.timeout_seconds || 90), parse_strategy: String(response.parse_strategy || ''), result_path: String(response.result_path || ''), inconsistency_path: String(response.inconsistency_path || ''), severity_path: String(response.severity_path || ''), risk_score_path: String(response.risk_score_path || '') })
  } catch (e) {
    ElMessage.error(toUserMessage(e, '加载详情失败'))
  } finally {
    detailLoading.value = false
  }
}

async function save() {
  if (!detail.value?.code) return
  let body: Record<string, unknown>
  try {
    body = JSON.parse(editJson.value) as Record<string, unknown>
  } catch {
    ElMessage.error('JSON 格式无效')
    return
  }
  try {
    body = applySourceCardsToConfig(body, sourceCards.value)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '来源配置无效，未覆盖 JSON')
    return
  }
  try {
    await ElMessageBox.confirm(
      '确认保存质控类型？密钥字段留空将保留旧密文；builder 输出仍须为 mr_text。',
      '请确认',
      { type: 'warning' },
    )
  } catch {
    return
  }
  const difyFields: Record<string, unknown> = { ...(body.dify as Record<string, unknown> || {}), base_url: visual.base_url, workflow_input_variable: visual.workflow_input_variable, workflow_output_key: visual.workflow_output_key, user_identifier: visual.user_identifier, timeout_seconds: visual.timeout_seconds }
  delete difyFields.api_key
  if (visual.api_key.trim()) difyFields.api_key = visual.api_key
  body = patchVisibleAuditFields(body, { name: visual.name, description: visual.description, enabled: visual.enabled, default_for_schedule: visual.default_for_schedule, sort_order: visual.sort_order, group_key: visual.group_key.split(',').map((s) => s.trim()).filter(Boolean), dimension_codes: visual.dimension_codes.split(',').map((s) => s.trim()).filter(Boolean), payload: { builder: visual.builder }, dify: difyFields, response: { parse_strategy: visual.parse_strategy, result_path: visual.result_path, inconsistency_path: visual.inconsistency_path, severity_path: visual.severity_path, risk_score_path: visual.risk_score_path } })
  const validationError = validateJsonContract(body)
  if (validationError) { ElMessage.error(validationError); return }
  if (actionLoading.value) return
  actionLoading.value = 'save'
  saving.value = true
  try {
    await apiPut(`/audit-types/${detail.value.code}`, body)
    ElMessage.success('已保存')
    await load()
    await openDetail(detail.value)
  } catch (e) {
    ElMessage.error(toUserMessage(e, '保存失败'))
  } finally {
    saving.value = false
    actionLoading.value = ''
  }
}

function validateJsonContract(body: Record<string, unknown>): string {
  return validateAuditTypeJson(body)
}

async function createType() {
  if (actionLoading.value) return
  createDialog.value = true
}
async function submitCreate() {
  const { code, name, description, backend, query_sql } = createForm
  if (!code || !name || !query_sql.trim()) { ElMessage.warning('编码、名称和初始查询 SQL 均为必填'); return }
  try {
    actionLoading.value = 'create'
    await ElMessageBox.confirm(`确认创建 ${code}？`, '创建确认', { type: 'warning' })
    await apiPost('/audit-types', { code, name, description, sources: { main: { type: 'sql', backend, data_source: backend, query_sql: query_sql.trim(), field_mapping: {}, required: true } } })
    createDialog.value = false; await load(); ElMessage.success('已创建')
  } catch (e) { if (!isDialogCancelled(e)) ElMessage.error(toUserMessage(e, '创建失败'))
  } finally { actionLoading.value = '' }
}

async function cloneType() {
  if (!detail.value?.code || actionLoading.value) return
  cloneForm.code = ''; cloneForm.name = `${String(detail.value.name || '')}（副本）`; cloneDialog.value = true
}
async function submitClone() {
  if (!detail.value?.code || !cloneForm.code || !cloneForm.name) return
  const newCode = cloneForm.code
  try {
    await ElMessageBox.confirm(`确认克隆为 ${newCode}？`, '克隆确认', { type: 'warning' })
    actionLoading.value = 'clone'
    await apiPost(`/audit-types/${detail.value.code}/clone`, { new_code: newCode, new_name: cloneForm.name })
    cloneDialog.value = false; ElMessage.success('已克隆')
    await load()
  } catch (e) { if (!isDialogCancelled(e)) ElMessage.error(toUserMessage(e, '克隆失败'))
  } finally { actionLoading.value = '' }
}
async function deleteType() {
  if (!detail.value?.code || actionLoading.value) return
  try {
    await ElMessageBox.confirm(`确认删除 ${detail.value.code}？此操作不可恢复。`, '删除确认', { type: 'error' })
    actionLoading.value = 'delete'
    await apiDelete(`/audit-types/${detail.value.code}`)
    detailVisible.value = false; detail.value = null; await load(); ElMessage.success('已删除')
  } catch (e) { if (!isDialogCancelled(e)) ElMessage.error(toUserMessage(e, '删除失败'))
  } finally { actionLoading.value = '' }
}
async function testSource() {
  if (!detail.value?.code || actionLoading.value || !testDate.value) { ElMessage.warning('请选择测试日期'); return }
  try {
    await ElMessageBox.confirm('Source 测试会查询真实业务库，仅可使用日期/科室条件，不会展示病历正文。确认继续？', 'Source 测试确认', { type: 'warning' })
    actionLoading.value = 'source'
    const result = await apiPost<Record<string, unknown>>(`/audit-types/${detail.value.code}/test-source`, { query_date: testDate.value, date_dimension: testDateDimension.value, dept_filter: testDept.value ? testDept.value.split(',').map((s) => s.trim()).filter(Boolean) : null })
    testResult.value = result; ElMessage.success('数据源测试完成（仅返回统计与脱敏样例）')
  } catch (e) { if (!isDialogCancelled(e)) ElMessage.error(toUserMessage(e, '数据源测试失败'))
  } finally { actionLoading.value = '' }
}
async function testDify() {
  if (!detail.value?.code || actionLoading.value || !testDifySample.value.trim()) { ElMessage.warning('请输入脱敏测试文本'); return }
  try {
    await ElMessageBox.confirm('测试 Dify 可能产生外部调用成本，确认继续？请勿填写病历正文或敏感信息。', 'Dify 测试确认', { type: 'warning' })
    actionLoading.value = 'dify'
    testResult.value = await apiPost<Record<string, unknown>>(`/audit-types/${detail.value.code}/test-dify`, { mr_txt_sample: testDifySample.value })
  } catch (e) { if (!isDialogCancelled(e)) ElMessage.error(toUserMessage(e, 'Dify 测试失败'))
  } finally { actionLoading.value = '' }
}

onMounted(() => {
  void load()
  void loadPrc()
})

// ---- 039 归档前规则中心（经主服务 BFF；不可用时降级提示不影响上方 CRUD） ----
const prcAvailable = ref<boolean | null>(null)
const prcDisabledReason = ref('')
const prcSettings = ref<PrcSettings | null>(null)
const prcRules = ref<PrcRuleRow[]>([])
const prcLoading = ref(false)
const prcFilterDomain = ref('')
const prcFilterStatus = ref('')
const prcDestinations = ref<PrcDestination[]>([])
const prcOutbox = ref<PrcOutboxRow[]>([])
const prcVersionsVisible = ref(false)
const prcVersions = ref<PrcRuleRow[]>([])
const prcVersionsKey = ref('')
const prcDiffVisible = ref(false)
const prcDiff = ref<{ changed_keys: string[]; changes: Array<{ key: string; from: unknown; to: unknown }> } | null>(null)

async function loadPrc() {
  prcLoading.value = true
  try {
    prcSettings.value = await prcSettingsApi()
    prcAvailable.value = true
    prcDisabledReason.value = ''
    await loadPrcRules()
    void loadPrcDestinations()
    void loadPrcOutbox()
  } catch (e) {
    prcAvailable.value = false
    // 041 T3：403=权限问题（不是服务故障）；502/503=服务不可用/未启用（共享口径见 utils/prc-degradation）
    prcDisabledReason.value = prcDisabledReasonFromError(e)
  } finally {
    prcLoading.value = false
  }
}

// 403 不套「规则中心不可用」前缀，避免把权限问题写成服务故障
const prcDisabledTitle = computed(() => prcDisabledTitleFromReason(
  prcDisabledReason.value,
  '。上方六类质控类型管理不受影响。',
))

async function loadPrcRules() {
  const data = await prcListRulesApi({
    domain: prcFilterDomain.value || undefined,
    status: prcFilterStatus.value || undefined,
  })
  prcRules.value = data.items || []
}

async function loadPrcDestinations() {
  const data = await prcDestinationsApi()
  prcDestinations.value = data.items || []
}

const PRC_OUTBOX_TAGS: Record<string, TagType> = { pending: 'info', sending: 'info', sent: 'success', retry: 'warning', dead: 'danger', disabled: 'info' }
function prcOutboxStatusTag(status: string): TagType {
  return PRC_OUTBOX_TAGS[status] || 'info'
}

async function loadPrcOutbox() {
  const data = await prcOutboxApi()
  prcOutbox.value = data.items || []
}

function prcDomainLabel(domain: string) {
  return ({ medical_record: '病历质控', medical_quality: '医疗质量', insurance: '医保', system_push: '系统推送' })[domain] || domain
}

function prcModeBanner() {
  const mode = prcSettings.value?.mode || 'file'
  return ({ file: '文件规则（现状）', compare: '影子比对（file 结果为准）', registry: '规则仓（已发布版本）' })[mode] || mode
}

function prcDeliveryBanner() {
  const enabled = (prcDestinations.value || []).filter((d) => d.enabled).length
  return enabled === 0 ? '对外推送关闭' : `对外推送：${enabled} 个目标启用`
}

type TagType = 'primary' | 'success' | 'warning' | 'danger' | 'info'
const PRC_STATUS_TAGS: Record<string, TagType> = { draft: 'info', validated: 'info', approved: 'warning', published: 'success', retired: 'danger' }
function prcStatusTag(status: string): TagType {
  return PRC_STATUS_TAGS[status] || 'info'
}

function prcRuleName(row: PrcRuleRow) {
  return String((row.content as { name?: string })?.name || '-')
}

async function prcValidate(row: PrcRuleRow) {
  try {
    const result = await prcValidateApi(row.rule_key, row.rule_version)
    if (result.valid) ElMessage.success('校验通过')
    else ElMessage.warning((result.errors || []).join('；') || '校验失败')
    await loadPrcRules()
  } catch (e) { ElMessage.error(toUserMessage(e, '校验失败')) }
}

async function prcDryRun(row: PrcRuleRow) {
  try {
    const result = await prcDryRunApi(row.rule_key, row.rule_version)
    const summary = (result.fixture_results || [])
      .map((r) => `${r.patient_id}/${r.visit_id}: ${r.problem_count} 问题`).join('；')
    ElMessage.info(summary || result.reason || '无 fixture 结果（demo 虚构数据）')
  } catch (e) { ElMessage.error(toUserMessage(e, '试运行失败')) }
}

async function prcApprove(row: PrcRuleRow) {
  try {
    await ElMessageBox.confirm(`确认审批 ${row.rule_key} @ ${row.rule_version}？`, '审批确认', { type: 'warning' })
    await prcApproveApi(row.rule_key, row.rule_version)
    ElMessage.success('已审批')
    await loadPrcRules()
  } catch (e) { if (!isDialogCancelled(e)) ElMessage.error(toUserMessage(e, '审批失败')) }
}

async function prcPublish(row: PrcRuleRow) {
  try {
    await ElMessageBox.confirm(
      `发布 ${row.rule_key} @ ${row.rule_version}\nSHA-256: ${row.content_sha256}\n发布后旧版本自动退役，可用回滚恢复。`,
      '确认发布（危险操作）', { type: 'warning' })
    await prcPublishApi(row.rule_key, row.rule_version)
    ElMessage.success('已发布并更新指针')
    await loadPrcRules()
  } catch (e) { if (!isDialogCancelled(e)) ElMessage.error(toUserMessage(e, '发布失败')) }
}

async function prcRollback(row: PrcRuleRow) {
  try {
    const { value } = await ElMessageBox.prompt('回滚到的已发布版本号', '回滚指针', { inputPlaceholder: '如 2026.09.02.1' })
    await prcRollbackApi(row.rule_key, String(value || '').trim())
    ElMessage.success('已回滚')
    await loadPrcRules()
  } catch (e) { if (!isDialogCancelled(e)) ElMessage.error(toUserMessage(e, '回滚失败')) }
}

async function openPrcVersions(row: PrcRuleRow) {
  prcVersionsKey.value = row.rule_key
  const data = await prcVersionsApi(row.rule_key)
  prcVersions.value = data.items || []
  prcVersionsVisible.value = true
}

async function openPrcDiff(versionA: string, versionB: string) {
  prcDiff.value = await prcDiffApi(prcVersionsKey.value, versionA, versionB)
  prcDiffVisible.value = true
}

async function prcToggleDestination(row: PrcDestination) {
  try {
    await prcUpsertDestinationApi({ code: row.code, enabled: !row.enabled })
    ElMessage.success(row.enabled ? '目标已停用' : '目标已启用（真实外发仍受 delivery 总开关控制）')
    await loadPrcDestinations()
  } catch (e) { ElMessage.error(toUserMessage(e, '目标更新失败')) }
}

async function prcContractTest(code: string) {
  try {
    await ElMessageBox.confirm(
      `向 ${code} 发送合成契约测试事件（不含真实患者数据；阶段 A 只构造请求不实际外发）？`,
      '契约测试', { type: 'info' })
    const result = await prcContractTestApi(code)
    ElMessage.success(`契约测试请求已构造（event=${result.event_id}，preview 模式）`)
  } catch (e) { if (!isDialogCancelled(e)) ElMessage.error(toUserMessage(e, '契约测试失败')) }
}

async function prcRetryOutbox(row: PrcOutboxRow) {
  try {
    await prcRetryOutboxApi(row.id)
    ElMessage.success('已重新入队')
    await loadPrcOutbox()
  } catch (e) { ElMessage.error(toUserMessage(e, '重试失败（仅 dead/disabled 可重试）')) }
}
</script>

<template>
  <div class="page-audit-types">
    <PageHeader
      title="质控类型"
      description="来源、builder、Dify、JSONPath 分层管理。mr_text/mr_txt 映射与 SQL/JSONPath 校验不可回退。"
    >
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :loading="actionLoading === 'create'" @click="createType">新建类型</el-button>
      </template>
    </PageHeader>

    <DataTableShell
      :loading="loading"
      :error="error"
      :empty="!items.length"
      :show-pagination="false"
      @retry="load"
    >
      <el-table v-loading="loading" :data="items" stripe border size="small">
        <el-table-column prop="code" label="Code" min-width="160" />
        <el-table-column label="名称" min-width="160">
          <template #default="{ row }">{{ displayText(row.name) }}</template>
        </el-table-column>
        <el-table-column label="启用" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.enabled ? 'success' : 'info'">
              {{ row.enabled ? '是' : '否' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row as AuditTypeRow)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
    </DataTableShell>

    <!-- 039 归档前规则中心：BFF 不可用时降级提示，不影响上方六类 CRUD -->
    <el-divider content-position="left">归档前规则中心（版本化维护 / 审批发布 / 目标投递）</el-divider>
    <el-alert
      v-if="prcAvailable === false"
      :title="prcDisabledTitle"
      type="info"
      :closable="false"
      style="margin-bottom: 10px"
    />
    <template v-if="prcAvailable">
      <div class="prc-toolbar">
        <el-tag size="small" :type="prcSettings?.mode === 'file' ? 'info' : prcSettings?.mode === 'compare' ? 'warning' : 'success'">运行模式：{{ prcModeBanner() }}</el-tag>
        <el-tag size="small" type="info">{{ prcDeliveryBanner() }}</el-tag>
        <el-select v-model="prcFilterDomain" placeholder="全部域" clearable size="small" style="width: 140px" @change="loadPrcRules">
          <el-option label="病历质控" value="medical_record" /><el-option label="医疗质量" value="medical_quality" />
          <el-option label="医保" value="insurance" /><el-option label="系统推送" value="system_push" />
        </el-select>
        <el-select v-model="prcFilterStatus" placeholder="全部状态" clearable size="small" style="width: 120px" @change="loadPrcRules">
          <el-option v-for="st in ['draft', 'validated', 'approved', 'published', 'retired']" :key="st" :label="st" :value="st" />
        </el-select>
        <el-button size="small" :loading="prcLoading" @click="loadPrc">刷新</el-button>
      </div>
      <el-table v-loading="prcLoading" :data="prcRules" stripe border size="small" max-height="420">
        <el-table-column prop="rule_key" label="规则ID" min-width="180" show-overflow-tooltip />
        <el-table-column label="域" width="92"><template #default="{ row }">{{ prcDomainLabel(row.domain) }}</template></el-table-column>
        <el-table-column label="名称" min-width="140" show-overflow-tooltip><template #default="{ row }">{{ prcRuleName(row as PrcRuleRow) }}</template></el-table-column>
        <el-table-column label="状态" width="92" align="center"><template #default="{ row }"><el-tag size="small" :type="prcStatusTag(row.status)">{{ row.status }}</el-tag></template></el-table-column>
        <el-table-column prop="rule_version" label="版本" width="130" show-overflow-tooltip />
        <el-table-column label="已发布" width="130" show-overflow-tooltip><template #default="{ row }">{{ row.published_version || '-' }}</template></el-table-column>
        <el-table-column label="操作" width="290" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'draft'" size="small" @click="prcValidate(row as PrcRuleRow)">校验</el-button>
            <el-button size="small" @click="prcDryRun(row as PrcRuleRow)">试运行</el-button>
            <el-button v-if="['draft', 'validated'].includes(row.status)" size="small" type="warning" @click="prcApprove(row as PrcRuleRow)">审批</el-button>
            <el-button v-if="row.status === 'approved'" size="small" type="danger" @click="prcPublish(row as PrcRuleRow)">发布</el-button>
            <el-button v-if="row.published_version" size="small" @click="prcRollback(row as PrcRuleRow)">回滚</el-button>
            <el-button size="small" @click="openPrcVersions(row as PrcRuleRow)">版本</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-divider content-position="left">投递目标（EMR/HIS）与 Outbox</el-divider>
      <el-alert title="真实 EMR/HIS 接口资料未到位（G2/G3）：目标默认禁用；契约测试仅构造合成请求，阶段 A 不实际外发。" type="warning" :closable="false" style="margin-bottom: 8px" />
      <el-table :data="prcDestinations" stripe border size="small" style="margin-bottom: 12px">
        <el-table-column prop="code" label="编码" width="110" />
        <el-table-column prop="kind" label="类型" width="64" />
        <el-table-column label="状态" width="76" align="center"><template #default="{ row }"><el-tag size="small" :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '启用' : '禁用' }}</el-tag></template></el-table-column>
        <el-table-column label="地址" min-width="220" show-overflow-tooltip><template #default="{ row }">{{ row.base_url }}{{ row.endpoint }}</template></el-table-column>
        <el-table-column prop="auth_type" label="认证" width="104" />
        <el-table-column label="密钥" width="64" align="center"><template #default="{ row }">{{ row.secret_configured ? '已配' : '未配' }}</template></el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button size="small" @click="prcToggleDestination(row as PrcDestination)">{{ row.enabled ? '停用' : '启用' }}</el-button>
            <el-button size="small" @click="prcContractTest(row.code)">契约测试</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-table :data="prcOutbox" stripe border size="small" max-height="260">
        <el-table-column prop="event_id" label="事件" min-width="180" show-overflow-tooltip />
        <el-table-column prop="destination_code" label="目标" width="100" />
        <el-table-column label="状态" width="82" align="center"><template #default="{ row }"><el-tag size="small" :type="prcOutboxStatusTag(row.status)">{{ row.status }}</el-tag></template></el-table-column>
        <el-table-column prop="attempts" label="次数" width="60" align="center" />
        <el-table-column prop="last_error" label="错误" min-width="160" show-overflow-tooltip />
        <el-table-column label="操作" width="86">
          <template #default="{ row }">
            <el-button v-if="['dead', 'disabled', 'retry'].includes(row.status)" size="small" @click="prcRetryOutbox(row as PrcOutboxRow)">重试</el-button>
          </template>
        </el-table-column>
      </el-table>
    </template>

    <el-dialog v-model="prcVersionsVisible" :title="`版本历史：${prcVersionsKey}`" width="min(92vw, 760px)">
      <el-table :data="prcVersions" stripe border size="small" max-height="360">
        <el-table-column prop="rule_version" label="版本" width="130" />
        <el-table-column label="状态" width="90" align="center"><template #default="{ row }"><el-tag size="small" :type="prcStatusTag(row.status)">{{ row.status }}</el-tag></template></el-table-column>
        <el-table-column prop="content_sha256" label="SHA-256" min-width="210" show-overflow-tooltip />
        <el-table-column prop="created_by" label="创建人" width="100" />
        <el-table-column label="操作" width="110">
          <template #default="{ row }">
            <el-button v-if="prcVersions.length" size="small" @click="openPrcDiff(prcVersions[0].rule_version, row.rule_version)">与最新差异</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
    <el-dialog v-model="prcDiffVisible" title="版本差异" width="min(92vw, 680px)">
      <el-alert v-if="prcDiff" :title="`变更键：${(prcDiff.changed_keys || []).join(', ') || '无'}`" :closable="false" style="margin-bottom: 8px" />
      <el-table :data="prcDiff?.changes || []" stripe border size="small">
        <el-table-column prop="key" label="字段" width="150" />
        <el-table-column label="from" show-overflow-tooltip><template #default="{ row }">{{ JSON.stringify(row.from) }}</template></el-table-column>
        <el-table-column label="to" show-overflow-tooltip><template #default="{ row }">{{ JSON.stringify(row.to) }}</template></el-table-column>
      </el-table>
    </el-dialog>

    <DetailDrawer v-model="detailVisible" title="质控类型详情" :loading="detailLoading" size="min(1200px, 90vw)">
      <div v-if="detail" class="editor-grid">
        <el-card shadow="never"><template #header>基本信息</template><div class="visual-grid"><el-input v-model="visual.name" placeholder="名称" /><el-input v-model="visual.description" placeholder="描述" /><el-input-number v-model="visual.sort_order" :min="0" /><el-input v-model="visual.group_key" placeholder="group_key，逗号分隔" /><el-input v-model="visual.dimension_codes" placeholder="dimension_codes，逗号分隔" /><el-input v-model="visual.builder" placeholder="payload.builder" /><el-checkbox v-model="visual.enabled">启用</el-checkbox><el-checkbox v-model="visual.default_for_schedule">默认调度</el-checkbox></div></el-card>
        <el-card shadow="never"><template #header><span>Sources</span><el-button class="header-action" size="small" @click="addSource">新增来源</el-button></template><div v-for="(card, index) in sourceCards" :key="index" class="source-card"><div class="source-head"><el-input v-model="card.name" size="small" placeholder="source name" /><el-button size="small" @click="copySource(index)">复制</el-button><el-button size="small" type="danger" plain @click="removeSource(index)">删除</el-button></div><div class="source-fields"><el-select v-model="card.source.backend" size="small"><el-option label="default" value="default" /><el-option label="oracle" value="oracle" /><el-option label="postgresql" value="postgresql" /><el-option label="emr_vastbase" value="emr_vastbase" /></el-select><el-input v-model="card.source.data_source" size="small" placeholder="data_source（兼容字段）" /><el-input v-model="card.source.document_kind" size="small" placeholder="document_kind" /><el-select v-model="card.source.load_strategy" size="small"><el-option label="bulk" value="bulk" /><el-option label="fanout" value="fanout" /></el-select><el-checkbox v-model="card.source.required">必需</el-checkbox></div><el-input v-model="card.source.query_sql" type="textarea" :rows="3" placeholder="query_sql" /><div v-if="card.source.load_strategy === 'fanout'" class="fanout-fields"><el-input v-model="card.source.fanout_params_json" size="small" placeholder="fanout_params JSON" /><el-input-number v-model="card.source.fanout_date_window_days" :min="1" size="small" /><el-input-number v-model="card.source.fanout_max_workers" :min="1" size="small" /><el-input-number v-model="card.source.fanout_max_records_per_bundle" :min="0" size="small" /><el-input-number v-model="card.source.fanout_bundle_timeout_seconds" :min="0" size="small" /><el-input v-model="card.source.kind_filter" size="small" placeholder="kind_filter" /></div><div class="mapping-list"><span>field_mapping</span><div v-for="(entry, mi) in (card.source.mapping_entries as Array<{ key: string; value: string }>)" :key="mi" class="mapping-row"><el-input v-model="entry.key" size="small" placeholder="源字段" /><el-input v-model="entry.value" size="small" placeholder="目标字段" /><el-button size="small" text type="danger" @click="removeMapping(card.source, mi)">删</el-button></div><el-button size="small" @click="addMapping(card.source)">增加映射</el-button></div></div></el-card>
        <el-card shadow="never"><template #header>Dify / Response</template><div class="visual-grid"><el-input v-model="visual.base_url" placeholder="Dify base_url" /><el-input v-model="visual.workflow_input_variable" placeholder="workflow_input_variable（建议 mr_txt）" /><el-input v-model="visual.workflow_output_key" placeholder="workflow_output_key" /><el-input v-model="visual.user_identifier" placeholder="user_identifier" /><el-input-number v-model="visual.timeout_seconds" :min="1" :max="300" /><el-input v-model="visual.parse_strategy" placeholder="response.parse_strategy" /><el-input v-model="visual.result_path" placeholder="result_path，如 $.result" /><el-input v-model="visual.inconsistency_path" placeholder="inconsistency_path" /><el-input v-model="visual.severity_path" placeholder="severity_path" /><el-input v-model="visual.risk_score_path" placeholder="risk_score_path" /></div><div class="contract-note">builder 使用 mr_text；dify_pusher 负责映射至 workflow 的 mr_txt。API Key 输入保持留空保留旧密文。</div></el-card>
        <el-card shadow="never"><template #header>只读测试</template><div class="test-row"><el-date-picker v-model="testDate" type="date" value-format="YYYY-MM-DD" placeholder="测试日期" size="small" /><el-select v-model="testDateDimension" size="small"><el-option label="查询日期" value="query_date" /><el-option label="创建日期" value="record_create_date" /><el-option label="入院日期" value="admission_date" /><el-option label="出院日期" value="discharge_date" /></el-select><el-input v-model="testDept" size="small" placeholder="可选科室，逗号分隔" /><el-button size="small" :loading="actionLoading === 'source'" @click="testSource">测试 Source</el-button><el-input v-model="testDifySample" size="small" placeholder="脱敏合成测试文本（勿填病历正文）" /><el-button size="small" type="warning" :loading="actionLoading === 'dify'" @click="testDify">测试 Dify</el-button></div><pre v-if="testResult" class="test-result">{{ JSON.stringify({ status: testResult.status, source_counts: testResult.source_counts, skipped_records: testResult.skipped_records, risk_score: testResult.risk_score, severity: testResult.severity }, null, 2) }}</pre></el-card>
      </div>
      <div class="sync-actions"><el-button size="small" @click="syncCardsFromJson">从 JSON 同步来源卡片</el-button><el-button size="small" @click="applyCardsToJson">应用卡片到 JSON</el-button></div>
      <el-divider content-position="left">高级 JSON（保持后端原结构）</el-divider>
      <el-input v-model="editJson" type="textarea" :rows="22" class="mono" />
      <div class="api-key-editor"><label>API Key（可选，留空保留原密钥）</label><el-input v-model="visual.api_key" type="password" show-password placeholder="留空保留原密钥" /></div>
      <template #footer>
        <el-button @click="detailVisible = false">取消</el-button>
        <el-button type="danger" plain :loading="actionLoading === 'delete'" @click="deleteType">删除</el-button>
        <el-button :loading="actionLoading === 'clone'" @click="cloneType">克隆</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </DetailDrawer>
    <el-dialog v-model="createDialog" title="新建质控类型" width="480px">
      <el-form label-width="90px"><el-form-item label="编码"><el-input v-model="createForm.code" placeholder="小写字母、数字、下划线" /></el-form-item><el-form-item label="名称"><el-input v-model="createForm.name" /></el-form-item><el-form-item label="描述"><el-input v-model="createForm.description" type="textarea" /></el-form-item><el-form-item label="后端"><el-select v-model="createForm.backend"><el-option label="oracle" value="oracle" /><el-option label="postgresql" value="postgresql" /><el-option label="emr_vastbase" value="emr_vastbase" /></el-select></el-form-item><el-form-item label="初始 SQL"><el-input v-model="createForm.query_sql" type="textarea" placeholder="必填：请输入初始查询 SQL" /></el-form-item></el-form>
      <template #footer><el-button @click="createDialog = false">取消</el-button><el-button type="primary" :loading="actionLoading === 'create'" @click="submitCreate">确认创建</el-button></template>
    </el-dialog>
    <el-dialog v-model="cloneDialog" title="克隆质控类型" width="480px">
      <el-form label-width="90px"><el-form-item label="新编码"><el-input v-model="cloneForm.code" /></el-form-item><el-form-item label="新名称"><el-input v-model="cloneForm.name" /></el-form-item></el-form>
      <template #footer><el-button @click="cloneDialog = false">取消</el-button><el-button type="primary" :loading="actionLoading === 'clone'" @click="submitClone">确认克隆</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.mono :deep(textarea) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}
.editor-grid { display: grid; gap: 8px; margin-bottom: 10px; }
.source-chips { display: flex; gap: 6px; flex-wrap: wrap; }
.contract-note, .test-result { margin-top: 8px; color: var(--el-text-color-secondary); font-size: 12px; white-space: pre-wrap; }
.test-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.test-row .el-input { min-width: 180px; flex: 1; }
.visual-grid, .source-fields, .fanout-fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px; align-items: center; }
.source-card { border: 1px solid var(--el-border-color-lighter); border-radius: 8px; padding: 10px; margin-top: 8px; }
.source-head { display: flex; gap: 8px; margin-bottom: 8px; }
.source-head .el-input { flex: 1; }
.header-action { float: right; }
.mapping-list { margin-top: 8px; display: grid; gap: 6px; }
.sync-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.mapping-row { display: grid; grid-template-columns: 1fr 1fr auto; gap: 6px; }
.api-key-editor { display: grid; gap: 6px; margin-top: 10px; }
.api-key-editor label { color: var(--el-text-color-secondary); font-size: 12px; }
.prc-toolbar { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 8px; }
@media (max-width: 640px) { .source-head { flex-wrap: wrap; } .mapping-row { grid-template-columns: 1fr; } }
</style>
