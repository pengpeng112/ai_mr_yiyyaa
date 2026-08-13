<script setup lang="ts">
import { ref } from 'vue'

const props = withDefaults(
  defineProps<{
    title?: string
    collapsible?: boolean
  }>(),
  {
    title: '筛选条件',
    collapsible: true,
  },
)

const emit = defineEmits<{
  search: []
  reset: []
}>()

const moreOpen = ref(false)
</script>

<template>
  <section class="filter-panel">
    <div class="filter-panel__head">
      <h2 class="filter-panel__title">{{ props.title }}</h2>
      <div class="filter-panel__actions">
        <el-button type="primary" @click="emit('search')">查询</el-button>
        <el-button @click="emit('reset')">重置</el-button>
        <el-button
          v-if="collapsible && $slots.more"
          link
          type="primary"
          @click="moreOpen = !moreOpen"
        >
          {{ moreOpen ? '收起筛选' : '更多筛选' }}
        </el-button>
      </div>
    </div>
    <div class="filter-panel__body">
      <slot />
    </div>
    <div v-if="moreOpen" class="filter-panel__more">
      <slot name="more" />
    </div>
  </section>
</template>

<style scoped>
.filter-panel {
  background: var(--ma-surface-card);
  border: 1px solid var(--ma-border);
  border-radius: var(--ma-radius);
  padding: 12px 14px;
  margin-bottom: 16px;
  box-shadow: var(--ma-shadow);
}
.filter-panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}
.filter-panel__title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}
.filter-panel__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.filter-panel__actions :deep(.el-button) {
  min-height: 36px;
}
.filter-panel__body,
.filter-panel__more {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px 12px;
}
.filter-panel__more {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--ma-border);
}
</style>
