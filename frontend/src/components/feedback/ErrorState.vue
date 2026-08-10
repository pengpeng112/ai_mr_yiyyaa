<script setup lang="ts">
defineProps<{
  title?: string
  message?: string
  requestId?: string
}>()

const emit = defineEmits<{
  retry: []
}>()
</script>

<template>
  <div class="error-state" role="alert">
    <div class="error-state__title">{{ title || '加载失败' }}</div>
    <p class="error-state__msg">{{ message || '请稍后重试' }}</p>
    <p v-if="requestId" class="error-state__rid">请求号：{{ requestId }}</p>
    <el-button type="primary" @click="emit('retry')">重试</el-button>
  </div>
</template>

<style scoped>
.error-state {
  text-align: center;
  padding: 40px 16px;
  color: var(--ma-text-secondary);
}
.error-state__title {
  font-size: 16px;
  font-weight: 600;
  color: var(--ma-text-primary);
  margin-bottom: 8px;
}
.error-state__msg {
  margin: 0 0 8px;
  max-width: 480px;
  margin-inline: auto;
}
.error-state__rid {
  font-size: 12px;
  color: var(--ma-text-muted);
  margin-bottom: 12px;
}
</style>
