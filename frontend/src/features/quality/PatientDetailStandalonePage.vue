<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import RiskTag from '@/components/base/RiskTag.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import EmptyState from '@/components/feedback/EmptyState.vue'
import { apiGet } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { displayText, formatDateTime } from '@/utils/format'

interface DetailData {
  patient: Record<string, unknown>
  summary: Record<string, unknown>
  audit_groups: Array<Record<string, unknown>>
}

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const error = ref('')
const detail = ref<DetailData | null>(null)

const patientId = computed(() => String(route.query.patient_id || ''))
const visitNumber = computed(() => String(route.query.visit_number || ''))
const dept = computed(() => String(route.query.dept || ''))

const issues = computed(() => {
  if (!detail.value?.audit_groups) return []
  const list: Array<Record<string, unknown>> = []
  for (const g of detail.value.audit_groups) {
    const logs = (g.logs as Array<Record<string, unknown>>) || []
    for (const log of logs) {
      const dims = (log.dimensions as Array<Record<string, unknown>>) || []
      for (const dim of dims) {
        if (['fail', 'risk', 'warning', 'warn'].includes(String(dim.status || '')) || dim.issue_summary) {
          list.push({
            audit_type_name: g.audit_type_name,
            dimension_name: dim.dimension || dim.dimension_name || dim.dimension_code,
            severity: dim.severity || log.severity || g.severity,
            issue_summary: dim.issue_summary || '',
            recommendation: dim.recommendation || '',
          })
        }
      }
    }
  }
  const order: Record<string, number> = { high: 0, medium: 1, low: 2 }
  return list.sort((a, b) => (order[String(a.severity)] ?? 3) - (order[String(b.severity)] ?? 3))
})

const riskLevel = computed(() => {
  if (!detail.value) return ''
  const s = detail.value.summary
  if (Number(s.high_count) > 0) return 'high'
  if (Number(s.medium_count) > 0) return 'medium'
  if (Number(s.issue_count) > 0) return 'low'
  return ''
})

async function load() {
  if (!patientId.value) {
    error.value = '缺少 patient_id 参数'
    return
  }
  loading.value = true
  error.value = ''
  try {
    detail.value = (await apiGet<DetailData>('/patient-qc/patient-detail', {
      params: { patient_id: patientId.value, visit_number: visitNumber.value, dept: dept.value },
    })) as DetailData
  } catch (e) {
    error.value = toUserMessage(e, '加载患者详情失败')
  } finally {
    loading.value = false
  }
}

function printPage() {
  window.print()
}

function back() {
  if (window.history.length > 1) router.back()
  else void router.push({ name: 'quality-patients' })
}

onMounted(load)
</script>

<template>
  <div class="standalone-detail">
    <div class="sd-toolbar no-print">
      <el-button size="small" @click="back">返回</el-button>
      <el-button type="primary" size="small" :disabled="!detail" @click="printPage">打印</el-button>
      <span class="sd-hint">本页为独立详情入口，受登录鉴权保护，可直接打印留档。</span>
    </div>

    <ErrorState v-if="error && !loading" :message="error" @retry="load" />
    <EmptyState v-else-if="!loading && !detail" description="未找到患者质控详情" />
    <div v-else v-loading="loading" class="sd-paper">
      <template v-if="detail">
        <div class="sd-head">
          <h2>患者质控详情报告</h2>
          <div class="sd-meta">
            {{ detail.patient.patient_name }} ｜ {{ detail.patient.patient_id }} ｜
            住院号 {{ displayText(detail.patient.admission_no) }} ｜
            {{ detail.patient.visit_number }} 次 ｜ {{ displayText(detail.patient.dept) }}
          </div>
          <div class="sd-counts">
            <RiskTag :value="riskLevel" />
            <span>问题 <b>{{ detail.summary.issue_count ?? 0 }}</b></span>
            <span class="sd-danger">高危 <b>{{ detail.summary.high_count ?? 0 }}</b></span>
            <span>中危 <b>{{ detail.summary.medium_count ?? 0 }}</b></span>
            <span>待处理 <b>{{ detail.summary.pending_count ?? 0 }}</b></span>
            <span class="sd-printed-at">打印时间：{{ formatDateTime(new Date().toISOString()) }}</span>
          </div>
        </div>

        <div class="sd-section">
          <h3>患者信息</h3>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="患者ID">{{ detail.patient.patient_id }}</el-descriptions-item>
            <el-descriptions-item label="姓名">{{ displayText(detail.patient.patient_name) }}</el-descriptions-item>
            <el-descriptions-item label="在院科室">{{ displayText(detail.patient.dept) }}</el-descriptions-item>
            <el-descriptions-item label="出院科室">{{ displayText(detail.patient.discharge_dept_name) }}</el-descriptions-item>
            <el-descriptions-item label="入院日期">{{ displayText(detail.patient.admission_date) }}</el-descriptions-item>
            <el-descriptions-item label="出院日期">{{ displayText(detail.patient.discharge_date) }}</el-descriptions-item>
            <el-descriptions-item label="管床医师">{{ displayText(detail.patient.attending_doctor_name) }}</el-descriptions-item>
            <el-descriptions-item label="入院诊断">{{ displayText(detail.patient.admission_diagnosis) }}</el-descriptions-item>
          </el-descriptions>
        </div>

        <div class="sd-section">
          <h3>问题明细（{{ issues.length }}）</h3>
          <div v-if="!issues.length" class="sd-empty">该患者暂无问题维度</div>
          <table v-else class="sd-table">
            <thead>
              <tr><th>严重度</th><th>核查类型</th><th>维度</th><th>问题摘要</th><th>整改建议</th></tr>
            </thead>
            <tbody>
              <tr v-for="(issue, i) in issues" :key="i">
                <td><RiskTag :value="String(issue.severity || '')" /></td>
                <td>{{ displayText(issue.audit_type_name) }}</td>
                <td>{{ displayText(issue.dimension_name) }}</td>
                <td class="sd-wrap">{{ displayText(issue.issue_summary) }}</td>
                <td class="sd-wrap">{{ displayText(issue.recommendation) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.standalone-detail { width: 100%; max-width: 980px; margin: 0 auto; }
.sd-toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; }
.sd-hint { font-size: 12px; color: var(--el-text-color-secondary); }
.sd-paper { background: #fff; border: 1px solid var(--el-border-color); border-radius: 10px; padding: 22px 26px; }
.sd-head h2 { margin: 0 0 6px; font-size: 18px; }
.sd-meta { color: var(--el-text-color-secondary); font-size: 13px; margin-bottom: 8px; }
.sd-counts { display: flex; gap: 14px; align-items: center; font-size: 13px; flex-wrap: wrap; }
.sd-counts b { margin-left: 2px; }
.sd-danger b { color: var(--el-color-danger); }
.sd-printed-at { margin-left: auto; font-size: 12px; color: var(--el-text-color-disabled); }
.sd-section { margin-top: 18px; }
.sd-section h3 { font-size: 14px; margin: 0 0 8px; }
.sd-empty { color: var(--el-text-color-disabled); text-align: center; padding: 24px; }
.sd-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.sd-table th, .sd-table td { border: 1px solid var(--el-border-color); padding: 6px 8px; text-align: left; vertical-align: top; }
.sd-table th { background: var(--el-fill-color-light); }
.sd-wrap { white-space: pre-wrap; word-break: break-all; }

@media print {
  .no-print { display: none !important; }
  .sd-paper { border: none; padding: 0; }
  .standalone-detail { max-width: none; }
}
</style>
