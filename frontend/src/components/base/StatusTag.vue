<script setup lang="ts">
import { computed } from 'vue'
import { normalizeStatus, statusLabel, statusTagType } from '@/utils/status'

const props = defineProps<{
  value?: unknown
  label?: string
}>()

const type = computed(() => statusTagType(props.value))
const text = computed(() => props.label || statusLabel(props.value))
const normalized = computed(() => normalizeStatus(props.value))
</script>

<template>
  <el-tag :type="type" size="small" effect="light" :data-status="normalized">
    {{ text }}
  </el-tag>
</template>
