<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    title?: string
    size?: string | number
    loading?: boolean
  }>(),
  {
    title: '详情',
    size: '520px',
    loading: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [boolean]
  closed: []
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

const drawerSize = computed(() => {
  if (typeof window !== 'undefined' && window.innerWidth < 900) return '100%'
  return props.size
})
</script>

<template>
  <el-drawer
    v-model="visible"
    :title="title"
    :size="drawerSize"
    destroy-on-close
    append-to-body
    @closed="emit('closed')"
  >
    <div v-loading="loading" class="detail-drawer__body">
      <slot />
    </div>
    <template v-if="$slots.footer" #footer>
      <slot name="footer" />
    </template>
  </el-drawer>
</template>

<style scoped>
.detail-drawer__body {
  min-height: 120px;
}
</style>
