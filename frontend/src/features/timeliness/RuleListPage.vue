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

    <!-- WP06 三轨统一定位横幅（第一轨 · 时效 · amber） -->
    <div class="track-banner track-banner--amber">
      <div class="track-banner__title">第一轨 · 时效锁定规则（嘉和病历事前/事中干预）</div>
      <div class="track-banner__desc">联动嘉和电子病历（JHEMR）做事前/事中时限锁控与预警；与 AI 内涵质控规则、归档前形式预检规则构成质控规则中心三轨。</div>
    </div>

    <!-- 临床阶段快捷过滤胶囊 -->
    <div class="stage-chips">
      <span
        v-for="chip in stageChips"
        :key="chip.key"
        class="stage-chip"
        :class="{ active: stageFilter === chip.key }"
        @click="stageFilter = chip.key"
      >{{ chip.label }} ({{ chip.count }})</span>
    </div>

    <el-card shadow="never">
      <el-alert
        type="info"
        :closable="false"
        class="tl-d8-alert"
        title="安全保护策略：主任（副主任）首次查房因历史存量监控行待清理，系统已强制禁止设为硬锁定；其余规则启用硬锁定须具备管理员权限且开启写库总闸。"
      />
      <el-alert v-if="loadError" type="error" :title="loadError" :closable="false" class="tl-alert" />

      <el-table v-loading="loading" :data="filteredRules" size="small" border :max-height="tableMaxHeight">
        <el-table-column label="规则名称" min-width="170" fixed="left">
          <template #default="{ row }">
            <div class="rule-name">{{ row.rule_name || row.rule_code }}</div>
            <div class="rule-sub">{{ row.rule_code }}<template v-if="row.current_version?.jhemr_monitor_code"> · {{ row.current_version.jhemr_monitor_code }}</template></div>
          </template>
        </el-table-column>
        <el-table-column label="触发事件" width="150">
          <template #default="{ row }">{{ triggerLabel(row.current_version?.trigger_type) }}</template>
        </el-table-column>
        <el-table-column label="时限要求" width="130">
          <template #default="{ row }">
            {{ limitText(row.current_version?.limit_minutes ?? null, Boolean(row.current_version?.workday_only)) }}
          </template>
        </el-table-column>
        <el-table-column label="JHEMR 锁控状态" width="130" align="center">
          <template #default="{ row }">
            <el-tooltip
              :disabled="!lockBadge(row as TlRule).hint"
              :content="lockBadge(row as TlRule).hint"
              placement="top"
            >
              <el-tag size="small" :type="lockBadge(row as TlRule).type">{{ lockBadge(row as TlRule).text }}</el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="适用范围" width="96" align="center">
          <template #default>全院</template>
        </el-table-column>
        <el-table-column label="启用" width="80" align="center">
          <template #default="{ row }">
            <el-switch
              :model-value="row.enabled"
              @change="toggleRule(row as TlRule, $event === true)"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="210" fixed="right">
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
// D8 禁锁口径见 dicts.d8_no_lock_rule_codes（lockBadge 灰徽章「临床禁锁(D8)」）。
// WP06（064 总计划）：三轨统一定位横幅（第一轨·时效 amber）+ 临床阶段胶囊筛选 +
// 精简 7 列固定表头（名称+码/触发事件/时限/JHEMR 锁控徽章/适用范围/启用/操作）；
// RuleEditorDrawer 的 rawTargetExtras 无损透传与 D8 禁锁护栏保持原样不触碰。
import { computed, onMounted, ref } from 'vue'
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

/** 固定表头高度。 */
const tableMaxHeight = 'calc(100vh - 420px)'

const editorVisible = ref(false)
const editingRule = ref<TlRule | null>(null)
const dryRunVisible = ref(false)
const dryRunRuleCode = ref('')
const historyVisible = ref(false)
const historyRuleCode = ref('')
const historyLoading = ref(false)
const versions = ref<TlVersion[]>([])

/** 临床阶段（胶囊筛选 key 与中文标签）。 */
type StageKey = 'all' | 'admission' | 'rounds' | 'surgery' | 'rescue' | 'consult' | 'discharge'
const STAGE_LABELS: Record<Exclude<StageKey, 'all'>, string> = {
  admission: '入院类',
  rounds: '查房类',
  surgery: '手术/麻醉',
  rescue: '抢救/死亡',
  consult: '会诊/输血',
  discharge: '出院类',
}

/** 规则码 → 临床阶段（编码关键词归桶；未匹配归其它并计入查房类之外的「全部」）。 */
function stageOf(ruleCode: string): Exclude<StageKey, 'all'> {
  const code = String(ruleCode || '').toUpperCase()
  if (code.includes('SURGERY') || code.includes('OPERATION') || code.includes('POSTOP')
    || code.includes('ANESTH') || code.includes('OPER')) return 'surgery'
  if (code.includes('RESCUE') || code.includes('DEATH')) return 'rescue'
  if (code.includes('CONSULT') || code.includes('TRANSFUSION')) return 'consult'
  if (code.includes('DISCHARGE')) return 'discharge'
  if (code.includes('ADM') || code.includes('ADMISSION') || code.includes('FRONT')) return 'admission'
  return 'rounds' // 查房/病程类（FIRST_COURSE / CHIEF_FIRST_ROUND / 日常病程等）
}

const stageFilter = ref<StageKey>('all')

const stageChips = computed(() => {
  const counts: Record<string, number> = {}
  for (const rule of rules.value) {
    const stage = stageOf(rule.rule_code)
    counts[stage] = (counts[stage] || 0) + 1
  }
  const chips: Array<{ key: StageKey; label: string; count: number }> = [
    { key: 'all', label: '全部', count: rules.value.length },
  ]
  for (const [stage, label] of Object.entries(STAGE_LABELS)) {
    chips.push({ key: stage as StageKey, label, count: counts[stage] || 0 })
  }
  return chips
})

const filteredRules = computed(() => {
  if (stageFilter.value === 'all') return rules.value
  return rules.value.filter((r) => stageOf(r.rule_code) === stageFilter.value)
})

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

function triggerLabel(code: string | undefined): string {
  return dicts.value?.trigger_types.find((o) => o.code === code)?.label || code || '—'
}

function actionModeLabel(mode: string | undefined): string {
  if (mode === 'LOCK_EMR') return '强制锁定'
  if (mode === 'WARN_ONLY') return '仅预警'
  return '影子记录'
}

/** WP04/WP06：JHEMR 锁控状态徽章（原生已锁/影子观察/预警模式/临床禁锁 D8）。 */
function lockBadge(row: TlRule): { type: 'success' | 'warning' | 'primary' | 'info'; text: string; hint: string } {
  const mode = String(row.current_version?.action_mode || '')
  const d8Codes = (dicts.value?.d8_no_lock_rule_codes || []) as string[]
  if (d8Codes.includes(row.rule_code)) {
    return { type: 'info', text: '临床禁锁(D8)', hint: '历史存量监控行待清理，系统禁止设为硬锁定（D8 防呆）' }
  }
  if (mode === 'LOCK_EMR') return { type: 'success', text: '原生已锁', hint: '超时将触发嘉和病历原生锁控' }
  if (mode === 'WARN_ONLY') return { type: 'primary', text: '预警模式', hint: '仅发送预警提醒，不触发锁控' }
  return { type: 'warning', text: '影子观察', hint: '只记录影子事件，不干预临床流程' }
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
.track-banner {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--ma-radius, 10px);
  padding: 10px 14px;
  margin-bottom: 10px;
  background: #f8fafc;
}
.track-banner--amber { border-left: 4px solid #f59e0b; }
.track-banner--blue { border-left: 4px solid #2563eb; }
.track-banner--cyan { border-left: 4px solid #0891b2; }
.track-banner__title { font-size: 14px; font-weight: 700; color: var(--el-text-color-primary); }
.track-banner__desc { margin-top: 2px; font-size: 12px; line-height: 1.6; color: var(--el-text-color-secondary); }
.stage-chips { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
.stage-chip {
  padding: 3px 12px; border: 1px solid var(--el-border-color); border-radius: 999px;
  font-size: 12px; cursor: pointer; color: var(--el-text-color-secondary); transition: all .2s;
}
.stage-chip:hover { border-color: var(--el-color-primary); color: var(--el-color-primary); }
.stage-chip.active { background: var(--el-color-primary); color: #fff; border-color: var(--el-color-primary); }
.rule-name { font-weight: 600; }
.rule-sub { font-size: 11px; color: var(--el-text-color-secondary); margin-top: 2px; }
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
