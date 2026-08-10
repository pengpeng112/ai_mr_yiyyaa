<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { toUserMessage } from '@/api/errors'

const props = withDefaults(
  defineProps<{
    type?: 'primary' | 'success' | 'warning' | 'danger' | 'info' | 'default'
    plain?: boolean
    link?: boolean
    disabled?: boolean
    confirm?: string
    successMessage?: string
    errorFallback?: string
  }>(),
  {
    type: 'primary',
    errorFallback: '操作失败',
  },
)

const emit = defineEmits<{
  click: []
}>()

const loading = ref(false)

async function handleClick() {
  if (loading.value || props.disabled) return
  if (props.confirm) {
    try {
      await ElMessageBox.confirm(props.confirm, '请确认', {
        type: 'warning',
        confirmButtonText: '确认',
        cancelButtonText: '取消',
      })
    } catch {
      return
    }
  }
  loading.value = true
  try {
    emit('click')
  } finally {
    window.setTimeout(() => {
      loading.value = false
    }, 300)
  }
}

async function run(task: () => Promise<void>) {
  if (loading.value || props.disabled) return
  if (props.confirm) {
    try {
      await ElMessageBox.confirm(props.confirm, '请确认', {
        type: 'warning',
        confirmButtonText: '确认',
        cancelButtonText: '取消',
      })
    } catch {
      return
    }
  }
  loading.value = true
  try {
    await task()
    if (props.successMessage) ElMessage.success(props.successMessage)
  } catch (e) {
    ElMessage.error(toUserMessage(e, props.errorFallback))
    throw e
  } finally {
    loading.value = false
  }
}

defineExpose({ run, loading })
</script>

<template>
  <el-button
    :type="type === 'default' ? undefined : type"
    :plain="plain"
    :link="link"
    :disabled="disabled || loading"
    :loading="loading"
    @click="handleClick"
  >
    <slot />
  </el-button>
</template>
