<template>
  <div class="page-prearchive-rules">
    <PageHeader
      title="归档前形式预检规则"
      description="病案室无纸化打回规则、系统推送报告规则与版本化发布管理（第三轨独立维护）。"
    >
      <template #actions>
        <el-button size="small" :loading="viewLoading" @click="reloadAll">刷新</el-button>
        <router-link to="/governance/audit-types" class="header-link">
          <el-button size="small" text type="primary">前往 AI 内涵质控规则 →</el-button>
        </router-link>
      </template>
    </PageHeader>

    <!-- WP06 三轨统一定位横幅（第三轨 · 预检 · cyan） -->
    <div class="track-banner track-banner--cyan">
      <div class="track-banner__title">第三轨 · 归档前形式预检规则（病案室无纸化打回与系统报告规则）</div>
      <div class="track-banner__desc">
        面向归档前形式核查的无纸化扣分项规则与系统推送报告规则，独立于第一轨时效锁控与第二轨 AI 内涵质控；
        已预留「确定性规则 + AI 语义混合规则」扩展引擎位。
      </div>
    </div>

    <!-- SummaryStrip 四卡（来自 /audit-types/prearchive 只读视图，fail-open） -->
    <SummaryStrip :items="summaryCards" :loading="viewLoading" />

    <el-tabs v-model="activeTab" class="pr-tabs">
      <!-- Tab 1：无纸化打回形式规则 -->
      <el-tab-pane label="无纸化打回形式规则" name="mark_item">
        <div class="engine-chips">
          <span
            v-for="chip in engineChips"
            :key="chip.key"
            class="engine-chip"
            :class="{ active: engineFilter === chip.key }"
            @click="engineFilter = chip.key"
          >{{ chip.label }} ({{ chip.count }})</span>
        </div>
        <el-table
          v-loading="viewLoading"
          :data="filteredMarkRules"
          stripe
          border
          size="small"
          :max-height="tableMaxHeight"
        >
          <el-table-column label="规则中文名" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="rule-name">{{ displayText(row.name) || row.rule_id }}</div>
              <div class="cell-sub">{{ row.rule_id }}</div>
            </template>
          </el-table-column>
          <el-table-column label="对应无纸化扣分项" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">
              {{ displayText(row.mark_item_note) || displayText(row.mark_item_fid) || '—' }}
              <span v-if="row.deduct_ref" class="cell-sub">（{{ row.deduct_ref }}）</span>
            </template>
          </el-table-column>
          <el-table-column label="引擎类型" width="140" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="engineTag(row.engine_mode).type" effect="plain">
                {{ engineTag(row.engine_mode).label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="严重度" width="90" align="center">
            <template #default="{ row }"><RiskTag :value="String(row.severity || '')" /></template>
          </el-table-column>
          <el-table-column label="当前状态" width="100" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="row.enabled ? 'success' : 'info'">
                {{ row.enabled ? '生效中' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openRuleDetail(row)">查看详情</el-button>
            </template>
          </el-table-column>
        </el-table>
        <p v-if="!viewLoading && !markRules.length" class="pane-empty">
          预检规则目录不可读（预检服务未随主服务部署时属预期）——只读视图 fail-open，不影响其他轨。
        </p>
      </el-tab-pane>

      <!-- Tab 2：系统推送类报告规则 -->
      <el-tab-pane label="系统推送类报告规则" name="system_push">
        <el-table v-loading="viewLoading" :data="systemPushRules" stripe border size="small" :max-height="tableMaxHeight">
          <el-table-column label="规则中文名" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="rule-name">{{ displayText(row.name) || row.rule_id }}</div>
              <div class="cell-sub">{{ row.rule_id }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="doc_name" label="报告文书" min-width="140" show-overflow-tooltip />
          <el-table-column label="完整度要求" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">{{ (row.expect || []).join('；') || '—' }}</template>
          </el-table-column>
          <el-table-column label="严重度" width="90" align="center">
            <template #default="{ row }"><RiskTag :value="String(row.severity || '')" /></template>
          </el-table-column>
          <el-table-column label="当前状态" width="100" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="row.enabled ? 'success' : 'info'">
                {{ row.enabled ? '生效中' : '待录入清单' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
        <p v-if="!viewLoading && !systemPushRules.length" class="pane-empty">
          系统推送规则清单由业务方（W10）提供后录入，当前为占位通道（豁免质控科签字口径）。
        </p>
      </el-tab-pane>

      <!-- Tab 3：规则版本与发布管理（自原 AuditTypesPage 迁移的规则中心） -->
      <el-tab-pane label="规则版本与发布管理" name="publish" lazy>
        <el-alert
          v-if="prcAvailable === false"
          :title="prcDisabledTitle"
          type="info"
          :closable="false"
          class="pr-alert"
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
              <el-option v-for="st in ['draft', 'validated', 'approved', 'published', 'retired']" :key="st" :label="prcStatusLabel(st)" :value="st" />
            </el-select>
            <el-button size="small" :loading="prcLoading" @click="loadPrc">刷新</el-button>
            <el-button size="small" type="primary" plain @click="openPrcCreate">新建草稿</el-button>
          </div>
          <el-table v-loading="prcLoading" :data="prcRules" stripe border size="small" max-height="420">
            <el-table-column prop="rule_key" label="规则ID" min-width="180" show-overflow-tooltip />
            <el-table-column label="域" width="92"><template #default="{ row }">{{ prcDomainLabel(row.domain) }}</template></el-table-column>
            <el-table-column label="名称" min-width="140" show-overflow-tooltip><template #default="{ row }">{{ prcRuleName(row as PrcRuleRow) }}</template></el-table-column>
            <el-table-column label="状态" width="92" align="center"><template #default="{ row }"><el-tag size="small" :type="prcStatusTag(row.status)">{{ prcStatusLabel(row.status) }}</el-tag></template></el-table-column>
            <el-table-column prop="rule_version" label="版本" width="130" show-overflow-tooltip />
            <el-table-column label="已发布" width="130" show-overflow-tooltip><template #default="{ row }">{{ row.published_version || '-' }}</template></el-table-column>
            <el-table-column label="操作" width="260" fixed="right">
              <template #default="{ row }">
                <el-button v-if="row.status === 'draft'" size="small" @click="openPrcEdit(row as PrcRuleRow)">编辑</el-button>
                <el-button size="small" @click="prcValidate(row as PrcRuleRow)">校验</el-button>
                <el-button size="small" @click="prcDryRun(row as PrcRuleRow)">试跑</el-button>
                <el-dropdown trigger="click" @command="(cmd: string) => prcMoreCommand(cmd, row as PrcRuleRow)">
                  <el-button size="small">更多</el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item v-if="row.status === 'approved'" command="publish">发布启用</el-dropdown-item>
                      <el-dropdown-item v-if="row.published_version" command="rollback">停用回滚</el-dropdown-item>
                      <el-dropdown-item command="copy">复制草稿</el-dropdown-item>
                      <el-dropdown-item v-if="row.status === 'draft'" command="approve">审批</el-dropdown-item>
                      <el-dropdown-item command="versions">版本历史</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
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
            <el-table-column label="状态" width="82" align="center"><template #default="{ row }"><el-tag size="small" :type="prcOutboxStatusTag(row.status)">{{ prcOutboxStatusLabel(row.status) }}</el-tag></template></el-table-column>
            <el-table-column prop="attempts" label="次数" width="60" align="center" />
            <el-table-column prop="last_error" label="错误" min-width="160" show-overflow-tooltip />
            <el-table-column label="操作" width="86">
              <template #default="{ row }">
                <el-button v-if="['dead', 'disabled', 'retry'].includes(row.status)" size="small" @click="prcRetryOutbox(row as PrcOutboxRow)">重试</el-button>
              </template>
            </el-table-column>
          </el-table>
        </template>
      </el-tab-pane>
    </el-tabs>

    <!-- 规则详情抽屉（含扩展引擎模式预留区） -->
    <DetailDrawer v-model="detailVisible" title="规则详情" size="640px">
      <template v-if="detailRule">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="规则ID">{{ detailRule.rule_id }}</el-descriptions-item>
          <el-descriptions-item label="规则名称">{{ displayText(detailRule.name) || '—' }}</el-descriptions-item>
          <el-descriptions-item label="引擎类型">{{ engineTag(detailRule.engine_mode).label }}</el-descriptions-item>
          <el-descriptions-item label="严重度"><RiskTag :value="String(detailRule.severity || '')" /></el-descriptions-item>
          <el-descriptions-item label="无纸化扣分项" :span="2">
            {{ displayText(detailRule.mark_item_note) || displayText(detailRule.mark_item_fid) || '—' }}
            <template v-if="detailRule.deduct_ref">（{{ detailRule.deduct_ref }}）</template>
          </el-descriptions-item>
          <el-descriptions-item label="适用文书">{{ displayText(detailRule.doc_name) || '—' }}</el-descriptions-item>
          <el-descriptions-item label="完整度要求">{{ (detailRule.expect || []).join('；') || '—' }}</el-descriptions-item>
          <el-descriptions-item label="规则消息" :span="2">{{ displayText(detailRule.message) || '—' }}</el-descriptions-item>
        </el-descriptions>
        <!-- 扩展引擎模式预留区（后续在归档前规则中接入 AI 语义能力的平滑入口） -->
        <el-card shadow="never" class="engine-card">
          <template #header>扩展引擎模式</template>
          <el-radio-group :model-value="detailRule.engine_mode || 'deterministic'" disabled>
            <el-radio value="deterministic">确定性规则引擎（当前生效）</el-radio>
            <el-radio value="ai_hybrid">AI 辅助混合引擎（支持绑定 Dify 提示词模板，扩展位）</el-radio>
          </el-radio-group>
          <p class="engine-hint">
            AI 辅助混合引擎为预留扩展位：启用后该规则可绑定 Dify 提示词模板，对形式预检
            命中结果做语义复核。字段 engine_mode 已在规则文件与只读视图中透传。
          </p>
        </el-card>
        <!-- 原始规则定义默认折叠 -->
        <el-collapse class="advanced-collapse">
          <el-collapse-item name="raw">
            <template #title><span class="advanced-title">查看高级规则定义（原始 JSON）</span></template>
            <pre class="raw-json">{{ JSON.stringify(detailRule, null, 2) }}</pre>
          </el-collapse-item>
        </el-collapse>
      </template>
    </DetailDrawer>

    <PrcRuleEditDrawer
      v-model:visible="prcEditVisible"
      :editing="prcEditingRow"
      :copy-of="prcCopyOfRow"
      @saved="onPrcSaved"
    />

    <el-dialog v-model="prcVersionsVisible" :title="`版本历史：${prcVersionsKey}`" width="min(92vw, 760px)">
      <el-table :data="prcVersions" stripe border size="small" max-height="360">
        <el-table-column prop="rule_version" label="版本" width="130" />
        <el-table-column label="状态" width="90" align="center"><template #default="{ row }"><el-tag size="small" :type="prcStatusTag(row.status)">{{ prcStatusLabel(row.status) }}</el-tag></template></el-table-column>
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
  </div>
</template>

<script setup lang="ts">
// WP06（064 总计划）：第三轨「归档前形式预检规则」独立页——自原 AuditTypesPage
// Tab 2 完整剥离（prc 规则中心/投递目标/Outbox/版本/diff/PrcRuleEditDrawer），
// 并新增无纸化打回形式规则（engine_mode 胶囊筛选）与系统推送类报告规则两个只读
// Tab（数据来自 /audit-types/prearchive 只读视图，fail-open）。
// 引擎类型标签：蓝「形式规则」deterministic / 紫「AI 混合规则」ai_hybrid（扩展位）。
import { computed, onMounted, ref } from 'vue'
import PageHeader from '@/components/base/PageHeader.vue'
import RiskTag from '@/components/base/RiskTag.vue'
import SummaryStrip, { type SummaryItem } from '@/components/base/SummaryStrip.vue'
import DetailDrawer from '@/components/base/DetailDrawer.vue'
import { apiGet } from '@/api/client'
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
import PrcRuleEditDrawer from './components/PrcRuleEditDrawer.vue'

// ---- 只读规则视图（mark_item / system_push） ----
interface RuleSummaryRow {
  rule_id?: string
  name?: string
  type?: string
  severity?: string
  mark_item_fid?: string
  mark_item_note?: string
  deduct_ref?: string
  enabled?: boolean
  version?: string
  message?: string
  expect?: string[]
  doc_name?: string
  sources?: string[]
  engine_mode?: string
  [key: string]: unknown
}

const viewLoading = ref(false)
const viewAvailable = ref(false)
const markRules = ref<RuleSummaryRow[]>([])
const systemPushRules = ref<RuleSummaryRow[]>([])
const markVersion = ref('')
const activeTab = ref('mark_item')

async function loadPrearchiveView(): Promise<void> {
  viewLoading.value = true
  try {
    const data = await apiGet<{
      available?: boolean
      categories?: Array<{ key: string; version?: string; rules?: RuleSummaryRow[] }>
    }>('/audit-types/prearchive')
    viewAvailable.value = data.available !== false
    for (const category of data.categories || []) {
      if (category.key === 'mark_item') {
        markRules.value = category.rules || []
        markVersion.value = category.version || ''
      } else if (category.key === 'system_push') {
        systemPushRules.value = category.rules || []
      }
    }
  } catch (e) {
    viewAvailable.value = false
    ElMessage.warning(toUserMessage(e, '预检规则只读视图加载失败（不影响版本管理）'))
  } finally {
    viewLoading.value = false
  }
}

/** 引擎类型胶囊：全部/确定性形式规则/AI 辅助混合规则（扩展位）。 */
const engineFilter = ref<'all' | 'deterministic' | 'ai_hybrid'>('all')

function engineOf(row: RuleSummaryRow): 'deterministic' | 'ai_hybrid' {
  return String(row.engine_mode || 'deterministic') === 'ai_hybrid' ? 'ai_hybrid' : 'deterministic'
}

const engineChips = computed(() => {
  const det = markRules.value.filter((r) => engineOf(r) === 'deterministic').length
  const hybrid = markRules.value.length - det
  return [
    { key: 'all' as const, label: '全部', count: markRules.value.length },
    { key: 'deterministic' as const, label: '确定性形式规则', count: det },
    { key: 'ai_hybrid' as const, label: 'AI 辅助混合规则', count: hybrid },
  ]
})

const filteredMarkRules = computed(() => {
  if (engineFilter.value === 'all') return markRules.value
  return markRules.value.filter((r) => engineOf(r) === engineFilter.value)
})

function engineTag(mode: string | undefined): { type: 'primary' | 'warning'; label: string } {
  if (String(mode || 'deterministic') === 'ai_hybrid') {
    return { type: 'warning', label: 'AI 混合规则' }
  }
  return { type: 'primary', label: '形式规则' }
}

/** SummaryStrip 四卡（任务书 §4.3 口径）。 */
const summaryCards = computed<SummaryItem[]>(() => {
  const enabledCount = markRules.value.filter((r) => r.enabled).length
  const detCount = markRules.value.filter((r) => engineOf(r) === 'deterministic' && r.enabled).length
  const hybridCount = markRules.value.filter((r) => engineOf(r) === 'ai_hybrid').length
  return [
    { key: 'active', label: '生效中形式规则', value: enabledCount, tone: 'success' },
    { key: 'deterministic', label: '无纸化项已规则化(A类)', value: detCount, hint: `规则版本 ${markVersion.value || '—'}` },
    { key: 'ai_hybrid', label: '规划转AI语义辅助(B类)', value: hybridCount, tone: 'warning', hint: '扩展引擎位' },
    { key: 'system_push', label: '系统推送报告类规则', value: systemPushRules.value.length, tone: 'info' },
  ]
})

const tableMaxHeight = 'calc(100vh - 430px)'

const detailVisible = ref(false)
const detailRule = ref<RuleSummaryRow | null>(null)

function openRuleDetail(row: RuleSummaryRow): void {
  detailRule.value = row
  detailVisible.value = true
}

function reloadAll(): void {
  void loadPrearchiveView()
  if (prcAvailable.value) void loadPrc()
}

// ---- 039/046 规则中心（自 AuditTypesPage 原样迁移；经主服务 BFF） ----
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
// 046 T4/F10：新建/编辑/复制草稿抽屉
const prcEditVisible = ref(false)
const prcEditingRow = ref<PrcRuleRow | null>(null)
const prcCopyOfRow = ref<PrcRuleRow | null>(null)

function openPrcCreate() {
  prcEditingRow.value = null
  prcCopyOfRow.value = null
  prcEditVisible.value = true
}
function openPrcEdit(row: PrcRuleRow) {
  prcEditingRow.value = row
  prcCopyOfRow.value = null
  prcEditVisible.value = true
}
function openPrcCopy(row: PrcRuleRow) {
  prcEditingRow.value = null
  prcCopyOfRow.value = row
  prcEditVisible.value = true
}
async function onPrcSaved() {
  await loadPrcRules()
}

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
    // 041 T3：403=权限问题（不是服务故障）；502/503=服务不可用/未启用
    prcDisabledReason.value = prcDisabledReasonFromError(e)
  } finally {
    prcLoading.value = false
  }
}

// 403 不套「规则中心不可用」前缀，避免把权限问题写成服务故障
const prcDisabledTitle = computed(() => prcDisabledTitleFromReason(
  prcDisabledReason.value,
  '。其他两轨规则页不受影响。',
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

type TagType = 'primary' | 'success' | 'warning' | 'danger' | 'info'
const PRC_OUTBOX_TAGS: Record<string, TagType> = { pending: 'info', sending: 'info', sent: 'success', retry: 'warning', dead: 'danger', disabled: 'info' }
function prcOutboxStatusTag(status: string): TagType {
  return PRC_OUTBOX_TAGS[status] || 'info'
}

// Outbox 投递状态中文展示（value 保持原英文不变）。
function prcOutboxStatusLabel(status: string): string {
  const map: Record<string, string> = {
    pending: '待发送', sending: '发送中', sent: '已送达',
    retry: '待重试', dead: '投递失败', disabled: '已停用',
  }
  return map[status] || status
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

const PRC_STATUS_TAGS: Record<string, TagType> = { draft: 'info', validated: 'info', approved: 'warning', published: 'success', retired: 'danger' }
function prcStatusTag(status: string): TagType {
  return PRC_STATUS_TAGS[status] || 'info'
}

// 预检规则生命周期中文展示（下拉 value 仍传原英文）。
const PRC_STATUS_LABELS: Record<string, string> = {
  draft: '草稿', validated: '已校验', approved: '已审批', published: '已发布', retired: '已退役',
}
function prcStatusLabel(status: string): string {
  return PRC_STATUS_LABELS[status] || status
}

function prcRuleName(row: PrcRuleRow) {
  return String((row.content as { name?: string })?.name || '-')
}

/** 「更多」下拉命令分发（复制/校验/审批/发布/回滚/版本历史）。 */
function prcMoreCommand(command: string, row: PrcRuleRow): void {
  if (command === 'copy') openPrcCopy(row)
  else if (command === 'validate') void prcValidate(row)
  else if (command === 'approve') void prcApprove(row)
  else if (command === 'publish') void prcPublish(row)
  else if (command === 'rollback') void prcRollback(row)
  else if (command === 'versions') void openPrcVersions(row)
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
  } catch (e) { if (e !== 'cancel' && e !== 'close') ElMessage.error(toUserMessage(e, '审批失败')) }
}

async function prcPublish(row: PrcRuleRow) {
  try {
    await ElMessageBox.confirm(
      `发布 ${row.rule_key} @ ${row.rule_version}\nSHA-256: ${row.content_sha256}\n发布后旧版本自动退役，可用回滚恢复。`,
      '确认发布（危险操作）', { type: 'warning' })
    await prcPublishApi(row.rule_key, row.rule_version)
    ElMessage.success('已发布并更新指针')
    await loadPrcRules()
  } catch (e) { if (e !== 'cancel' && e !== 'close') ElMessage.error(toUserMessage(e, '发布失败')) }
}

async function prcRollback(row: PrcRuleRow) {
  try {
    const { value } = await ElMessageBox.prompt('回滚到的已发布版本号', '停用回滚指针', { inputPlaceholder: '如 2026.09.02.1' })
    await prcRollbackApi(row.rule_key, String(value || '').trim())
    ElMessage.success('已回滚')
    await loadPrcRules()
  } catch (e) { if (e !== 'cancel' && e !== 'close') ElMessage.error(toUserMessage(e, '回滚失败')) }
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
  } catch (e) { if (e !== 'cancel' && e !== 'close') ElMessage.error(toUserMessage(e, '契约测试失败')) }
}

async function prcRetryOutbox(row: PrcOutboxRow) {
  try {
    await prcRetryOutboxApi(row.id)
    ElMessage.success('已重新入队')
    await loadPrcOutbox()
  } catch (e) { ElMessage.error(toUserMessage(e, '重试失败（仅 dead/disabled 可重试）')) }
}

onMounted(() => {
  void loadPrearchiveView()
  void loadPrc()
})
</script>

<style scoped>
.page-prearchive-rules { padding: 4px; }
.track-banner {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--ma-radius, 10px);
  padding: 10px 14px;
  margin-bottom: 12px;
  background: #f8fafc;
}
.track-banner--cyan { border-left: 4px solid #0891b2; }
.track-banner__title { font-size: 14px; font-weight: 700; color: var(--el-text-color-primary); }
.track-banner__desc { margin-top: 2px; font-size: 12px; line-height: 1.6; color: var(--el-text-color-secondary); }
.header-link { text-decoration: none; }
.pr-tabs { margin-top: 4px; }
.engine-chips { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
.engine-chip {
  padding: 3px 12px; border: 1px solid var(--el-border-color); border-radius: 999px;
  font-size: 12px; cursor: pointer; color: var(--el-text-color-secondary); transition: all .2s;
}
.engine-chip:hover { border-color: var(--el-color-primary); color: var(--el-color-primary); }
.engine-chip.active { background: var(--el-color-primary); color: #fff; border-color: var(--el-color-primary); }
.rule-name { font-weight: 600; }
.cell-sub { font-size: 11px; color: var(--el-text-color-secondary); }
.pane-empty { color: var(--el-text-color-secondary); text-align: center; padding: 16px; font-size: 12px; }
.pr-alert { margin-bottom: 10px; }
.prc-toolbar { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 8px; }
.engine-card { margin-top: 12px; }
.engine-hint { margin: 8px 0 0; font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.6; }
.advanced-collapse { margin-top: 10px; }
.advanced-title { font-size: 13px; font-weight: 600; }
.raw-json {
  margin: 0; max-height: 360px; overflow: auto; padding: 10px 12px; border-radius: 8px;
  background: #0f172a; color: #e2e8f0; font-size: 12px; line-height: 1.5;
  white-space: pre-wrap; word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
</style>
