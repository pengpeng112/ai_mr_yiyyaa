<script setup lang="ts">
export interface SummaryItem {
  key: string
  label: string
  value: string | number
  hint?: string
  tone?: 'default' | 'danger' | 'warning' | 'success' | 'info'
}

defineProps<{
  items: SummaryItem[]
  loading?: boolean
}>()
</script>

<template>
  <div class="summary-strip" :aria-busy="loading ? 'true' : 'false'">
    <div
      v-for="item in items"
      :key="item.key"
      class="summary-strip__card"
      :class="`is-${item.tone || 'default'}`"
    >
      <div class="summary-strip__label">{{ item.label }}</div>
      <div class="summary-strip__value">
        <template v-if="loading">—</template>
        <template v-else>{{ item.value }}</template>
      </div>
      <div v-if="item.hint" class="summary-strip__hint">{{ item.hint }}</div>
    </div>
  </div>
</template>

<style scoped>
.summary-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.summary-strip__card {
  background: var(--ma-surface-card);
  border: 1px solid var(--ma-border);
  border-radius: var(--ma-radius);
  padding: 12px 14px;
  box-shadow: var(--ma-shadow);
}
.summary-strip__label {
  font-size: 12px;
  color: var(--ma-text-muted);
}
.summary-strip__value {
  margin-top: 6px;
  font-size: 22px;
  font-weight: 700;
  color: var(--ma-text-primary);
}
.summary-strip__hint {
  margin-top: 4px;
  font-size: 12px;
  color: var(--ma-text-secondary);
}
.is-danger .summary-strip__value {
  color: var(--ma-risk-high);
}
.is-warning .summary-strip__value {
  color: var(--ma-risk-medium);
}
.is-success .summary-strip__value {
  color: var(--ma-risk-low);
}
.is-info .summary-strip__value {
  color: var(--ma-status-info);
}
</style>
