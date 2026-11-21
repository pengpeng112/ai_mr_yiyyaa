<script setup lang="ts">
import { computed } from 'vue'
// WP09：连通性测试结果中文结构化卡（成功/失败、耗时、错误信息；原始响应折叠）。
// ConfigPage 与 RelayConfigPage 共用；供测试注入或真实 /test 响应。
const props = defineProps<{
  result: Record<string, any> | null | undefined
  title?: string
}>()

const ok = computed(() => {
  const item = props.result as Record<string, any> | null
  if (!item || typeof item !== 'object') return false
  return item.status === 'up' || item.status === 'success' || item.success === true
})
const latencyText = computed(() => {
  const ms = Number(props.result?.latency_ms || 0)
  return ms ? `耗时 ${ms}ms` : ''
})
const messageText = computed(() => String(props.result?.message || props.result?.error || ''))
const rawJson = computed(() => JSON.stringify(props.result ?? {}, null, 2))

</script>

<template>
  <div v-if="result && typeof result === 'object'" class="test-card">
    <div class="test-card-head">
      <span v-if="title" class="test-card-title">{{ title }}</span>
      <span :class="ok ? 'test-ok' : 'test-fail'">{{ ok ? '✓ 连接成功' : '✗ 连接失败' }}</span>
      <span v-if="latencyText" class="cfg-label">{{ latencyText }}</span>
    </div>
    <div v-if="messageText" class="test-msg">{{ messageText }}</div>
    <details class="test-raw">
      <summary>查看原始响应</summary>
      <pre class="raw-json">{{ rawJson }}</pre>
    </details>
  </div>
</template>

<style scoped>
.test-card { margin-top: 10px; padding: 10px 12px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; }
.test-card-head { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.test-card-title { font-size: 13px; font-weight: 600; }
.test-ok { color: var(--el-color-success); font-weight: 700; }
.test-fail { color: var(--el-color-danger); font-weight: 700; }
.cfg-label { font-size: 12px; color: var(--el-text-color-secondary); }
.test-msg { margin-top: 4px; font-size: 12px; color: var(--el-text-color-secondary); word-break: break-all; }
.test-raw { margin-top: 8px; }
.test-raw summary { cursor: pointer; font-size: 12px; color: var(--el-text-color-secondary); }
.raw-json {
  margin: 6px 0 0; max-height: 240px; overflow: auto; padding: 8px 10px; border-radius: 8px;
  background: #0f172a; color: #e2e8f0; font-size: 12px; line-height: 1.5;
  white-space: pre-wrap; word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
</style>
