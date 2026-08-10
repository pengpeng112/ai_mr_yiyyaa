<script setup lang="ts">
import ErrorState from '@/components/feedback/ErrorState.vue'
import EmptyState from '@/components/feedback/EmptyState.vue'

withDefaults(
  defineProps<{
    loading?: boolean
    error?: string
    empty?: boolean
    emptyText?: string
    total?: number
    page?: number
    pageSize?: number
    showPagination?: boolean
  }>(),
  {
    emptyText: '暂无数据',
    showPagination: true,
    page: 1,
    pageSize: 20,
    total: 0,
  },
)

const emit = defineEmits<{
  retry: []
  'update:page': [number]
  'update:pageSize': [number]
}>()
</script>

<template>
  <section class="table-shell">
    <ErrorState v-if="error && !loading" :message="error" @retry="emit('retry')" />
    <template v-else>
      <div class="table-shell__scroll">
        <slot />
      </div>
      <EmptyState v-if="!loading && empty" :description="emptyText" />
      <div v-if="showPagination && !empty" class="table-shell__pager">
        <el-pagination
          background
          layout="total, sizes, prev, pager, next"
          :total="total"
          :current-page="page"
          :page-size="pageSize"
          :page-sizes="[10, 20, 50, 100]"
          @current-change="(p: number) => emit('update:page', p)"
          @size-change="(s: number) => emit('update:pageSize', s)"
        />
      </div>
    </template>
  </section>
</template>

<style scoped>
.table-shell {
  background: var(--ma-surface-card);
  border: 1px solid var(--ma-border);
  border-radius: var(--ma-radius);
  box-shadow: var(--ma-shadow);
  padding: 8px;
}
.table-shell__scroll {
  width: 100%;
  overflow-x: auto;
}
.table-shell__pager {
  display: flex;
  justify-content: flex-end;
  padding: 10px 6px 4px;
}
</style>
