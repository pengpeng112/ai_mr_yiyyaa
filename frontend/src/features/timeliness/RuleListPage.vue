<template>
  <section class="tl-page">
    <PageHeader
      title="时效锁定规则"
      description="可视化配置（零代码）：触发源 → 目标文书 → 提醒 → 超时处置；每次保存生成新版本，旧版本可回溯。"
    >
      <template #actions>
        <el-button size="small" @click="loadAll">刷新</el-button>
      </template>
    </PageHeader>

    <el-card shadow="never">
      <el-alert
        type="info"
        :closable="false"
        class="tl-d8-alert"
        title="安全保护策略：主任（副主任）首次查房因历史存量监控行待清理，系统已强制禁止设为硬锁定；其余规则启用硬锁定须具备管理员权限且开启写库总闸。"
      />
      <el-alert v-if="loadError" type="error" :title="loadError" :closable="false" class="tl-alert" />

      <el-table v-loading="loading" :data="rules" size="small" border>
        <el-table-column prop="rule_code" label="编码" width="170" />
        <el-table-column prop="rule_name" label="名称" min-width="150" />
        <el-table-column label="分类" width="110">
          <template #default="{ row }">{{ categoryLabel(row.category) }}</template>
        </el-table-column>
        <el-table-column label="启用" width="70">
          <template #default="{ row }">
            <el-switch
              :model-value="row.enabled"
              @change="toggleRule(row as TlRule, $event === true)"
            />
          </template>
        </el-table-column>
        <el-table-column label="触发源" width="130">
          <template #default="{ row }">{{ triggerLabel(row.current_version?.trigger_type) }}</template>
        </el-table-column>
        <el-table-column label="时限" width="110">
          <template #default="{ row }">
            {{ limitText(row.current_version?.limit_minutes ?? null, Boolean(row.current_version?.workday_only)) }}
          </template>
        </el-table-column>
        <el-table-column label="处置模式" width="120">
          <template #default="{ row }">
            <el-tag
              size="small"
              :type="row.current_version?.action_mode === 'LOCK_EMR' ? 'danger' : row.current_version?.action_mode === 'WARN_ONLY' ? 'warning' : 'info'"
            >
              {{ actionModeLabel(row.current_version?.action_mode) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="当前版本" width="90">
          <template #default="{ row }">v{{ row.current_version?.version_no ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" text data-testid="edit-rule" @click="openEditor(row as TlRule)">
              编辑
            </el-button>
            <el-button size="small" text data-testid="dry-run-rule" @click="openDryRun(row as TlRule)">
              试算
            </el-button>
            <el-button size="small" text @click="openHistory(row as TlRule)">历史版本</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <RuleEditorDrawer
      v-model:visible="editorVisible"
      :rule="editingRule"
      :dicts="dicts"
      :departments="departments"
      :jhemr-write-enabled="dicts?.jhemr_write_enabled === true"
      :notify-mode="dicts?.notify_mode || 'LOG_ONLY'"
      @saved="loadAll"
    />

    <DryRunPanel v-model:visible="dryRunVisible" :rule-code="dryRunRuleCode" :changes="{}" auto-run />

    <el-dialog v-model="historyVisible" :title="`版本历史：${historyRuleCode}`" width="min(94vw, 860px)">
      <el-table v-loading="historyLoading" :data="versions" size="small" border max-height="420">
        <el-table-column prop="version_no" label="版本" width="70" />
        <el-table-column label="处置模式" width="110">
          <template #default="{ row }">{{ actionModeLabel(row.action_mode) }}</template>
        </el-table-column>
        <el-table-column label="时限" width="110">
          <template #default="{ row }">{{ limitText(row.limit_minutes, Boolean(row.workday_only)) }}</template>
        </el-table-column>
        <el-table-column label="完成基准" width="120">
          <template #default="{ row }">{{ completionBasisLabel(row.completion_basis) }}</template>
        </el-table-column>
        <el-table-column prop="created_by" label="创建人" width="110" />
        <el-table-column label="创建时间" min-width="150">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="200" show-overflow-tooltip />
      </el-table>
      <p class="tl-subtitle">版本只追加不覆盖；事件台账记录命中时的版本号，可按版本回溯口径。</p>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
// T6 规则列表页：字典 + 规则 + 科室加载；编辑抽屉 / 试算面板 / 版本历史入口。
// 2026-11-15 P1：PageHeader 视觉统一；安全提示改纯中文（不再拼接 d8_note 英文原值）；
// 版本历史弹窗完成基准/创建时间中文化。
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/base/PageHeader.vue'
import {
  fetchDepartmentsApi,
  fetchRuleVersionsApi,
  fetchTimelinessDictsApi,
  fetchTimelinessRulesApi,
  toggleRuleApi,
} from './api'
import RuleEditorDrawer from './RuleEditorDrawer.vue'
import DryRunPanel from './DryRunPanel.vue'
import {
  RULE_CATEGORY_OPTIONS,
  limitText,
  type DepartmentOption,
  type TlDicts,
  type TlRule,
  type TlVersion,
} from './types'

const loading = ref(false)
const loadError = ref('')
const rules = ref<TlRule[]>([])
const dicts = ref<TlDicts | null>(null)
const departments = ref<DepartmentOption[]>([])

const editorVisible = ref(false)
const editingRule = ref<TlRule | null>(null)
const dryRunVisible = ref(false)
const dryRunRuleCode = ref('')
const historyVisible = ref(false)
const historyRuleCode = ref('')
const historyLoading = ref(false)
const versions = ref<TlVersion[]>([])

onMounted(loadAll)

async function loadAll(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    // 字典/科室失败不阻塞规则列表（编辑抽屉内对应控件退化为空选项）
    const [rulesRes, dictsRes, deptsRes] = await Promise.allSettled([
      fetchTimelinessRulesApi(),
      fetchTimelinessDictsApi(),
      fetchDepartmentsApi(),
    ])
    if (rulesRes.status === 'rejected') {
      loadError.value = rulesRes.reason instanceof Error ? rulesRes.reason.message : '规则列表加载失败'
    } else {
      rules.value = rulesRes.value.items
    }
    if (dictsRes.status === 'fulfilled') dicts.value = dictsRes.value
    if (deptsRes.status === 'fulfilled') departments.value = deptsRes.value
  } finally {
    loading.value = false
  }
}

function categoryLabel(category: string): string {
  return RULE_CATEGORY_OPTIONS.find((o) => o.value === category)?.label || category
}

function triggerLabel(code: string | undefined): string {
  return dicts.value?.trigger_types.find((o) => o.code === code)?.label || code || '—'
}

function actionModeLabel(mode: string | undefined): string {
  if (mode === 'LOCK_EMR') return '强制锁定'
  if (mode === 'WARN_ONLY') return '仅预警'
  return '影子记录'
}

/** 完成基准中文名（FIRST_SIGN=首次审签时间；CREATE=文书创建时间；未知原样）。 */
function completionBasisLabel(basis: string | undefined): string {
  if (basis === 'FIRST_SIGN') return '首次审签时间'
  if (basis === 'CREATE') return '文书创建时间'
  return basis || '—'
}

/** 时间统一 YYYY-MM-DD HH:mm:ss（去 T 与微秒尾巴）。 */
function fmtTime(value: string | null | undefined): string {
  return value ? String(value).replace('T', ' ').slice(0, 19) : '—'
}

async function toggleRule(row: TlRule, enabled: boolean): Promise<void> {
  try {
    await toggleRuleApi(row.rule_code, enabled)
    row.enabled = enabled
    ElMessage.success(`${row.rule_code} 已${enabled ? '启用' : '停用'}`)
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : '启停失败')
  }
}

function openEditor(row: TlRule): void {
  editingRule.value = row
  editorVisible.value = true
}

function openDryRun(row: TlRule): void {
  dryRunRuleCode.value = row.rule_code
  dryRunVisible.value = true
}

async function openHistory(row: TlRule): Promise<void> {
  historyRuleCode.value = row.rule_code
  historyVisible.value = true
  historyLoading.value = true
  try {
    versions.value = (await fetchRuleVersionsApi(row.rule_code)).items
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : '版本历史加载失败')
  } finally {
    historyLoading.value = false
  }
}
</script>

<style scoped>
.tl-page {
  padding: 4px;
}
.tl-subtitle {
  margin: 4px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.6;
}
.tl-d8-alert {
  margin-bottom: 10px;
}
.tl-alert {
  margin-bottom: 10px;
}
</style>
