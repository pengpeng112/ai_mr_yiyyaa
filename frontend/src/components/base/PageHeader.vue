<script setup lang="ts">
defineProps<{
  title: string
  description?: string
}>()
</script>

<template>
  <header class="page-header">
    <div class="page-header__text">
      <h1 class="page-header__title" tabindex="-1">{{ title }}</h1>
      <p v-if="description" class="page-header__desc">{{ description }}</p>
    </div>
    <div class="page-header__actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}
.page-header__title {
  margin: 0;
  font-size: 20px;
  font-weight: 650;
  color: var(--ma-text-primary);
  outline: none;
}
.page-header__desc {
  margin: 6px 0 0;
  color: var(--ma-text-muted);
  font-size: 13px;
  line-height: 1.5;
  max-width: 720px;
}
.page-header__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  justify-content: flex-end;
}
@media (max-width: 640px) {
  .page-header {
    flex-direction: column;
  }
  .page-header__actions {
    width: 100%;
    justify-content: flex-start;
  }
}
</style>
