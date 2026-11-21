<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  DEFAULT_HOLOGRAPHY_CONFIG,
  loadHolographyConfig,
  openHolography360,
  type HolographyConfig,
} from '@/utils/holography'

const props = withDefaults(defineProps<{
  patientId?: string | null
  label?: string
  size?: 'small' | 'default' | 'large'
  link?: boolean
  type?: 'primary' | 'default' | 'info'
}>(), {
  label: '360全息',
  size: 'small',
  link: false,
  type: 'primary',
})

const cfg = ref<HolographyConfig>(DEFAULT_HOLOGRAPHY_CONFIG)

onMounted(async () => {
  cfg.value = await loadHolographyConfig()
})

const hasPatientId = computed(() => Boolean(String(props.patientId || '').trim()))

function handleClick() {
  if (!hasPatientId.value) return
  openHolography360(String(props.patientId).trim(), cfg.value)
}
</script>

<template>
  <el-tooltip
    v-if="cfg.enabled"
    :content="hasPatientId ? '在新窗口打开患者 360 全息视图' : '缺少患者号，暂无法打开 360 全息视图'"
    placement="top"
  >
    <el-button
      :type="type"
      :size="size"
      :link="link"
      :plain="!link"
      :disabled="!hasPatientId"
      data-testid="holography-360-btn"
      @click.stop="handleClick"
    >
      {{ label }}
    </el-button>
  </el-tooltip>
</template>
