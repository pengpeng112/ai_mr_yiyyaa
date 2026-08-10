<script setup lang="ts">
import ErrorState from '@/components/feedback/ErrorState.vue'
</script>

<template>
  <ErrorState title="500 服务异常" message="服务暂时不可用，请稍后重试。不会展示内部堆栈或 SQL 详情。" />
</template>
