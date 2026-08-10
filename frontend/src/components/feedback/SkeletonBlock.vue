<script setup lang="ts">
withDefaults(
  defineProps<{
    rows?: number
  }>(),
  { rows: 4 },
)
</script>

<template>
  <div class="skeleton-block" aria-hidden="true">
    <div v-for="i in rows" :key="i" class="skeleton-block__row" />
  </div>
</template>

<style scoped>
.skeleton-block {
  display: grid;
  gap: 10px;
  padding: 8px 0;
}
.skeleton-block__row {
  height: 14px;
  border-radius: 6px;
  background: linear-gradient(90deg, #e2e8f0 25%, #f8fafc 50%, #e2e8f0 75%);
  background-size: 200% 100%;
  animation: shimmer 1.2s infinite;
}
.skeleton-block__row:nth-child(odd) {
  width: 92%;
}
.skeleton-block__row:nth-child(even) {
  width: 78%;
}
@keyframes shimmer {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}
@media (prefers-reduced-motion: reduce) {
  .skeleton-block__row {
    animation: none;
  }
}
</style>
