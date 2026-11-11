<template>
  <el-dialog
    :model-value="visible"
    title="规则试算（Shadow Dry-Run，不写库）"
    width="min(94vw, 860px)"
    destroy-on-close
    @update:model-value="emit('update:visible', $event)"
  >
    <div v-if="loading" class="dry-run-loading">
      <el-skeleton :rows="4" animated />
      <p class="dry-run-hint">正在按待保存口径对当前在院/近期出院患者试算…</p>
    </div>

    <div v-else-if="error" class="dry-run-error">
      <el-alert type="error" :title="'试算失败'" :description="error" show-icon :closable="false" />
      <p class="dry-run-hint">
        LOCK_EMR 试算与保存同口径校验：D8 限制规则或后端写开关未开时会被拒绝（400）。
      </p>
    </div>

    <div v-else-if="result" class="dry-run-body" data-testid="dry-run-result">
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="规则">{{ result.rule_code }}</el-descriptions-item>
        <el-descriptions-item label="基准版本">v{{ result.base_version_no }}</el-descriptions-item>
      </el-descriptions>

      <el-alert
        :title="summary.headline"
        type="info"
        :closable="false"
        class="dry-run-headline"
        data-testid="dry-run-headline"
      />

      <el-alert
        v-if="summary.dataSourceNote"
        :title="summary.dataSourceNote"
        type="warning"
        :closable="false"
        class="dry-run-headline"
      />

      <div class="dry-run-histogram">
        <span
          v-for="row in summary.histogram"
          :key="row.status"
          class="dry-run-hist-chip"
          :class="`is-${row.status.toLowerCase()}`"
        >
          {{ row.label }}：{{ row.count }}
        </span>
        <span v-if="summary.histogram.length === 0" class="dry-run-hint">
          未命中任何事件（规则启用后同样不会产生台账）。
        </span>
      </div>

      <el-table :data="result.samples" size="small" border max-height="320">
        <el-table-column prop="patient_id" label="患者ID" width="110" />
        <el-table-column prop="visit_id" label="住院次" width="70" />
        <el-table-column prop="dept_code" label="科室编码" min-width="90" />
        <el-table-column prop="t0" label="起算时间 T0" min-width="150" :formatter="fmtT0" />
        <el-table-column prop="deadline" label="截止时间" min-width="150" :formatter="fmtDeadline" />
        <el-table-column label="试算状态" width="110">
          <template #default="{ row }">{{ eventStatusLabel(row.status) }}</template>
        </el-table-column>
      </el-table>
      <p v-if="result.sample_truncated" class="dry-run-hint">
        样例仅展示前 {{ result.samples.length }} 条（后端上限 50，绝不写库）。
      </p>
    </div>

    <div v-else class="dry-run-hint">点击【开始试算】后展示命中人数与样例。</div>

    <template #footer>
      <el-button @click="emit('update:visible', false)">关闭</el-button>
      <el-button type="primary" :loading="loading" :disabled="!ruleCode" @click="run">
        开始试算
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
// T6 试算面板：调用 POST /rules/{code}/dry-run（待保存口径，绝不写库），
// 渲染命中统计（dryRunSummary）与样例表；数据源不可用时明确降级提示。
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { dryRunRuleApi } from './api'
import { dryRunSummary, eventStatusLabel, type DryRunResult, type DryRunSummary } from './types'

const props = defineProps<{
  visible: boolean
  ruleCode: string
  /** 待保存口径的版本改动（draftToChanges 产物）；空对象=按当前版本原样试算。 */
  changes?: Record<string, unknown>
  /** 打开时是否自动试算一次。 */
  autoRun?: boolean
}>()
const emit = defineEmits<{ 'update:visible': [v: boolean] }>()

const loading = ref(false)
const error = ref('')
const result = ref<DryRunResult | null>(null)

const summary = computed<DryRunSummary>(() =>
  result.value
    ? dryRunSummary(result.value)
    : { headline: '', histogram: [], dataSourceNote: '' },
)

watch(
  () => props.visible,
  (open) => {
    if (open) {
      error.value = ''
      result.value = null
      if (props.autoRun && props.ruleCode) run()
    }
  },
)

async function run(): Promise<void> {
  if (!props.ruleCode) {
    ElMessage.warning('缺少规则编码，无法试算')
    return
  }
  loading.value = true
  error.value = ''
  try {
    result.value = await dryRunRuleApi(props.ruleCode, props.changes || {})
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc)
  } finally {
    loading.value = false
  }
}

function fmtT0(row: { t0: string }): string {
  return row.t0 ? row.t0.replace('T', ' ').slice(0, 19) : '—'
}

function fmtDeadline(row: { deadline: string | null }): string {
  return row.deadline ? row.deadline.replace('T', ' ').slice(0, 19) : '时限待定'
}
</script>

<style scoped>
.dry-run-body > * + * {
  margin-top: 12px;
}
.dry-run-headline :deep(.el-alert__title) {
  font-weight: 600;
}
.dry-run-histogram {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.dry-run-hist-chip {
  padding: 2px 10px;
  border-radius: 10px;
  background: var(--el-fill-color);
  font-size: 12px;
}
.dry-run-hist-chip.is-overdue {
  background: var(--el-color-danger);
  color: #fff;
}
.dry-run-hist-chip.is-warning {
  background: var(--el-color-warning);
  color: #fff;
}
.dry-run-hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-top: 8px;
}
</style>
