<script setup lang="ts">
import { computed } from 'vue'
import { normalizeSeverity, severityLabel, severityTagType } from '@/utils/status'

const props = defineProps<{
  value?: unknown
  label?: string
}>()

const type = computed(() => severityTagType(props.value))
const text = computed(() => props.label || severityLabel(props.value))
const normalized = computed(() => normalizeSeverity(props.value))
</script>

<template>
  <el-tag :type="type" size="small" effect="dark" :data-severity="normalized">
    <span class="risk-tag__icon" aria-hidden="true">●</span>
    {{ text }}
  </el-tag>
</template>

<style scoped>
.risk-tag__icon {
  margin-right: 4px;
  font-size: 10px;
}
</style>
