<template>
  <el-drawer
    :model-value="visible"
    :title="editing ? `编辑草稿：${editing.rule_key}` : '新建规则草稿'"
    size="min(100vw, 720px)"
    destroy-on-close
    @update:model-value="emit('update:visible', $event)"
  >
    <el-form label-width="92px" size="small">
      <el-form-item label="规则ID" required>
        <el-input v-model="form.rule_id" :disabled="!!editing" placeholder="如 R-TIME-XXX-24H" />
      </el-form-item>
      <el-form-item label="名称" required><el-input v-model="form.name" /></el-form-item>
      <el-form-item label="提示语" required><el-input v-model="form.message" /></el-form-item>
      <el-form-item label="类型" required>
        <el-select v-model="form.type" :disabled="!!editing" style="width: 200px">
          <el-option label="时限（time_limit）" value="time_limit" />
          <el-option label="缺文书（missing_doc）" value="missing_doc" />
          <el-option label="空项（empty_field）" value="empty_field" />
          <el-option label="重复（duplicate）" value="duplicate" />
        </el-select>
      </el-form-item>
      <el-form-item label="严重度">
        <el-radio-group v-model="form.severity">
          <el-radio value="low">low</el-radio><el-radio value="medium">medium</el-radio><el-radio value="high">high</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="版本" required><el-input v-model="form.version" placeholder="如 2026.09.10.1（草稿编辑不可改版本）" :disabled="!!editing" /></el-form-item>
      <el-form-item label="FID"><el-input-number v-model="form.mark_item_fid" :min="1" :max="999" clearable placeholder="无纸化评分项 FID" /></el-form-item>
      <el-form-item label="扣分参考"><el-input-number v-model="form.deduct_ref" :min="0" :step="0.5" /></el-form-item>
      <el-form-item label="科室范围"><el-input v-model="form.dept_codes_text" placeholder="逗号分隔科室编码；留空=全院" /></el-form-item>

      <template v-if="form.type === 'time_limit'">
        <el-form-item label="文书名" required><el-input v-model="form.doc_name" placeholder="如 入院记录" /></el-form-item>
        <el-form-item label="事件">
          <el-select v-model="form.event" style="width: 200px">
            <el-option label="入院（admission）" value="admission" />
            <el-option label="手术（surgery）" value="surgery" />
            <el-option label="出院（discharge）" value="discharge" />
          </el-select>
        </el-form-item>
        <el-form-item label="时限(小时)"><el-input-number v-model="form.threshold_hours" :min="0.5" :step="1" /></el-form-item>
        <el-form-item label="时间源">
          <el-select v-model="form.doc_time_source" style="width: 240px">
            <el-option label="v_blws 完成时间（blws）" value="blws" />
            <el-option label="嘉和标题时间戳（file_index_topic）" value="file_index_topic" />
          </el-select>
        </el-form-item>
      </template>

      <template v-if="form.type === 'missing_doc'">
        <el-form-item label="期望文书" required><el-input v-model="form.expect_text" placeholder="逗号分隔，如 手术安全核查表,手术护理记录单" /></el-form-item>
        <el-form-item label="触发 JSON" required>
          <el-input v-model="form.trigger_json" type="textarea" :rows="4" placeholder='{"patient_has":"surgery","evidence":{"surgery_evidence":"sm_itf_entry"}}' />
        </el-form-item>
        <el-form-item label="匹配 JSON" required>
          <el-input v-model="form.match_json" type="textarea" :rows="6" placeholder='{"sources":["sm_itf"],"by":"report_name_fuzzy","vocab":{},"exclude_vocab":[]}' />
        </el-form-item>
      </template>

      <template v-if="form.type === 'empty_field'">
        <el-form-item label="首页字段"><el-input v-model="form.fields_text" placeholder="逗号分隔，如 allergy_drug（注意：首页结构化源未证实，发布门将拦截）" /></el-form-item>
      </template>
      <template v-if="form.type === 'duplicate'">
        <el-form-item label="列表字段">
          <el-select v-model="form.list_field" style="width: 200px">
            <el-option label="诊断（diagnoses）" value="diagnoses" />
            <el-option label="手术（surgeries）" value="surgeries" />
          </el-select>
        </el-form-item>
      </template>

      <el-divider content-position="left">高级：整段 JSON（time_limit/missing_doc 公共 match 段可在此覆盖）</el-divider>
      <el-form-item label="内容 JSON">
        <el-input v-model="form.content_json" type="textarea" :rows="8" placeholder="留空=按上方表单构造；填写=整体覆盖（非法 JSON 拒绝保存，不会静默清空）" />
        <div v-if="jsonError" style="color: var(--el-color-danger); font-size: 12px">{{ jsonError }}</div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:visible', false)">取消</el-button>
      <el-button type="primary" :loading="submitting" :disabled="!!jsonError" @click="submit">保存草稿</el-button>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
// 046 T4/F10：UI Next 新建/编辑/复制草稿入口（表单化为主，JSON 仅高级入口；
// 非法 JSON 拒绝保存并保留用户输入——与 legacy 同契约，不再静默回落）。
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  prcCreateDraftApi,
  prcUpdateDraftApi,
  type PrcRuleRow,
} from '@/api/endpoints/prearchiveAdmin'

const props = defineProps<{
  visible: boolean
  editing: PrcRuleRow | null
  copyOf?: PrcRuleRow | null
}>()
const emit = defineEmits<{
  'update:visible': [v: boolean]
  saved: []
}>()

interface RuleForm {
  rule_id: string
  name: string
  message: string
  type: string
  severity: string
  version: string
  mark_item_fid: number | null
  deduct_ref: number
  dept_codes_text: string
  doc_name: string
  event: string
  threshold_hours: number
  doc_time_source: string
  expect_text: string
  trigger_json: string
  match_json: string
  fields_text: string
  list_field: string
  content_json: string
}

function emptyForm(): RuleForm {
  return {
    rule_id: '', name: '', message: '', type: 'time_limit', severity: 'medium',
    version: '', mark_item_fid: null, deduct_ref: 0, dept_codes_text: '',
    doc_name: '', event: 'admission', threshold_hours: 24, doc_time_source: 'blws',
    expect_text: '', trigger_json: '{\n  "patient_has": "surgery",\n  "evidence": {"surgery_evidence": "sm_itf_entry"}\n}',
    match_json: '{\n  "sources": ["jhemr_blws"],\n  "by": "report_name_fuzzy",\n  "vocab": {},\n  "exclude_vocab": []\n}',
    fields_text: '', list_field: 'diagnoses', content_json: '',
  }
}

const form = ref<RuleForm>(emptyForm())
const submitting = ref(false)

watch(() => props.visible, (open) => {
  if (!open) return
  const row = props.editing || props.copyOf || null
  if (!row) {
    form.value = emptyForm()
    return
  }
  const c = (row.content || {}) as Record<string, unknown>
  form.value = {
    ...emptyForm(),
    rule_id: props.editing ? row.rule_key : `${row.rule_key}-COPY`,
    name: String(c.name || ''),
    message: String(c.message || ''),
    type: String(c.type || 'time_limit'),
    severity: String(c.severity || 'medium'),
    version: props.editing ? row.rule_version : '',
    mark_item_fid: (c.mark_item_fid as number | null) ?? null,
    deduct_ref: Number(c.deduct_ref || 0),
    dept_codes_text: ((c.dept_codes as string[]) || []).join(','),
    doc_name: String(c.doc_name || ''),
    event: String(c.event || 'admission'),
    threshold_hours: Number(c.threshold_hours || 24),
    doc_time_source: String(c.doc_time_source || 'blws'),
    expect_text: ((c.expect as string[]) || []).join(','),
    trigger_json: JSON.stringify(c.trigger || {}, null, 2),
    match_json: JSON.stringify(c.match || {}, null, 2),
    fields_text: ((c.fields as string[]) || []).join(','),
    list_field: String(c.list_field || 'diagnoses'),
    content_json: '',
  }
})

const jsonError = computed(() => {
  if (!form.value.content_json.trim()) return ''
  try { JSON.parse(form.value.content_json); return '' } catch { return '内容 JSON 格式非法：请修正后再保存（不会静默清空）' }
})

function buildContent(): Record<string, unknown> {
  if (form.value.content_json.trim()) {
    return JSON.parse(form.value.content_json) as Record<string, unknown>
  }
  const f = form.value
  const content: Record<string, unknown> = {
    rule_id: f.rule_id.trim(),
    name: f.name.trim(),
    message: f.message.trim(),
    type: f.type,
    severity: f.severity,
    version: f.version.trim(),
    enabled: true,
    mark_item_fid: f.mark_item_fid ?? null,
    deduct_ref: Number(f.deduct_ref || 0),
    dept_codes: f.dept_codes_text.split(',').map((s) => s.trim()).filter(Boolean),
  }
  if (f.type === 'time_limit') {
    content.doc_name = f.doc_name.trim()
    content.event = f.event
    content.threshold_hours = Number(f.threshold_hours || 0)
    content.doc_time_source = f.doc_time_source
    let match: Record<string, unknown> | null = null
    try { match = JSON.parse(f.match_json || '{}') as Record<string, unknown> } catch { match = null }
    if (match === null) {
      throw new Error('match JSON 格式非法：请修正后再保存（不会静默清空）')
    }
    content.match = match
  }
  if (f.type === 'missing_doc') {
    // 非法 JSON 在 buildContent 前由 jsonError 门禁拦截（time_limit 的 match 段
    // 同样走严格校验，非法直接拒绝保存）
    let trigger: unknown = null
    let match: unknown = null
    try { trigger = JSON.parse(f.trigger_json || '{}') } catch { trigger = null }
    try { match = JSON.parse(f.match_json || '{}') } catch { match = null }
    if (trigger === null || match === null) {
      throw new Error('trigger/match JSON 格式非法：请修正后再保存（不会静默清空）')
    }
    content.trigger = trigger
    content.match = match
    content.expect = f.expect_text.split(',').map((s) => s.trim()).filter(Boolean)
  }
  if (f.type === 'empty_field') {
    content.fields = f.fields_text.split(',').map((s) => s.trim()).filter(Boolean)
  }
  if (f.type === 'duplicate') {
    content.list_field = f.list_field
  }
  return content
}

async function submit() {
  let content: Record<string, unknown>
  try {
    content = buildContent()
  } catch (error) {
    ElMessage.error((error as Error).message)
    return
  }
  submitting.value = true
  try {
    if (props.editing) {
      await prcUpdateDraftApi(props.editing.rule_key, {
        rule_version: props.editing.rule_version,
        expect_edit_version: props.editing.draft_edit_version,
        content,
      })
      ElMessage.success('草稿已保存')
    } else {
      await prcCreateDraftApi({ ...content, _domain: 'medical_record', _origin: 'manual' })
      ElMessage.success('草稿已创建')
    }
    emit('update:visible', false)
    emit('saved')
  } catch (error) {
    ElMessage.error(`保存草稿失败：${(error as Error)?.message || '请检查权限/版本冲突'}`)
  } finally {
    submitting.value = false
  }
}
</script>
