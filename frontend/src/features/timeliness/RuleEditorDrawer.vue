<template>
  <el-drawer
    :model-value="visible"
    :title="`编辑规则：${draft.rule_code}`"
    size="min(100vw, 760px)"
    destroy-on-close
    @update:model-value="emit('update:visible', $event)"
  >
    <el-form label-width="128px" size="small">
      <!-- 区块 1：基本信息与分类（§11.1） -->
      <el-divider content-position="left">区块 1 · 基本信息与分类</el-divider>
      <el-form-item label="规则编码">
        <el-input :model-value="draft.rule_code" disabled data-testid="rule-code-readonly" />
      </el-form-item>
      <el-form-item label="规则名称" required>
        <el-input v-model="draft.rule_name" placeholder="如：危急值 6 小时病程记录" />
      </el-form-item>
      <el-form-item label="规则大类" required>
        <el-select v-model="draft.category" style="width: 220px">
          <el-option
            v-for="opt in RULE_CATEGORY_OPTIONS"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="启用状态">
        <el-switch v-model="draft.enabled" />
        <span class="tl-hint">保存新版本后如启停状态变化，将一并提交启停接口</span>
      </el-form-item>
      <el-form-item label="适用范围">
        <el-radio-group v-model="draft.deptScopeAll">
          <el-radio-button :value="true">全院</el-radio-button>
          <el-radio-button :value="false">指定科室</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item v-if="!draft.deptScopeAll" label="适用科室">
        <el-select
          v-model="draft.deptScopeCodes"
          multiple
          filterable
          placeholder="多选科室（JHEMR 科室编码）；空列表=全院"
          style="width: 100%"
        >
          <el-option
            v-for="dept in departments"
            :key="dept.id"
            :label="dept.code ? `${dept.code} ${dept.name}` : dept.name"
            :value="dept.code || dept.name"
          />
        </el-select>
      </el-form-item>

      <!-- 区块 2：触发源（字段+运算符+值 行编辑器，不让用户手写 SQL） -->
      <el-divider content-position="left">区块 2 · 触发源（什么时候开始算 T0）</el-divider>
      <el-form-item label="触发事件" required>
        <el-select v-model="draft.trigger_type" style="width: 260px">
          <el-option
            v-for="opt in dicts?.trigger_types || []"
            :key="opt.code"
            :label="opt.label"
            :value="opt.code"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="过滤条件">
        <div class="tl-filter-rows">
          <div v-for="(row, idx) in draft.filterRows" :key="idx" class="tl-filter-row">
            <el-input
              v-model="row.field"
              placeholder="字段（如 dept_code）"
              class="tl-filter-field"
            />
            <el-select v-model="row.op" class="tl-filter-op">
              <el-option
                v-for="op in FILTER_OPERATOR_OPTIONS"
                :key="op.value"
                :label="op.label"
                :value="op.value"
              />
            </el-select>
            <el-input
              v-model="row.value"
              placeholder="值（属于=逗号分隔多值）"
              class="tl-filter-value"
            />
            <el-button
              type="danger"
              text
              :disabled="draft.filterRows.length === 1"
              @click="draft.filterRows.splice(idx, 1)"
            >
              删除
            </el-button>
          </div>
          <el-button size="small" @click="draft.filterRows.push({ field: '', op: 'eq', value: '' })">
            添加条件
          </el-button>
          <div class="tl-hint">
            行编辑器仅生成结构化过滤条件（等于 / 属于·任一命中），不允许手写 SQL；
            引擎按字段值精确匹配，未支持其他比较符。
          </div>
        </div>
      </el-form-item>

      <!-- 区块 3：目标文书与完成标准 -->
      <el-divider content-position="left">区块 3 · 目标文书与完成标准</el-divider>
      <el-form-item label="目标文书" required>
        <el-select
          v-model="draft.mrClass"
          multiple
          filterable
          placeholder="多选 MR_CLASS（字典来自 /api/timeliness/dicts）"
          style="width: 100%"
        >
          <el-option
            v-for="opt in dicts?.mr_class || []"
            :key="opt.code"
            :label="`${opt.code} ${opt.label}`"
            :value="opt.code"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="标题关键词">
        <el-select
          v-model="draft.titleKeywords"
          multiple
          filterable
          allow-create
          default-first-option
          :reserve-keyword="false"
          placeholder="输入关键词回车添加（任一命中即算目标文书）"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item label="职称关键词">
        <el-select
          v-model="draft.signerTitleKeywords"
          multiple
          filterable
          allow-create
          default-first-option
          :reserve-keyword="false"
          placeholder="如：主治 / 副主任 / 主任（回车添加）"
          style="width: 100%"
        />
        <div class="tl-hint">预留位：按签名医师职称匹配，引擎当前版本暂不按此过滤（见交付说明）。</div>
      </el-form-item>
      <el-form-item label="时间要求">
        <el-switch
          v-model="draft.timeGeT0"
          active-text="要求完成时间 ≥ 起算时间 T0"
          inactive-text="不要求"
        />
        <div class="tl-hint">手术结束/危急值/会诊/抢救/输血/麻醉类默认要求（引擎按触发类型给默认值）。</div>
      </el-form-item>
      <el-form-item label="JHEMR 监控码">
        <el-select
          v-model="draft.monitorCode"
          filterable
          clearable
          placeholder="可选：关联 JHEMR 原生监控项"
          style="width: 320px"
        >
          <el-option
            v-for="opt in dicts?.monitor_items?.items || []"
            :key="opt.code"
            :label="`${opt.code} ${opt.label}（${opt.limit || '无时限'}）`"
            :value="opt.code"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="完成基准" required>
        <el-radio-group v-model="draft.completion_basis">
          <el-radio value="FIRST_SIGN">按首次签名时间（防空壳文书）</el-radio>
          <el-radio value="CREATE">按文书创建时间</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="规定时限" required>
        <el-input-number v-model="draft.limit.value" :min="0" :step="1" />
        <el-select v-model="draft.limit.unit" style="width: 110px; margin-left: 8px">
          <el-option
            v-for="opt in LIMIT_UNIT_OPTIONS"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>
        <div v-if="limitError" class="tl-error" data-testid="limit-error">{{ limitError }}</div>
        <div class="tl-hint">
          时限必须大于 0；前置类规则（PREOP_SUMMARY 术前小结）允许 0=截止时刻即触发时刻。
          选择「工作日」时按工作日计时（非工作日整天跳过）。
        </div>
      </el-form-item>

      <!-- 区块 4：提醒策略（未开通通道置灰提示未授权） -->
      <el-divider content-position="left">区块 4 · 事前提醒策略</el-divider>
      <el-form-item label="提前预警">
        <el-input-number v-model="draft.warnBefore.value" :min="0" :step="1" />
        <el-select v-model="draft.warnBefore.unit" style="width: 110px; margin-left: 8px">
          <el-option
            v-for="opt in LIMIT_UNIT_OPTIONS.filter((o) => o.value !== 'workday')"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>
        <span class="tl-hint" style="margin-left: 8px">距截止前多久开始预警（留空=不预警）</span>
      </el-form-item>
      <el-form-item label="提醒通道">
        <div class="tl-channels">
          <el-checkbox
            v-for="channel in NOTIFY_CHANNELS"
            :key="channel.code"
            :model-value="draft.channels.includes(channel.code)"
            :disabled="!channel.authorized"
            :data-testid="`channel-${channel.code}`"
            @update:model-value="toggleChannel(channel.code, $event)"
          >
            {{ channel.label }}
            <el-tag v-if="!channel.authorized" size="small" type="info">未授权</el-tag>
          </el-checkbox>
          <div v-for="channel in unauthorizedChecked" :key="channel.code" class="tl-error">
            {{ channel.label }}：{{ channel.unauthorizedReason }}
          </div>
          <div class="tl-hint">通道开通前所有提醒只记录台账（notify_mode=LOG_ONLY），不发送真实消息。</div>
        </div>
      </el-form-item>

      <!-- 区块 5：超时处置与考核 -->
      <el-divider content-position="left">区块 5 · 超时处置与考核</el-divider>
      <el-form-item label="超时处置" required>
        <el-radio-group v-model="draft.action_mode">
          <el-radio value="SHADOW">影子记录（只记录不处置）</el-radio>
          <el-radio value="WARN_ONLY">仅预警与纳入月度考核</el-radio>
          <el-radio
            value="LOCK_EMR"
            :disabled="!lockEmr.allowed"
            data-testid="lock-emr-radio"
          >
            强制锁定 JHEMR 病历
          </el-radio>
        </el-radio-group>
        <div v-if="!lockEmr.allowed" class="tl-error" data-testid="lock-emr-reason">
          {{ lockEmr.reason }}
        </div>
      </el-form-item>
      <el-form-item label="扣罚金额">
        <el-input-number v-model="draft.penaltyAmount" :min="0" :step="50" />
        <span class="tl-hint" style="margin-left: 8px">元 / 次（医疗部规定默认 200 元）</span>
      </el-form-item>
      <el-form-item label="年度累计">
        <el-switch v-model="draft.annualTally" active-text="计入个人年度累计处分榜" />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="emit('update:visible', false)">取消</el-button>
      <el-button data-testid="dry-run-button" @click="openDryRun">试算</el-button>
      <el-button type="primary" :disabled="!!limitError" data-testid="save-button" @click="confirmSave">
        保存为新版本
      </el-button>
    </template>

    <!-- 版本差异确认弹窗：与当前版本逐字段对比后才真正保存 -->
    <el-dialog
      v-model="diffVisible"
      title="确认保存：与当前版本的差异"
      width="min(94vw, 720px)"
      append-to-body
    >
      <el-alert
        v-if="diffRows.length === 0"
        type="warning"
        title="本次改动与当前版本完全一致"
        :closable="false"
        description="保存将生成内容相同的新版本；如确需留存版本痕迹请继续，否则请取消。"
      />
      <el-table v-else :data="diffRows" size="small" border max-height="380">
        <el-table-column prop="label" label="字段" width="150" />
        <el-table-column prop="before" label="当前版本" min-width="220" show-overflow-tooltip />
        <el-table-column prop="after" label="保存后（新版本）" min-width="220" show-overflow-tooltip />
      </el-table>
      <p class="tl-hint">
        保存只追加新版本并切换为当前版本（旧版本完整保留、可回溯）；新版本对之后触发的事件生效。
      </p>
      <template #footer>
        <el-button @click="diffVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">确认保存</el-button>
      </template>
    </el-dialog>

    <DryRunPanel
      v-model:visible="dryRunVisible"
      :rule-code="draft.rule_code"
      :changes="draftToChanges(draft)"
      auto-run
    />
  </el-drawer>
</template>

<script setup lang="ts">
// T6 可视化规则编辑抽屉（§11.1 五区块）。纯逻辑（校验/差异/LOCK_EMR 判定/通道授权表）
// 在 ./types.ts，便于单测；本组件只做表单绑定与 API 调用。
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { createRuleVersionApi, toggleRuleApi } from './api'
import DryRunPanel from './DryRunPanel.vue'
import {
  DEFAULT_PENALTY_AMOUNT,
  FILTER_OPERATOR_OPTIONS,
  LIMIT_UNIT_OPTIONS,
  NOTIFY_CHANNELS,
  RULE_CATEGORY_OPTIONS,
  buildDraft,
  diffVersions,
  draftToChanges,
  lockEmrAvailability,
  validateDraft,
  validateLimit,
  type ChannelCode,
  type RuleEditorDraft,
  type TlDicts,
  type TlRule,
  type VersionDiffRow,
} from './types'
import type { DepartmentOption } from './types'

const props = defineProps<{
  visible: boolean
  rule: TlRule | null
  dicts: TlDicts | null
  departments: DepartmentOption[]
  /** 后端 JHEMR 写开关（timeliness.jhemr_write.enabled）；当前无读取端点，保守默认 false。 */
  jhemrWriteEnabled?: boolean
}>()
const emit = defineEmits<{
  'update:visible': [v: boolean]
  saved: []
}>()

const draft = ref<RuleEditorDraft>(emptyDraft())
const diffVisible = ref(false)
const diffRows = ref<VersionDiffRow[]>([])
const saving = ref(false)
const dryRunVisible = ref(false)

function emptyDraft(): RuleEditorDraft {
  return {
    rule_code: '',
    rule_name: '',
    category: 'TIMELINESS',
    enabled: false,
    deptScopeAll: true,
    deptScopeCodes: [],
    trigger_type: 'ADMISSION',
    filterRows: [{ field: '', op: 'eq', value: '' }],
    mrClass: [],
    titleKeywords: [],
    signerTitleKeywords: [],
    timeGeT0: false,
    monitorCode: '',
    completion_basis: 'FIRST_SIGN',
    limit: { value: null, unit: 'hour' },
    warnBefore: { value: null, unit: 'hour' },
    channels: [],
    action_mode: 'SHADOW',
    penaltyAmount: DEFAULT_PENALTY_AMOUNT,
    annualTally: true,
    description: '',
  }
}

watch(
  () => [props.visible, props.rule] as const,
  ([open, rule]) => {
    if (open && rule) draft.value = buildDraft(rule)
  },
  { immediate: true },
)

const limitError = computed(() => (draft.value.rule_code ? validateLimit(draft.value.rule_code, draft.value.limit) : null))

const lockEmr = computed(() =>
  lockEmrAvailability(draft.value.rule_code, {
    d8NoLockCodes: props.dicts?.d8_no_lock_rule_codes || [],
    jhemrWriteEnabled: props.jhemrWriteEnabled ?? false,
  }),
)

const unauthorizedChecked = computed(() =>
  NOTIFY_CHANNELS.filter((channel) => !channel.authorized && draft.value.channels.includes(channel.code)),
)

function toggleChannel(code: ChannelCode, checked: boolean | string | number): void {
  const next = new Set<ChannelCode>(draft.value.channels)
  if (checked === true) next.add(code)
  else next.delete(code)
  draft.value.channels = [...next]
}

function openDryRun(): void {
  const errors = validateDraft(draft.value, {
    d8NoLockCodes: props.dicts?.d8_no_lock_rule_codes || [],
    jhemrWriteEnabled: props.jhemrWriteEnabled ?? false,
  })
  if (errors.length > 0) {
    ElMessage.warning(errors[0])
    return
  }
  dryRunVisible.value = true
}

function confirmSave(): void {
  const errors = validateDraft(draft.value, {
    d8NoLockCodes: props.dicts?.d8_no_lock_rule_codes || [],
    jhemrWriteEnabled: props.jhemrWriteEnabled ?? false,
  })
  if (errors.length > 0) {
    ElMessage.warning(errors.join('；'))
    return
  }
  diffRows.value = diffVersions(props.rule?.current_version || null, draftToChanges(draft.value))
  diffVisible.value = true
}

async function save(): Promise<void> {
  if (!props.rule) return
  saving.value = true
  try {
    await createRuleVersionApi(props.rule.rule_code, draftToChanges(draft.value))
    if (draft.value.enabled !== props.rule.enabled) {
      await toggleRuleApi(props.rule.rule_code, draft.value.enabled)
    }
    diffVisible.value = false
    emit('update:visible', false)
    emit('saved')
    ElMessage.success(`已保存为新版本：${props.rule.rule_code}`)
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : '保存失败')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.tl-hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.6;
  margin-top: 4px;
}
.tl-error {
  color: var(--el-color-danger);
  font-size: 12px;
  margin-top: 4px;
}
.tl-filter-rows {
  width: 100%;
}
.tl-filter-row {
  display: flex;
  gap: 6px;
  margin-bottom: 6px;
  align-items: center;
}
.tl-filter-field {
  width: 200px;
  flex: none;
}
.tl-filter-op {
  width: 150px;
  flex: none;
}
.tl-filter-value {
  flex: 1;
}
.tl-channels {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
</style>
