<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import PageHeader from '@/components/base/PageHeader.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import SkeletonBlock from '@/components/feedback/SkeletonBlock.vue'
import { apiGet } from '@/api/client'
import { toUserMessage } from '@/api/errors'

const loading = ref(false)
const error = ref('')
const data = ref<Record<string, unknown> | null>(null)

const warnings = computed(() => ((data.value?.warnings as Array<Record<string, unknown>>) || []))
const warningGroups = computed(() => {
  const g: Record<string, Array<Record<string, unknown>>> = { error: [], warning: [], info: [] }
  for (const w of warnings.value) {
    const lv = String(w.level || 'info')
    if (g[lv]) g[lv].push(w)
  }
  return g
})
const schedulers = computed(() => ((data.value?.schedulers as Array<Record<string, unknown>>) || []))
const deptScopes = computed(() => ((data.value?.dept_scopes as Array<Record<string, unknown>>) || []))
const auditTypes = computed(() => ((data.value?.audit_types as Array<Record<string, unknown>>) || []))
const meta = computed(() => ((data.value?.meta as Record<string, unknown>) || {}))

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await apiGet<Record<string, unknown>>('/config/runtime-summary')
  } catch (e) {
    error.value = toUserMessage(e, '加载运行总览失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => { void load() })
</script>

<template>
  <div class="page-runtime">
    <PageHeader title="运行总览" description="系统配置风险、运行模式与审计类型总览。">
      <template #actions><el-button :loading="loading" @click="load">刷新</el-button></template>
    </PageHeader>

    <ErrorState v-if="error" :message="error" @retry="load" />
    <SkeletonBlock v-else-if="loading" />

    <template v-else-if="data">
      <!-- 风险告警 -->
      <el-card shadow="never" class="section-card">
        <div class="section-title">配置风险（{{ warnings.length }}）</div>
        <div v-if="!warnings.length" class="empty-text">暂无配置风险</div>
        <el-alert
          v-for="(w, i) in warningGroups.error"
          :key="'e' + i"
          type="error"
          :closable="false"
          show-icon
          class="mt-sm"
        >
          <template #title>{{ w.message }}</template>
          <template #default><span class="warn-detail">{{ w.code }} · {{ w.path }}{{ w.related_path ? ' → ' + w.related_path : '' }}</span></template>
        </el-alert>
        <el-alert
          v-for="(w, i) in warningGroups.warning"
          :key="'w' + i"
          type="warning"
          :closable="false"
          show-icon
          class="mt-sm"
        >
          <template #title>{{ w.message }}</template>
          <template #default><span class="warn-detail">{{ w.code }} · {{ w.path }}</span></template>
        </el-alert>
        <el-alert
          v-for="(w, i) in warningGroups.info"
          :key="'i' + i"
          type="info"
          :closable="false"
          show-icon
          class="mt-sm"
        >
          <template #title>{{ w.message }}</template>
        </el-alert>
      </el-card>

      <!-- 系统元信息 -->
      <el-card shadow="never" class="section-card">
        <div class="section-title">系统信息</div>
        <el-descriptions :column="3" border size="small">
          <el-descriptions-item label="只读模式">{{ meta.readonly ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="密钥脱敏">{{ meta.secrets_masked ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="SQL 包含">{{ meta.sql_included ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="配置形态">{{ meta.config_shape }}</el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- 调度器 -->
      <el-card v-if="schedulers.length" shadow="never" class="section-card">
        <div class="section-title">调度器（{{ schedulers.length }}）</div>
        <el-table :data="schedulers" stripe border size="small" style="width: 100%">
          <el-table-column prop="key" label="调度" width="160" show-overflow-tooltip />
          <el-table-column label="启用" width="60"><template #default="{ row }"><el-tag size="small" :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '是' : '否' }}</el-tag></template></el-table-column>
          <el-table-column prop="cron" label="Cron" width="120" />
          <el-table-column prop="schedule_mode" label="模式" width="100" />
          <el-table-column prop="audit_run_mode" label="运行模式" width="130" />
          <el-table-column label="审计类型" min-width="150"><template #default="{ row }">{{ Array.isArray(row.audit_type_codes) ? row.audit_type_codes.join(', ') : '' }}</template></el-table-column>
        </el-table>
      </el-card>

      <!-- 审计类型 -->
      <el-card v-if="auditTypes.length" shadow="never" class="section-card">
        <div class="section-title">审计类型（{{ auditTypes.length }}）</div>
        <el-table :data="auditTypes" stripe border size="small" style="width: 100%">
          <el-table-column prop="code" label="编码" width="180" show-overflow-tooltip />
          <el-table-column prop="name" label="名称" width="140" />
          <el-table-column label="启用" width="55"><template #default="{ row }"><el-tag size="small" :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '是' : '否' }}</el-tag></template></el-table-column>
          <el-table-column label="默认调度" width="75"><template #default="{ row }">{{ row.default_for_schedule ? '✓' : '' }}</template></el-table-column>
          <el-table-column prop="builder" label="Builder" width="220" show-overflow-tooltip />
          <el-table-column label="数据源" min-width="140"><template #default="{ row }">{{ Array.isArray(row.source_keys) ? row.source_keys.join(', ') : '' }}</template></el-table-column>
          <el-table-column label="必需源" width="120"><template #default="{ row }">{{ Array.isArray(row.required_source_keys) ? row.required_source_keys.join(', ') : '' }}</template></el-table-column>
        </el-table>
      </el-card>

      <!-- 科室范围 -->
      <el-card v-if="deptScopes.length" shadow="never" class="section-card">
        <div class="section-title">科室范围</div>
        <div v-for="scope in deptScopes" :key="String(scope.key || scope.scope)" class="dept-scope">
          <span class="scope-label">{{ scope.key || scope.scope }}：</span>
          <el-tag size="small" :type="scope.mode === 'include' ? 'success' : 'warning'">{{ scope.mode === 'include' ? '仅包含' : '排除' }}</el-tag>
          <span class="scope-list">{{ Array.isArray(scope.list) ? scope.list.join('、') : (scope.count || 0) + ' 个科室' }}</span>
        </div>
      </el-card>
    </template>
  </div>
</template>

<style scoped>
.section-card { margin-bottom: 12px; border-radius: 10px; }
.section-title { font-size: 15px; font-weight: 600; margin-bottom: 12px; }
.empty-text { text-align: center; padding: 20px; color: var(--el-text-color-disabled); font-size: 13px; }
.warn-detail { font-size: 11px; color: var(--el-text-color-disabled); font-family: monospace; }
.dept-scope { display: flex; align-items: center; gap: 8px; padding: 6px 0; font-size: 13px; border-bottom: 1px solid var(--el-border-color-lighter); }
.scope-label { font-weight: 600; min-width: 120px; }
.scope-list { color: var(--el-text-color-secondary); flex: 1; }
.mt-sm { margin-top: 8px; }
</style>
