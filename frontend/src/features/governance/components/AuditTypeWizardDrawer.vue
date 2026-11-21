<script setup lang="ts">
// WP06（064 总计划，用户拍板 D4）：AI 内涵质控规则 3 步式清爽编辑抽屉（760px）。
// 步骤可自由点击切换；第 2 步高级 SQL/JSONPath 配置默认折叠（仅信息科维护）；
// 第 3 步 JHEMR 提交前提醒策略（路线 B 主推 + 路线 A 兼容）+ 模板实时预览；
// rawExtras 无损透传（保存一次绝不洗丢高级字段）；密钥留空保留旧密文。
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiPost, apiPut } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { applySourceCardsToConfig, sourceCardsFromConfig, validateAuditTypeJson } from '@/utils/audit-types'
import { DEFAULT_MESSAGE_TEMPLATE, formToPayload, ruleToForm, type WizardForm } from '@/utils/audit-type-form'

const props = defineProps<{
  visible: boolean
  rule: Record<string, any> | null
  isNew?: boolean
}>()

const emit = defineEmits<{
  'update:visible': [boolean]
  saved: []
}>()

const visible = computed({
  get: () => props.visible,
  set: (v: boolean) => emit('update:visible', v),
})

const step = ref(0)
const saving = ref(false)
const actionLoading = ref('')
const form = reactive<WizardForm>({ ...emptyForm() })

function emptyForm(): WizardForm {
  return {
    code: '', name: '', description: '', enabled: true, default_for_schedule: false,
    sort_order: 100, dimension_codes: '', builder: '',
    base_url: '', api_key: '', workflow_input_variable: 'mr_txt', workflow_output_key: 'aa',
    user_identifier: 'med-audit-system', timeout_seconds: 90,
    parse_strategy: '', result_path: '', inconsistency_path: '', severity_path: '', risk_score_path: '',
    reminder_enabled: false, delivery_mode: 'pull_api', severities: ['high'],
    trigger_stage: 'before_submit', block_submit: false, exclude_reviewed: true,
    message_template: DEFAULT_MESSAGE_TEMPLATE,
  }
}

let rawExtras: Record<string, any> = {}
const editJson = ref('')
const sourceCards = ref<Array<{ name: string; source: Record<string, any> }>>([])
const advancedOpen = ref<string[]>([])
const isNew = computed(() => !!props.isNew)
const ruleCode = computed(() => String(form.code || ''))

watch(() => props.visible, (open) => {
  if (open) openFor(props.rule)
})

function openFor(rule: Record<string, any> | null): void {
  step.value = 0
  advancedOpen.value = []
  testResult.value = null
  if (rule && Object.keys(rule).length) {
    const { form: parsed, rawExtras: extras } = ruleToForm(rule)
    Object.assign(form, emptyForm(), parsed)
    rawExtras = extras
    editJson.value = JSON.stringify(rule, null, 2)
    sourceCards.value = sourceCardsFromConfig(rule.sources).map((card) => ({
      ...card,
      source: {
        ...card.source,
        fanout_params_json: JSON.stringify(card.source.fanout_params || {}),
        mapping_entries: Object.entries((card.source.field_mapping as Record<string, string>) || {})
          .map(([key, value]) => ({ key, value })),
      },
    }))
  } else {
    Object.assign(form, emptyForm())
    rawExtras = {}
    editJson.value = ''
    sourceCards.value = []
  }
}

// ---- 步骤 2：来源卡片与高级 JSON（自旧详情抽屉迁移） ----
function addSource() {
  sourceCards.value.push({
    name: `source_${sourceCards.value.length + 1}`,
    source: {
      type: 'sql', backend: 'default', data_source: '', document_kind: '',
      load_strategy: 'bulk', required: true, query_sql: '', field_mapping: {},
      mapping_entries: [],
    },
  })
}
function copySource(index: number) {
  const card = sourceCards.value[index]
  sourceCards.value.splice(index + 1, 0, { name: `${card.name}_copy`, source: JSON.parse(JSON.stringify(card.source)) })
}
function removeSource(index: number) {
  sourceCards.value.splice(index, 1)
}
function addMapping(source: Record<string, unknown>) {
  const rows = (source.mapping_entries as Array<{ key: string; value: string }>) || []
  rows.push({ key: '', value: '' })
  source.mapping_entries = rows
}
function removeMapping(source: Record<string, unknown>, index: number) {
  const rows = (source.mapping_entries as Array<{ key: string; value: string }>) || []
  rows.splice(index, 1)
  source.mapping_entries = rows
}
function syncCardsFromJson() {
  try {
    const parsed = JSON.parse(editJson.value) as Record<string, unknown>
    sourceCards.value = sourceCardsFromConfig(parsed.sources).map((card) => ({
      ...card,
      source: {
        ...card.source,
        fanout_params_json: JSON.stringify(card.source.fanout_params || {}),
        mapping_entries: Object.entries((card.source.field_mapping as Record<string, string>) || {})
          .map(([key, value]) => ({ key, value })),
      },
    }))
    ElMessage.success('已从 JSON 同步来源卡片')
  } catch {
    ElMessage.error('JSON 格式无效，未覆盖来源卡片')
  }
}
function applyCardsToJson() {
  try {
    const parsed = JSON.parse(editJson.value) as Record<string, unknown>
    editJson.value = JSON.stringify(applySourceCardsToConfig(parsed, sourceCards.value), null, 2)
    ElMessage.success('已将来源卡片应用到 JSON')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : 'JSON 格式无效，未覆盖 JSON')
  }
}

// ---- 步骤 2：测试 Dify 连通 ----
const testSample = ref('')
const testResult = ref<Record<string, unknown> | null>(null)
const testBusy = ref(false)

async function testDify(): Promise<void> {
  if (!ruleCode.value) {
    ElMessage.warning('请先在第 1 步填写规则编码并保存后再测试 Dify 连通')
    return
  }
  if (!testSample.value.trim()) {
    ElMessage.warning('请输入脱敏测试文本')
    return
  }
  try {
    await ElMessageBox.confirm('测试 Dify 可能产生外部调用成本，确认继续？请勿填写病历正文或敏感信息。', 'Dify 测试确认', { type: 'warning' })
  } catch {
    return
  }
  testBusy.value = true
  try {
    testResult.value = await apiPost<Record<string, unknown>>(
      `/audit-types/${ruleCode.value}/test-dify`, { mr_txt_sample: testSample.value })
    ElMessage.success('Dify 测试完成')
  } catch (e) {
    ElMessage.error(toUserMessage(e, 'Dify 测试失败'))
  } finally {
    testBusy.value = false
  }
}

// ---- 第 3 步：提醒文案实时预览 ----
const templatePreview = computed(() => {
  const severityLabel = form.severities.includes('high') ? '高危'
    : form.severities.includes('medium') ? '中危' : form.severities.includes('low') ? '低危' : '高危'
  return String(form.message_template || DEFAULT_MESSAGE_TEMPLATE)
    .replace(/\{severity\}/g, severityLabel)
    .replace(/\{audit_type_name\}/g, form.name || '（规则名称）')
    .replace(/\{summary\}/g, '（此处为该条 AI 高危问题的中文摘要）')
})

function toggleSeverity(value: string, checked: boolean | unknown): void {
  const set = new Set(form.severities)
  if (checked === true) set.add(value)
  else set.delete(value)
  if (!set.size) {
    ElMessage.warning('至少保留一个触发风险等级')
    return
  }
  form.severities = ['high', 'medium', 'low'].filter((s) => set.has(s))
}

// ---- 保存 ----
function buildPayload(): Record<string, any> {
  // 若高级 JSON 被手动改过，以其为基底合并卡片，再走 rawExtras 合并
  let extras = rawExtras
  if (editJson.value.trim()) {
    try {
      const manual = JSON.parse(editJson.value) as Record<string, any>
      extras = { ...ruleToForm(manual).rawExtras, ...extras }
    } catch {
      // 高级 JSON 非法时走最后校验拦截
    }
  }
  const body = formToPayload(form, extras)
  if (sourceCards.value.length) {
    const parsed = editJson.value.trim() ? (() => {
      try { return JSON.parse(editJson.value) as Record<string, unknown> } catch { return body }
    })() : body
    return applySourceCardsToConfig(parsed as Record<string, any>, sourceCards.value)
  }
  return body
}

function validateForm(): string {
  if (!form.code.trim()) return '请填写规则编码'
  if (!form.name.trim()) return '请填写规则中文名称'
  if (String(form.message_template || '').trim().length > 300) return '提醒文案模板过长（≤300 字）'
  return ''
}

async function save(): Promise<void> {
  const formError = validateForm()
  if (formError) {
    ElMessage.warning(formError)
    return
  }
  let body: Record<string, any>
  try {
    body = buildPayload()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '来源配置无效，未保存')
    return
  }
  const contractError = validateAuditTypeJson(body)
  if (contractError) {
    ElMessage.error(contractError)
    return
  }
  try {
    await ElMessageBox.confirm(
      '确认保存质控规则？密钥字段留空将保留旧密文；builder 输出仍须为 mr_text。',
      '请确认', { type: 'warning' },
    )
  } catch {
    return
  }
  saving.value = true
  try {
    if (isNew.value) {
      await apiPost('/audit-types', body)
    } else {
      await apiPut(`/audit-types/${form.code}`, body)
    }
    ElMessage.success('已保存（高级配置字段无损保留）')
    visible.value = false
    emit('saved')
  } catch (e) {
    ElMessage.error(toUserMessage(e, '保存失败'))
  } finally {
    saving.value = false
  }
}

async function removeRule(): Promise<void> {
  if (!ruleCode.value || actionLoading.value) return
  try {
    await ElMessageBox.confirm(`确认删除 ${ruleCode.value}？此操作不可恢复。`, '删除确认', { type: 'error' })
  } catch {
    return
  }
  actionLoading.value = 'delete'
  try {
    const { apiDelete } = await import('@/api/client')
    await apiDelete(`/audit-types/${ruleCode.value}`)
    ElMessage.success('已删除')
    visible.value = false
    emit('saved')
  } catch (e) {
    ElMessage.error(toUserMessage(e, '删除失败'))
  } finally {
    actionLoading.value = ''
  }
}

defineExpose({ openFor })
</script>

<template>
  <el-drawer
    :model-value="visible"
    title="AI 内涵质控规则编辑（3 步）"
    size="760px"
    append-to-body
    destroy-on-close
    @update:model-value="(v: boolean) => emit('update:visible', v)"
  >
    <el-steps :active="step" simple class="wizard-steps">
      <el-step title="基础信息" @click="step = 0" />
      <el-step title="模型与数据" @click="step = 1" />
      <el-step title="告警与 JHEMR 提醒" @click="step = 2" />
    </el-steps>

    <!-- 第 1 步：基础信息与触发范围 -->
    <div v-show="step === 0" class="step-body">
      <div class="field-grid">
        <label class="w-field"><span class="w-label">规则编码</span>
          <el-input v-model="form.code" :disabled="!isNew" placeholder="小写字母数字下划线（编辑只读）" />
        </label>
        <label class="w-field"><span class="w-label">规则中文名称</span>
          <el-input v-model="form.name" placeholder="如：病程与护理一致性" />
        </label>
        <label class="w-field w-field--full"><span class="w-label">业务描述</span>
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="面向医务人员的规则用途说明" />
        </label>
        <label class="w-field"><span class="w-label">适用就诊维度</span>
          <el-input v-model="form.dimension_codes" placeholder="dimension_codes，逗号分隔" />
        </label>
        <label class="w-field"><span class="w-label">排序权重</span>
          <el-input-number v-model="form.sort_order" :min="0" style="width: 100%" />
        </label>
        <div class="w-field w-field--full w-switches">
          <el-checkbox v-model="form.enabled">启用该规则（停用后进入「草稿与待扩展」）</el-checkbox>
          <el-checkbox v-model="form.default_for_schedule">纳入出院终末默认调度</el-checkbox>
        </div>
        <div class="w-field w-field--full w-hint">
          运行模式说明：启用规则随每日在院核查调度自动运行；勾选「纳入出院终末默认调度」后同时参与出院终末核查批次。
        </div>
      </div>
    </div>

    <!-- 第 2 步：AI 模型（Dify）与数据来源 -->
    <div v-show="step === 1" class="step-body">
      <div class="field-grid">
        <label class="w-field w-field--full"><span class="w-label">Dify API 基础地址</span>
          <el-input v-model="form.base_url" placeholder="不要带 /workflows/run 后缀（系统自动拼接）" />
        </label>
        <label class="w-field"><span class="w-label">API 密钥</span>
          <el-input v-model="form.api_key" type="password" show-password placeholder="留空保持原密文" />
        </label>
        <label class="w-field"><span class="w-label">工作流输入变量名</span>
          <el-input v-model="form.workflow_input_variable" placeholder="默认 mr_txt" />
        </label>
        <label class="w-field"><span class="w-label">输出变量名</span>
          <el-input v-model="form.workflow_output_key" placeholder="workflow_output_key" />
        </label>
        <label class="w-field"><span class="w-label">超时时间（秒）</span>
          <el-input-number v-model="form.timeout_seconds" :min="1" :max="300" style="width: 100%" />
        </label>
        <div class="w-field w-field--full">
          <span class="w-label">一键测试 Dify 连通</span>
          <div class="test-row">
            <el-input v-model="testSample" size="small" placeholder="脱敏合成测试文本（勿填病历正文）" />
            <el-button size="small" type="warning" :loading="testBusy" @click="testDify">测试 Dify</el-button>
          </div>
          <pre v-if="testResult" class="test-result">{{ JSON.stringify({ status: testResult.status, severity: testResult.severity, risk_score: testResult.risk_score }, null, 2) }}</pre>
        </div>
      </div>

      <el-collapse v-model="advancedOpen" class="advanced-collapse">
        <el-collapse-item name="advanced">
          <template #title>
            <span class="advanced-title">高级技术配置（SQL 数据源、字段映射与 JSONPath — 仅信息科/开发者维护）</span>
          </template>
          <el-card shadow="never">
            <template #header>
              <span>SQL 查询卡片配置（Sources）</span>
              <el-button class="header-action" size="small" @click="addSource">新增来源</el-button>
            </template>
            <div v-for="(card, index) in sourceCards" :key="index" class="source-card">
              <div class="source-head">
                <el-input v-model="card.name" size="small" placeholder="source name" />
                <el-button size="small" @click="copySource(index)">复制</el-button>
                <el-button size="small" type="danger" plain @click="removeSource(index)">删除</el-button>
              </div>
              <div class="source-fields">
                <el-select v-model="card.source.backend" size="small">
                  <el-option label="default" value="default" /><el-option label="oracle" value="oracle" />
                  <el-option label="postgresql" value="postgresql" /><el-option label="emr_vastbase" value="emr_vastbase" />
                </el-select>
                <el-input v-model="card.source.data_source" size="small" placeholder="data_source（兼容字段）" />
                <el-input v-model="card.source.document_kind" size="small" placeholder="document_kind" />
                <el-select v-model="card.source.load_strategy" size="small">
                  <el-option label="bulk" value="bulk" /><el-option label="fanout" value="fanout" />
                </el-select>
                <el-checkbox v-model="card.source.required">必需</el-checkbox>
              </div>
              <el-input v-model="card.source.query_sql" type="textarea" :rows="3" placeholder="query_sql" />
              <div v-if="card.source.load_strategy === 'fanout'" class="fanout-fields">
                <el-input v-model="card.source.fanout_params_json" size="small" placeholder="fanout_params JSON" />
                <el-input-number v-model="card.source.fanout_date_window_days" :min="1" size="small" />
                <el-input-number v-model="card.source.fanout_max_workers" :min="1" size="small" />
              </div>
              <div class="mapping-list">
                <span class="w-label">字段映射 field_mapping</span>
                <div v-for="(entry, mi) in (card.source.mapping_entries as Array<{ key: string; value: string }>)" :key="mi" class="mapping-row">
                  <el-input v-model="entry.key" size="small" placeholder="源字段" />
                  <el-input v-model="entry.value" size="small" placeholder="目标字段" />
                  <el-button size="small" text type="danger" @click="removeMapping(card.source, mi)">删</el-button>
                </div>
                <el-button size="small" @click="addMapping(card.source)">增加映射</el-button>
              </div>
            </div>
          </el-card>
          <div class="sync-actions">
            <el-button size="small" @click="syncCardsFromJson">从 JSON 同步来源卡片</el-button>
            <el-button size="small" @click="applyCardsToJson">应用卡片到 JSON</el-button>
          </div>
          <div class="w-field"><span class="w-label">解析策略</span>
            <el-input v-model="form.parse_strategy" placeholder="response.parse_strategy（如 hybrid）" />
          </div>
          <div class="field-grid">
            <label class="w-field"><span class="w-label">结果路径</span>
              <el-input v-model="form.result_path" placeholder="JSONPath，必须以 $ 开头" />
            </label>
            <label class="w-field"><span class="w-label">不一致路径</span>
              <el-input v-model="form.inconsistency_path" placeholder="JSONPath" />
            </label>
            <label class="w-field"><span class="w-label">风险等级路径</span>
              <el-input v-model="form.severity_path" placeholder="JSONPath" />
            </label>
            <label class="w-field"><span class="w-label">风险分路径</span>
              <el-input v-model="form.risk_score_path" placeholder="JSONPath" />
            </label>
          </div>
          <div class="w-field"><span class="w-label">高级 JSON（保持后端原结构，未在表单中的扩展键原样透传）</span>
            <el-input v-model="editJson" type="textarea" :rows="14" class="mono" />
          </div>
        </el-collapse-item>
      </el-collapse>
    </div>

    <!-- 第 3 步：告警与 JHEMR 提交前提醒 -->
    <div v-show="step === 2" class="step-body">
      <el-alert
        type="info"
        :closable="false"
        class="step-hint"
        title="路线 B（主推）：嘉和客户端提交病历前调用本系统拉取该患者未闭环高危 AI 问题并弹窗提醒；路线 A：177 FILEVERIFY 受控写入（056 v4 启用后复用同一策略）。"
      />
      <div class="field-grid">
        <div class="w-field w-field--full w-switches">
          <el-checkbox v-model="form.reminder_enabled">开启 JHEMR 提交病历前高危提醒</el-checkbox>
        </div>
        <label class="w-field"><span class="w-label">对接通道</span>
          <el-radio-group v-model="form.delivery_mode" :disabled="!form.reminder_enabled">
            <el-radio value="pull_api">嘉和客户端接口拉取（路线 B，推荐）</el-radio>
            <el-radio value="fileverify_write">177 FILEVERIFY 规则写入（路线 A）</el-radio>
            <el-radio value="both">双路同时启用</el-radio>
          </el-radio-group>
        </label>
        <div class="w-field"><span class="w-label">触发风险等级</span>
          <div class="severity-row">
            <el-checkbox
              :model-value="form.severities.includes('high')"
              :disabled="!form.reminder_enabled"
              @change="(v: unknown) => toggleSeverity('high', v)"
            >高危</el-checkbox>
            <el-checkbox
              :model-value="form.severities.includes('medium')"
              :disabled="!form.reminder_enabled"
              @change="(v: unknown) => toggleSeverity('medium', v)"
            >中危</el-checkbox>
            <el-checkbox
              :model-value="form.severities.includes('low')"
              :disabled="!form.reminder_enabled"
              @change="(v: unknown) => toggleSeverity('low', v)"
            >低危</el-checkbox>
          </div>
        </div>
        <label class="w-field"><span class="w-label">提醒方式</span>
          <el-radio-group v-model="form.block_submit" :disabled="!form.reminder_enabled">
            <el-radio :value="false">仅弹窗提醒（允许继续提交）</el-radio>
            <el-radio :value="true">高危阻断提示（需说明/整改）</el-radio>
          </el-radio-group>
        </label>
        <div class="w-field w-field--full w-switches">
          <el-checkbox v-model="form.exclude_reviewed" :disabled="!form.reminder_enabled">
            排除已复核/已整改闭环记录（避免重复打扰）
          </el-checkbox>
        </div>
        <label class="w-field w-field--full"><span class="w-label">提醒文案模板</span>
          <el-input
            v-model="form.message_template"
            type="textarea"
            :rows="3"
            :disabled="!form.reminder_enabled"
            placeholder="支持 {severity} {audit_type_name} {summary} 占位符"
          />
        </label>
        <div class="w-field w-field--full">
          <span class="w-label">预览效果</span>
          <div class="preview-box">{{ templatePreview }}</div>
        </div>
      </div>
    </div>

    <template #footer>
      <div class="wizard-footer">
        <div class="footer-left">
          <el-button v-if="!isNew" type="danger" plain :loading="actionLoading === 'delete'" @click="removeRule">删除</el-button>
        </div>
        <el-button v-if="step > 0" @click="step--">上一步</el-button>
        <el-button v-if="step < 2" type="primary" plain @click="step++">下一步</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </div>
    </template>
  </el-drawer>
</template>

<style scoped>
.wizard-steps { margin-bottom: 14px; }
.wizard-steps :deep(.el-step) { cursor: pointer; }
.step-body { min-height: 240px; }
.field-grid { display: grid; grid-template-columns: repeat(2, minmax(240px, 1fr)); gap: 12px 16px; align-items: start; }
.w-field { display: grid; gap: 4px; min-width: 0; }
.w-field--full { grid-column: 1 / -1; }
.w-label { font-size: 12px; color: var(--el-text-color-secondary); }
.w-switches { display: flex; flex-direction: column; gap: 6px; align-items: flex-start; }
.w-hint { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.6; }
.step-hint { margin-bottom: 12px; }
.test-row { display: flex; gap: 8px; align-items: center; }
.test-row .el-input { flex: 1; }
.test-result {
  margin: 8px 0 0; color: var(--el-text-color-secondary); font-size: 12px;
  white-space: pre-wrap; border: 1px dashed var(--el-border-color); border-radius: 8px; padding: 8px;
}
.advanced-collapse { margin-top: 4px; }
.advanced-title { font-size: 13px; font-weight: 600; }
.source-card { border: 1px solid var(--el-border-color-lighter); border-radius: 8px; padding: 10px; margin-top: 8px; }
.source-head { display: flex; gap: 8px; margin-bottom: 8px; }
.source-head .el-input { flex: 1; }
.header-action { float: right; }
.source-fields, .fanout-fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px; align-items: center; margin-bottom: 8px; }
.mapping-list { margin-top: 8px; display: grid; gap: 6px; }
.mapping-row { display: grid; grid-template-columns: 1fr 1fr auto; gap: 6px; }
.sync-actions { display: flex; gap: 8px; flex-wrap: wrap; margin: 10px 0; }
.severity-row { display: flex; gap: 14px; flex-wrap: wrap; }
.preview-box {
  padding: 10px 12px; border-radius: 8px; background: #eff6ff;
  border: 1px solid #bfdbfe; color: #1e40af; font-size: 13px; line-height: 1.6;
}
.mono :deep(textarea) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}
.wizard-footer { display: flex; align-items: center; gap: 8px; }
.footer-left { flex: 1; display: flex; gap: 8px; }
@media (max-width: 680px) {
  .field-grid { grid-template-columns: 1fr; }
  .mapping-row { grid-template-columns: 1fr; }
  .source-head { flex-wrap: wrap; }
}
</style>
