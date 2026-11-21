<script setup lang="ts">
// WP06（064 总计划，用户拍板 D4）：第二轨「AI 内涵质控规则」独立页。
// - 原 Tab 2「归档前形式预检」已剥离至第三轨独立页 /governance/prearchive-rules
//   （PrearchiveRulesPage.vue），本页专注 AI 规则，不再混排两轨；
// - 区域 1「运行中生产规则」：卡片网格（规则名/核心检查场景/运行模式徽章/Dify 连通
//   摘要/JHEMR 提交提醒状态徽章/操作组：编辑规则-测试 Dify-启停）；
// - 区域 2「草稿与待扩展规则模板」：默认折叠（el-collapse），不与生产规则混排；
// - 编辑接入 3 步式 AuditTypeWizardDrawer（rawExtras 无损透传 + 密钥留空保留旧密文）；
// - 保留既有 Dify 测试连通语义（test-dify + 留空密文不覆盖 api_key_enc）。
import { computed, onMounted, ref } from 'vue'
import PageHeader from '@/components/base/PageHeader.vue'
import { apiGet, apiPost, apiPut } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { displayText } from '@/utils/format'
import { ElMessage, ElMessageBox } from 'element-plus'
import AuditTypeWizardDrawer from './components/AuditTypeWizardDrawer.vue'

interface AuditTypeRow {
  code: string
  name?: string
  enabled?: boolean
  jhemr_reminder_policy?: Record<string, unknown>
  [key: string]: unknown
}

const loading = ref(false)
const error = ref('')
const items = ref<AuditTypeRow[]>([])

/** 区域 1：运行中生产规则（enabled）；区域 2：草稿与待扩展（停用项）。 */
const productionRules = computed(() => items.value.filter((row) => row.enabled !== false))
const draftRules = computed(() => items.value.filter((row) => row.enabled === false))
const draftOpen = ref<string[]>([])

const wizardVisible = ref(false)
const wizardRule = ref<Record<string, any> | null>(null)
const wizardIsNew = ref(false)

/** 运行模式徽章：纳入出院终末调度=「每日+出院终末」；否则「每日在院」。 */
function runModeLabel(row: AuditTypeRow): string {
  return row.default_for_schedule ? '每日在院 + 出院终末' : '每日在院'
}

/** Dify 连通摘要（超时/来源数/目标数）。 */
function difySummary(row: AuditTypeRow): string {
  const dify = (row.dify || {}) as Record<string, unknown>
  const sources = row.sources as Record<string, unknown> | undefined
  const targets = Array.isArray(dify.targets) ? dify.targets.length : 0
  const parts = [
    `超时 ${Number(dify.timeout_seconds || 0) || '—'}s`,
    `来源 ${sources && typeof sources === 'object' ? Object.keys(sources).length : 0} 个`,
    `目标 ${targets}`,
  ]
  return parts.join(' · ')
}

/** JHEMR 提交提醒状态徽章（WP06 D4）：已开启·路线B拉取 / 已预留·未开启。 */
function reminderBadge(row: AuditTypeRow): { type: 'success' | 'info'; text: string; hint: string } {
  const policy = (row.jhemr_reminder_policy || {}) as Record<string, unknown>
  if (policy.enabled === true) {
    const mode = String(policy.delivery_mode || 'pull_api')
    if (mode === 'pull_api') return { type: 'success', text: '已开启·路线B拉取', hint: '嘉和客户端提交前调用 ai-reminders 拉取未闭环高危问题' }
    if (mode === 'fileverify_write') return { type: 'success', text: '已开启·路线A写入', hint: '177 FILEVERIFY 受控写入（056 v4）' }
    return { type: 'success', text: '已开启·双路', hint: '路线 B 拉取与路线 A 写入同时生效' }
  }
  return { type: 'info', text: '已预留·未开启', hint: '策略结构已就绪，在规则编辑第 3 步开启即可' }
}

async function load(): Promise<void> {
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

function openWizard(row: AuditTypeRow | null): void {
  wizardIsNew.value = !row
  wizardRule.value = row ? { ...row } : null
  wizardVisible.value = true
}

/** 行内启停（PUT 合并既有配置；无权限/校验失败后端 422 降级提示）。 */
async function toggleEnabled(row: AuditTypeRow): Promise<void> {
  const next = row.enabled === false
  try {
    await ElMessageBox.confirm(
      `确认${next ? '启用' : '停用'}规则「${displayText(row.name) || row.code}」？`,
      '启停确认', { type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await apiPut(`/audit-types/${row.code}`, { enabled: next })
    ElMessage.success(`已${next ? '启用' : '停用'}`)
    await load()
  } catch (e) {
    ElMessage.error(toUserMessage(e, '启停失败'))
  }
}

/** 快捷测试 Dify（保持既有确认语义：外部调用成本 + 禁止病历正文）。 */
const testBusyCode = ref('')
async function quickTestDify(row: AuditTypeRow): Promise<void> {
  if (testBusyCode.value) return
  try {
    await ElMessageBox.confirm(
      '将使用默认合成样本测试 Dify 连通（可能产生外部调用成本，不含真实患者数据）。确认继续？',
      'Dify 测试确认', { type: 'warning' },
    )
  } catch {
    return
  }
  testBusyCode.value = row.code
  try {
    await apiPost(`/audit-types/${row.code}/test-dify`, {
      mr_txt_sample: '【合成测试】患者某某，男，45岁，术后第一天，病程记录已书写。本文本仅用于连通性测试。',
    })
    ElMessage.success('Dify 连通测试完成（详见编辑抽屉测试区）')
  } catch (e) {
    ElMessage.error(toUserMessage(e, 'Dify 测试失败'))
  } finally {
    testBusyCode.value = ''
  }
}

onMounted(load)
</script>

<template>
  <div class="page-audit-types">
    <PageHeader
      title="AI 内涵质控规则"
      description="第二轨 · 基于 Dify 大模型做内涵语义质控；支持企微高危推送，并预留对接嘉和病历（JHEMR）提交前弹窗提醒策略。"
    >
      <template #actions>
        <el-button size="small" :loading="loading" @click="load">刷新</el-button>
        <router-link to="/governance/prearchive-rules" class="header-link">
          <el-button size="small" text type="primary">前往归档前形式预检规则 →</el-button>
        </router-link>
        <el-button size="small" type="primary" data-testid="create-rule" @click="openWizard(null)">新建规则</el-button>
      </template>
    </PageHeader>

    <!-- WP06 三轨统一定位横幅（第二轨 · AI · blue） -->
    <div class="track-banner track-banner--blue">
      <div class="track-banner__title">第二轨 · AI 内涵质控规则（Dify 大模型语义质控）</div>
      <div class="track-banner__desc">
        负责深度核查病历临床逻辑一致性，支持企微高危推送，并已预留对接嘉和病历（JHEMR）提交前弹窗提醒策略。
        三轨关系：第一轨时效锁控 /governance/timeliness-rules，第三轨归档前形式预检 /governance/prearchive-rules。
      </div>
    </div>

    <!-- 区域 1：运行中生产规则（卡片网格） -->
    <div class="section-head">
      <span class="section-title">运行中生产规则（{{ productionRules.length }} 条）</span>
      <el-alert v-if="error" type="error" :title="error" :closable="false" class="section-error" />
    </div>
    <div v-loading="loading" class="rule-grid">
      <el-empty v-if="!loading && !productionRules.length" description="暂无启用中的 AI 质控规则" class="rule-empty" />
      <el-card v-for="row in productionRules" :key="row.code" shadow="never" class="rule-card">
        <div class="rule-card-head">
          <div class="rule-card-title">
            <span class="rule-name">{{ displayText(row.name) || row.code }}</span>
            <span class="cell-sub">{{ row.code }}</span>
          </div>
          <el-tag size="small" :type="reminderBadge(row).type" effect="plain" :title="reminderBadge(row).hint">
            {{ reminderBadge(row).text }}
          </el-tag>
        </div>
        <p class="rule-desc">{{ displayText(row.description) || '（未填写业务描述）' }}</p>
        <div class="rule-meta">
          <el-tag size="small" type="info" effect="plain">{{ runModeLabel(row) }}</el-tag>
          <span class="cell-sub">Dify：{{ difySummary(row) }}</span>
        </div>
        <div class="rule-actions">
          <el-button size="small" type="primary" plain @click="openWizard(row)">编辑规则</el-button>
          <el-button size="small" :loading="testBusyCode === row.code" @click="quickTestDify(row)">测试 Dify</el-button>
          <el-button size="small" :type="row.enabled === false ? 'success' : 'warning'" plain @click="toggleEnabled(row)">
            {{ row.enabled === false ? '启用' : '停用' }}
          </el-button>
        </div>
      </el-card>
    </div>

    <!-- 区域 2：草稿与待扩展规则模板（默认折叠） -->
    <el-collapse v-model="draftOpen" class="draft-collapse">
      <el-collapse-item name="drafts">
        <template #title>
          <span class="draft-title">草稿与待扩展规则模板（{{ draftRules.length }} 条，点击展开）</span>
        </template>
        <el-table v-if="draftRules.length" :data="draftRules" stripe border size="small" max-height="360">
          <el-table-column prop="code" label="规则编码" min-width="170" />
          <el-table-column label="规则名称" min-width="150">
            <template #default="{ row }">{{ displayText(row.name) || '—' }}</template>
          </el-table-column>
          <el-table-column label="说明" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">{{ displayText(row.description) || '—' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="180" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openWizard(row as AuditTypeRow)">编辑规则</el-button>
              <el-button link type="success" size="small" @click="toggleEnabled(row as AuditTypeRow)">启用</el-button>
            </template>
          </el-table-column>
        </el-table>
        <p v-else class="pane-empty">暂无草稿/停用规则——新建规则后可先停用保存为草稿。</p>
      </el-collapse-item>
    </el-collapse>

    <!-- 3 步式清爽编辑抽屉（rawExtras 无损往返） -->
    <AuditTypeWizardDrawer
      v-model:visible="wizardVisible"
      :rule="wizardRule"
      :is-new="wizardIsNew"
      @saved="load"
    />
  </div>
</template>

<style scoped>
.page-audit-types { padding: 4px; }
.header-link { text-decoration: none; }
.track-banner {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--ma-radius, 10px);
  padding: 10px 14px;
  margin-bottom: 12px;
  background: #f8fafc;
}
.track-banner--blue { border-left: 4px solid #2563eb; }
.track-banner__title { font-size: 14px; font-weight: 700; color: var(--el-text-color-primary); }
.track-banner__desc { margin-top: 2px; font-size: 12px; line-height: 1.6; color: var(--el-text-color-secondary); }
.section-head { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.section-title { font-size: 14px; font-weight: 700; }
.section-error { flex: 1; }
.rule-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 16px;
  margin-bottom: 16px;
  min-height: 120px;
}
.rule-empty { grid-column: 1 / -1; }
.rule-card { border-radius: 10px; }
.rule-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.rule-card-title { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.rule-name { font-size: 15px; font-weight: 700; }
.cell-sub { font-size: 11px; color: var(--el-text-color-secondary); }
.rule-desc { margin: 8px 0; font-size: 12px; line-height: 1.6; color: var(--el-text-color-regular); min-height: 18px; }
.rule-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.rule-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.draft-collapse { margin-top: 4px; }
.draft-title { font-size: 13px; font-weight: 600; color: var(--el-text-color-secondary); }
.pane-empty { color: var(--el-text-color-secondary); text-align: center; padding: 16px; font-size: 12px; }
@media (max-width: 720px) {
  .rule-grid { grid-template-columns: 1fr; }
}
</style>
