<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import PageHeader from '@/components/base/PageHeader.vue'
import SummaryStrip, { type SummaryItem } from '@/components/base/SummaryStrip.vue'
import StatusTag from '@/components/base/StatusTag.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import { apiGet, apiPost } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import type { PushProgress } from '@/api/types'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useTaskStore } from '@/stores/task'

const taskStore = useTaskStore()
const loading = ref(false)
const error = ref('')
const latest = ref<PushProgress | null>(null)
let timer: ReturnType<typeof setInterval> | null = null
let gen = 0

const summary = ref<SummaryItem[]>([])

function updateSummary(t: PushProgress | null) {
  summary.value = [
    { key: 'status', label: '状态', value: String(t?.status ?? '—') },
    { key: 'total', label: '总量', value: Number(t?.total ?? 0) },
    { key: 'done', label: '已完成', value: Number(t?.done ?? 0), tone: 'info' },
    { key: 'success', label: '成功', value: Number(t?.success ?? 0), tone: 'success' },
    { key: 'failed', label: '失败', value: Number(t?.failed ?? 0), tone: 'danger' },
    { key: 'skipped', label: '跳过', value: Number(t?.skipped ?? 0), tone: 'warning' },
  ]
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await apiGet<PushProgress>('/push/tasks/latest')
    latest.value = data
    taskStore.latest = data
    updateSummary(data)
  } catch (e) {
    error.value = toUserMessage(e, '加载任务进度失败')
  } finally {
    loading.value = false
  }
}

function startLocalPolling() {
  stopLocalPolling()
  const my = ++gen
  timer = setInterval(() => {
    if (my !== gen) return
    void load()
  }, 5000)
}

function stopLocalPolling() {
  gen += 1
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

async function cancelTask() {
  const id = latest.value?.task_id
  if (!id) return
  try {
    await ElMessageBox.confirm('确认取消当前运行中的推送任务？', '危险操作', { type: 'warning' })
    await apiPost(`/push/cancel/${id}`)
    ElMessage.success('已请求取消')
    await load()
  } catch (e) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error(toUserMessage(e, '取消失败'))
  }
}

onMounted(() => {
  void load()
  startLocalPolling()
})

onUnmounted(() => {
  stopLocalPolling()
})
</script>

<template>
  <div class="page-progress">
    <PageHeader title="任务进度" description="运行中优先展示；全院任务能力保留。离开页面后停止本页轮询。">
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-button
          type="danger"
          :disabled="!latest?.task_id || !/run|process|pending/i.test(String(latest?.status || ''))"
          @click="cancelTask"
        >
          取消任务
        </el-button>
      </template>
    </PageHeader>

    <ErrorState v-if="error && !loading" :message="error" @retry="load" />
    <template v-else>
      <SummaryStrip :items="summary" :loading="loading" />
      <el-card shadow="never" class="card">
        <template #header>
          <div class="card-head">
            <span>最新任务</span>
            <StatusTag :value="latest?.status" />
          </div>
        </template>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="任务 ID">{{ latest?.task_id || '—' }}</el-descriptions-item>
          <el-descriptions-item label="进度">
            {{ latest?.done ?? 0 }} / {{ latest?.total ?? 0 }}
            <span v-if="latest?.percent != null">（{{ latest.percent }}%）</span>
          </el-descriptions-item>
          <el-descriptions-item label="成功">{{ latest?.success ?? 0 }}</el-descriptions-item>
          <el-descriptions-item label="失败">{{ latest?.failed ?? 0 }}</el-descriptions-item>
          <el-descriptions-item label="跳过">{{ latest?.skipped ?? 0 }}</el-descriptions-item>
          <el-descriptions-item label="消息">{{ latest?.message || '—' }}</el-descriptions-item>
        </el-descriptions>
        <el-progress
          class="mt"
          :percentage="Math.min(100, Number(latest?.percent ?? 0))"
          :status="String(latest?.status || '').includes('fail') ? 'exception' : undefined"
        />
      </el-card>
    </template>
  </div>
</template>

<style scoped>
.card {
  border-radius: 12px;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.mt {
  margin-top: 16px;
}
</style>
