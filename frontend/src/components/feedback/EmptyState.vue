<script setup lang="ts">
defineProps<{
  title?: string
  description?: string
}>()
</script>

<template>
  <div class="empty-state">
    <div class="empty-state__title">{{ title || '暂无数据' }}</div>
    <p v-if="description" class="empty-state__desc">{{ description }}</p>
    <div v-if="$slots.default" class="empty-state__actions">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.empty-state {
  text-align: center;
  padding: 36px 12px;
  color: var(--ma-text-muted);
}
.empty-state__title {
  font-size: 15px;
  font-weight: 600;
  color: var(--ma-text-secondary);
}
.empty-state__desc {
  margin: 8px 0 0;
  font-size: 13px;
}
.empty-state__actions {
  margin-top: 12px;
}
</style>
