<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import PageHeader from '@/components/base/PageHeader.vue'
import StatusTag from '@/components/base/StatusTag.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import { apiGet, apiPost } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { buildSchedulerTriggerParams } from '@/utils/mutation-contracts'
import { ElMessage, ElMessageBox } from 'element-plus'

const loading = ref(false)
const saving = ref(false)
const error = ref('')
const status = ref<Record<string, unknown> | null>(null)
const daily = reactive<Record<string, unknown>>({})
const discharge = reactive<Record<string, unknown>>({})
const legacy = reactive<Record<string, unknown>>({})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [st, d, di, l] = await Promise.all([
      apiGet<Record<string, unknown>>('/scheduler/status'),
      apiGet<Record<string, unknown>>('/config/scheduler-daily'),
      apiGet<Record<string, unknown>>('/config/scheduler-discharge'),
      apiGet<Record<string, unknown>>('/config/scheduler'),
    ])
    status.value = st
    Object.assign(daily, d || {})
    Object.assign(discharge, di || {})
    Object.assign(legacy, l || {})
  } catch (e) {
    error.value = toUserMessage(e, '加载定时任务失败')
  } finally {
    loading.value = false
  }
}

async function saveSection(kind: 'daily' | 'discharge' | 'legacy') {
  const body = kind === 'daily' ? daily : kind === 'discharge' ? discharge : legacy
  const url =
    kind === 'daily'
      ? '/config/scheduler-daily'
      : kind === 'discharge'
        ? '/config/scheduler-discharge'
        : '/config/scheduler'
  try {
    await ElMessageBox.confirm(
      `确认保存 ${kind} 调度配置？daily 与 discharge 使用不同运行锁，请勿混用语义。`,
      '请确认',
      { type: 'warning' },
    )
  } catch {
    return
  }
  saving.value = true
  try {
    await apiPost(url, body)
    ElMessage.success('已保存')
    await load()
  } catch (e) {
    ElMessage.error(toUserMessage(e, '保存失败'))
  } finally {
    saving.value = false
  }
}

async function triggerNow(mode: 'daily_increment' | 'discharge_final') {
  try {
    await ElMessageBox.confirm(
      `立即触发 ${mode} 属于危险操作，可能调用 Dify。确认继续？与 legacy 一致使用 query 参数 audit_run_mode。`,
      '危险操作',
      { type: 'error', confirmButtonText: '确认触发' },
    )
  } catch {
    return
  }
  try {
    // 契约：POST /api/scheduler/trigger?audit_run_mode=...（非 JSON body.mode）
    const params = buildSchedulerTriggerParams({ audit_run_mode: mode })
    await apiPost('/scheduler/trigger', null, { params })
    ElMessage.success('已触发')
    await load()
  } catch (e) {
    ElMessage.error(toUserMessage(e, '触发失败'))
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="page-scheduler">
    <PageHeader
      title="定时任务"
      description="daily/discharge/legacy 明确区分；立即触发置于危险区。双任务锁语义不可回退。"
    >
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </template>
    </PageHeader>

    <ErrorState v-if="error && !loading" :message="error" @retry="load" />
    <template v-else>
      <el-card shadow="never" class="card" v-loading="loading">
        <template #header>
          <div class="head">
            <span>运行状态</span>
            <StatusTag :value="status?.running ? 'running' : 'pending'" />
          </div>
        </template>
        <pre class="json-pre">{{ JSON.stringify(status || {}, null, 2) }}</pre>
        <div class="actions">
          <el-button type="danger" plain @click="triggerNow('daily_increment')">立即触发 daily</el-button>
          <el-button type="danger" plain @click="triggerNow('discharge_final')">立即触发 discharge</el-button>
        </div>
      </el-card>

      <el-row :gutter="12">
        <el-col :xs="24" :lg="8">
          <el-card shadow="never" class="card">
            <template #header>daily_increment</template>
            <el-form label-position="top">
              <el-form-item label="enabled">
                <el-switch v-model="daily.enabled as boolean" />
              </el-form-item>
              <el-form-item label="cron / daily_time">
                <el-input v-model="daily.cron as string" placeholder="cron" />
              </el-form-item>
              <el-button type="primary" :loading="saving" @click="saveSection('daily')">保存 daily</el-button>
            </el-form>
          </el-card>
        </el-col>
        <el-col :xs="24" :lg="8">
          <el-card shadow="never" class="card">
            <template #header>discharge_final</template>
            <el-form label-position="top">
              <el-form-item label="enabled">
                <el-switch v-model="discharge.enabled as boolean" />
              </el-form-item>
              <el-form-item label="cron">
                <el-input v-model="discharge.cron as string" placeholder="cron" />
              </el-form-item>
              <el-button type="primary" :loading="saving" @click="saveSection('discharge')">保存 discharge</el-button>
            </el-form>
          </el-card>
        </el-col>
        <el-col :xs="24" :lg="8">
          <el-card shadow="never" class="card">
            <template #header>legacy scheduler</template>
            <el-form label-position="top">
              <el-form-item label="enabled">
                <el-switch v-model="legacy.enabled as boolean" />
              </el-form-item>
              <el-form-item label="cron">
                <el-input v-model="legacy.cron as string" placeholder="cron" />
              </el-form-item>
              <el-button :loading="saving" @click="saveSection('legacy')">保存 legacy</el-button>
            </el-form>
          </el-card>
        </el-col>
      </el-row>
    </template>
  </div>
</template>

<style scoped>
.card {
  margin-bottom: 12px;
  border-radius: 12px;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.json-pre {
  margin: 0;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 240px;
  overflow: auto;
}
.actions {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
